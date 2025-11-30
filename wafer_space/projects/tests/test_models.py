"""Tests for project models."""

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from wafer_space.projects.exceptions import InvalidStateTransitionError
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

    @patch("wafer_space.projects.tasks.celery_job_run.delay")
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

    @patch("wafer_space.projects.tasks.celery_job_run.delay")
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
            status=ManufacturabilityCheck.Status.RUNNING,
            celery_job_id="existing-task-123",
        )

        self.project.submit()

        # Verify only one check exists
        assert ManufacturabilityCheck.objects.filter(project=self.project).count() == 1
        # Verify it's the original check (not replaced)
        check = ManufacturabilityCheck.objects.get(project_file=_pf)
        assert check.id == existing_check.id
        assert check.status == ManufacturabilityCheck.Status.RUNNING

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
class TestManufacturabilityCheckCancellingState(TestCase):
    """Test CANCELLING state in ManufacturabilityCheck."""

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

    def test_cancelling_status_exists(self):
        """Test CANCELLING is a valid status choice."""
        assert hasattr(ManufacturabilityCheck.Status, "CANCELLING")
        assert ManufacturabilityCheck.Status.CANCELLING.value == "cancelling"
        assert ManufacturabilityCheck.Status.CANCELLING.label == "Cancelling"

    def test_can_transition_to_cancelling_from_pending(self):
        """Test PENDING can transition to CANCELLING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.CANCELLING) is True

    def test_can_transition_to_cancelling_from_dispatched(self):
        """Test DISPATCHED can transition to CANCELLING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.CANCELLING) is True

    def test_can_transition_to_cancelling_from_running(self):
        """Test RUNNING can transition to CANCELLING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.CANCELLING) is True

    def test_cancelling_can_only_transition_to_cancelled(self):
        """Test CANCELLING can only transition to CANCELLED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.CANCELLED) is True
        # Cannot transition to anything else
        assert check.can_transition_to(ManufacturabilityCheck.Status.PENDING) is False
        assert check.can_transition_to(ManufacturabilityCheck.Status.ERROR) is False
        assert check.can_transition_to(ManufacturabilityCheck.Status.FINISHED) is False

    def test_cannot_transition_to_cancelled_directly_from_running(self):
        """Test RUNNING cannot skip CANCELLING and go directly to CANCELLED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        # Must go through CANCELLING first
        assert check.can_transition_to(ManufacturabilityCheck.Status.CANCELLED) is False


@pytest.mark.django_db
class TestManufacturabilityCheckMarkCancelling(TestCase):
    """Test mark_cancelling method."""

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

    def test_mark_cancelling_from_pending(self):
        """Test mark_cancelling transitions PENDING to CANCELLING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        check.mark_cancelling(reason="User requested cancellation")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLING
        assert "User requested cancellation" in check.processing_logs

    def test_mark_cancelling_from_dispatched(self):
        """Test mark_cancelling transitions DISPATCHED to CANCELLING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="test-job-123",
        )

        check.mark_cancelling(reason="New file submitted")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLING
        # Job ID preserved for cleanup task
        assert check.celery_job_id == "test-job-123"

    def test_mark_cancelling_from_running(self):
        """Test mark_cancelling transitions RUNNING to CANCELLING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_container_id="abc123def",
        )

        check.mark_cancelling(reason="Admin cancelled")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLING
        # Container ID preserved for cleanup task
        assert check.docker_container_id == "abc123def"

    def test_mark_cancelling_appends_to_existing_logs(self):
        """Test mark_cancelling appends reason to existing logs."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
            processing_logs="Previous log output",
        )

        check.mark_cancelling(reason="Cancelled by user")

        check.refresh_from_db()
        assert "Previous log output" in check.processing_logs
        assert "CANCELLATION REQUESTED: Cancelled by user" in check.processing_logs

    def test_mark_cancelling_from_finished_raises(self):
        """Test mark_cancelling raises for terminal FINISHED state."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )

        with pytest.raises(InvalidStateTransitionError):
            check.mark_cancelling(reason="Should fail")

    def test_mark_cancelling_from_cancelled_raises(self):
        """Test mark_cancelling raises for terminal CANCELLED state."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLED,
        )

        with pytest.raises(InvalidStateTransitionError):
            check.mark_cancelling(reason="Should fail")

    def test_mark_cancelling_from_error_raises(self):
        """Test mark_cancelling raises for ERROR state (should retry instead)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
        )

        with pytest.raises(InvalidStateTransitionError):
            check.mark_cancelling(reason="Should fail")


@pytest.mark.django_db
class TestManufacturabilityCheckMarkCancelled(TestCase):
    """Test ManufacturabilityCheck.mark_cancelled() method."""

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

    def test_mark_cancelled_from_pending(self):
        """Can mark PENDING check as CANCELLED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        result = check.mark_cancelled(reason="User cancelled during pending")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        assert "CANCELLED: User cancelled during pending" in check.processing_logs
        assert check.celery_job_finished_at is not None
        assert result is None  # No job_id for PENDING

    def test_mark_cancelled_from_dispatched(self):
        """Can mark DISPATCHED check as CANCELLED and returns job_id."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="celery-task-123",
        )
        result = check.mark_cancelled(reason="User cancelled after dispatch")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        assert "CANCELLED: User cancelled after dispatch" in check.processing_logs
        assert check.celery_job_finished_at is not None
        assert result == "celery-task-123"

    def test_mark_cancelled_from_running(self):
        """Can mark RUNNING check as CANCELLED and returns job_id."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
            celery_job_id="celery-task-456",
        )
        result = check.mark_cancelled(reason="User cancelled during execution")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        assert "CANCELLED: User cancelled during execution" in check.processing_logs
        assert result == "celery-task-456"

    def test_mark_cancelled_sets_fields(self):
        """mark_cancelled() sets status and timestamp correctly."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        before = timezone.now()
        check.mark_cancelled(reason="Testing field assignment")
        after = timezone.now()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        assert check.celery_job_finished_at is not None
        assert before <= check.celery_job_finished_at <= after
        assert "CANCELLED: Testing field assignment" in check.processing_logs

    def test_mark_cancelled_returns_celery_job_id(self):
        """mark_cancelled() returns celery_job_id when one exists."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
            celery_job_id="test-job-789",
        )

        result = check.mark_cancelled(reason="Test return value")

        assert result == "test-job-789"

    def test_mark_cancelled_returns_none_when_no_job(self):
        """mark_cancelled() returns None when celery_job_id is empty."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
            celery_job_id="",
        )

        result = check.mark_cancelled(reason="No job ID")

        assert result is None

    def test_mark_cancelled_from_finished_raises(self):
        """Cannot mark FINISHED check as CANCELLED (terminal state)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check.mark_cancelled(reason="Should not work")

        assert "finished" in str(exc_info.value).lower()
        assert "cancelled" in str(exc_info.value).lower()

        # Verify status unchanged
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FINISHED

    def test_mark_cancelled_from_error_raises(self):
        """Cannot mark ERROR check as CANCELLED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            error_message="Previous failure",
        )

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check.mark_cancelled(reason="Should not work")

        assert "error" in str(exc_info.value).lower()
        assert "cancelled" in str(exc_info.value).lower()

        # Verify status unchanged
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR

    def test_mark_cancelled_from_cancelled_raises(self):
        """Cannot mark CANCELLED check as CANCELLED again (terminal state)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLED,
        )

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check.mark_cancelled(reason="Already cancelled")

        assert "cancelled" in str(exc_info.value).lower()

        # Verify status unchanged
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED

    def test_mark_cancelled_appends_to_existing_logs(self):
        """mark_cancelled() appends to existing processing_logs."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
            celery_job_id="test-job",
            processing_logs="Previous log entry\nAnother entry",
        )

        check.mark_cancelled(reason="User requested stop")

        check.refresh_from_db()
        assert "Previous log entry" in check.processing_logs
        assert "Another entry" in check.processing_logs
        assert "\n\nCANCELLED: User requested stop" in check.processing_logs

    def test_mark_cancelled_creates_logs_when_empty(self):
        """mark_cancelled() creates processing_logs when none exist."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
            processing_logs="",
        )

        check.mark_cancelled(reason="Early cancellation")

        check.refresh_from_db()
        assert check.processing_logs == "CANCELLED: Early cancellation"

    def test_is_cancellable_for_pending(self):
        """Test is_cancellable returns True for PENDING checks."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        assert check.is_cancellable is True

    def test_is_cancellable_for_dispatched(self):
        """Test is_cancellable returns True for DISPATCHED checks."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
        )

        assert check.is_cancellable is True

    def test_is_cancellable_for_running(self):
        """Test is_cancellable returns True for RUNNING checks."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        assert check.is_cancellable is True

    def test_is_not_cancellable_for_finished(self):
        """Test is_cancellable returns False for FINISHED checks."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )

        assert check.is_cancellable is False

    def test_is_not_cancellable_for_error(self):
        """Test is_cancellable returns False for ERROR checks."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
        )

        assert check.is_cancellable is False

    def test_is_not_cancellable_for_cancelled(self):
        """Test is_cancellable returns False for already CANCELLED checks."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLED,
        )

        assert check.is_cancellable is False


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

    def test_queue_position_returns_none_when_not_pending(self):
        """Test queue_position returns None for non-PENDING checks."""
        # Create check and transition to RUNNING using state machine
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        check.mark_dispatched(celery_job_id="test-job-1")
        check.mark_running(
            celery_worker_pid=12345,
            celery_worker_hostname="test-worker",
            docker_container_id="container-123",
        )

        assert check.queue_position is None

    def test_queue_position_returns_1_when_first_in_queue(self):
        """Test queue_position returns 1 when first in queue."""
        # PENDING checks should have queue position based on pk ordering
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        assert check.queue_position == 1

    def test_checks_ahead_counts_earlier_pending_checks(self):
        """Test checks_ahead counts PENDING checks with lower pk."""
        # Create another project with file for second check
        project2 = Project.objects.create(user=self.user, name="Project 2")
        file2 = ProjectFile.objects.create(
            project=project2,
            original_url="https://example.com/file2.gds",
            source_url="https://example.com/file2.gds",
            original_filename="file2.gds",
            is_active=True,
        )

        # Create first check (will have lower pk, so ahead in queue)
        ManufacturabilityCheck.objects.create(
            project=project2,
            project_file=file2,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        # Create our check (higher pk, so behind in queue)
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        assert check.checks_ahead == 1
        assert check.queue_position == 2  # noqa: PLR2004

    def test_checks_running_counts_dispatched_and_running(self):
        """Test checks_running counts DISPATCHED and RUNNING checks."""
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

        # Create DISPATCHED check using state machine
        check2 = ManufacturabilityCheck.objects.create(
            project=project2,
            project_file=file2,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        check2.mark_dispatched(celery_job_id="test-job-2")

        # Create RUNNING check using state machine
        check3 = ManufacturabilityCheck.objects.create(
            project=project3,
            project_file=file3,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        check3.mark_dispatched(celery_job_id="test-job-3")
        check3.mark_running(
            celery_worker_pid=12345,
            celery_worker_hostname="test-worker",
            docker_container_id="container-123",
        )

        # Create our PENDING check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        assert check.checks_running == 2  # noqa: PLR2004


class TestManufacturabilityCheckResultDisplay(TestCase):
    """Tests for the result_display property of ManufacturabilityCheck."""

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

    def test_result_display_empty_when_not_completed(self):
        """Test result_display returns empty string for non-completed checks."""
        statuses = [
            ManufacturabilityCheck.Status.PENDING,
            ManufacturabilityCheck.Status.DISPATCHED,
            ManufacturabilityCheck.Status.RUNNING,
            ManufacturabilityCheck.Status.ERROR,
            ManufacturabilityCheck.Status.CANCELLED,
        ]
        for status in statuses:
            check = ManufacturabilityCheck.objects.create(
                project=self.project,
                project_file=self.project_file,
                status=status,
            )
            assert check.result_display == "", f"Expected empty for {status}"
            check.delete()

    def test_result_display_empty_when_is_manufacturable_none(self):
        """Test result_display returns empty string when is_manufacturable is None."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=None,
        )
        assert check.result_display == ""

    def test_result_display_manufacturable_clean(self):
        """Test result_display returns 'Manufacturable - Clean' with no warnings."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
            warnings=[],  # Empty list - no warnings
        )
        assert check.result_display == "Manufacturable - Clean"

    def test_result_display_manufacturable_clean_default_warnings(self):
        """Test result_display shows 'Manufacturable - Clean' with default warnings."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
            # warnings uses default empty list
        )
        assert check.result_display == "Manufacturable - Clean"

    def test_result_display_manufacturable_with_warnings(self):
        """Test result_display returns 'Manufacturable with Warnings' when warnings."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
            warnings=["Some minor design issue", "Another warning"],
        )
        assert check.result_display == "Manufacturable with Warnings"

    def test_result_display_not_manufacturable(self):
        """Test result_display returns 'Not Manufacturable' when failed."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=False,
            errors=["Critical design rule violation"],
        )
        assert check.result_display == "Not Manufacturable"


@pytest.mark.django_db
class TestManufacturabilityCheckStateTransitions(TestCase):
    """Tests for state machine transitions."""

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

    def test_can_transition_pending_to_dispatched(self):
        """PENDING can transition to DISPATCHED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.DISPATCHED) is True

    def test_can_transition_pending_to_error(self):
        """PENDING can transition to ERROR."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.ERROR) is True

    def test_can_transition_pending_to_cancelled(self):
        """PENDING can transition to CANCELLED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.CANCELLED) is True

    def test_cannot_transition_pending_to_running(self):
        """PENDING cannot transition directly to RUNNING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.RUNNING) is False

    def test_cannot_transition_pending_to_finished(self):
        """PENDING cannot transition to FINISHED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.FINISHED) is False

    def test_can_transition_dispatched_to_running(self):
        """DISPATCHED can transition to RUNNING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.RUNNING) is True

    def test_can_transition_running_to_finished(self):
        """RUNNING can transition to FINISHED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.FINISHED) is True

    def test_can_transition_running_to_error(self):
        """RUNNING can transition to ERROR."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.ERROR) is True

    def test_cannot_transition_finished_to_anything(self):
        """FINISHED is terminal - no transitions allowed."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        for status in ManufacturabilityCheck.Status:
            assert check.can_transition_to(status) is False

    def test_cannot_transition_cancelled_to_anything(self):
        """CANCELLED is terminal - no transitions allowed."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLED,
        )
        for status in ManufacturabilityCheck.Status:
            assert check.can_transition_to(status) is False

    def test_can_transition_error_to_pending(self):
        """ERROR can transition to PENDING (retry)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.PENDING) is True

    def test_cannot_transition_error_to_dispatched(self):
        """ERROR cannot transition directly to DISPATCHED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
        )
        result = check.can_transition_to(ManufacturabilityCheck.Status.DISPATCHED)
        assert result is False


@pytest.mark.django_db
class TestManufacturabilityCheckMarkDispatched(TestCase):
    """Tests for mark_dispatched() method."""

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

    def test_mark_dispatched_from_pending(self):
        """Can mark PENDING check as DISPATCHED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        check.mark_dispatched(celery_job_id="test-job-123")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.DISPATCHED
        assert check.celery_job_id == "test-job-123"
        assert check.celery_job_dispatched_at is not None

    def test_mark_dispatched_from_invalid_state_raises(self):
        """Cannot mark FINISHED check as DISPATCHED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check.mark_dispatched(celery_job_id="test-job-123")

        assert "finished" in str(exc_info.value).lower()
        assert "dispatched" in str(exc_info.value).lower()

    def test_mark_dispatched_from_cancelled_raises(self):
        """Cannot mark CANCELLED check as DISPATCHED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLED,
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_dispatched(celery_job_id="test-job-123")


@pytest.mark.django_db
class TestManufacturabilityCheckMarkRunning(TestCase):
    """Tests for mark_running() method."""

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

    def test_mark_running_from_dispatched(self):
        """Can mark DISPATCHED check as RUNNING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
        )
        check.mark_running(
            celery_worker_pid=TEST_WORKER_PID,
            celery_worker_hostname="worker-01",
            docker_container_id="abc123def456",
        )

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.RUNNING

    def test_mark_running_sets_all_fields(self):
        """mark_running() sets all required fields."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
        )

        before = timezone.now()
        check.mark_running(
            celery_worker_pid=TEST_WORKER_PID,
            celery_worker_hostname="worker-01",
            docker_container_id="abc123def456",
        )
        after = timezone.now()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.RUNNING
        assert check.celery_worker_pid == TEST_WORKER_PID
        assert check.celery_worker_hostname == "worker-01"
        assert check.docker_container_id == "abc123def456"
        assert check.docker_container_started_at is not None
        assert before <= check.docker_container_started_at <= after
        assert check.celery_job_started_at is not None
        assert before <= check.celery_job_started_at <= after

    def test_mark_running_from_pending_raises(self):
        """Cannot mark PENDING check as RUNNING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check.mark_running(
                celery_worker_pid=TEST_WORKER_PID,
                celery_worker_hostname="worker-01",
                docker_container_id="abc123def456",
            )

        assert "pending" in str(exc_info.value).lower()
        assert "running" in str(exc_info.value).lower()

    def test_mark_running_from_running_raises(self):
        """Cannot mark RUNNING check as RUNNING again."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_running(
                celery_worker_pid=TEST_WORKER_PID,
                celery_worker_hostname="worker-01",
                docker_container_id="abc123def456",
            )

    def test_mark_running_from_finished_raises(self):
        """Cannot mark FINISHED check as RUNNING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check.mark_running(
                celery_worker_pid=TEST_WORKER_PID,
                celery_worker_hostname="worker-01",
                docker_container_id="abc123def456",
            )

        assert "finished" in str(exc_info.value).lower()
        assert "running" in str(exc_info.value).lower()

    def test_mark_running_from_error_raises(self):
        """Cannot mark ERROR check as RUNNING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_running(
                celery_worker_pid=TEST_WORKER_PID,
                celery_worker_hostname="worker-01",
                docker_container_id="abc123def456",
            )

    def test_mark_running_from_cancelled_raises(self):
        """Cannot mark CANCELLED check as RUNNING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLED,
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_running(
                celery_worker_pid=TEST_WORKER_PID,
                celery_worker_hostname="worker-01",
                docker_container_id="abc123def456",
            )


@pytest.mark.django_db
class TestProjectSlotSize(TestCase):
    """Test Project.slot_size field and SlotSize choices."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )

    def test_slot_size_default_is_full(self):
        """Test that default slot_size is FULL (1x1)."""
        project = Project.objects.create(
            user=self.user,
            name="Test Project",
        )

        assert project.slot_size == Project.SlotSize.FULL
        assert project.slot_size == "1x1"

    def test_slot_size_choices_exist(self):
        """Test that all expected slot size choices exist."""
        choices = [choice[0] for choice in Project.SlotSize.choices]
        assert "1x1" in choices
        assert "0p5x1" in choices
        assert "1x0p5" in choices
        assert "0p5x0p5" in choices

    def test_can_create_project_with_each_slot_size(self):
        """Test that projects can be created with each slot size."""
        for slot_size, _label in Project.SlotSize.choices:
            project = Project.objects.create(
                user=self.user,
                name=f"Test Project {slot_size}",
                slot_size=slot_size,
            )
            project.refresh_from_db()
            assert project.slot_size == slot_size

    def test_slot_size_display_values(self):
        """Test that slot size display values are correct."""
        # Test that the display labels match expected format with mm dimensions and area
        expected_full = "1×1 - Full Slot (3.88mm × 5.07mm = 19.67mm²)"
        assert Project.SlotSize.FULL.label == expected_full
        expected_half_width = "0.5×1 - Half Width (1.94mm × 5.07mm = 9.84mm²)"
        assert Project.SlotSize.HALF_WIDTH.label == expected_half_width
        expected_half_height = "1×0.5 - Half Height (3.88mm × 2.535mm = 9.84mm²)"
        assert Project.SlotSize.HALF_HEIGHT.label == expected_half_height
        expected_quarter = "0.5×0.5 - Quarter Slot (1.94mm × 2.535mm = 4.92mm²)"
        assert Project.SlotSize.QUARTER.label == expected_quarter

    def test_slot_size_can_be_updated(self):
        """Test that slot_size can be updated after creation."""
        project = Project.objects.create(
            user=self.user,
            name="Test Project",
            slot_size=Project.SlotSize.FULL,
        )

        project.slot_size = Project.SlotSize.QUARTER
        project.save()

        project.refresh_from_db()
        assert project.slot_size == Project.SlotSize.QUARTER
        assert project.slot_size == "0p5x0p5"


@pytest.mark.django_db
class TestManufacturabilityCheckMarkFinished(TestCase):
    """Tests for mark_finished() method."""

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

    def test_mark_finished_from_running(self):
        """Can mark RUNNING check as FINISHED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        check.mark_finished(
            is_manufacturable=True,
            errors=[],
            warnings=[],
            processing_logs="Processing completed successfully",
        )

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FINISHED
        assert check.is_manufacturable is True
        assert check.celery_job_finished_at is not None

    def test_mark_finished_sets_all_fields(self):
        """mark_finished() sets all required fields."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        test_errors = [
            {"rule": "metal1.width", "message": "Width violation"},
        ]
        test_warnings = [
            {"rule": "density", "message": "Low metal density"},
        ]
        test_logs = "Step 1: Loading GDS\nStep 2: Running checks\nComplete"

        before = timezone.now()
        check.mark_finished(
            is_manufacturable=False,
            errors=test_errors,
            warnings=test_warnings,
            processing_logs=test_logs,
        )
        after = timezone.now()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FINISHED
        assert check.is_manufacturable is False
        assert check.errors == test_errors
        assert check.warnings == test_warnings
        assert check.processing_logs == test_logs
        assert check.celery_job_finished_at is not None
        assert before <= check.celery_job_finished_at <= after

    def test_mark_finished_from_pending_raises(self):
        """Cannot mark PENDING check as FINISHED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check.mark_finished(
                is_manufacturable=True,
                errors=[],
                warnings=[],
                processing_logs="Should fail",
            )

        assert "pending" in str(exc_info.value).lower()
        assert "finished" in str(exc_info.value).lower()

    def test_mark_finished_from_dispatched_raises(self):
        """Cannot mark DISPATCHED check as FINISHED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
        )
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check.mark_finished(
                is_manufacturable=True,
                errors=[],
                warnings=[],
                processing_logs="Should fail",
            )

        assert "dispatched" in str(exc_info.value).lower()
        assert "finished" in str(exc_info.value).lower()

    def test_mark_finished_from_finished_raises(self):
        """Cannot mark FINISHED check as FINISHED again (terminal state)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_finished(
                is_manufacturable=True,
                errors=[],
                warnings=[],
                processing_logs="Should fail",
            )

    def test_mark_finished_from_error_raises(self):
        """Cannot mark ERROR check as FINISHED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
        )
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check.mark_finished(
                is_manufacturable=True,
                errors=[],
                warnings=[],
                processing_logs="Should fail",
            )

        assert "error" in str(exc_info.value).lower()
        assert "finished" in str(exc_info.value).lower()

    def test_mark_finished_from_cancelled_raises(self):
        """Cannot mark CANCELLED check as FINISHED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLED,
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_finished(
                is_manufacturable=True,
                errors=[],
                warnings=[],
                processing_logs="Should fail",
            )


@pytest.mark.django_db
class TestManufacturabilityCheckMarkError(TestCase):
    """Tests for mark_error() method."""

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

    def test_mark_error_from_pending(self):
        """Can mark PENDING check as ERROR."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        check.mark_error(
            error_message="Docker container failed to start",
            processing_logs="Error starting container\nExit code: 1",
        )

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR
        assert check.error_message == "Docker container failed to start"
        assert check.processing_logs == "Error starting container\nExit code: 1"
        assert check.celery_job_finished_at is not None

    def test_mark_error_from_dispatched(self):
        """Can mark DISPATCHED check as ERROR."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
        )
        check.mark_error(
            error_message="Worker crashed during startup",
        )

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR
        assert check.error_message == "Worker crashed during startup"

    def test_mark_error_from_running(self):
        """Can mark RUNNING check as ERROR."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        check.mark_error(
            error_message="Timeout after 30 minutes",
            processing_logs="Processing started\nStep 1 completed\nTimeout",
        )

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR
        assert check.error_message == "Timeout after 30 minutes"
        assert check.processing_logs == "Processing started\nStep 1 completed\nTimeout"

    def test_mark_error_sets_all_fields(self):
        """mark_error() sets all required fields."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        test_error = "System error: out of memory"
        test_logs = "Started processing\nMemory usage: 95%\nOOM kill"

        before = timezone.now()
        check.mark_error(
            error_message=test_error,
            processing_logs=test_logs,
        )
        after = timezone.now()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR
        assert check.error_message == test_error
        assert check.processing_logs == test_logs
        assert check.celery_job_finished_at is not None
        assert before <= check.celery_job_finished_at <= after

    def test_mark_error_with_default_logs(self):
        """mark_error() uses empty string as default for processing_logs."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        # Don't provide processing_logs - should use default empty string
        check.mark_error(error_message="Quick failure")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR
        assert check.error_message == "Quick failure"
        assert check.processing_logs == ""

    def test_mark_error_from_finished_raises(self):
        """Cannot mark FINISHED check as ERROR (terminal state)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check.mark_error(error_message="Should not work")

        assert "finished" in str(exc_info.value).lower()
        assert "error" in str(exc_info.value).lower()

    def test_mark_error_from_error_raises(self):
        """Cannot mark ERROR check as ERROR again."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            error_message="First error",
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_error(error_message="Second error")

    def test_mark_error_from_cancelled_raises(self):
        """Cannot mark CANCELLED check as ERROR (terminal state)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLED,
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_error(error_message="Should not work")


@pytest.mark.django_db
class TestManufacturabilityCheckResetForRetry(TestCase):
    """Test ManufacturabilityCheck.reset_for_retry() state machine method."""

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
            status=Project.Status.DRAFT,
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

    def test_reset_for_retry_from_error(self):
        """Can reset ERROR check to PENDING for retry."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            retry_count=0,
            error_message="Initial error",
        )
        check.reset_for_retry(reason="Retrying after timeout")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.PENDING
        assert check.retry_count == 1

    def test_reset_for_retry_increments_count(self):
        """reset_for_retry() increments retry_count."""
        initial_count = 1
        expected_count = 2
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            retry_count=initial_count,
        )
        check.reset_for_retry()

        check.refresh_from_db()
        assert check.retry_count == expected_count

    def test_reset_for_retry_clears_job_fields(self):
        """reset_for_retry() clears all Celery/Docker tracking fields."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            retry_count=0,
            celery_job_id="abc-123",
            celery_job_dispatched_at=timezone.now(),
            celery_job_started_at=timezone.now(),
            celery_job_finished_at=timezone.now(),
            celery_worker_pid=TEST_WORKER_PID,
            celery_worker_hostname="worker-1",
            docker_container_id="container-123",
            docker_container_started_at=timezone.now(),
            error_message="Previous error",
        )
        check.reset_for_retry()

        check.refresh_from_db()
        assert check.celery_job_id == ""
        assert check.celery_job_dispatched_at is None
        assert check.celery_job_started_at is None
        assert check.celery_job_finished_at is None
        assert check.celery_worker_pid is None
        assert check.celery_worker_hostname == ""
        assert check.docker_container_id == ""
        assert check.docker_container_started_at is None
        assert check.error_message == ""

    def test_reset_for_retry_at_max_retries_raises(self):
        """Cannot retry when retry_count >= 3."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            retry_count=3,
        )
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check.reset_for_retry()

        # Verify error message mentions max retries
        assert "maximum retry limit" in str(exc_info.value).lower()
        assert "3" in str(exc_info.value)

    def test_reset_for_retry_from_pending_raises(self):
        """Cannot reset PENDING check (invalid transition)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        with pytest.raises(InvalidStateTransitionError):
            check.reset_for_retry()

    def test_reset_for_retry_from_dispatched_raises(self):
        """Cannot reset DISPATCHED check (invalid transition)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHED,
        )
        with pytest.raises(InvalidStateTransitionError):
            check.reset_for_retry()

    def test_reset_for_retry_from_running_raises(self):
        """Cannot reset RUNNING check (invalid transition)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        with pytest.raises(InvalidStateTransitionError):
            check.reset_for_retry()

    def test_reset_for_retry_from_finished_raises(self):
        """Cannot reset FINISHED check (terminal state)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        with pytest.raises(InvalidStateTransitionError):
            check.reset_for_retry()

    def test_reset_for_retry_from_cancelled_raises(self):
        """Cannot reset CANCELLED check (terminal state)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLED,
        )
        with pytest.raises(InvalidStateTransitionError):
            check.reset_for_retry()

    def test_reset_for_retry_with_reason_appends_to_logs(self):
        """reset_for_retry() appends reason to processing_logs."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            retry_count=0,
            processing_logs="Previous logs from error",
        )
        check.reset_for_retry(reason="Temporary network failure")

        check.refresh_from_db()
        assert "RETRY #1: Temporary network failure" in check.processing_logs
        assert "Previous logs from error" in check.processing_logs

    def test_reset_for_retry_with_reason_creates_logs_when_empty(self):
        """reset_for_retry() creates processing_logs when empty."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            retry_count=1,
            processing_logs="",
        )
        check.reset_for_retry(reason="Docker timeout")

        check.refresh_from_db()
        assert check.processing_logs == "RETRY #2: Docker timeout"

    def test_reset_for_retry_without_reason_does_not_modify_logs(self):
        """reset_for_retry() without reason doesn't modify processing_logs."""
        original_logs = "Error occurred at step 3"
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            retry_count=0,
            processing_logs=original_logs,
        )
        check.reset_for_retry()

        check.refresh_from_db()
        assert check.processing_logs == original_logs
