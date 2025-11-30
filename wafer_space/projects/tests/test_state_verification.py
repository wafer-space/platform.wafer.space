"""Tests for download state verification periodic task."""

import contextlib
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase

from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.tasks import download_project_file
from wafer_space.projects.tasks import ensure_download_tasks_queued

User = get_user_model()
TEST_PASSWORD = "testpass123"  # noqa: S105 - Test password constant
TEST_WORKER_PID = 12345
TEST_WORKER_HOSTNAME = "worker-01"


@pytest.mark.django_db
class DownloadStateVerificationTests(TestCase):
    """Tests for ensure_download_tasks_queued() task."""

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
        # Create PENDING file with no task (status = PENDING automatically)
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
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
        result = ensure_download_tasks_queued()

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
        # Create file with task_id (status = QUEUED automatically)
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_task_id="task-123",
            is_active=True,
        )

        # Mock verification returns True
        mock_is_queued.return_value = True
        mock_is_running.return_value = True

        result = ensure_download_tasks_queued()

        assert result["verified"] == 1
        assert result["orphaned"] == 0

        # File should still be QUEUED
        project_file.refresh_from_db()
        assert project_file.download_status == ProjectFile.DownloadStatus.QUEUED

    @patch("wafer_space.projects.tasks.is_task_actively_running")
    @patch("wafer_space.projects.tasks.is_task_queued")
    def test_queued_file_orphaned(self, mock_is_queued, mock_is_running):
        """Test QUEUED file not in queue is marked orphaned."""
        # Create file with task_id (status = QUEUED automatically)
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_task_id="task-456",
            is_active=True,
        )

        # Mock verification returns False
        mock_is_queued.return_value = False
        mock_is_running.return_value = True

        result = ensure_download_tasks_queued()

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
        # Create file with task_id and DOWNLOADING attempt
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_task_id="task-789",
            is_active=True,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        # Mock verification returns True
        mock_is_running.return_value = True
        mock_is_queued.return_value = True

        result = ensure_download_tasks_queued()

        assert result["verified"] == 1
        assert result["orphaned"] == 0

        # File should still be DOWNLOADING
        project_file.refresh_from_db()
        assert project_file.download_status == ProjectFile.DownloadStatus.DOWNLOADING

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.tasks.is_task_queued")
    @patch("wafer_space.projects.tasks.is_task_actively_running")
    def test_downloading_file_orphaned(
        self, mock_is_running, mock_is_queued, mock_delay
    ):
        """Test DOWNLOADING file not running is marked orphaned and requeued."""
        # Create file with task_id and DOWNLOADING attempt
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_task_id="task-999",
            is_active=True,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        # Mock verification returns False (orphaned)
        mock_is_running.return_value = False
        mock_is_queued.return_value = True

        # Mock the requeued task
        mock_task = Mock()
        mock_task.id = "requeued-task-123"
        mock_delay.return_value = mock_task

        result = ensure_download_tasks_queued()

        assert result["verified"] == 0
        assert result["orphaned"] == 1
        assert result["requeued"] == 1  # Orphan should be requeued

        # Verify new task was queued
        mock_delay.assert_called_once_with(self.project.id)

        # File should have new task_id from requeued task
        project_file.refresh_from_db()
        assert project_file.download_task_id == "requeued-task-123"

        # First attempt should be marked FAILED
        first_attempt = project_file.download_attempts.get(attempt_number=1)
        assert first_attempt.status == DownloadAttempt.Status.FAILED
        assert "not running" in first_attempt.download_error

    @patch("wafer_space.projects.tasks.download_project_file.delay")
    @patch("wafer_space.projects.tasks.is_task_queued")
    @patch("wafer_space.projects.tasks.is_task_actively_running")
    def test_downloading_file_orphaned_max_retries(
        self, mock_is_running, mock_is_queued, mock_delay
    ):
        """Test DOWNLOADING file with max attempts is not requeued."""
        # Create file with task_id and 3 FAILED attempts (max)
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_task_id="task-999",
            is_active=True,
        )
        # Create 3 previous attempts (max_retries + 1)
        # Two failed attempts and one currently "downloading" (orphaned)
        max_attempts = 3
        for attempt_num in range(1, max_attempts + 1):
            is_latest = attempt_num == max_attempts
            DownloadAttempt.objects.create(
                project_file=project_file,
                attempt_number=attempt_num,
                status=(
                    DownloadAttempt.Status.DOWNLOADING
                    if is_latest
                    else DownloadAttempt.Status.FAILED
                ),
            )

        # Mock verification returns False (orphaned)
        mock_is_running.return_value = False
        mock_is_queued.return_value = True

        result = ensure_download_tasks_queued()

        assert result["orphaned"] == 1
        assert result["requeued"] == 0  # Should NOT be requeued (max retries)

        # Verify NO new task was queued
        mock_delay.assert_not_called()

    @patch("wafer_space.projects.tasks.socket")
    @patch("wafer_space.projects.tasks.os")
    def test_download_task_captures_worker_info(self, mock_os, mock_socket):
        """Test that download task captures PID and hostname in DownloadAttempt."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/small.txt",
            download_task_id="task-123",
            is_active=True,
        )

        # Mock PID and hostname
        mock_os.getpid.return_value = TEST_WORKER_PID
        mock_socket.gethostname.return_value = TEST_WORKER_HOSTNAME

        # This will fail to download (no server), but should capture worker info
        with contextlib.suppress(Exception):
            download_project_file(self.project.id)

        # Verify worker info was captured in the first (executed) DownloadAttempt
        # Note: When a retry is scheduled, a new PENDING attempt is created.
        # The latest_attempt would be this pending retry, not the executed one.
        project_file.refresh_from_db()

        # Get the first attempt (the one that actually executed)
        attempts = project_file.download_attempts.order_by("attempt_number")
        first_attempt = attempts.first()
        assert first_attempt is not None
        assert first_attempt.worker_pid == TEST_WORKER_PID
        assert first_attempt.worker_hostname == TEST_WORKER_HOSTNAME
        assert first_attempt.task_started_at is not None
