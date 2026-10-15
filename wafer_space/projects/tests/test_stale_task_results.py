"""A STARTED result older than the hard time limit is not running (#183).

Reproduced on 15 Oct 2026 with a prefork worker on PostgreSQL: SIGKILL of
the whole worker mid-task left the TaskResult row STARTED, and
checks_cleanup_stale_pending_tasks kept the check's lock ("still_active")
indefinitely. (Killing only the pool child is different: the surviving main
process records FAILURE within a minute and the lock is freed.)
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from celery import current_app
from django.conf import settings
from django.utils import timezone
from django_celery_results.models import TaskResult

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import ManufacturabilityCheckTask
from wafer_space.projects.tasks_checks import checks_cleanup_stale_pending_tasks
from wafer_space.projects.verification import is_check_task_actively_running
from wafer_space.projects.verification import longest_task_time_limit

from .factories import ManufacturabilityCheckFactory

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def not_in_broker_queue() -> Iterator[None]:
    """The test database has no kombu tables; nothing is waiting in the queue."""
    with patch(
        "wafer_space.projects.verification._is_task_in_broker_queue",
        return_value=False,
    ):
        yield


def started_result(*, started_ago: timedelta) -> str:
    """A STARTED TaskResult whose current state began ``started_ago``."""
    task_id = str(uuid.uuid4())
    TaskResult.objects.create(task_id=task_id, status="STARTED")
    # date_done is auto_now, so set it with an update
    TaskResult.objects.filter(task_id=task_id).update(
        date_done=timezone.now() - started_ago
    )
    return task_id


def hard_limit() -> timedelta:
    limit = longest_task_time_limit()
    assert limit is not None
    return timedelta(seconds=limit)


def locked_check(task_id: str) -> ManufacturabilityCheckTask:
    check = ManufacturabilityCheckFactory(status=ManufacturabilityCheck.Status.RUNNING)
    lock = ManufacturabilityCheckTask.objects.create(
        manufacturability_check=check,
        task_id=task_id,
        task_name="do_running",
    )
    ManufacturabilityCheckTask.objects.filter(pk=lock.pk).update(
        queued_at=timezone.now() - timedelta(hours=2)
    )
    return lock


def test_longest_limit_is_the_configured_hard_limit() -> None:
    """Read from settings, and no shorter than any task's own limit."""
    limit = longest_task_time_limit()
    task_limits = [
        task.time_limit
        for task in current_app.tasks.values()
        if task.time_limit is not None
    ]
    assert limit == max([settings.CELERY_TASK_TIME_LIMIT, *task_limits])


def test_recently_started_task_is_running() -> None:
    task_id = started_result(started_ago=timedelta(minutes=1))
    assert is_check_task_actively_running(task_id) is True


def test_started_task_within_the_limit_is_running() -> None:
    task_id = started_result(started_ago=hard_limit() - timedelta(minutes=1))
    assert is_check_task_actively_running(task_id) is True


def test_started_task_past_the_limit_is_not_running(caplog) -> None:
    task_id = started_result(started_ago=hard_limit() + timedelta(minutes=1))
    with caplog.at_level(logging.ERROR, logger="wafer_space.projects.verification"):
        running = is_check_task_actively_running(task_id)
    assert running is False
    assert [r.getMessage() for r in caplog.records if task_id in r.getMessage()]


def test_cleanup_frees_the_lock_of_a_dead_worker_only() -> None:
    """End to end: the lock left by a dead worker goes, a live one stays."""
    dead = locked_check(started_result(started_ago=hard_limit() + timedelta(1)))
    live = locked_check(started_result(started_ago=timedelta(minutes=5)))

    result = checks_cleanup_stale_pending_tasks.run()

    remaining = set(ManufacturabilityCheckTask.objects.values_list("pk", flat=True))
    assert result == {"deleted": 1, "still_active": 1}
    assert remaining == {live.pk}
    assert dead.pk not in remaining
