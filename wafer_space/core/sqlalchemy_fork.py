"""Keep a forked process off its parent's SQLAlchemy connections (issue #426).

The Celery broker is kombu's SQLAlchemy transport on PostgreSQL. kombu keeps
one engine per broker URL for the whole process (a class attribute of its
Channel), so a prefork pool child inherits the parent's engine and its pool.
When the child publishes (``.delay()``), the pool can hand it the
connection the parent's consumer checked back in: the same PostgreSQL
session over the same socket. The two processes then read each other's
replies. One of them fails with "error with status PGRES_TUPLES_OK and no
message from the libpq", and the other can wait forever for a reply that
was already read: the checks-orch worker stayed "running" and consumed
nothing.

This is SQLAlchemy's event recipe for pools used across os.fork()
(<https://docs.sqlalchemy.org/en/20/core/pooling.html#using-connection-pools-with-multiprocessing-or-os-fork>),
installed on the Pool class so that it covers every pool in the process,
including those created after a fork. A connection records the process
that opened it; checking it out in any other process discards it
without closing it (closing would end the parent's session) and has the
pool open a new one.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import event
from sqlalchemy.exc import DisconnectionError
from sqlalchemy.pool import Pool

_PID_KEY = "wafer_space_pid"


def record_opening_process(
    _dbapi_connection: Any,
    connection_record: Any,
) -> None:
    """Remember which process opened this connection."""
    connection_record.info[_PID_KEY] = os.getpid()


def refuse_another_process_connection(
    _dbapi_connection: Any,
    connection_record: Any,
    connection_proxy: Any,
) -> None:
    """Make a forked process open its own connection.

    Raising DisconnectionError at checkout makes the pool discard the record
    and connect again. The DBAPI connection is unhooked first, so discarding
    it doesn't close it: closing would send PostgreSQL's Terminate over the
    socket the parent is still using.
    """
    opened_by = connection_record.info.get(_PID_KEY)
    pid = os.getpid()
    # None: opened before the guard was installed, so its process is not
    # known. Discarding it would leak an open session, so it is left alone;
    # config/celery.py installs the guard before kombu connects.
    if opened_by is None or opened_by == pid:
        return
    connection_record.dbapi_connection = None
    connection_proxy.dbapi_connection = None
    msg = (
        f"Connection opened by process {opened_by} checked out in "
        f"process {pid}; opening a new one"
    )
    raise DisconnectionError(msg)


def install_fork_guard() -> None:
    """Install the guard on every SQLAlchemy pool. Calling it again is a no-op."""
    if not event.contains(Pool, "connect", record_opening_process):
        event.listen(Pool, "connect", record_opening_process)
    if not event.contains(Pool, "checkout", refuse_another_process_connection):
        event.listen(Pool, "checkout", refuse_another_process_connection)
