"""Exit a Celery worker whose consumer has stopped taking messages (issue #426).

On 16 Oct 2026 production's checks-orch worker wedged twice. Its main
process stayed alive, so systemd showed it running, while messages waited on
its queue and nothing took them. The first time it was blocked in libpq's
poll() with no error after a broker DatabaseError; the second time nothing
was logged at all. PR #430 fixed the cause that was found (a prefork child
sharing the parent's broker connection). This watchdog makes any wedge, of
whatever cause, fail fast and loud instead of lasting until someone notices:
it logs CRITICAL (which emails ADMINS), dumps every thread's stack, lists the
process's sockets, and exits so systemd restarts the worker.

It runs as a thread in the worker's main process, started by worker_ready.
Every WORKER_WEDGE_POLL_SECONDS it asks the broker, over its own connection
(not kombu's engine), for the lowest id of a message still waiting on the
worker's queues. The worker is wedged when, for WORKER_WEDGE_EXIT_SECONDS:
- the same message has been waiting (kombu leaves a waiting message's
  timestamp NULL, so the watchdog tracks the message id across polls), and
- the worker has received no message at all (task_received), and
- the worker has no task reserved or running.

The last condition keeps it from exiting while tasks run: a long task, or a
full pool, legitimately stops the consumer from taking more. Other states
that look idle but are not wedges, and why they don't trigger it:
- an empty queue, or beat pausing: no message is waiting;
- a message that has only just arrived after a quiet spell: it has not been
  waiting long, though the last receipt was long ago;
- the pool replacing a child (max_tasks_per_child): the consumer resumes
  within seconds, far below the limit.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from celery.signals import task_received
from celery.signals import worker_ready
from celery.worker import state as worker_state
from django.conf import settings
from sqlalchemy import bindparam
from sqlalchemy import create_engine
from sqlalchemy import make_url
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterable

    from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

SQLA_SCHEME = "sqla+"
# EX_SOFTWARE: the unit's Restart= policy restarts the worker on it.
WEDGED_EXIT_CODE = 70
PROC_SELF_FD = Path("/proc/self/fd")
POLL_TIMEOUT_SECONDS = 10
# libpq connection parameters, the same for psycopg2 and psycopg 3: give up
# connecting after 10 s, cancel the query after 10 s, and notice a dead TCP
# peer within about a minute.
POSTGRESQL_POLL_LIMITS: dict[str, Any] = {
    "connect_timeout": POLL_TIMEOUT_SECONDS,
    "options": f"-c statement_timeout={POLL_TIMEOUT_SECONDS * 1000}",
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
}

OLDEST_WAITING_SQL = text(
    "SELECT min(m.id) FROM kombu_message m "
    "JOIN kombu_queue q ON q.id = m.queue_id "
    "WHERE m.visible AND q.name IN :queues"
).bindparams(bindparam("queues", expanding=True))


@dataclass
class WedgeState:
    """What the watchdog has seen; times are time.monotonic() seconds."""

    last_received: float
    oldest_waiting_id: int | None = None
    oldest_waiting_since: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def received(self, now: float) -> None:
        """The consumer took a message."""
        with self.lock:
            self.last_received = now

    def saw_oldest_waiting(self, message_id: int | None, now: float) -> None:
        """Record the lowest waiting message id from one poll of the broker."""
        with self.lock:
            if message_id != self.oldest_waiting_id:
                self.oldest_waiting_id = message_id
                self.oldest_waiting_since = now

    def is_wedged(self, now: float, *, busy: bool, limit: float) -> bool:
        """Whether a message has waited, and nothing was taken, for ``limit`` s."""
        with self.lock:
            return (
                not busy
                and self.oldest_waiting_id is not None
                and now - self.oldest_waiting_since >= limit
                and now - self.last_received >= limit
            )


def worker_is_busy() -> bool:
    """Whether the worker has a task reserved (prefetched) or running."""
    return bool(worker_state.reserved_requests) or bool(worker_state.active_requests)


def socket_inodes() -> dict[int, str]:
    """This process's socket fds, as {fd: "socket:[inode]"} (Linux only).

    Two processes using one broker connection show the same inode, which is
    how the shared socket behind #426 was proven on production.
    """
    sockets: dict[int, str] = {}
    if not PROC_SELF_FD.is_dir():
        return sockets
    for entry in PROC_SELF_FD.iterdir():
        try:
            target = str(entry.readlink())
        except OSError:
            continue  # closed between listing and reading
        if target.startswith("socket:"):
            sockets[int(entry.name)] = target
    return sockets


def flush_logs_and_exit(code: int) -> None:
    """Flush every log handler, then end the process at once.

    os._exit, not sys.exit: the main thread is stuck, so a normal shutdown
    would wait on it forever, which is the state being escaped.
    """
    logging.shutdown()
    os._exit(code)


def thread_stacks() -> str:
    """Every thread's stack, as faulthandler prints it.

    faulthandler writes only to a real file descriptor. A deployed worker
    runs with --detach and --logfile, where sys.stderr is Celery's
    LoggingProxy, which has none, so the dump goes to a temporary file and
    comes back as text for the log.
    """
    with tempfile.TemporaryFile(mode="w+") as dump:
        faulthandler.dump_traceback(file=dump, all_threads=True)
        dump.seek(0)
        return dump.read()


def exit_wedged(
    queues: Iterable[str],
    waited: float,
    *,
    exit_process: Callable[[int], Any] = flush_logs_and_exit,
) -> None:
    """Log the wedge loudly, with every thread's stack, then exit the process.

    The exit is in a finally: if the report itself fails, the worker must
    still not stay wedged.
    """
    try:
        logger.critical(
            "Celery worker wedged: a message has waited %d s on %s and nothing "
            "was taken, with no task running. Exiting so systemd restarts it "
            "(issue #426). Sockets: %s\nStacks of its threads:\n%s",
            waited,
            ",".join(sorted(queues)),
            socket_inodes(),
            thread_stacks(),
        )
    finally:
        exit_process(WEDGED_EXIT_CODE)


class BrokerWatchdog:
    """The watchdog thread for one worker's main process."""

    def __init__(self, engine: Engine, queues: Iterable[str]) -> None:
        self.engine = engine
        self.queues = sorted(queues)
        self.state = WedgeState(last_received=time.monotonic())
        self.stop = threading.Event()

    def oldest_waiting_id(self) -> int | None:
        """The lowest id of a message waiting on this worker's queues."""
        with self.engine.connect() as connection:
            return connection.execute(
                OLDEST_WAITING_SQL, {"queues": self.queues}
            ).scalar()

    def poll_once(self, now: float) -> bool:
        """Poll the broker once; True if the worker is wedged."""
        try:
            self.state.saw_oldest_waiting(self.oldest_waiting_id(), now)
        except SQLAlchemyError:
            # The broker database is unreachable: that is not this worker
            # being wedged, and the consumer reports it itself. Forget the
            # waiting message, so the outage's length isn't counted as
            # waiting time once the database is back and kombu reconnects.
            logger.exception("Broker watchdog could not read the broker")
            self.state.saw_oldest_waiting(None, now)
            return False
        return self.state.is_wedged(
            now, busy=worker_is_busy(), limit=settings.WORKER_WEDGE_EXIT_SECONDS
        )

    def run(self) -> None:
        """Poll until the worker is wedged, then exit the process.

        If anything ends the loop other than stop, the worker keeps running
        unwatched, so that is reported as CRITICAL (ADMINS) on the way out;
        the exception itself goes on to threading.excepthook with its
        traceback.
        """
        try:
            while not self.stop.wait(settings.WORKER_WEDGE_POLL_SECONDS):
                now = time.monotonic()
                if self.poll_once(now):
                    exit_wedged(self.queues, now - self.state.oldest_waiting_since)
        finally:
            if not self.stop.is_set():
                logger.critical(
                    "Broker watchdog stopped: %s is no longer watched for a "
                    "wedge (issue #426). Restart the worker to watch it again.",
                    ",".join(self.queues),
                )


def broker_engine(broker_url: str) -> Engine | None:
    """The watchdog's own engine for an SQLAlchemy broker URL, else None.

    NullPool: each poll opens and closes its connection, so no connection
    is held while the pool forks children. On PostgreSQL every poll is
    bounded (POSTGRESQL_POLL_LIMITS): a wedge can be a connection that hangs
    in libpq with no error, and the watchdog's own poll must not hang the
    same way.
    """
    if not broker_url.startswith(SQLA_SCHEME):
        return None
    url = make_url(broker_url.removeprefix(SQLA_SCHEME))
    connect_args = (
        POSTGRESQL_POLL_LIMITS if url.get_backend_name() == "postgresql" else {}
    )
    return create_engine(url, poolclass=NullPool, connect_args=connect_args)


# The running watchdog (one per worker main process), for note_received.
WATCHDOGS: list[BrokerWatchdog] = []


def start_watchdog(consumer: Any, **_kwargs: Any) -> None:
    """worker_ready: start the watchdog for this worker's queues."""
    engine = broker_engine(consumer.app.conf.broker_url or "")
    if engine is None:
        logger.info("Broker watchdog off: the broker is not SQLAlchemy")
        return
    queues = [queue.name for queue in consumer.task_consumer.queues]
    watchdog = BrokerWatchdog(engine, queues)
    WATCHDOGS.append(watchdog)
    threading.Thread(target=watchdog.run, name="broker-watchdog", daemon=True).start()
    logger.info(
        "Broker watchdog on for %s: exits after %d s wedged",
        ",".join(watchdog.queues),
        settings.WORKER_WEDGE_EXIT_SECONDS,
    )


def note_received(**_kwargs: Any) -> None:
    """task_received: the consumer took a message."""
    for watchdog in WATCHDOGS:
        watchdog.state.received(time.monotonic())


def install_broker_watchdog() -> None:
    """Connect the watchdog to the worker's signals (config/celery.py)."""
    worker_ready.connect(start_watchdog, weak=False)
    task_received.connect(note_received, weak=False)
