"""
Service layer for project-related business logic.

This module contains business logic that orchestrates between models and tasks,
helping to avoid circular imports and keeping models focused on data representation.
"""

from django.utils import timezone


def start_file_download(project_file):
    """Start background download for a project file.

    Args:
        project_file: ProjectFile instance to download

    Returns:
        Celery task instance for monitoring
    """
    from .tasks import download_project_file

    project_file.download_status = project_file.DownloadStatus.DOWNLOADING
    project_file.download_started_at = timezone.now()
    project_file.save()

    # Queue the download task
    task = download_project_file.delay(project_file.id)
    project_file.download_task_id = task.id
    project_file.save()

    return task
