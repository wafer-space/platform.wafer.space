"""Test fixtures and helpers for projects app tests."""

from __future__ import annotations

import pytest
from django.utils import timezone

from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ProjectFile


@pytest.fixture
def create_file_with_status():
    """Factory fixture for creating ProjectFile with specific download status.

    Since download_status is now a property derived from DownloadAttempt,
    this helper creates the appropriate DownloadAttempt to achieve the
    desired status.

    Usage:
        project_file = create_file_with_status(
            project=project,
            status=ProjectFile.DownloadStatus.DOWNLOADING
        )
    """

    def _create(status: str, **file_kwargs) -> ProjectFile:
        """Create ProjectFile with DownloadAttempt in specified status.

        Args:
            status: Desired download_status (PENDING, DOWNLOADING, etc.)
            **file_kwargs: Additional kwargs for ProjectFile.objects.create()

        Returns:
            ProjectFile: Created file with correct download_status
        """
        # Remove download_status if accidentally passed
        file_kwargs.pop("download_status", None)

        # Create the ProjectFile
        project_file = ProjectFile.objects.create(**file_kwargs)

        # Set task_id if status requires it
        if status != ProjectFile.DownloadStatus.PENDING:
            if not project_file.download_task_id:
                project_file.download_task_id = "test-task-id"
                project_file.save(update_fields=["download_task_id"])

        # Create DownloadAttempt if needed for non-PENDING/QUEUED statuses
        if status in [
            ProjectFile.DownloadStatus.DOWNLOADING,
            ProjectFile.DownloadStatus.COMPLETED,
            ProjectFile.DownloadStatus.FAILED,
        ]:
            DownloadAttempt.objects.create(
                project_file=project_file,
                attempt_number=1,
                status=status,
                download_started_at=timezone.now(),
            )

        return project_file

    return _create
