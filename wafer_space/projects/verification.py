"""Download and check verification functions for state checking."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING

import psutil
from celery import current_app

if TYPE_CHECKING:
    from wafer_space.projects.models import ManufacturabilityCheck
    from wafer_space.projects.models import ProjectFile


def is_task_queued(project_file: ProjectFile) -> bool:
    """Verify task is in Celery queue (reserved but not started).

    Args:
        project_file: ProjectFile to check

    Returns:
        True if task is queued or started, False if missing

    Note:
        Download status is now derived from DownloadAttempt records.
        Auto-transition to DOWNLOADING happens when DownloadAttempt is created
        in the task execution, not here.
    """
    task_id = project_file.download_task_id
    inspect = current_app.control.inspect()

    # Check reserved queue
    reserved = inspect.reserved()
    if reserved:
        for tasks in reserved.values():
            if any(t["id"] == task_id for t in tasks):
                return True

    # Check if task started
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
    if latest_attempt.celery_worker_pid and latest_attempt.celery_worker_hostname:
        return _verify_worker_process(
            latest_attempt.celery_worker_pid,
            latest_attempt.celery_worker_hostname,
        )

    return True


def is_check_task_queued(check: ManufacturabilityCheck) -> bool:
    """Verify manufacturability check task is in Celery queue.

    Args:
        check: ManufacturabilityCheck to verify

    Returns:
        True if task is queued or started, False if missing
    """
    task_id = check.celery_job_id
    if not task_id:
        return False

    inspect = current_app.control.inspect()

    # Check reserved queue
    reserved = inspect.reserved()
    if reserved:
        for tasks in reserved.values():
            if any(t["id"] == task_id for t in tasks):
                return True

    # Check if task started
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
