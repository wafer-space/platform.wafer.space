"""Download verification functions for state checking."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING

import psutil
from celery import current_app

if TYPE_CHECKING:
    from wafer_space.projects.models import ProjectFile


def is_task_queued(project_file: ProjectFile) -> bool:
    """Verify task is in Celery queue (reserved but not started).

    Args:
        project_file: ProjectFile to check

    Returns:
        True if task is queued or started, False if missing
    """
    task_id = project_file.download_task_id
    inspect = current_app.control.inspect()

    # Check reserved queue
    reserved = inspect.reserved()
    if reserved:
        for tasks in reserved.values():
            if any(t["id"] == task_id for t in tasks):
                return True

    # Check if task started (auto-transition to DOWNLOADING)
    active = inspect.active()
    if active:
        for tasks in active.values():
            if any(t["id"] == task_id for t in tasks):
                # Update state to DOWNLOADING
                project_file.download_status = project_file.DownloadStatus.DOWNLOADING
                project_file.save(update_fields=["download_status"])
                return True

    return False


def is_task_actively_running(project_file: ProjectFile) -> bool:
    """Verify task is executing AND process exists.

    Args:
        project_file: ProjectFile to check

    Returns:
        True if task is running with valid PID, False otherwise
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

    # Verify PID exists (MANDATORY if available)
    if project_file.worker_pid and project_file.worker_hostname:
        # Only check if on same host
        if socket.gethostname() == project_file.worker_hostname:
            try:
                if not psutil.pid_exists(project_file.worker_pid):
                    return False

                proc = psutil.Process(project_file.worker_pid)
                cmdline = " ".join(proc.cmdline()).lower()

                if "celery" not in cmdline:
                    return False
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return False

    return True
