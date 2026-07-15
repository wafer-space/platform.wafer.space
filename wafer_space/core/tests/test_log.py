"""Tests for rate-limited admin error emails and task-failure reporting."""

from __future__ import annotations

import logging

import pytest
from celery.signals import task_failure
from django.core import mail
from django.core.cache import cache

from config.celery import report_task_failure
from wafer_space.core.log import RateLimitedAdminEmailHandler

SEPARATE_EMAILS = 2


def _record(
    msg: str,
    args: tuple = (),
    name: str = "wafer_space.test",
) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


@pytest.fixture(autouse=True)
def _clean_cache():
    """Isolate the handler's rate-limit keys between tests."""
    cache.clear()
    yield
    cache.clear()


class TestRateLimitedAdminEmailHandler:
    """Tests for RateLimitedAdminEmailHandler deduplication."""

    def test_first_error_sends_admin_email(self):
        """A new error signature emails ADMINS."""
        handler = RateLimitedAdminEmailHandler()

        handler.emit(_record("metadata fetch failed for %s", args=("abc",)))

        assert len(mail.outbox) == 1

    def test_repeated_template_sends_only_one_email(self):
        """Same message template with different args is one signature."""
        handler = RateLimitedAdminEmailHandler()

        handler.emit(_record("metadata fetch failed for %s", args=("abc",)))
        handler.emit(_record("metadata fetch failed for %s", args=("def",)))
        handler.emit(_record("metadata fetch failed for %s", args=("ghi",)))

        assert len(mail.outbox) == 1

    def test_different_templates_send_separate_emails(self):
        """Distinct message templates are distinct signatures."""
        handler = RateLimitedAdminEmailHandler()

        handler.emit(_record("metadata fetch failed for %s", args=("abc",)))
        handler.emit(_record("container cleanup failed for %s", args=("abc",)))

        assert len(mail.outbox) == SEPARATE_EMAILS

    def test_different_logger_names_send_separate_emails(self):
        """The same template from different loggers is reported separately."""
        handler = RateLimitedAdminEmailHandler()

        handler.emit(_record("something failed", name="wafer_space.a"))
        handler.emit(_record("something failed", name="wafer_space.b"))

        assert len(mail.outbox) == SEPARATE_EMAILS


class TestReportTaskFailure:
    """Tests for the celery task_failure -> wafer_space logger bridge."""

    def test_receiver_logs_task_name_and_id(self, caplog):
        """Direct call logs an ERROR naming the task and its id."""
        sender = type("DummyTask", (), {"name": "wafer_space.projects.boom"})

        with caplog.at_level(logging.ERROR, logger="wafer_space.celery"):
            report_task_failure(
                sender=sender,
                task_id="task-id-123",
                exception=RuntimeError("kaboom"),
                einfo=None,
            )

        assert any(
            "wafer_space.projects.boom" in record.message
            and "task-id-123" in record.message
            and record.levelno == logging.ERROR
            for record in caplog.records
        )

    def test_signal_dispatch_reaches_wafer_space_logger(self, caplog):
        """Firing the celery signal itself reaches the wafer_space tree."""
        sender = type("DummyTask", (), {"name": "wafer_space.projects.boom"})

        with caplog.at_level(logging.ERROR, logger="wafer_space.celery"):
            task_failure.send(
                sender=sender,
                task_id="signal-task-456",
                exception=RuntimeError("kaboom"),
                einfo=None,
                args=(),
                kwargs={},
                traceback=None,
            )

        assert "signal-task-456" in caplog.text
        assert "kaboom" in caplog.text
