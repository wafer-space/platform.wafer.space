"""A forked process never uses its parent's SQLAlchemy connection (issue #426).

The broker failure behind #426 needs PostgreSQL: two processes on one libpq
socket read each other's replies. CI's broker tests run on SQLite, so these
tests check the guard itself: which connection each process gets, and that
the parent's connection is left open. The PostgreSQL reproduction (the
PGRES_TUPLES_OK error, the wedged worker, and the fix's 900 s run) is in the
PR that added this.
"""

from __future__ import annotations

import os
import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from kombu import Connection
from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import Pool
from sqlalchemy.pool import QueuePool

import config.celery
from wafer_space.core import sqlalchemy_fork
from wafer_space.core.sqlalchemy_fork import install_fork_guard
from wafer_space.core.sqlalchemy_fork import record_opening_process
from wafer_space.core.sqlalchemy_fork import refuse_another_process_connection

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy import Engine

ANOTHER_PID = os.getpid() + 1
CHILD_REPORT_BYTES = 512


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """A pooled engine on a SQLite file, as kombu's sqla transport makes."""
    return create_engine(f"sqlite:///{tmp_path / 'broker.db'}", poolclass=QueuePool)


def checked_out_dbapi(engine: Engine) -> sqlite3.Connection:
    """Check a connection out, run a query, check it back in; return its DBAPI side."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        dbapi = conn.connection.dbapi_connection
    assert isinstance(dbapi, sqlite3.Connection)
    return dbapi


def test_celery_config_installs_the_guard() -> None:
    """Importing the Celery app installs the guard on every pool.

    No test here leaves an install of its own behind (see
    guard_state_restored), so only config/celery.py can have installed it.
    """
    assert config.celery.app.main == "wafer_space"
    assert event.contains(Pool, "checkout", refuse_another_process_connection)
    assert event.contains(Pool, "connect", record_opening_process)


@pytest.fixture
def guard_state_restored() -> Iterator[None]:
    """Undo any install this test adds, so it can't hide a missing one."""
    listeners: list[tuple[str, Callable[..., None]]] = [
        ("connect", record_opening_process),
        ("checkout", refuse_another_process_connection),
    ]
    installed = [event.contains(Pool, name, fn) for name, fn in listeners]
    yield
    for (name, fn), was_installed in zip(listeners, installed, strict=True):
        if not was_installed and event.contains(Pool, name, fn):
            event.remove(Pool, name, fn)


@pytest.mark.usefixtures("guard_state_restored")
def test_installing_twice_adds_no_second_listener(engine: Engine) -> None:
    """install_fork_guard is safe to call again."""
    install_fork_guard()
    install_fork_guard()

    listeners = list(engine.pool.dispatch.checkout)
    assert listeners.count(refuse_another_process_connection) == 1


def test_same_process_reuses_its_pooled_connection(engine: Engine) -> None:
    """Pooling is unchanged within one process."""
    first = checked_out_dbapi(engine)

    assert checked_out_dbapi(engine) is first


def test_another_process_gets_a_new_connection(engine: Engine) -> None:
    """A process other than the opener is given a connection of its own."""
    parents = checked_out_dbapi(engine)

    with patch.object(sqlalchemy_fork.os, "getpid", return_value=ANOTHER_PID):
        childs = checked_out_dbapi(engine)

    assert childs is not parents


def test_the_parents_connection_is_not_closed(engine: Engine) -> None:
    """Discarding it must not close it: that would end the parent's session."""
    parents = checked_out_dbapi(engine)

    with patch.object(sqlalchemy_fork.os, "getpid", return_value=ANOTHER_PID):
        checked_out_dbapi(engine)

    assert parents.execute("SELECT 1").fetchone() == (1,)


def test_a_connection_opened_before_the_guard_is_left_alone(engine: Engine) -> None:
    """Its opener is unknown, so it is not discarded: that would leak a session."""
    event.remove(Pool, "connect", record_opening_process)
    event.remove(Pool, "checkout", refuse_another_process_connection)
    try:
        before_the_guard = checked_out_dbapi(engine)
    finally:
        install_fork_guard()

    with patch.object(sqlalchemy_fork.os, "getpid", return_value=ANOTHER_PID):
        assert checked_out_dbapi(engine) is before_the_guard


def test_a_forked_child_does_not_get_the_parents_broker_connection(
    tmp_path: Path,
) -> None:
    """Through kombu's SQLAlchemy transport and a real fork, as a prefork child.

    The parent's channel queries and commits, so its connection goes back to
    the pool kombu shares across the fork (Channel's class-level engine
    cache). The child then opens a new kombu Connection, as .delay() does.
    """
    url = f"sqla+sqlite:///{tmp_path / 'broker.db'}"
    parent = Connection(url)
    parent_session = parent.default_channel.session
    parent_session.execute(text("SELECT 1"))
    parent_dbapi_id = id(parent_session.connection().connection.dbapi_connection)
    parent_session.commit()

    read_end, write_end = os.pipe()
    child = os.fork()
    if child == 0:  # the child: report, then leave without pytest's teardown
        try:
            session = Connection(url).default_channel.session
            session.execute(text("SELECT 1"))
            child_dbapi_id = id(session.connection().connection.dbapi_connection)
            shared = child_dbapi_id == parent_dbapi_id
            os.write(write_end, b"shared" if shared else b"own")
        except (SQLAlchemyError, OSError) as exc:  # shown in the parent's assert
            os.write(write_end, repr(exc).encode()[:CHILD_REPORT_BYTES])
        finally:
            os._exit(0)
    os.close(write_end)
    os.waitpid(child, 0)
    answer = os.read(read_end, CHILD_REPORT_BYTES)
    os.close(read_end)
    parent.release()

    assert answer == b"own"
