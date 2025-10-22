"""Download verification functions for state checking."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
