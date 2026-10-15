"""ADMINS hear when checks-orch stops running its dispatchers (issue #426).

On 16 Oct 2026 the checks-orch worker wedged twice while systemd showed it
running, and no one was told. checks_orch_stalled reads when checks_running,
which checks-orch runs every 15 s, last recorded a result.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from django_celery_results.models import TaskResult

from config.celery import app
from wafer_space.core.log import RateLimitedAdminEmailHandler
from wafer_space.projects.tasks_checks import CHECKS_RUNNING_TASK_NAME
from wafer_space.projects.tasks_checks import checks_orch_stalled

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.core.mail import EmailMessage

pytestmark = pytest.mark.django_db

ALERT_TASK_NAME = "wafer_space.projects.tasks_checks.checks_orch_stalled"
CHECKS_ORCH_QUEUE = "none:ro:checks-orch"
LIMIT = timedelta(seconds=settings.CHECKS_ORCH_STALL_ALERT_SECONDS)


@pytest.fixture
def admin_mail() -> Iterator[list[EmailMessage]]:
    """Route wafer_space.* ERRORs to ADMINS email, as prod and stage LOGGING do."""
    cache.clear()
    handler = RateLimitedAdminEmailHandler()
    handler.setLevel(logging.ERROR)  # "level": "ERROR" in prod LOGGING
    app_logger = logging.getLogger("wafer_space")
    app_logger.addHandler(handler)
    yield mail.outbox
    app_logger.removeHandler(handler)
    cache.clear()


def a_result(task_name: str | None, age: timedelta) -> None:
    """A result row for ``task_name`` that finished ``age`` ago."""
    row = TaskResult.objects.create(
        task_id=str(uuid.uuid4()), task_name=task_name, status="SUCCESS"
    )
    # date_done is auto_now, so set it after the row is written.
    TaskResult.objects.filter(pk=row.pk).update(date_done=timezone.now() - age)


class TestWhenItAlerts:
    def test_checks_running_with_no_result_for_over_the_limit(
        self, admin_mail: list[EmailMessage]
    ) -> None:
        a_result(CHECKS_RUNNING_TASK_NAME, LIMIT + timedelta(minutes=1))

        assert checks_orch_stalled()["stalled"]
        assert len(admin_mail) == 1

    def test_the_email_is_critical_and_names_checks_orch(
        self, admin_mail: list[EmailMessage]
    ) -> None:
        a_result(CHECKS_RUNNING_TASK_NAME, LIMIT + timedelta(minutes=1))

        checks_orch_stalled()

        assert "CRITICAL: checks-orch has stalled" in admin_mail[0].subject

    def test_checks_running_has_no_result_at_all(
        self, admin_mail: list[EmailMessage]
    ) -> None:
        assert checks_orch_stalled() == {"stalled": True, "last_done": None}
        assert len(admin_mail) == 1

    def test_a_recent_row_without_a_task_name_does_not_count(self) -> None:
        """A row written before CELERY_RESULT_EXTENDED was set: no task_name."""
        a_result(None, timedelta(seconds=5))

        assert checks_orch_stalled()["stalled"]

    def test_another_tasks_recent_row_does_not_count(self) -> None:
        a_result("wafer_space.projects.tasks_checks.checks_pending", timedelta())

        assert checks_orch_stalled()["stalled"]

    def test_a_repeat_sends_no_second_email_within_the_hour(
        self, admin_mail: list[EmailMessage]
    ) -> None:
        """It runs every 60 s; RateLimitedAdminEmailHandler keeps it to one."""
        checks_orch_stalled()
        checks_orch_stalled()

        assert len(admin_mail) == 1


class TestWhenItStaysQuiet:
    def test_a_recent_checks_running_result(
        self, admin_mail: list[EmailMessage]
    ) -> None:
        a_result(CHECKS_RUNNING_TASK_NAME, timedelta(minutes=1))

        assert not checks_orch_stalled()["stalled"]
        assert admin_mail == []

    def test_just_inside_the_limit(self) -> None:
        a_result(CHECKS_RUNNING_TASK_NAME, LIMIT - timedelta(seconds=5))

        assert not checks_orch_stalled()["stalled"]

    def test_an_old_row_beside_a_recent_one(self) -> None:
        a_result(CHECKS_RUNNING_TASK_NAME, timedelta(hours=2))
        a_result(CHECKS_RUNNING_TASK_NAME, timedelta(seconds=15))

        assert not checks_orch_stalled()["stalled"]

    def test_a_row_the_result_backend_wrote(self) -> None:
        """The real django-db backend stores task_name now it is extended."""
        request = SimpleNamespace(task=CHECKS_RUNNING_TASK_NAME, id="r1")
        app.backend.store_result("r1", {"queued": 0}, "SUCCESS", request=request)

        assert not checks_orch_stalled()["stalled"]


class TestWhereItRuns:
    def test_result_extended_reaches_celery(self) -> None:
        """Without it TaskResult.task_name is never written."""
        assert app.conf.result_extended is True

    def test_it_is_routed_to_the_default_worker(self) -> None:
        route = app.amqp.router.route(
            {"queue": checks_orch_stalled.queue}, ALERT_TASK_NAME
        )

        assert route["queue"].name == "none:ro:default"

    def test_it_never_runs_on_checks_orch(self) -> None:
        """A wedged checks-orch would never run its own alert."""
        assert checks_orch_stalled.queue != CHECKS_ORCH_QUEUE

    def test_beat_runs_it_every_minute(self) -> None:
        entries = [
            entry
            for entry in settings.CELERY_BEAT_SCHEDULE.values()
            if entry["task"] == ALERT_TASK_NAME
        ]

        assert [entry["schedule"] for entry in entries] == [60.0]
