"""Download and check verification functions for state checking."""

from __future__ import annotations

import logging
import socket
from typing import TYPE_CHECKING

import docker
import docker.errors
import psutil
from celery import current_app
from django.db import DatabaseError
from django.db import connection

if TYPE_CHECKING:
    from wafer_space.projects.models import ManufacturabilityCheck
    from wafer_space.projects.models import ProjectFile

logger = logging.getLogger(__name__)


def is_check_container_running(check: ManufacturabilityCheck) -> bool | None:
    """Check if Docker container for this check is running.

    This is the most reliable way to verify a check is actively running because:
    1. Container is created BEFORE check enters RUNNING state (verified by Task 4)
    2. Container has label wafer.space.check_id={check.id} for reliable lookup
    3. Docker API is authoritative for container state

    Args:
        check: ManufacturabilityCheck to verify

    Returns:
        True if running container found
        False if no container found (definitely orphaned)
        None if Docker unavailable (caller should fall back to other checks)
    """
    try:
        client = docker.from_env(timeout=300)
    except docker.errors.DockerException:
        logger.warning(
            "Failed to connect to Docker - cannot verify container for check %s",
            check.id,
        )
        return None

    try:
        # Query for containers with this check's label
        containers = client.containers.list(
            all=False,  # Only running containers
            filters={"label": f"wafer.space.check_id={check.id}"},
        )
    except docker.errors.DockerException:
        logger.exception(
            "Error querying Docker for check %s containers",
            check.id,
        )
        return None
    finally:
        # Close client to avoid lingering HTTP connections. Use hasattr check
        # for compatibility with test mocks that may not implement close().
        if hasattr(client, "close"):
            client.close()

    if containers:
        # Found at least one running container with this check ID
        logger.debug(
            "Check %s has %d running container(s)",
            check.id,
            len(containers),
        )
        return True

    # No running containers found
    logger.debug(
        "Check %s has no running containers",
        check.id,
    )
    return False


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


def _check_container_status(check: ManufacturabilityCheck) -> bool | None:
    """Check Docker container status for verification.

    Args:
        check: ManufacturabilityCheck to verify

    Returns:
        True if container running, False if definitely orphaned, None to continue
    """
    container_result = is_check_container_running(check)
    if container_result is False:
        # Definitely orphaned - no container running
        logger.debug(
            "Check %s is orphaned: no running container",
            check.id,
        )
        return False
    if container_result is True:
        # Container running - definitely active
        logger.debug(
            "Check %s verified active: container running",
            check.id,
        )
        return True
    # container_result is None - Docker unavailable, fall through to next check
    return None


def _check_pid_status(check: ManufacturabilityCheck) -> bool | None:
    """Check worker PID status for verification.

    Args:
        check: ManufacturabilityCheck to verify

    Returns:
        True if PID alive, False if dead, None to continue
    """
    if not (check.celery_worker_pid and check.celery_worker_hostname):
        return None

    pid_alive = _verify_worker_process(
        check.celery_worker_pid,
        check.celery_worker_hostname,
    )
    if not pid_alive:
        # PID dead - definitely orphaned
        logger.debug(
            "Check %s is orphaned: PID %s on %s is dead",
            check.id,
            check.celery_worker_pid,
            check.celery_worker_hostname,
        )
        return False

    # PID alive - likely active
    logger.debug(
        "Check %s verified active: PID %s on %s alive",
        check.id,
        check.celery_worker_pid,
        check.celery_worker_hostname,
    )
    return True


def _check_celery_status(check: ManufacturabilityCheck, task_id: str) -> bool:
    """Check Celery task status for verification.

    Args:
        check: ManufacturabilityCheck to verify
        task_id: Celery task ID

    Returns:
        True if task active or cannot verify, False if definitely orphaned
    """
    inspect = current_app.control.inspect()
    active_result = _check_inspect_result(inspect.active(), task_id, "active")
    if active_result is None:
        # Cannot verify - assume still active to be safe
        logger.debug(
            "Check %s assumed active: cannot verify (unsupported broker)",
            check.id,
        )
        return True
    if not active_result:
        # Task not in active list - orphaned
        logger.debug(
            "Check %s is orphaned: not in Celery active list",
            check.id,
        )
        return False

    # Task in active list
    logger.debug(
        "Check %s verified active: in Celery active list",
        check.id,
    )
    return True


def is_check_task_actively_running(check: ManufacturabilityCheck) -> bool:
    """Best-effort verification that a manufacturability check task is still active.

    Detection order (most reliable first):
    1. Docker container exists - most reliable (container created before RUNNING)
    2. Worker PID exists - reliable for local workers
    3. Celery task in active list - unreliable with PostgreSQL broker

    Args:
        check: ManufacturabilityCheck to verify

    Returns:
        True if task appears to be running or cannot be verified,
        False if definitely orphaned
    """
    task_id = check.celery_job_id
    if not task_id:
        return False

    # STEP 1: Check Docker container (most reliable)
    container_status = _check_container_status(check)
    if container_status is not None:
        return container_status

    # STEP 2: Check worker PID (reliable for local workers)
    pid_status = _check_pid_status(check)
    if pid_status is not None:
        return pid_status

    # STEP 3: Check Celery task in active list (unreliable with PostgreSQL)
    return _check_celery_status(check, task_id)
