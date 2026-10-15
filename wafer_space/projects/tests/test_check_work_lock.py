"""A check's work is published once and run once (issue #426).

On production, check 809 got two do_analyzing runs: the first finished it
with a pass, and the second then marked it ERROR. These tests cover each way
a second run could happen, and what stops it:
- the dispatchers write the check's lock before they publish, so overlapping
  dispatcher runs cannot both publish;
- a work task runs only if the lock carries its own task id, so a duplicate
  message is skipped, while Celery's own retry still runs;
- a work task that fails after the check moved on does not overwrite it.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any
from unittest.mock import patch

import pytest
from celery import current_task
from django.conf import settings
from django.utils import timezone

from wafer_space.projects.exceptions import TaskExecutionError
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import ManufacturabilityCheckTask
from wafer_space.projects.tasks_checks import DISPATCHER_TIME_LIMITS
from wafer_space.projects.tasks_checks import checks_analyzing
from wafer_space.projects.tasks_checks import checks_cleanup_stale_pending_tasks
from wafer_space.projects.tasks_checks import checks_dispatching
from wafer_space.projects.tasks_checks import checks_pending
from wafer_space.projects.tasks_checks import checks_running
from wafer_space.projects.tasks_checks import checks_starting
from wafer_space.projects.tasks_checks import do_analyzing
from wafer_space.projects.tasks_checks import queue_check_work
from wafer_space.projects.tasks_checks import queued_check_task
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory

if TYPE_CHECKING:
    from unittest.mock import MagicMock

Status = ManufacturabilityCheck.Status
LOCK_ID = "the-lock-holders-id"
OTHER_ID = "a-duplicate-messages-id"
STALE_LOCK_AGE = timedelta(seconds=31)  # the cleanup leaves locks under 30 s
attempts: list[str | None] = []


@queued_check_task(
    expected_status="ANALYZING",
    name="wafer_space.projects.tests.test_check_work_lock.record_attempt",
)
def record_attempt(_check: ManufacturabilityCheck) -> dict[str, str]:
    """A work task that records which task id ran it."""
    attempts.append(current_task.request.id)
    return {"status": "ran"}


@queued_check_task(
    expected_status="ANALYZING",
    name="wafer_space.projects.tests.test_check_work_lock.retry_once",
)
def retry_once(_check: ManufacturabilityCheck) -> dict[str, str]:
    """A work task that asks Celery to retry it once, then succeeds."""
    attempts.append(current_task.request.id)
    if len(attempts) == 1:
        raise current_task.retry(countdown=0)
    return {"status": "ran"}


@queued_check_task(
    expected_status="ANALYZING",
    name="wafer_space.projects.tests.test_check_work_lock.fail_after_a_finish",
)
def fail_after_a_finish(check: ManufacturabilityCheck) -> dict[str, str]:
    """809's second do_analyzing: another run finishes the check, this one fails."""
    ManufacturabilityCheck.objects.get(pk=check.pk).mark_finished(
        is_manufacturable=True, errors=[], warnings=[], tool_versions={}
    )
    raise TaskExecutionError(reason="lost", message="analysis failed")


@queued_check_task(
    expected_status="ANALYZING",
    name="wafer_space.projects.tests.test_check_work_lock.lose_the_lock",
)
def lose_the_lock(check: ManufacturabilityCheck) -> dict[str, str]:
    """While this runs, its lock is cleared and another run locks the check."""
    ManufacturabilityCheckTask.objects.filter(manufacturability_check=check).delete()
    lock(check, OTHER_ID)
    return {"status": "ran"}


@pytest.fixture(autouse=True)
def no_attempts_yet() -> None:
    attempts.clear()


def an_analyzing_check() -> ManufacturabilityCheck:
    return ManufacturabilityCheckFactory(status=Status.ANALYZING)


def lock(check: ManufacturabilityCheck, task_id: str) -> ManufacturabilityCheckTask:
    return ManufacturabilityCheckTask.objects.create(
        manufacturability_check=check, task_id=task_id, task_name="do_analyzing"
    )


def lock_ids(check: ManufacturabilityCheck) -> list[str]:
    return list(
        ManufacturabilityCheckTask.objects.filter(
            manufacturability_check=check
        ).values_list("task_id", flat=True)
    )


@pytest.mark.django_db
class TestLockBeforePublish:
    """The dispatchers write the lock, then publish under the lock's task id."""

    def test_the_lock_exists_when_the_message_is_published(self) -> None:
        check = an_analyzing_check()
        seen: list[list[str]] = []

        def publish(*_args: Any, **kwargs: Any) -> None:
            seen.append(lock_ids(check))
            assert kwargs["task_id"] in seen[-1]

        with patch.object(do_analyzing, "apply_async", side_effect=publish):
            task_id = queue_check_work(check, do_analyzing)

        assert seen == [[task_id]]

    def test_an_overlapping_dispatcher_run_publishes_nothing(self) -> None:
        """Two runs both picked the check before either locked it: one publish."""
        check = an_analyzing_check()

        with patch.object(do_analyzing, "apply_async") as publish:
            first = queue_check_work(check, do_analyzing)
            second = queue_check_work(check, do_analyzing)

        assert (publish.call_count, second, lock_ids(check)) == (1, None, [first])

    def test_a_publish_that_raises_removes_its_own_lock(self) -> None:
        """The check is free again for the next run, 15 s later."""
        check = an_analyzing_check()

        with (
            patch.object(do_analyzing, "apply_async", side_effect=OSError("broker")),
            pytest.raises(OSError, match="broker"),
        ):
            queue_check_work(check, do_analyzing)

        assert lock_ids(check) == []

    def test_a_publish_error_fails_the_dispatcher_run(self) -> None:
        """Loudly: the run raises rather than counting the check as queued."""
        an_analyzing_check()

        with (
            patch.object(do_analyzing, "apply_async", side_effect=OSError("broker")),
            pytest.raises(OSError, match="broker"),
        ):
            checks_analyzing()

    def test_a_lock_that_could_not_be_removed_is_cleared_after_30_s(self) -> None:
        """The longest a failed publish can hold a check.

        If removing the lock fails too, the lock has no message and no task
        result, so checks_cleanup_stale_pending_tasks (every 60 s) removes it
        once it is 30 s old, and the next dispatcher run queues the check.
        """
        check = an_analyzing_check()
        lock(check, LOCK_ID)
        ManufacturabilityCheckTask.objects.filter(task_id=LOCK_ID).update(
            queued_at=timezone.now() - STALE_LOCK_AGE
        )

        checks_cleanup_stale_pending_tasks()

        assert lock_ids(check) == []

    def test_a_lock_under_30_s_old_is_kept(self) -> None:
        """A message in transit to a worker keeps its lock."""
        check = an_analyzing_check()
        lock(check, LOCK_ID)

        checks_cleanup_stale_pending_tasks()

        assert lock_ids(check) == [LOCK_ID]


@pytest.mark.django_db
class TestOnlyTheLockHolderRuns:
    """A work task runs only if the check's lock carries its task id."""

    def test_the_lock_holder_runs(self) -> None:
        """Also a redelivered message: it keeps its task id."""
        check = an_analyzing_check()
        lock(check, LOCK_ID)

        record_attempt.apply((check.id,), task_id=LOCK_ID)

        assert attempts == [LOCK_ID]

    def test_the_lock_holder_removes_its_lock(self) -> None:
        check = an_analyzing_check()
        lock(check, LOCK_ID)

        record_attempt.apply((check.id,), task_id=LOCK_ID)

        assert lock_ids(check) == []

    def test_a_message_without_the_lock_is_skipped(self) -> None:
        """A duplicate: its publish raised but landed, or its lock was cleared."""
        check = an_analyzing_check()
        lock(check, LOCK_ID)

        result = record_attempt.apply((check.id,), task_id=OTHER_ID).get()

        assert (attempts, result["reason"]) == ([], "not_lock_holder")

    def test_a_skipped_duplicate_leaves_the_holders_lock(self) -> None:
        check = an_analyzing_check()
        lock(check, LOCK_ID)

        record_attempt.apply((check.id,), task_id=OTHER_ID)

        assert lock_ids(check) == [LOCK_ID]

    def test_a_finishing_task_leaves_a_newer_lock_alone(self) -> None:
        """Its lock was replaced while it ran: the new holder keeps the check."""
        check = an_analyzing_check()
        lock(check, LOCK_ID)

        lose_the_lock.apply((check.id,), task_id=LOCK_ID)

        assert lock_ids(check) == [OTHER_ID]

    def test_a_message_for_an_unlocked_check_is_skipped(self) -> None:
        """Its lock is gone, so the check may already be queued again."""
        check = an_analyzing_check()

        record_attempt.apply((check.id,), task_id=OTHER_ID)

        assert attempts == []

    def test_a_direct_call_runs(self) -> None:
        """No Celery message, so no task id, and nothing to be a duplicate of."""
        check = an_analyzing_check()

        record_attempt(check.id)

        assert attempts == [None]

    def test_celerys_retry_runs_again_under_the_same_lock(self) -> None:
        """The retry carries the same task id, so the lock is kept for it."""
        check = an_analyzing_check()
        lock(check, LOCK_ID)

        # throw=False: apply() then re-runs the retry itself, as a worker
        # would; the test settings otherwise propagate the Retry.
        retry_once.apply((check.id,), task_id=LOCK_ID, throw=False)

        assert attempts == [LOCK_ID, LOCK_ID]

    def test_a_retry_is_not_recorded_as_an_error(self) -> None:
        check = an_analyzing_check()
        lock(check, LOCK_ID)

        # throw=False: apply() then re-runs the retry itself, as a worker
        # would; the test settings otherwise propagate the Retry.
        retry_once.apply((check.id,), task_id=LOCK_ID, throw=False)

        check.refresh_from_db()
        assert check.status == Status.ANALYZING


@pytest.mark.django_db
class TestAFailureAfterTheCheckMovedOn:
    """809: a work task failing after another run finished the check."""

    def test_the_check_stays_finished(self) -> None:
        check = an_analyzing_check()
        lock(check, LOCK_ID)

        fail_after_a_finish.apply((check.id,), task_id=LOCK_ID)

        check.refresh_from_db()
        assert (check.status, check.is_manufacturable) == (Status.FINISHED, True)

    def test_the_refused_error_is_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        check = an_analyzing_check()
        lock(check, LOCK_ID)

        with caplog.at_level(logging.WARNING):
            fail_after_a_finish.apply((check.id,), task_id=LOCK_ID)

        assert f"Not recording the error for check {check.id}" in caplog.text


@pytest.mark.parametrize(
    "dispatcher",
    [
        checks_pending,
        checks_dispatching,
        checks_starting,
        checks_running,
        checks_analyzing,
    ],
)
def test_each_dispatcher_has_its_own_short_time_limits(dispatcher: MagicMock) -> None:
    """Not the 30-minute default: a hung dispatcher held a child that long."""
    limits = {
        "soft_time_limit": dispatcher.soft_time_limit,
        "time_limit": dispatcher.time_limit,
    }

    assert limits == DISPATCHER_TIME_LIMITS
    assert dispatcher.time_limit < settings.CELERY_TASK_TIME_LIMIT
