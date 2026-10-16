"""One ADMINS email per error signature per hour across processes (#450).

RateLimitedAdminEmailHandler kept its window in the LocMem cache, which is
per process, so one checks-orch stall sent an email from each process that
logged it: up to 4 an hour on test-platform. The window is now a row in
the database, claimed on a connection of the handler's own.

Clearing the LocMem cache stands in for another process: it is all a
process keeps to itself. The claims commit on their own connection, which
a test's transaction can't roll back, so these tests use transactional_db.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any

import pytest
from celery.app.task import Task
from django.core import mail
from django.core.cache import cache
from django.db import OperationalError
from django.db import connection
from django.db import transaction
from django.utils import timezone
from kombu.exceptions import OperationalError as BrokerError

from wafer_space.core import log as core_log
from wafer_space.core.log import RateLimitedAdminEmailHandler
from wafer_space.core.models import AdminEmailClaim
from wafer_space.core.models import AdminEmailClaimManager
from wafer_space.users.models import User

if TYPE_CHECKING:
    from collections.abc import Iterator

STALL = "checks-orch stalled: last checks_running %s s ago"
HAND_OFF_LOGGER = "admin_email_hand_off"
# How long a test lets the handler wait for a claim that hangs
TEST_CLAIM_TIMEOUT = 0.2
HUNG_SECONDS = 3.0
TWO_EMAILS = 2
TEN_MINUTES = 10 * 60
# Time the test itself may take between setting a claim and reading it back
SLACK_SECONDS = 30

pytestmark = pytest.mark.django_db(transaction=True)


def stall_record(seconds: int = 600) -> logging.LogRecord:
    return logging.LogRecord(
        name="wafer_space.projects.tasks_checks",
        level=logging.CRITICAL,
        pathname=__file__,
        lineno=1,
        msg=STALL,
        args=(seconds,),
        exc_info=None,
    )


def another_process() -> None:
    """Forget everything this process noted; the database remembers."""
    cache.clear()


@pytest.fixture(autouse=True)
def _shared_limit(settings: Any) -> Iterator[None]:
    settings.ADMIN_EMAIL_RATE_LIMIT_SHARED = True
    cache.clear()
    yield
    cache.clear()


class TestOneEmailAcrossProcesses:
    def test_the_first_process_sends(self) -> None:
        RateLimitedAdminEmailHandler().emit(stall_record())

        assert len(mail.outbox) == 1
        assert AdminEmailClaim.objects.count() == 1

    def test_another_process_within_the_hour_sends_none(self) -> None:
        RateLimitedAdminEmailHandler().emit(stall_record(600))
        for seconds in (660, 720, 780):
            another_process()
            RateLimitedAdminEmailHandler().emit(stall_record(seconds))

        assert len(mail.outbox) == 1

    def test_a_process_sends_again_once_the_hour_has_passed(self) -> None:
        RateLimitedAdminEmailHandler().emit(stall_record())
        AdminEmailClaim.objects.update(sent_at=timezone.now() - timedelta(hours=2))
        another_process()

        RateLimitedAdminEmailHandler().emit(stall_record())

        assert len(mail.outbox) == TWO_EMAILS
        assert AdminEmailClaim.objects.count() == 1

    def test_a_refused_process_asks_again_only_when_that_hour_ends(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A repeating error asks the database once per window, not per record."""
        RateLimitedAdminEmailHandler().emit(stall_record())
        another_process()
        asked: list[str] = []
        claim = core_log.claim_admin_email

        def counting_claim(signature: str, now: Any) -> Any:
            asked.append(signature)
            return claim(signature, now)

        monkeypatch.setattr(core_log, "claim_admin_email", counting_claim)
        handler = RateLimitedAdminEmailHandler()

        for seconds in (660, 720, 780):
            handler.emit(stall_record(seconds))

        assert len(asked) == 1

    def test_a_refused_process_waits_out_the_rest_of_that_hour(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        RateLimitedAdminEmailHandler().emit(stall_record())
        AdminEmailClaim.objects.update(sent_at=timezone.now() - timedelta(minutes=50))
        another_process()
        timeouts: list[float] = []
        set_key = cache.set

        def recording_set(key: str, value: object, timeout: float) -> None:
            timeouts.append(timeout)
            set_key(key, value, timeout)

        monkeypatch.setattr(cache, "set", recording_set)

        RateLimitedAdminEmailHandler().emit(stall_record())

        assert len(timeouts) == 1
        assert TEN_MINUTES - SLACK_SECONDS < timeouts[0] <= TEN_MINUTES

    def test_distinct_errors_each_send(self) -> None:
        RateLimitedAdminEmailHandler().emit(stall_record())
        another_process()
        other = stall_record()
        other.msg = "checks-orch broker error: %s"

        RateLimitedAdminEmailHandler().emit(other)

        assert len(mail.outbox) == TWO_EMAILS


class TestTheCallersTransaction:
    def test_a_failed_transaction_is_left_failed_and_the_email_sent(self) -> None:
        """Logging inside a failed transaction neither queries on it nor ends it."""
        with transaction.atomic():
            try:
                with transaction.atomic(savepoint=False), connection.cursor() as cur:
                    cur.execute("SELECT * FROM no_such_table")
            except OperationalError:
                pass
            assert connection.needs_rollback

            RateLimitedAdminEmailHandler().emit(stall_record())

            assert connection.needs_rollback
            assert connection.in_atomic_block

        assert len(mail.outbox) == 1
        assert AdminEmailClaim.objects.count() == 1

    def test_the_claim_outlives_the_callers_rollback(self) -> None:
        """The claim commits on its own connection, not in the caller's transaction."""
        with transaction.atomic():
            User.objects.filter(username="nobody").exists()
            RateLimitedAdminEmailHandler().emit(stall_record())
            transaction.set_rollback(True)

        assert AdminEmailClaim.objects.count() == 1


@pytest.fixture
def failing_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """The claims table can't be reached, as when the database is down."""

    def fail(*_args: Any, **_kwargs: Any) -> None:
        msg = "connection to server failed"
        raise OperationalError(msg)

    monkeypatch.setattr(AdminEmailClaimManager, "claim", fail)


class TestWhenTheDatabaseFails:
    @pytest.mark.usefixtures("failing_database")
    def test_the_email_is_sent(self) -> None:
        RateLimitedAdminEmailHandler().emit(stall_record())

        assert len(mail.outbox) == 1

    @pytest.mark.usefixtures("failing_database")
    def test_the_process_keeps_its_own_hour(self) -> None:
        handler = RateLimitedAdminEmailHandler()

        for seconds in (600, 660, 720):
            handler.emit(stall_record(seconds))

        assert len(mail.outbox) == 1

    @pytest.mark.usefixtures("failing_database")
    def test_it_says_so_on_the_console_only(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No record goes to a wafer_space logger, so none loops back here."""
        with caplog.at_level(logging.INFO):
            RateLimitedAdminEmailHandler().emit(stall_record())

        assert not [r for r in caplog.records if r.name.startswith("wafer_space")]
        assert {r.name for r in caplog.records if r.levelno >= logging.WARNING} == {
            HAND_OFF_LOGGER
        }
        assert "own rate limit" in caplog.text

    def test_a_hung_database_holds_the_caller_up_briefly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        release = threading.Event()

        def hang(*_args: Any, **_kwargs: Any) -> None:
            release.wait(HUNG_SECONDS)

        monkeypatch.setattr(AdminEmailClaimManager, "claim", hang)
        monkeypatch.setattr(core_log, "CLAIM_TIMEOUT_SECONDS", TEST_CLAIM_TIMEOUT)
        try:
            RateLimitedAdminEmailHandler().emit(stall_record())
        finally:
            release.set()

        assert len(mail.outbox) == 1


class TestALostEmail:
    def test_gives_its_slot_back_to_every_process(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broker_down(*_args: Any, **_kwargs: Any) -> None:
            msg = "broker unreachable"
            raise BrokerError(msg)

        with monkeypatch.context() as patch:
            patch.setattr(Task, "apply_async", broker_down)
            RateLimitedAdminEmailHandler().emit(stall_record())
        for thread in list(core_log.pending_hand_offs):
            thread.join(HUNG_SECONDS)
        another_process()

        RateLimitedAdminEmailHandler().emit(stall_record())

        assert len(mail.outbox) == 1
