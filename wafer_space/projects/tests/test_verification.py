"""Tests for download verification functions."""

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase

from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.verification import is_task_queued

User = get_user_model()
TEST_PASSWORD = "testpass123"  # noqa: S105


@pytest.mark.django_db
class TaskQueuedVerificationTests(TestCase):
    """Tests for is_task_queued() function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test Description",
        )

    @patch("wafer_space.projects.verification.current_app")
    def test_task_in_reserved_queue(self, mock_app):
        """Test that task found in reserved queue returns True."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.QUEUED,
            download_task_id="task-123",
            is_active=False,
        )

        # Mock Celery inspect to return task in reserved
        mock_inspect = Mock()
        mock_inspect.reserved.return_value = {
            "worker1": [
                {"id": "task-123", "name": "download_project_file"},
            ],
        }
        mock_inspect.active.return_value = {}
        mock_app.control.inspect.return_value = mock_inspect

        result = is_task_queued(project_file)

        assert result is True
        project_file.refresh_from_db()
        assert project_file.download_status == ProjectFile.DownloadStatus.QUEUED

    @patch("wafer_space.projects.verification.current_app")
    def test_task_in_active_auto_transitions(self, mock_app):
        """Test that task in active list auto-transitions to DOWNLOADING."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.QUEUED,
            download_task_id="task-456",
            is_active=False,
        )

        # Mock Celery inspect to return task in active
        mock_inspect = Mock()
        mock_inspect.reserved.return_value = {}
        mock_inspect.active.return_value = {
            "worker1": [
                {"id": "task-456", "name": "download_project_file"},
            ],
        }
        mock_app.control.inspect.return_value = mock_inspect

        result = is_task_queued(project_file)

        assert result is True
        project_file.refresh_from_db()
        # Should auto-transition to DOWNLOADING
        assert project_file.download_status == ProjectFile.DownloadStatus.DOWNLOADING

    @patch("wafer_space.projects.verification.current_app")
    def test_task_not_found_returns_false(self, mock_app):
        """Test that missing task returns False."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.QUEUED,
            download_task_id="task-789",
            is_active=False,
        )

        # Mock Celery inspect to return empty
        mock_inspect = Mock()
        mock_inspect.reserved.return_value = {}
        mock_inspect.active.return_value = {}
        mock_app.control.inspect.return_value = mock_inspect

        result = is_task_queued(project_file)

        assert result is False
