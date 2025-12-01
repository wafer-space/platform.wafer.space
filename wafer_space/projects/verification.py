"""Download and check verification functions for state checking."""

from __future__ import annotations

import logging
import socket
from typing import TYPE_CHECKING

import psutil
from celery import current_app
from django.db import DatabaseError
from django.db import connection

if TYPE_CHECKING:
    from wafer_space.projects.models import ManufacturabilityCheck
    from wafer_space.projects.models import ProjectFile

logger = logging.getLogger(__name__)


def _is_task_in_broker_queue(task_id: str | None) -> bool:
    """Check if a task exists in the Celery broker queue (kombu_message table).

    This checks the broker's message store directly, which is necessary because
    Celery's inspect.reserved()/active() only show tasks that have been picked
    up by a worker. Tasks waiting in the broker queue are invisible to those APIs.

    For SQLAlchemy broker, tasks are stored in the kombu_message table with the
    task ID in the JSON payload's headers.id field.

    Args:
        task_id: The Celery task ID to search for

    Returns:
        True if task is found in the broker queue, False otherwise
    """
    if not task_id:
        return False

    try:
        with connection.cursor() as cursor:
            # Query kombu_message for visible messages containing this task ID.
            # The task ID is in the JSON payload's headers.id field.
            # Using LIKE is safe here since task_id is a UUID we generated.
            # Use TRUE for PostgreSQL compatibility (SQLite also accepts TRUE)
            cursor.execute(
                """
                SELECT COUNT(*) FROM kombu_message
                WHERE visible = TRUE AND payload LIKE %s
                """,
                [f'%"id": "{task_id}"%'],
            )
            count = cursor.fetchone()[0]
            return count > 0
    except DatabaseError:
        logger.exception("Error checking broker queue for task %s", task_id)
        return False


def is_task_queued(project_file: ProjectFile) -> bool:
    """Verify task is in Celery queue or broker queue.

    This function checks three places for the task:
    1. Broker queue (kombu_message table) - tasks waiting to be picked up
    2. Reserved queue - tasks fetched by worker but not started
    3. Active queue - tasks currently executing

    Args:
        project_file: ProjectFile to check

    Returns:
        True if task is found in any queue, False if missing

    Note:
        Download status is now derived from DownloadAttempt records.
        Auto-transition to DOWNLOADING happens when DownloadAttempt is created
        in the task execution, not here.
    """
    task_id = project_file.download_task_id
    if not task_id:
        return False

    # First check broker queue (tasks waiting in kombu_message table)
    # This is checked first because it's the most common case for newly queued tasks
    if _is_task_in_broker_queue(task_id):
        return True

    # Check reserved queue (tasks fetched by worker but not started)
    inspect = current_app.control.inspect()
    reserved = inspect.reserved()
    if reserved:
        for tasks in reserved.values():
            if any(t["id"] == task_id for t in tasks):
                return True

    # Check if task started (actively running)
    active = inspect.active()
    if active:
        for tasks in active.values():
            if any(t["id"] == task_id for t in tasks):
                return True

    return False


def _verify_worker_process(worker_pid: int, worker_hostname: str) -> bool:
    """Verify worker process exists and is a Celery worker.

    Args:
        worker_pid: Process ID to check
        worker_hostname: Hostname where process should be running

    Returns:
        True if process exists and is Celery worker, False otherwise
    """
    # Only check if on same host
    if socket.gethostname() != worker_hostname:
        return True  # Can't verify remote processes

    try:
        if not psutil.pid_exists(worker_pid):
            return False

        proc = psutil.Process(worker_pid)
        cmdline = " ".join(proc.cmdline()).lower()
        is_celery = "celery" in cmdline
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    else:
        return is_celery


def is_task_actively_running(project_file: ProjectFile) -> bool:
    """Verify task is executing AND process exists.

    Args:
        project_file: ProjectFile to check

    Returns:
        True if task is running with valid PID, False otherwise

    Note:
        Worker PID/hostname now stored in DownloadAttempt records.
        Checks latest_attempt for worker information.
    """
    task_id = project_file.download_task_id
    inspect = current_app.control.inspect()

    # Check task in active list
    active = inspect.active()
    task_in_active = False

    if active:
        for tasks in active.values():
            if any(t["id"] == task_id for t in tasks):
                task_in_active = True
                break

    if not task_in_active:
        return False

    # Get worker info from latest DownloadAttempt
    latest_attempt = project_file.latest_attempt
    if not latest_attempt:
        # No attempt yet - task queued but not started
        return True

    # Verify PID exists (if available)
    if latest_attempt.worker_pid and latest_attempt.worker_hostname:
        return _verify_worker_process(
            latest_attempt.worker_pid,
            latest_attempt.worker_hostname,
        )

    return True


def is_check_task_queued(check: ManufacturabilityCheck) -> bool:
    """Verify manufacturability check task is in Celery queue or broker queue.

    This function checks three places for the task:
    1. Broker queue (kombu_message table) - tasks waiting to be picked up
    2. Reserved queue - tasks fetched by worker but not started
    3. Active queue - tasks currently executing

    Args:
        check: ManufacturabilityCheck to verify

    Returns:
        True if task is found in any queue, False if missing
    """
    task_id = check.celery_job_id
    if not task_id:
        return False

    # First check broker queue (tasks waiting in kombu_message table)
    if _is_task_in_broker_queue(task_id):
        return True

    # Check reserved queue (tasks fetched by worker but not started)
    inspect = current_app.control.inspect()
    reserved = inspect.reserved()
    if reserved:
        for tasks in reserved.values():
            if any(t["id"] == task_id for t in tasks):
                return True

    # Check if task started (actively running)
    active = inspect.active()
    if active:
        for tasks in active.values():
            if any(t["id"] == task_id for t in tasks):
                return True

    return False


def is_check_task_actively_running(check: ManufacturabilityCheck) -> bool:
    """Verify manufacturability check task is executing AND process exists.

    Args:
        check: ManufacturabilityCheck to verify

    Returns:
        True if task is running with valid PID, False otherwise
    """
    task_id = check.celery_job_id
    if not task_id:
        return False

    inspect = current_app.control.inspect()

    # Check task in active list
    active = inspect.active()
    task_in_active = False

    if active:
        for tasks in active.values():
            if any(t["id"] == task_id for t in tasks):
                task_in_active = True
                break

    if not task_in_active:
        return False

    # Verify PID exists (if available)
    if check.celery_worker_pid and check.celery_worker_hostname:
        return _verify_worker_process(
            check.celery_worker_pid,
            check.celery_worker_hostname,
        )

    return True
