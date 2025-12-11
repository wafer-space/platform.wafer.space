"""Download and check verification functions for state checking."""

from __future__ import annotations

import logging
import socket
from typing import TYPE_CHECKING

import psutil
from celery import current_app
from celery.states import READY_STATES
from django.db import DatabaseError
from django.db import connection
from django.utils import timezone
from django_celery_results.models import TaskResult

if TYPE_CHECKING:
    from wafer_space.projects.models import ProjectFile

logger = logging.getLogger(__name__)


def _check_inspect_result(
    inspect_result: dict | None,
    task_id: str,
    operation_name: str,
) -> bool | None:
    """Check inspect result for task, handling None (unsupported broker).

    Args:
        inspect_result: Result from inspect.reserved() or inspect.active()
        task_id: Task ID to search for
        operation_name: Name of operation for logging (e.g., "reserved", "active")

    Returns:
        True if task found, False if not found, None if unable to verify
    """
    # If result is None, broker doesn't support this operation (PostgreSQL)
    if inspect_result is None:
        logger.warning(
            "inspect.%s() returned None (unsupported broker) - cannot verify task %s",
            operation_name,
            task_id,
        )
        return None  # Cannot verify

    # Check all worker queues for this task
    for tasks in inspect_result.values():
        if any(t["id"] == task_id for t in tasks):
            return True

    return False


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


def _is_task_in_results_unfinished(task_id: str | None) -> bool:
    """Check if a task exists in TaskResult with an unfinished status.

    This checks Django Celery Results for a task that has been picked up by a
    worker but hasn't finished yet (status is not SUCCESS, FAILURE, or REVOKED).

    Args:
        task_id: The Celery task ID to search for

    Returns:
        True if task is found with unfinished status, False otherwise
    """
    if not task_id:
        return False

    try:
        task_result = TaskResult.objects.filter(task_id=task_id).first()
        if task_result is None:
            # Task not in results - could be waiting in queue or never executed
            return False

        # Task is unfinished if its status is NOT in READY_STATES
        is_unfinished = task_result.status not in READY_STATES
        if is_unfinished:
            # Calculate age for debugging stale tasks
            age_seconds = None
            if task_result.date_created:
                age_delta = timezone.now() - task_result.date_created
                age_seconds = age_delta.total_seconds()

            logger.debug(
                "Task %s found in results: status=%s, worker=%s, "
                "date_created=%s, age=%.1fs",
                task_id,
                task_result.status,
                task_result.worker,
                task_result.date_created,
                age_seconds or 0,
            )
    except Exception:
        logger.exception("Error checking task result for task %s", task_id)
        # Err on the side of caution - assume still running
        return True
    else:
        return is_unfinished


def is_check_task_actively_running(task_id: str | None) -> bool:
    """Check if a Celery task is still actively running or waiting in queue.

    This function checks two places:
    1. Broker queue (kombu_message table) - tasks waiting to be picked up
    2. Task results (django_celery_results_taskresult) - tasks being executed

    A task is considered active if:
    - It's in the broker queue (visible=TRUE), OR
    - It's in TaskResult with a non-ready status (PENDING, STARTED, etc.)

    A task is considered orphaned (not active) if:
    - It's NOT in the broker queue, AND
    - It's either NOT in TaskResult, OR in TaskResult with READY status
      (SUCCESS, FAILURE, REVOKED)

    Args:
        task_id: The Celery task ID to check

    Returns:
        True if task is still active (queued or running), False if orphaned
    """
    if not task_id:
        return False

    # Check 1: Is task waiting in broker queue?
    if _is_task_in_broker_queue(task_id):
        logger.debug("Task %s is in broker queue", task_id)
        return True

    # Check 2: Is task in results with unfinished status?
    if _is_task_in_results_unfinished(task_id):
        logger.debug("Task %s is in results with unfinished status", task_id)
        return True

    # Task is not in queue and not running - it's orphaned
    logger.debug("Task %s is orphaned (not in queue, not running)", task_id)
    return False


def is_download_task_queued(project_file: ProjectFile) -> bool:
    """Verify download task is in Celery queue or broker queue.

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

    # Check reserved and active queues using inspect API
    inspect = current_app.control.inspect()

    # Check reserved queue (tasks fetched by worker but not started)
    reserved_result = _check_inspect_result(inspect.reserved(), task_id, "reserved")
    if reserved_result is None or reserved_result:
        return True  # Cannot verify or found - assume queued

    # Check active queue (tasks currently executing)
    active_result = _check_inspect_result(inspect.active(), task_id, "active")
    # Return True if unable to verify (None) or if found, False otherwise
    return active_result is None or bool(active_result)


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


def is_download_task_actively_running(project_file: ProjectFile) -> bool:
    """Verify download task is executing AND process exists.

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
    active_result = _check_inspect_result(inspect.active(), task_id, "active")
    if active_result is None:
        return True  # Cannot verify - assume still active to be safe
    if not active_result:
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
