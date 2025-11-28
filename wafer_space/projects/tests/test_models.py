"""Tests for project models."""

from datetime import timedelta
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.users.models import User

from .constants import PROGRESS_COMPLETE
from .constants import TEST_PASSWORD
from .constants import TEST_WORKER_PID


@pytest.mark.django_db
class TestProjectCanSubmit(TestCase):
    """Test Project.can_submit() validation method."""

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
            description="Test project",
            status=Project.Status.DRAFT,
        )

    def test_cannot_submit_without_active_file(self):
        """Test that project cannot be submitted without active file."""
        can_submit, reason = self.project.can_submit()

        assert can_submit is False
        assert "no active file" in reason.lower()

    def test_cannot_submit_with_pending_download(self):
        """Test that project cannot be submitted with pending download."""
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

        can_submit, reason = self.project.can_submit()

        assert can_submit is False
        assert "download" in reason.lower()
        assert "pending" in reason.lower() or "not completed" in reason.lower()

    def test_cannot_submit_with_downloading_status(self):
        """Test that project cannot be submitted while downloading."""
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

        can_submit, reason = self.project.can_submit()

        assert can_submit is False
        assert "download" in reason.lower()
        assert "downloading" in reason.lower() or "not completed" in reason.lower()

    def test_cannot_submit_with_failed_download(self):
        """Test that project cannot be submitted with failed download."""

        _pf = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_error="Download failed",
        )
        DownloadAttempt.objects.create(
            project_file=_pf,
            attempt_number=1,
            status=DownloadAttempt.Status.FAILED,
            download_error="Download failed",
        )

        can_submit, reason = self.project.can_submit()

        assert can_submit is False
        assert "download" in reason.lower()
        assert "failed" in reason.lower()

    def test_cannot_submit_with_unverified_hash(self):
        """Test that project cannot be submitted with unverified hash."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=False,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        can_submit, reason = self.project.can_submit()

        assert can_submit is False
        assert "hash" in reason.lower()
        assert "not been verified" in reason.lower()

    def test_cannot_submit_if_already_submitted(self):
        """Test that project cannot be submitted if already submitted."""
        # Create completed file

        _pf = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=True,
        )
        DownloadAttempt.objects.create(
            project_file=_pf,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        # Mark as manufacturable and submitted
        self.project.is_manufacturable = True
        self.project.status = Project.Status.SUBMITTED
        self.project.save()

        can_submit, reason = self.project.can_submit()

        assert can_submit is False
        assert "already" in reason.lower()
        assert "submitted" in reason.lower() or "draft" in reason.lower()

    def test_can_submit_with_completed_verified_file(self):
        """Test that project can be submitted with completed and verified file."""

        _pf = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=True,
        )
        DownloadAttempt.objects.create(
            project_file=_pf,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )
        # Mark as manufacturable
        self.project.is_manufacturable = True
        self.project.save()

        can_submit, reason = self.project.can_submit()

        assert can_submit is True
        assert reason == ""


@pytest.mark.django_db
class TestProjectSubmit(TestCase):
    """Test Project.submit() method."""

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
            description="Test project",
            status=Project.Status.DRAFT,
        )

    def test_submit_fails_without_active_file(self):
        """Test that submit() raises ValidationError without active file."""
        with pytest.raises(ValidationError) as exc_info:
            self.project.submit()

        assert "no active file" in str(exc_info.value).lower()

    def test_submit_fails_with_unverified_file(self):
        """Test that submit() raises ValidationError with unverified file."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=False,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        with pytest.raises(ValidationError) as exc_info:
            self.project.submit()

        assert "hash" in str(exc_info.value).lower()

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_submit_sets_status_to_submitted(self, mock_task):
        """Test that submit() sets status to SUBMITTED."""
        mock_task.return_value = Mock(id="task-123")

        _pf = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=True,
        )

        DownloadAttempt.objects.create(
            project_file=_pf,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        # Mark as manufacturable
        self.project.is_manufacturable = True
        self.project.save()

        self.project.submit()

        self.project.refresh_from_db()
        assert self.project.status == Project.Status.SUBMITTED

    def test_submit_sets_submitted_at_timestamp(self):
        """Test that submit() sets submitted_at timestamp."""

        _pf = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=True,
        )
        DownloadAttempt.objects.create(
            project_file=_pf,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        # Mark as manufacturable
        self.project.is_manufacturable = True
        self.project.save()

        before = timezone.now()
        self.project.submit()
        after = timezone.now()

        self.project.refresh_from_db()
        assert self.project.submitted_at is not None
        assert before <= self.project.submitted_at <= after

    def test_submit_does_not_create_new_manufacturability_check(self):
        """Test that submit() does not create a new manufacturability check.

        Manufacturability checks are created earlier in the workflow
        (when hash is verified), not during submission.
        This test verifies submit() doesn't create duplicate checks.
        """

        _pf = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=True,
        )
        DownloadAttempt.objects.create(
            project_file=_pf,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        # Mark as manufacturable (simulating completed check from earlier workflow)
        self.project.is_manufacturable = True
        self.project.save()

        # Verify no check exists before submission
        initial_check_count = ManufacturabilityCheck.objects.filter(
            project=self.project
        ).count()

        self.project.submit()

        # Verify submit() did not create a check
        final_check_count = ManufacturabilityCheck.objects.filter(
            project=self.project
        ).count()
        assert final_check_count == initial_check_count

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_submit_does_not_create_duplicate_check(self, mock_task):
        """Test that submit() does not create duplicate manufacturability check."""
        mock_task.return_value = Mock(id="task-123")

        _pf = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=True,
        )

        DownloadAttempt.objects.create(
            project_file=_pf,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        # Mark as manufacturable
        self.project.is_manufacturable = True
        self.project.save()

        # Create existing check
        existing_check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=_pf,
            status=ManufacturabilityCheck.Status.PROCESSING,
            task_id="existing-task-123",
        )

        self.project.submit()

        # Verify only one check exists
        assert ManufacturabilityCheck.objects.filter(project=self.project).count() == 1
        # Verify it's the original check (not replaced)
        check = ManufacturabilityCheck.objects.get(project_file=_pf)
        assert check.id == existing_check.id
        assert check.status == ManufacturabilityCheck.Status.PROCESSING

    def test_submit_prevents_double_submission(self):
        """Test that submit() prevents double submission."""

        _pf = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=True,
        )
        DownloadAttempt.objects.create(
            project_file=_pf,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        # Mark as manufacturable
        self.project.is_manufacturable = True
        self.project.save()

        # First submission should succeed
        self.project.submit()
        first_submitted_at = self.project.submitted_at

        # Second submission should fail
        self.project.refresh_from_db()
        with pytest.raises(ValidationError) as exc_info:
            self.project.submit()

        assert "already" in str(exc_info.value).lower()

        # Verify submitted_at didn't change
        self.project.refresh_from_db()
        assert self.project.submitted_at == first_submitted_at


@pytest.mark.django_db
class TestProjectFileProgressMethods(TestCase):
    """Test ProjectFile progress helper methods."""

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
            description="Test project",
        )

    def test_get_progress_percentage_completed(self):
        """Test get_progress_percentage returns 100 when completed."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        assert project_file.get_progress_percentage() == PROGRESS_COMPLETE

    def test_get_progress_percentage_failed(self):
        """Test get_progress_percentage returns 0 when failed."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
        )

        assert project_file.get_progress_percentage() == 0

    def test_get_progress_percentage_downloading_no_size(self):
        """Test get_progress_percentage returns 0 when downloading without size info."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            file_size=None,
        )

        assert project_file.get_progress_percentage() == 0

    def test_get_progress_percentage_pending(self):
        """Test get_progress_percentage returns 0 when pending."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
        )

        assert project_file.get_progress_percentage() == 0

    def test_get_progress_message_completed(self):
        """Test get_progress_message for completed download."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        message = project_file.get_progress_message()
        assert "completed" in message.lower()
        assert "success" in message.lower()

    def test_get_progress_message_failed_with_error(self):
        """Test get_progress_message for failed download with error."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            download_error="Connection timeout",
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.FAILED,
            download_error="Download failed",
        )

        message = project_file.get_progress_message()
        assert "failed" in message.lower()
        assert "Connection timeout" in message

    def test_get_progress_message_failed_without_error(self):
        """Test get_progress_message for failed download without specific error."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            download_error="",
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.FAILED,
            download_error="Download failed",
        )

        message = project_file.get_progress_message()
        assert "failed" in message.lower()

    def test_get_progress_message_downloading(self):
        """Test get_progress_message for downloading status."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        message = project_file.get_progress_message()
        assert "downloading" in message.lower()

    def test_get_progress_message_pending(self):
        """Test get_progress_message for pending status."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
        )

        message = project_file.get_progress_message()
        assert "pending" in message.lower()
        assert "waiting" in message.lower()


@pytest.mark.django_db
class TestProjectFile(TestCase):
    """Test ProjectFile model fields and behavior."""

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
            description="Test project",
        )

    def test_downloadattempt_has_worker_tracking_fields(self):
        """Test that DownloadAttempt has worker tracking fields."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            is_active=False,
        )

        # Create attempt with worker tracking
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        # Verify fields exist and are nullable
        assert hasattr(attempt, "worker_pid")
        assert hasattr(attempt, "worker_hostname")
        assert hasattr(attempt, "task_started_at")
        assert attempt.worker_pid is None
        assert attempt.worker_hostname == ""
        assert attempt.task_started_at is None

        # Verify we can set values
        attempt.worker_pid = TEST_WORKER_PID
        attempt.worker_hostname = "worker-01"
        attempt.task_started_at = timezone.now()
        attempt.save()

        attempt.refresh_from_db()
        assert attempt.worker_pid == TEST_WORKER_PID
        assert attempt.worker_hostname == "worker-01"
        assert attempt.task_started_at is not None

    def test_projectfile_queued_status_exists(self):
        """Test that QUEUED status exists in DownloadStatus choices."""
        # Verify QUEUED is in choices
        statuses = [choice[0] for choice in ProjectFile.DownloadStatus.choices]
        assert "queued" in statuses

        # Verify we can create a file with QUEUED status
        # QUEUED = has task_id but no DownloadAttempt
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_task_id="task-123",
            is_active=False,
            original_filename="test.gds",
        )

        assert project_file.download_status == ProjectFile.DownloadStatus.QUEUED


@pytest.mark.django_db
class TestManufacturabilityCheckCancel(TestCase):
    """Test ManufacturabilityCheck.cancel() method."""

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
            description="Test project",
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

    def test_cancel_queued_check_returns_task_id(self):
        """Test that cancelling a queued check returns the task_id."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.QUEUED,
            task_id="celery-task-123",
        )

        result = check.cancel(reason="Test cancellation")

        assert result == "celery-task-123"
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        assert "CANCELLED: Test cancellation" in check.processing_logs
        assert check.completed_at is not None

    def test_cancel_processing_check_returns_task_id(self):
        """Test that cancelling a processing check returns the task_id."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PROCESSING,
            task_id="celery-task-456",
            started_at=timezone.now(),
        )

        result = check.cancel(reason="User requested cancellation")

        assert result == "celery-task-456"
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        assert "CANCELLED: User requested cancellation" in check.processing_logs

    def test_cancel_completed_check_returns_none(self):
        """Test that cancelling a completed check returns None."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.COMPLETED,
            task_id="celery-task-789",
            is_manufacturable=True,
        )

        result = check.cancel(reason="Should not work")

        assert result is None
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.COMPLETED

    def test_cancel_failed_check_returns_none(self):
        """Test that cancelling a failed check returns None."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FAILED,
            task_id="celery-task-999",
            error_message="Previous failure",
        )

        result = check.cancel(reason="Should not work")

        assert result is None
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FAILED

    def test_cancel_without_task_id_returns_empty_string(self):
        """Test that cancelling a check without task_id returns empty string."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.QUEUED,
            task_id="",  # No task ID
        )

        result = check.cancel(reason="No task")

        # Should still be cancelled, just returns empty string
        assert result == ""
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED

    def test_is_cancellable_for_queued(self):
        """Test is_cancellable returns True for queued checks."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.QUEUED,
        )

        assert check.is_cancellable is True

    def test_is_cancellable_for_processing(self):
        """Test is_cancellable returns True for processing checks."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PROCESSING,
        )

        assert check.is_cancellable is True

    def test_is_not_cancellable_for_completed(self):
        """Test is_cancellable returns False for completed checks."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.COMPLETED,
        )

        assert check.is_cancellable is False

    def test_is_not_cancellable_for_failed(self):
        """Test is_cancellable returns False for failed checks."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FAILED,
        )

        assert check.is_cancellable is False

    def test_is_not_cancellable_for_cancelled(self):
        """Test is_cancellable returns False for already cancelled checks."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLED,
        )

        assert check.is_cancellable is False

    def test_is_cancellable_for_starting(self):
        """Test is_cancellable returns True for starting checks."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.STARTING,
        )

        assert check.is_cancellable is True


class TestManufacturabilityCheckQueueProperties(TestCase):
    """Tests for queue position and count properties."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",  # noqa: S106
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

    def test_queue_position_returns_none_when_not_queued(self):
        """Test queue_position returns None for non-queued checks."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PROCESSING,
            queued_at=timezone.now(),
        )

        assert check.queue_position is None

    def test_queue_position_returns_none_when_no_queued_at(self):
        """Test queue_position returns None when queued_at is not set."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.QUEUED,
            queued_at=None,
        )

        assert check.queue_position is None

    def test_queue_position_returns_1_when_first_in_queue(self):
        """Test queue_position returns 1 when first in queue."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.QUEUED,
            queued_at=timezone.now(),
        )

        assert check.queue_position == 1

    def test_checks_ahead_counts_earlier_queued_checks(self):
        """Test checks_ahead counts checks queued before this one."""
        # Create another project with file for second check
        project2 = Project.objects.create(user=self.user, name="Project 2")
        file2 = ProjectFile.objects.create(
            project=project2,
            original_url="https://example.com/file2.gds",
            source_url="https://example.com/file2.gds",
            original_filename="file2.gds",
            is_active=True,
        )

        # Create first check (ahead)
        ManufacturabilityCheck.objects.create(
            project=project2,
            project_file=file2,
            status=ManufacturabilityCheck.Status.QUEUED,
            queued_at=timezone.now() - timedelta(minutes=5),
        )

        # Create our check (behind)
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.QUEUED,
            queued_at=timezone.now(),
        )

        assert check.checks_ahead == 1
        assert check.queue_position == 2  # noqa: PLR2004

    def test_checks_running_counts_starting_and_processing(self):
        """Test checks_running counts STARTING and PROCESSING checks."""
        # Create another project with files for additional checks
        project2 = Project.objects.create(user=self.user, name="Project 2")
        file2 = ProjectFile.objects.create(
            project=project2,
            original_url="https://example.com/file2.gds",
            source_url="https://example.com/file2.gds",
            original_filename="file2.gds",
            is_active=True,
        )
        project3 = Project.objects.create(user=self.user, name="Project 3")
        file3 = ProjectFile.objects.create(
            project=project3,
            original_url="https://example.com/file3.gds",
            source_url="https://example.com/file3.gds",
            original_filename="file3.gds",
            is_active=True,
        )

        # Create STARTING check
        ManufacturabilityCheck.objects.create(
            project=project2,
            project_file=file2,
            status=ManufacturabilityCheck.Status.STARTING,
        )

        # Create PROCESSING check
        ManufacturabilityCheck.objects.create(
            project=project3,
            project_file=file3,
            status=ManufacturabilityCheck.Status.PROCESSING,
        )

        # Create our QUEUED check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.QUEUED,
            queued_at=timezone.now(),
        )

        assert check.checks_running == 2  # noqa: PLR2004

    def test_queue_wait_duration_returns_timedelta(self):
        """Test queue_wait_duration returns correct timedelta."""
        wait_minutes = 10
        queued_time = timezone.now() - timedelta(minutes=wait_minutes)
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.QUEUED,
            queued_at=queued_time,
        )

        duration = check.queue_wait_duration
        assert duration is not None
        # Should be approximately 10 minutes (allow some margin)
        expected_seconds = wait_minutes * 60
        assert duration.total_seconds() >= expected_seconds
        assert duration.total_seconds() < expected_seconds + 100
