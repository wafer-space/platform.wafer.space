"""ADMINS emails are handed to the mail worker, never sent in-process (#439).

Six deployed workers have no network by design (none:ro:* and dock:*), so
an in-process send waited for anymail's 30 s timeout and failed silently:
the stall alert, the watchdog's CRITICAL and every wafer_space ERROR from
those workers were lost. The handler now publishes the email to
mail:ro:email, the worker built to send mail, and never blocks the caller
for long, even when the broker is down or wedged.

These tests patch the two ways out of the process: Celery's publish
(``Task.apply_async``) and anymail's HTTP call (``requests.Session.request``).
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from typing import TYPE_CHECKING
from typing import Any

import pytest
import requests
from celery.app.task import Task
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from kombu.exceptions import OperationalError

from wafer_space.core import log as core_log
from wafer_space.core.debug import scrub_url_credentials
from wafer_space.core.log import RateLimitedAdminEmailHandler

if TYPE_CHECKING:
    from collections.abc import Iterator

# Mailgun's key in these tests: the HTTP call it would sign is patched out
PLACEHOLDER = "placeholder"
# A credential that must never leave the process unscrubbed (#339)
SENTINEL = "sentinel-not-a-real-credential"
SECRET_URL = f"postgresql://wafer:{SENTINEL}@db.example/wafer"
MAIL_QUEUE = "mail:ro:email"
TASKS_MODULE = "wafer_space.core.tasks"
MAIL_TASK = f"{TASKS_MODULE}.send_admin_email"
# Long enough that a blocked hand-off shows; the tests release it after
BLOCKED_SECONDS = 3.0
# How long a test lets the handler wait for a blocked hand-off
TEST_HAND_OFF_TIMEOUT = 0.2
# A caller blocked for less than this was not blocked by the hand-off
NOT_BLOCKED_SECONDS = 1.5


def error_record(msg: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord(
        name="wafer_space.projects.tasks_checks",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


@pytest.fixture(autouse=True)
def _clean_cache() -> Iterator[None]:
    """Isolate the handler's rate-limit keys between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def anymail_backend(settings: Any) -> None:
    """A deployed worker's mail backend; the API key is a placeholder."""
    settings.EMAIL_BACKEND = "anymail.backends.mailgun.EmailBackend"
    settings.ANYMAIL = {"MAILGUN_API_KEY": PLACEHOLDER}


class Exits:
    """What left the process: published tasks and HTTP requests."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str | None, Any]] = []
        self.http: list[str] = []


@pytest.fixture
def exits(monkeypatch: pytest.MonkeyPatch) -> Exits:
    """Record each publish and each HTTP request instead of making it."""
    seen = Exits()

    def publish(task: Task, args: Any = None, kwargs: Any = None, **_: Any) -> None:
        seen.published.append((task.name, task.queue, args))

    def http(_session: requests.Session, method: str, url: str, **_: Any) -> None:
        seen.http.append(f"{method} {url}")
        msg = "no network in this worker"
        raise requests.ConnectionError(msg)

    monkeypatch.setattr(Task, "apply_async", publish)
    monkeypatch.setattr(requests.Session, "request", http)
    return seen


@pytest.fixture
def blocked(monkeypatch: pytest.MonkeyPatch) -> Iterator[threading.Event]:
    """The broker (and the network) hang, as in a wedged worker.

    Each call waits until the test releases it, or BLOCKED_SECONDS, then
    fails. The handler waits TEST_HAND_OFF_TIMEOUT for a hand-off.
    """
    release = threading.Event()

    def hang_publish(*_args: Any, **_kwargs: Any) -> None:
        release.wait(BLOCKED_SECONDS)
        msg = "broker unreachable"
        raise OperationalError(msg)

    def hang_http(*_args: Any, **_kwargs: Any) -> None:
        release.wait(BLOCKED_SECONDS)
        msg = "no network in this worker"
        raise requests.ConnectTimeout(msg)

    monkeypatch.setattr(Task, "apply_async", hang_publish)
    monkeypatch.setattr(requests.Session, "request", hang_http)
    monkeypatch.setattr(
        core_log, "HAND_OFF_TIMEOUT_SECONDS", TEST_HAND_OFF_TIMEOUT, raising=False
    )
    yield release
    release.set()
    # The hung hand-offs end now; none may log into a later test
    for thread in list(core_log.pending_hand_offs):
        thread.join(BLOCKED_SECONDS)


@pytest.mark.usefixtures("anymail_backend")
class TestAnErrorInAWorker:
    def test_enqueues_exactly_one_mail_task_on_the_mail_queue(
        self, exits: Exits
    ) -> None:
        RateLimitedAdminEmailHandler().emit(error_record("Dispatch failed: %s", 1))

        assert [(name, queue) for name, queue, _ in exits.published] == [
            (MAIL_TASK, MAIL_QUEUE)
        ]

    def test_makes_no_http_call(self, exits: Exits) -> None:
        RateLimitedAdminEmailHandler().emit(error_record("Dispatch failed: %s", 1))

        assert exits.http == []

    def test_hands_off_scrubbed_content(self, exits: Exits) -> None:
        """#339's scrubbing happens before the email leaves the process."""
        RateLimitedAdminEmailHandler().emit(
            error_record("Broker %s refused the connection", SECRET_URL)
        )

        [(_, _, args)] = exits.published
        assert SENTINEL not in repr(args)
        assert scrub_url_credentials(SECRET_URL) in args[1]

    def test_the_rate_limit_still_holds(self, exits: Exits) -> None:
        """#293: one email per signature per window, counted before enqueueing."""
        handler = RateLimitedAdminEmailHandler()

        for check_id in (1, 2, 3):
            handler.emit(error_record("Dispatch failed: %s", check_id))

        assert len(exits.published) == 1


class TestTheMailTask:
    def test_sends_one_email_with_the_content(self) -> None:
        # Looked up here, not imported at the top, so that on code without
        # the task only this test fails
        send_admin_email = importlib.import_module(TASKS_MODULE).send_admin_email

        send_admin_email("subject", "the body", "<p>the body</p>")

        [email] = mail.outbox
        assert isinstance(email, EmailMultiAlternatives)
        assert (email.subject, email.body, email.alternatives[0][0]) == (
            f"{settings.EMAIL_SUBJECT_PREFIX}subject",
            "the body",
            "<p>the body</p>",
        )

    def test_the_handler_and_the_task_deliver_scrubbed_content(self) -> None:
        """In tests Celery runs the task eagerly, so this is the whole path."""
        RateLimitedAdminEmailHandler().emit(
            error_record("Broker %s refused the connection", SECRET_URL)
        )

        [email] = mail.outbox
        assert (
            SENTINEL in f"{email.subject}{email.body}",
            scrub_url_credentials(SECRET_URL) in email.body,
        ) == (False, True)


def break_the_way_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """The broker refuses the publish; the network refuses anymail."""

    def broker(*_args: Any, **_kwargs: Any) -> None:
        msg = "broker unreachable"
        raise OperationalError(msg)

    def http(*_args: Any, **_kwargs: Any) -> None:
        msg = "no network in this worker"
        raise requests.ConnectionError(msg)

    monkeypatch.setattr(Task, "apply_async", broker)
    monkeypatch.setattr(requests.Session, "request", http)


@pytest.mark.usefixtures("anymail_backend")
class TestABrokerFailureDuringTheHandOff:
    def test_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        break_the_way_out(monkeypatch)

        RateLimitedAdminEmailHandler().emit(error_record("Dispatch failed: %s", 1))

    def test_is_logged_loudly_to_the_console(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        break_the_way_out(monkeypatch)

        with caplog.at_level(logging.ERROR):
            RateLimitedAdminEmailHandler().emit(error_record("Dispatch failed: %s", 1))

        assert [
            (r.levelno, "Dispatch failed: 1" in r.getMessage())
            for r in caplog.records
            if "ADMINS email" in r.getMessage()
        ] == [(logging.ERROR, True)]

    def test_the_console_record_carries_the_broker_error(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The traceback is in the worker log, next to the lost email."""
        break_the_way_out(monkeypatch)
        # Anything left to threading.excepthook would not be in caplog
        monkeypatch.setattr(threading, "excepthook", lambda _args: None)

        with caplog.at_level(logging.ERROR):
            RateLimitedAdminEmailHandler().emit(error_record("Dispatch failed: %s", 1))

        [record] = [r for r in caplog.records if "ADMINS email" in r.getMessage()]
        assert record.exc_info is not None
        assert record.exc_info[0] is OperationalError

    def test_a_lost_email_does_not_silence_the_next(
        self, monkeypatch: pytest.MonkeyPatch, exits: Exits
    ) -> None:
        """The rate-limit slot is given back when the hand-off fails."""
        handler = RateLimitedAdminEmailHandler()
        recording = Task.apply_async
        break_the_way_out(monkeypatch)
        handler.emit(error_record("Dispatch failed: %s", 1))

        monkeypatch.setattr(Task, "apply_async", recording)
        handler.emit(error_record("Dispatch failed: %s", 2))

        assert len(exits.published) == 1

    def test_a_slow_publish_that_succeeds_keeps_its_slot(
        self, monkeypatch: pytest.MonkeyPatch, exits: Exits
    ) -> None:
        """Past the caller's wait it may still arrive, so no second email."""
        release = threading.Event()
        recording = Task.apply_async

        def slow(task: Task, *args: Any, **kwargs: Any) -> None:
            release.wait(BLOCKED_SECONDS)
            recording(task, *args, **kwargs)

        monkeypatch.setattr(Task, "apply_async", slow)
        monkeypatch.setattr(core_log, "HAND_OFF_TIMEOUT_SECONDS", TEST_HAND_OFF_TIMEOUT)
        handler = RateLimitedAdminEmailHandler()
        handler.emit(error_record("Dispatch failed: %s", 1))
        release.set()
        for thread in list(core_log.pending_hand_offs):
            thread.join(BLOCKED_SECONDS)

        handler.emit(error_record("Dispatch failed: %s", 2))

        assert len(exits.published) == 1

    def test_a_slow_publish_that_fails_gives_its_slot_back(
        self, monkeypatch: pytest.MonkeyPatch, exits: Exits
    ) -> None:
        """It fails after the caller stopped waiting; the next one is sent."""
        release = threading.Event()
        recording = Task.apply_async

        def slow_then_broken(*_args: Any, **_kwargs: Any) -> None:
            release.wait(BLOCKED_SECONDS)
            msg = "broker unreachable"
            raise OperationalError(msg)

        monkeypatch.setattr(Task, "apply_async", slow_then_broken)
        monkeypatch.setattr(core_log, "HAND_OFF_TIMEOUT_SECONDS", TEST_HAND_OFF_TIMEOUT)
        handler = RateLimitedAdminEmailHandler()
        handler.emit(error_record("Dispatch failed: %s", 1))
        release.set()
        for thread in list(core_log.pending_hand_offs):
            thread.join(BLOCKED_SECONDS)

        monkeypatch.setattr(Task, "apply_async", recording)
        handler.emit(error_record("Dispatch failed: %s", 2))

        assert len(exits.published) == 1

    def test_an_email_dropped_at_the_cap_gives_its_slot_back(
        self, monkeypatch: pytest.MonkeyPatch, exits: Exits
    ) -> None:
        release = threading.Event()
        recording = Task.apply_async

        def hang(*_args: Any, **_kwargs: Any) -> None:
            release.wait(BLOCKED_SECONDS)

        monkeypatch.setattr(Task, "apply_async", hang)
        monkeypatch.setattr(core_log, "HAND_OFF_TIMEOUT_SECONDS", TEST_HAND_OFF_TIMEOUT)
        handler = RateLimitedAdminEmailHandler()
        for n in range(core_log.MAX_PENDING_HAND_OFFS):
            handler.emit(error_record(f"Distinct failure {n}"))
        handler.emit(error_record("Dropped at the cap"))
        release.set()
        for thread in list(core_log.pending_hand_offs):
            thread.join(BLOCKED_SECONDS)

        monkeypatch.setattr(Task, "apply_async", recording)
        handler.emit(error_record("Dropped at the cap"))

        assert [args[1].splitlines()[0] for _, _, args in exits.published] == [
            "Dropped at the cap"
        ]

    def test_an_unexpected_error_still_names_the_lost_email(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def odd(*_args: Any, **_kwargs: Any) -> None:
            msg = "not a broker error"
            raise LookupError(msg)

        monkeypatch.setattr(Task, "apply_async", odd)
        # The thread's own traceback goes to threading.excepthook
        monkeypatch.setattr(threading, "excepthook", lambda _args: None)

        with caplog.at_level(logging.ERROR):
            RateLimitedAdminEmailHandler().emit(error_record("Dispatch failed: %s", 1))

        assert any(
            "ADMINS email not handed" in r.getMessage()
            and "Dispatch failed: 1" in r.getMessage()
            for r in caplog.records
        )

    def test_a_hung_broker_holds_at_most_the_cap_of_threads(
        self, blocked: threading.Event, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Further emails are dropped, and each drop is logged."""
        handler = RateLimitedAdminEmailHandler()

        with caplog.at_level(logging.ERROR):
            for n in range(core_log.MAX_PENDING_HAND_OFFS + 1):
                handler.emit(error_record(f"Distinct failure {n}"))

        messages = [r.getMessage() for r in caplog.records]
        assert len([m for m in messages if "ADMINS email dropped" in m]) == 1

    def test_does_not_block_the_caller(self, blocked: threading.Event) -> None:
        start = time.monotonic()

        RateLimitedAdminEmailHandler().emit(error_record("Dispatch failed: %s", 1))

        assert time.monotonic() - start < NOT_BLOCKED_SECONDS

    def test_a_hand_off_still_pending_is_logged(
        self, blocked: threading.Event, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.ERROR):
            RateLimitedAdminEmailHandler().emit(error_record("Dispatch failed: %s", 1))

        assert any(
            "ADMINS email" in r.getMessage() and "Dispatch failed: 1" in r.getMessage()
            for r in caplog.records
        )
