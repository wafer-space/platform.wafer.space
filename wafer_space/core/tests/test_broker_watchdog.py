"""A worker whose consumer stops taking messages exits, loudly (issue #426).

The wedge itself (a main process blocked in libpq's poll()) cannot be made
on demand in a unit test, so these tests pin down each part: when the
watchdog calls it a wedge and when it must not, what it reports before it
exits, that it reads the real kombu tables, and how it is started.

That its thread keeps running while the main thread waits in libpq, as the
wedged worker's main thread did, needs PostgreSQL, which the test settings
don't use; it was checked separately, and the PR that added this shows it.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from celery.signals import task_received
from celery.utils.log import LoggingProxy
from celery.worker import state as worker_state
from django.core import mail
from django.core.cache import cache
from kombu import Connection
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from wafer_space.core import broker_watchdog
from wafer_space.core.broker_watchdog import POSTGRESQL_POLL_LIMITS
from wafer_space.core.broker_watchdog import WATCHDOGS
from wafer_space.core.broker_watchdog import WEDGED_EXIT_CODE
from wafer_space.core.broker_watchdog import BrokerWatchdog
from wafer_space.core.broker_watchdog import WedgeState
from wafer_space.core.broker_watchdog import broker_engine
from wafer_space.core.broker_watchdog import exit_wedged
from wafer_space.core.broker_watchdog import socket_inodes
from wafer_space.core.broker_watchdog import start_watchdog
from wafer_space.core.broker_watchdog import worker_is_busy
from wafer_space.core.log import RateLimitedAdminEmailHandler

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from django.core.mail import EmailMessage
    from pytest_django.fixtures import Settings

LIMIT = 300.0  # WORKER_WEDGE_EXIT_SECONDS
QUEUE = "none:ro:watchdog-test"


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


@pytest.fixture(autouse=True)
def no_running_watchdogs() -> Iterator[None]:
    yield
    for watchdog in WATCHDOGS:
        watchdog.stop.set()
    WATCHDOGS.clear()


class FakeRequest:
    """Stands in for a Celery Request in the worker's (weak) request sets."""


def waited(*, waiting_for: float, received_ago: float) -> tuple[WedgeState, float]:
    """A state where one message has waited ``waiting_for`` s; returns it and now."""
    now = 10_000.0
    state = WedgeState(last_received=now - received_ago)
    state.saw_oldest_waiting(42, now - waiting_for)
    return state, now


class TestWhenItIsAWedge:
    def test_a_message_waiting_with_nothing_taken_for_the_limit(self) -> None:
        state, now = waited(waiting_for=LIMIT, received_ago=LIMIT)

        assert state.is_wedged(now, busy=False, limit=LIMIT)

    @pytest.mark.parametrize(
        ("case", "waiting_for", "received_ago", "busy"),
        [
            # A long task, or a full pool, stops the consumer taking more.
            ("a task is running or reserved", LIMIT * 4, LIMIT * 4, True),
            # The first message after a quiet spell: the last receipt is old.
            ("a message has only just arrived", 1.0, LIMIT * 4, False),
            # max_tasks_per_child: the consumer pauses while a child is replaced.
            ("the pool is replacing a child", LIMIT * 4, 20.0, False),
            ("a message was taken just now", LIMIT * 4, 0.0, False),
            ("one second short of the limit", LIMIT - 1, LIMIT - 1, False),
        ],
    )
    def test_states_that_look_idle_are_not(
        self, case: str, waiting_for: float, received_ago: float, *, busy: bool
    ) -> None:
        state, now = waited(waiting_for=waiting_for, received_ago=received_ago)

        assert not state.is_wedged(now, busy=busy, limit=LIMIT), case

    def test_an_empty_queue_is_not(self) -> None:
        """Also beat pausing: nothing is waiting."""
        now = 10_000.0
        state = WedgeState(last_received=now - LIMIT * 4)
        state.saw_oldest_waiting(None, now - LIMIT * 4)

        assert not state.is_wedged(now, busy=False, limit=LIMIT)

    def test_a_newer_oldest_message_restarts_the_clock(self) -> None:
        """The old one was taken, so the queue is moving."""
        state, now = waited(waiting_for=LIMIT * 4, received_ago=LIMIT * 4)

        state.saw_oldest_waiting(43, now)

        assert not state.is_wedged(now, busy=False, limit=LIMIT)

    def test_the_same_message_seen_again_keeps_its_clock(self) -> None:
        state, now = waited(waiting_for=LIMIT, received_ago=LIMIT)

        state.saw_oldest_waiting(42, now)

        assert state.is_wedged(now, busy=False, limit=LIMIT)

    def test_a_reserved_task_makes_the_worker_busy(self) -> None:
        request = FakeRequest()
        worker_state.reserved_requests.add(request)
        try:
            assert worker_is_busy()
        finally:
            worker_state.reserved_requests.discard(request)

    def test_a_worker_with_no_tasks_is_not_busy(self) -> None:
        assert not worker_is_busy()


class TestWhatItReportsBeforeExiting:
    def test_it_exits_with_the_wedged_code(self) -> None:
        exit_process = MagicMock()

        exit_wedged([QUEUE], LIMIT, exit_process=exit_process)

        exit_process.assert_called_once_with(WEDGED_EXIT_CODE)

    def test_it_emails_admins_through_the_wafer_space_logger(
        self, admin_mail: list[EmailMessage]
    ) -> None:
        exit_wedged([QUEUE], LIMIT, exit_process=MagicMock())

        assert len(admin_mail) == 1
        assert "CRITICAL: Celery worker wedged" in admin_mail[0].subject
        assert f"has waited {int(LIMIT)} s on {QUEUE}" in admin_mail[0].body

    def test_it_logs_every_threads_stack(self, admin_mail: list[EmailMessage]) -> None:
        """In the email too, so the stacks reach ADMINS with the alert."""
        exit_wedged([QUEUE], LIMIT, exit_process=MagicMock())

        assert "Stacks of its threads:" in admin_mail[0].body
        assert "most recent call first" in admin_mail[0].body

    def test_it_works_under_celerys_redirected_stderr(
        self, admin_mail: list[EmailMessage]
    ) -> None:
        """--detach --logfile makes sys.stderr a LoggingProxy, with no fileno()."""
        exit_process = MagicMock()
        proxy = LoggingProxy(logging.getLogger("celery.redirected"))

        with patch.object(sys, "stderr", proxy):
            exit_wedged([QUEUE], LIMIT, exit_process=exit_process)

        exit_process.assert_called_once_with(WEDGED_EXIT_CODE)
        assert "most recent call first" in admin_mail[0].body

    def test_it_exits_even_if_the_report_fails(self) -> None:
        exit_process = MagicMock()

        with (
            patch.object(
                broker_watchdog, "thread_stacks", side_effect=OSError("no space")
            ),
            pytest.raises(OSError, match="no space"),
        ):
            exit_wedged([QUEUE], LIMIT, exit_process=exit_process)

        exit_process.assert_called_once_with(WEDGED_EXIT_CODE)

    def test_it_logs_before_it_exits(self) -> None:
        order: list[str] = []
        with patch.object(
            broker_watchdog.logger, "critical", lambda *_a: order.append("log")
        ):
            exit_wedged([QUEUE], LIMIT, exit_process=lambda _c: order.append("exit"))

        assert order == ["log", "exit"]

    def test_it_lists_the_processs_sockets_by_inode(self) -> None:
        """The same inode in two processes is a shared broker connection."""
        with socket.socket() as sock:
            fd = sock.fileno()
            assert socket_inodes()[fd] == f"socket:[{os.fstat(fd).st_ino}]"


@pytest.fixture
def broker_url(tmp_path: Path) -> str:
    """A kombu SQLAlchemy broker URL on its own SQLite file.

    The test settings use SQLite, as #430's fork tests do; the query is
    plain SQL that PostgreSQL runs the same way.
    """
    return f"sqla+sqlite:///{tmp_path / 'broker.sqlite'}"


@pytest.fixture
def kombu_broker(broker_url: str) -> Iterator[Connection]:
    """A real kombu SQLAlchemy broker, its tables made by kombu itself."""
    broker = Connection(broker_url)
    yield broker
    broker.release()


def watchdog_on(broker_url: str) -> BrokerWatchdog:
    engine = broker_engine(broker_url)
    assert engine is not None
    return BrokerWatchdog(engine, [QUEUE])


class TestItReadsTheBroker:
    def test_it_finds_the_oldest_message_waiting(
        self, kombu_broker: Connection, broker_url: str
    ) -> None:
        queue = kombu_broker.SimpleQueue(QUEUE)
        queue.put({"n": 1})
        queue.put({"n": 2})
        with create_engine(broker_url.removeprefix("sqla+")).connect() as conn:
            first = conn.execute(text("SELECT min(id) FROM kombu_message")).scalar()

        assert watchdog_on(broker_url).oldest_waiting_id() == first

    def test_a_taken_message_is_not_waiting(
        self, kombu_broker: Connection, broker_url: str
    ) -> None:
        queue = kombu_broker.SimpleQueue(QUEUE)
        queue.put({"n": 1})
        queue.get(timeout=5).ack()

        assert watchdog_on(broker_url).oldest_waiting_id() is None

    def test_another_queues_message_is_not_counted(
        self, kombu_broker: Connection, broker_url: str
    ) -> None:
        kombu_broker.SimpleQueue("none:ro:someone-else").put({"n": 1})
        kombu_broker.SimpleQueue(QUEUE)

        assert watchdog_on(broker_url).oldest_waiting_id() is None

    def test_a_broker_outage_is_not_counted_as_waiting(self, broker_url: str) -> None:
        """After the database comes back, the same message's clock restarts."""
        watchdog = watchdog_on(broker_url)
        watchdog.state.last_received = 0.0
        error = OperationalError("SELECT", {}, OSError("connection refused"))
        with patch.object(watchdog, "oldest_waiting_id", return_value=42):
            watchdog.poll_once(10.0)
        with patch.object(watchdog, "oldest_waiting_id", side_effect=error):
            watchdog.poll_once(10.0 + LIMIT)

        with patch.object(watchdog, "oldest_waiting_id", return_value=42):
            wedged = watchdog.poll_once(10.0 + LIMIT + 30)

        assert not wedged

    def test_an_unreadable_broker_is_logged_not_called_a_wedge(
        self, admin_mail: list[EmailMessage], broker_url: str
    ) -> None:
        watchdog = watchdog_on(broker_url)
        error = OperationalError("SELECT", {}, OSError("connection refused"))

        with patch.object(watchdog, "oldest_waiting_id", side_effect=error):
            wedged = watchdog.poll_once(time.monotonic())

        assert (wedged, len(admin_mail)) == (False, 1)


class TestStartingIt:
    def consumer(self, broker_url: str) -> SimpleNamespace:
        return SimpleNamespace(
            app=SimpleNamespace(conf=SimpleNamespace(broker_url=broker_url)),
            task_consumer=SimpleNamespace(queues=[SimpleNamespace(name=QUEUE)]),
        )

    def test_worker_ready_starts_it_for_the_workers_queues(self) -> None:
        start_watchdog(self.consumer("sqla+postgresql:///wafer_space"))

        assert [w.queues for w in WATCHDOGS] == [[QUEUE]]

    def test_its_thread_is_a_daemon(self) -> None:
        """A normal shutdown is never held up by it."""
        start_watchdog(self.consumer("sqla+postgresql:///wafer_space"))

        threads = [t for t in threading.enumerate() if t.name == "broker-watchdog"]
        assert threads
        assert all(t.daemon for t in threads)

    def test_a_broker_that_is_not_sqlalchemy_gets_none(self) -> None:
        start_watchdog(self.consumer("memory://"))

        assert WATCHDOGS == []

    def test_its_engine_is_not_kombus(self) -> None:
        """Its own engine and pool, with no connection kept between polls."""
        engine = broker_engine("sqla+postgresql:///wafer_space")

        assert engine is not None
        assert type(engine.pool).__name__ == "NullPool"

    def test_its_postgresql_polls_cannot_hang(self) -> None:
        """A hung poll would silence the watchdog in the very failure it guards."""
        with patch.object(broker_watchdog, "create_engine") as create:
            broker_engine("sqla+postgresql://u@db/wafer_space")

        assert create.call_args.kwargs["connect_args"] == POSTGRESQL_POLL_LIMITS

    def test_its_postgresql_limits_are_ten_seconds(self) -> None:
        assert (
            POSTGRESQL_POLL_LIMITS["connect_timeout"],
            POSTGRESQL_POLL_LIMITS["options"],
        ) == (10, "-c statement_timeout=10000")

    def test_sqlite_gets_no_libpq_parameters(self) -> None:
        with patch.object(broker_watchdog, "create_engine") as create:
            broker_engine("sqla+sqlite:///broker.sqlite")

        assert create.call_args.kwargs["connect_args"] == {}

    def test_a_received_message_is_noted(self) -> None:
        """config/celery.py connects it to task_received."""
        watchdog = BrokerWatchdog(MagicMock(), [QUEUE])
        watchdog.state.last_received = 0.0
        WATCHDOGS.append(watchdog)

        task_received.send(sender=None, request=None)

        assert watchdog.state.last_received > 0.0

    def test_an_unexpected_error_that_stops_it_is_reported(
        self, admin_mail: list[EmailMessage], settings: Settings
    ) -> None:
        """Else the worker would run on unwatched, and no one would know."""
        settings.WORKER_WEDGE_POLL_SECONDS = 0
        watchdog = BrokerWatchdog(MagicMock(), [QUEUE])

        with (
            patch.object(watchdog, "poll_once", side_effect=KeyError("surprise")),
            pytest.raises(KeyError, match="surprise"),
        ):
            watchdog.run()

        assert len(admin_mail) == 1
        assert "CRITICAL: Broker watchdog stopped" in admin_mail[0].subject

    def test_stopping_it_on_purpose_is_not_reported(
        self, admin_mail: list[EmailMessage]
    ) -> None:
        watchdog = BrokerWatchdog(MagicMock(), [QUEUE])
        watchdog.stop.set()

        watchdog.run()

        assert admin_mail == []

    def test_a_wedge_found_by_a_poll_exits(self, settings: Settings) -> None:
        settings.WORKER_WEDGE_POLL_SECONDS = 0
        watchdog = BrokerWatchdog(MagicMock(), [QUEUE])

        with (
            patch.object(watchdog, "poll_once", return_value=True),
            patch.object(
                broker_watchdog,
                "exit_wedged",
                side_effect=lambda *_a: watchdog.stop.set(),
            ) as exit_wedged_mock,
        ):
            watchdog.run()

        exit_wedged_mock.assert_called_once()
