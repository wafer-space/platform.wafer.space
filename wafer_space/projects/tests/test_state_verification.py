"""Tests for download state verification periodic task."""

import contextlib
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase

from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.tasks import check_download_states
from wafer_space.projects.tasks import download_project_file

User = get_user_model()
TEST_PASSWORD = "testpass123"  # noqa: S105
TEST_WORKER_PID = 12345
TEST_WORKER_HOSTNAME = "worker-01"


@pytest.mark.django_db
class DownloadStateVerificationTests(TestCase):
    """Tests for check_download_states() task."""

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

    @patch("wafer_space.projects.tasks.is_task_actively_running")
    @patch("wafer_space.projects.tasks.is_task_queued")
    @patch("wafer_space.projects.tasks.download_project_file.delay")
    def test_pending_file_creates_task(
        self, mock_delay, mock_is_queued, mock_is_running
    ):
        """Test PENDING file gets task created and transitions to QUEUED."""
        # Create PENDING file with no task
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.PENDING,
            is_active=True,
        )

        # Mock task creation
        mock_task = Mock()
        mock_task.id = "new-task-123"
        mock_delay.return_value = mock_task

        # Mock verification functions (no other files to check)
        mock_is_queued.return_value = True
        mock_is_running.return_value = True

        # Run state check
        result = check_download_states()

        # Verify task created
        mock_delay.assert_called_once_with(self.project.id)
        assert result["created_tasks"] == 1

        # Verify state transition
        project_file.refresh_from_db()
        assert project_file.download_task_id == "new-task-123"
        assert project_file.download_status == ProjectFile.DownloadStatus.QUEUED

    @patch("wafer_space.projects.tasks.is_task_actively_running")
    @patch("wafer_space.projects.tasks.is_task_queued")
    def test_queued_file_verified(self, mock_is_queued, mock_is_running):
        """Test QUEUED file is verified and counted."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.QUEUED,
            download_task_id="task-123",
            is_active=True,
        )

        # Mock verification returns True
        mock_is_queued.return_value = True
        mock_is_running.return_value = True

        result = check_download_states()

        assert result["verified"] == 1
        assert result["orphaned"] == 0

        # File should still be QUEUED
        project_file.refresh_from_db()
        assert project_file.download_status == ProjectFile.DownloadStatus.QUEUED

    @patch("wafer_space.projects.tasks.is_task_actively_running")
    @patch("wafer_space.projects.tasks.is_task_queued")
    def test_queued_file_orphaned(self, mock_is_queued, mock_is_running):
        """Test QUEUED file not in queue is marked orphaned."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.QUEUED,
            download_task_id="task-456",
            is_active=True,
        )

        # Mock verification returns False
        mock_is_queued.return_value = False
        mock_is_running.return_value = True

        result = check_download_states()

        assert result["verified"] == 0
        assert result["orphaned"] == 1

        # File should be FAILED
        project_file.refresh_from_db()
        assert project_file.download_status == ProjectFile.DownloadStatus.FAILED
        assert "not found in Celery queue" in project_file.download_error

    @patch("wafer_space.projects.tasks.is_task_queued")
    @patch("wafer_space.projects.tasks.is_task_actively_running")
    def test_downloading_file_verified(self, mock_is_running, mock_is_queued):
        """Test DOWNLOADING file is verified and counted."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.DOWNLOADING,
            download_task_id="task-789",
            is_active=True,
        )

        # Mock verification returns True
        mock_is_running.return_value = True
        mock_is_queued.return_value = True

        result = check_download_states()

        assert result["verified"] == 1
        assert result["orphaned"] == 0

        # File should still be DOWNLOADING
        project_file.refresh_from_db()
        assert project_file.download_status == ProjectFile.DownloadStatus.DOWNLOADING

    @patch("wafer_space.projects.tasks.is_task_queued")
    @patch("wafer_space.projects.tasks.is_task_actively_running")
    def test_downloading_file_orphaned(self, mock_is_running, mock_is_queued):
        """Test DOWNLOADING file not running is marked orphaned."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_status=ProjectFile.DownloadStatus.DOWNLOADING,
            download_task_id="task-999",
            is_active=True,
        )

        # Mock verification returns False
        mock_is_running.return_value = False
        mock_is_queued.return_value = True

        result = check_download_states()

        assert result["verified"] == 0
        assert result["orphaned"] == 1

        # File should be FAILED
        project_file.refresh_from_db()
        assert project_file.download_status == ProjectFile.DownloadStatus.FAILED
        assert "not running" in project_file.download_error

    @patch("wafer_space.projects.tasks.socket")
    @patch("wafer_space.projects.tasks.os")
    def test_download_task_captures_worker_info(self, mock_os, mock_socket):
        """Test that download task captures PID and hostname."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/small.txt",
            download_status=ProjectFile.DownloadStatus.QUEUED,
            download_task_id="task-123",
            is_active=True,
        )

        # Mock PID and hostname
        mock_os.getpid.return_value = TEST_WORKER_PID
        mock_socket.gethostname.return_value = TEST_WORKER_HOSTNAME

        # This will fail to download (no server), but should capture worker info
        with contextlib.suppress(Exception):
            download_project_file(self.project.id)

        # Verify worker info was captured
        project_file.refresh_from_db()
        assert project_file.worker_pid == TEST_WORKER_PID
        assert project_file.worker_hostname == TEST_WORKER_HOSTNAME
        assert project_file.task_started_at is not None
