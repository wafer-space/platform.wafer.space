"""Tests for project models."""

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.users.models import User

from .constants import PROGRESS_COMPLETE
from .constants import TEST_PASSWORD


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
            download_status=ProjectFile.DownloadStatus.PENDING,
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
            download_status=ProjectFile.DownloadStatus.DOWNLOADING,
        )

        can_submit, reason = self.project.can_submit()

        assert can_submit is False
        assert "download" in reason.lower()
        assert "downloading" in reason.lower() or "not completed" in reason.lower()

    def test_cannot_submit_with_failed_download(self):
        """Test that project cannot be submitted with failed download."""
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.FAILED,
            download_error="Download failed",
        )

        can_submit, reason = self.project.can_submit()

        assert can_submit is False
        assert "download" in reason.lower()
        assert "failed" in reason.lower()

    def test_cannot_submit_with_unverified_hash(self):
        """Test that project cannot be submitted with unverified hash."""
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.COMPLETED,
            hash_verified=False,
        )

        can_submit, reason = self.project.can_submit()

        assert can_submit is False
        assert "hash" in reason.lower()
        assert "not been verified" in reason.lower()

    def test_cannot_submit_if_already_submitted(self):
        """Test that project cannot be submitted if already submitted."""
        # Create completed file
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.COMPLETED,
            hash_verified=True,
        )

        # Mark as submitted
        self.project.status = Project.Status.SUBMITTED
        self.project.save()

        can_submit, reason = self.project.can_submit()

        assert can_submit is False
        assert "already" in reason.lower()
        assert "submitted" in reason.lower() or "draft" in reason.lower()

    def test_can_submit_with_completed_verified_file(self):
        """Test that project can be submitted with completed and verified file."""
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.COMPLETED,
            hash_verified=True,
        )

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
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.COMPLETED,
            hash_verified=False,
        )

        with pytest.raises(ValidationError) as exc_info:
            self.project.submit()

        assert "hash" in str(exc_info.value).lower()

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_submit_sets_status_to_submitted(self, mock_task):
        """Test that submit() sets status to SUBMITTED."""
        mock_task.return_value = Mock(id="task-123")

        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.COMPLETED,
            hash_verified=True,
        )

        self.project.submit()

        self.project.refresh_from_db()
        assert self.project.status == Project.Status.SUBMITTED

    def test_submit_sets_submitted_at_timestamp(self):
        """Test that submit() sets submitted_at timestamp."""
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.COMPLETED,
            hash_verified=True,
        )

        before = timezone.now()
        self.project.submit()
        after = timezone.now()

        self.project.refresh_from_db()
        assert self.project.submitted_at is not None
        assert before <= self.project.submitted_at <= after

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_submit_creates_manufacturability_check(self, mock_task):
        """Test that submit() creates a manufacturability check."""
        mock_task.return_value = Mock(id="task-123")

        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.COMPLETED,
            hash_verified=True,
        )

        # Verify no check exists
        assert not hasattr(self.project, "manufacturability_check")

        self.project.submit()

        # Verify check was created
        self.project.refresh_from_db()
        assert hasattr(self.project, "manufacturability_check")
        check = ManufacturabilityCheck.objects.get(project=self.project)
        assert check.status == ManufacturabilityCheck.Status.QUEUED

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_submit_does_not_create_duplicate_check(self, mock_task):
        """Test that submit() does not create duplicate manufacturability check."""
        mock_task.return_value = Mock(id="task-123")

        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.COMPLETED,
            hash_verified=True,
        )

        # Create existing check
        existing_check = ManufacturabilityCheck.objects.create(
            project=self.project,
            status=ManufacturabilityCheck.Status.PROCESSING,
        )

        self.project.submit()

        # Verify only one check exists
        assert ManufacturabilityCheck.objects.filter(project=self.project).count() == 1
        # Verify it's the original check (not replaced)
        check = ManufacturabilityCheck.objects.get(project=self.project)
        assert check.id == existing_check.id
        assert check.status == ManufacturabilityCheck.Status.PROCESSING

    def test_submit_prevents_double_submission(self):
        """Test that submit() prevents double submission."""
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_status=ProjectFile.DownloadStatus.COMPLETED,
            hash_verified=True,
        )

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
            download_status=ProjectFile.DownloadStatus.COMPLETED,
        )

        assert project_file.get_progress_percentage() == PROGRESS_COMPLETE

    def test_get_progress_percentage_failed(self):
        """Test get_progress_percentage returns 0 when failed."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            download_status=ProjectFile.DownloadStatus.FAILED,
        )

        assert project_file.get_progress_percentage() == 0

    def test_get_progress_percentage_downloading_no_size(self):
        """Test get_progress_percentage returns 0 when downloading without size info."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            download_status=ProjectFile.DownloadStatus.DOWNLOADING,
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
            download_status=ProjectFile.DownloadStatus.PENDING,
        )

        assert project_file.get_progress_percentage() == 0

    def test_get_progress_message_completed(self):
        """Test get_progress_message for completed download."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            download_status=ProjectFile.DownloadStatus.COMPLETED,
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
            download_status=ProjectFile.DownloadStatus.FAILED,
            download_error="Connection timeout",
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
            download_status=ProjectFile.DownloadStatus.FAILED,
            download_error="",
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
            download_status=ProjectFile.DownloadStatus.DOWNLOADING,
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
            download_status=ProjectFile.DownloadStatus.PENDING,
        )

        message = project_file.get_progress_message()
        assert "pending" in message.lower()
        assert "waiting" in message.lower()
