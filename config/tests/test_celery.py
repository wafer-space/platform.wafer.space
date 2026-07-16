"""Tests for Celery worker recycling settings (issue #309).

Production Celery pool processes accumulate 2-3.5GB RSS each because they
are never recycled. ``worker_max_tasks_per_child`` and
``worker_max_memory_per_child`` bound a pool process's lifetime so leaked
or fragmented memory is returned to the OS. These tests assert the values
reach the Celery app through the ``CELERY`` settings namespace, not just
that the Django settings exist.
"""

from __future__ import annotations

from config.celery import app

MAX_TASKS_PER_CHILD = 100
ONE_GIB_IN_KB = 1024 * 1024


def test_worker_max_tasks_per_child_is_set() -> None:
    """Pool processes are replaced after a bounded number of tasks."""
    assert app.conf.worker_max_tasks_per_child == MAX_TASKS_PER_CHILD


def test_worker_max_memory_per_child_is_set() -> None:
    """Pool processes exceeding ~1GiB RSS are recycled after their task."""
    assert app.conf.worker_max_memory_per_child == ONE_GIB_IN_KB
