"""Tests for Celery worker settings: recycling (issue #309), queues (#382).

Production Celery pool processes accumulate 2-3.5GB RSS each because they
are never recycled. ``worker_max_tasks_per_child`` and
``worker_max_memory_per_child`` bound a pool process's lifetime so leaked
or fragmented memory is returned to the OS. These tests assert the values
reach the Celery app through the ``CELERY`` settings namespace, not just
that the Django settings exist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from config.celery import app

MAX_TASKS_PER_CHILD = 100
ONE_GIB_IN_KB = 1024 * 1024


def test_worker_max_tasks_per_child_is_set() -> None:
    """Pool processes are replaced after a bounded number of tasks."""
    assert app.conf.worker_max_tasks_per_child == MAX_TASKS_PER_CHILD


def test_worker_max_memory_per_child_is_set() -> None:
    """Pool processes exceeding ~1GiB RSS are recycled after their task."""
    assert app.conf.worker_max_memory_per_child == ONE_GIB_IN_KB


# Default queue and result expiry (issue #382)
# ------------------------------------------------------------------------------
# Celery's own default queue is "celery", which no deployed worker consumes,
# so celery.backend_cleanup (beat's daily enforcement of CELERY_RESULT_EXPIRES)
# never ran on production and django_celery_results_taskresult grew without
# bound. Every task must route to a queue a worker consumes. The Procfile's
# worker -Q lists mirror the deployed workers (hetzner-ansible
# inventory/group_vars/platform_wafer_space.yml, one worker per queue).

PROCFILE = Path(__file__).resolve().parents[2] / "Procfile"
QUEUE_NAME = re.compile(r"^(none|mail|http|dock):(ro|rw):[a-z][a-z-]*$")


def _procfile_queues() -> set[str]:
    """Return every queue a Procfile worker consumes (its -Q lists)."""
    queues: set[str] = set()
    for line in PROCFILE.read_text().splitlines():
        match = re.search(r"celery -A config worker -Q (\S+)", line)
        if match:
            queues.update(match.group(1).split(","))
    return queues


def _routed_queue(task_name: str) -> str:
    """Return the queue Celery's router sends ``task_name`` to.

    Mirrors Task.apply_async: a task's own ``queue`` attribute is passed to
    the router as an option; without one the router falls back to
    task_default_queue.
    """
    task = app.tasks[task_name]
    # Task defines no class-level queue; only tasks declared with queue= have one.
    queue = getattr(task, "queue", None)
    options = {"queue": queue} if queue else {}
    return app.amqp.router.route(options, task_name)["queue"].name


@pytest.fixture
def registered_task_names() -> list[str]:
    """Names of every task the workers register, built-ins included."""
    app.loader.import_default_modules()
    return sorted(app.tasks)


def test_procfile_queues_follow_naming_convention() -> None:
    """The parsed worker queue list is non-empty and named network:fs:purpose."""
    queues = _procfile_queues()

    assert queues
    assert all(QUEUE_NAME.match(queue) for queue in queues), queues


def test_default_queue_is_consumed_by_a_worker() -> None:
    """Tasks without an explicit queue land on a queue a worker consumes."""
    assert app.conf.task_default_queue in _procfile_queues()


def test_backend_cleanup_routes_to_default_queue() -> None:
    """Beat's result-expiry task goes to none:ro:default, not "celery"."""
    assert _routed_queue("celery.backend_cleanup") == "none:ro:default"


def test_every_task_routes_to_a_consumed_queue(
    registered_task_names: list[str],
) -> None:
    """No registered task routes to a queue that no worker consumes."""
    consumed = _procfile_queues()
    unconsumed = {
        name: _routed_queue(name)
        for name in registered_task_names
        if _routed_queue(name) not in consumed
    }

    assert unconsumed == {}


def test_result_expiry_outlives_task_time_limit(
    registered_task_names: list[str],
) -> None:
    """Expiry never deletes the STARTED row of a task that may still run.

    backend_cleanup deletes rows by date_done whatever their state, and
    checks_cleanup_stale_pending_tasks treats a STARTED row as "still
    running", so a row must outlive the longest a task can run.
    """
    limits = [app.conf.task_time_limit]
    limits += [
        app.tasks[name].time_limit
        for name in registered_task_names
        if app.tasks[name].time_limit is not None
    ]

    assert app.conf.result_expires > max(limits)
