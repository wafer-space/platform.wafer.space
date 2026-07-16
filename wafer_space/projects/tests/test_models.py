"""Tests for project models."""

import hashlib
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from wafer_space.core.enums import SlotSize
from wafer_space.projects.exceptions import InvalidStateTransitionError
from wafer_space.projects.models import CheckExecutionContext
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import LicenseType
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.models import validate_crowd_supply_order_id
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.projects.tests.factories import ProjectFileFactory
from wafer_space.projects.tests.read_instrumentation import ReadSizeRecorder
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.models import User
from wafer_space.users.tests.factories import UserFactory

from .constants import FLOAT_PRECISION_TOLERANCE
from .constants import PROGRESS_COMPLETE
from .constants import TEST_PASSWORD
from .constants import TEST_WORKER_PID


def _make_exec_context(**kwargs) -> CheckExecutionContext:
    """Create a CheckExecutionContext for tests with sensible defaults."""
    return CheckExecutionContext(
        docker_container_id=kwargs.get("docker_container_id", "abc123def456"),
        docker_image=kwargs.get("docker_image", "test-image:latest"),
        docker_image_digest=kwargs.get("docker_image_digest", "sha256:test"),
        docker_command=kwargs.get("docker_command", "docker run ..."),
    )


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
        self.project.submitted_file = _pf
        self.project.status = Project.Status.SUBMITTED
        self.project.save()
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=_pf,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

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
        # Mark as manufacturable (simulates completed check via mark_finished)
        self.project.submitted_file = _pf
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=_pf,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

        can_submit, reason = self.project.can_submit()

        assert can_submit is True
        assert reason == ""

    def test_cannot_submit_unchecked_latest_revision(self):
        """An unchecked latest revision cannot ride on stale MANUFACTURABLE.

        mark_finished() on an older revision's check also sets the project
        status to MANUFACTURABLE, which must not allow submitting a newer
        revision that has no passing check of its own (Rule 1 in
        docs/manufacturable_vs_submitted.md).
        """
        old_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/old.gds",
            source_url="https://example.com/old.gds",
            original_filename="old.gds",
            is_active=False,
            hash_verified=True,
        )
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=old_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        new_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/new.gds",
            source_url="https://example.com/new.gds",
            original_filename="new.gds",
            is_active=True,
            hash_verified=True,
        )
        DownloadAttempt.objects.create(
            project_file=new_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()

        can_submit, reason = self.project.can_submit()

        assert can_submit is False
        assert "latest file" in reason.lower()


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

    def test_submit_sets_status_to_submitted(self):
        """Test that submit() sets status to SUBMITTED."""

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

        # Mark as manufacturable (simulates completed check via mark_finished)
        self.project.submitted_file = _pf
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=_pf,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

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

        # Mark as manufacturable (simulates completed check via mark_finished)
        self.project.submitted_file = _pf
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=_pf,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

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

        # Mark as manufacturable (simulates completed check via mark_finished)
        self.project.submitted_file = _pf
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=_pf,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

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

    def test_submit_does_not_create_duplicate_check(self):
        """Test that submit() does not create duplicate manufacturability check."""

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

        # Mark as manufacturable (simulates completed check via mark_finished)
        self.project.submitted_file = _pf
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()
        finished_check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=_pf,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

        initial_check_count = ManufacturabilityCheck.objects.filter(
            project=self.project
        ).count()

        self.project.submit()

        # Verify submit() did not create a new check
        final_check_count = ManufacturabilityCheck.objects.filter(
            project=self.project
        ).count()
        assert final_check_count == initial_check_count
        # Verify the finished check still exists
        finished_check.refresh_from_db()
        assert finished_check.status == ManufacturabilityCheck.Status.FINISHED

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

        # Mark as manufacturable (simulates completed check via mark_finished)
        self.project.submitted_file = _pf
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=_pf,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
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
class TestProjectDerivedManufacturabilityProperties(TestCase):
    """Tests for Project's per-file-revision derived properties.

    See docs/manufacturable_vs_submitted.md: manufacturability (a) is a
    property of a file revision, submission for manufacturing (b) is the
    revision submitted_file points at. Each property names the revision
    it reads from.
    """

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

    def test_latest_file_returns_none_without_files(self):
        """Returns None when the project has no files."""
        assert self.project.latest_file is None

    def test_latest_file_returns_active_file(self):
        """Returns the active file, not older inactive revisions."""
        ProjectFileFactory(project=self.project, is_active=False)
        active = ProjectFileFactory(project=self.project, is_active=True)
        assert self.project.latest_file == active

    def test_latest_file_check_returns_none_without_checks(self):
        """Returns None when the latest revision has no checks."""
        ProjectFileFactory(project=self.project)
        assert self.project.latest_file_check is None

    def test_latest_file_check_ignores_older_revisions(self):
        """Reads checks from the latest revision, not older ones."""
        old_file = ProjectFileFactory(project=self.project, is_active=False)
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=old_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        new_file = ProjectFileFactory(project=self.project, is_active=True)
        new_check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=new_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        assert self.project.latest_file_check == new_check

    def test_submitted_file_check_returns_none_without_submitted_file(self):
        """Returns None when nothing has been submitted for manufacturing."""
        project_file = ProjectFileFactory(project=self.project)
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        assert self.project.submitted_file_check is None

    def test_submitted_file_check_reads_submitted_revision(self):
        """Reads checks from the submitted revision even when not latest."""
        submitted = ProjectFileFactory(project=self.project, is_active=False)
        submitted_check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=submitted,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        latest = ProjectFileFactory(project=self.project, is_active=True)
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=latest,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        self.project.submitted_file = submitted
        self.project.save()
        assert self.project.submitted_file_check == submitted_check

    def test_latest_file_manufacturable_none_without_files(self):
        """Returns None when the project has no files."""
        assert self.project.latest_file_manufacturable is None

    def test_latest_file_manufacturable_none_without_finished_check(self):
        """Returns None while the latest revision has no finished check."""
        project_file = ProjectFileFactory(project=self.project)
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        assert self.project.latest_file_manufacturable is None

    def test_latest_file_manufacturable_true_from_finished_check(self):
        """Returns True when the latest revision's finished check passed."""
        project_file = ProjectFileFactory(project=self.project)
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        assert self.project.latest_file_manufacturable is True

    def test_latest_file_manufacturable_false_from_finished_check(self):
        """Returns False when the latest revision's finished check failed."""
        project_file = ProjectFileFactory(project=self.project)
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=False,
        )
        assert self.project.latest_file_manufacturable is False

    def test_latest_file_manufacturable_keeps_verdict_during_recheck(self):
        """An in-flight re-check does not reset an existing verdict."""
        project_file = ProjectFileFactory(project=self.project)
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        assert self.project.latest_file_manufacturable is True

    def test_latest_file_manufacturable_ignores_submitted_revision(self):
        """A passing submitted revision does not mask a failing latest one."""
        submitted = ProjectFileFactory(project=self.project, is_active=False)
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=submitted,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        latest = ProjectFileFactory(project=self.project, is_active=True)
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=latest,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=False,
        )
        self.project.submitted_file = submitted
        self.project.save()
        assert self.project.latest_file_manufacturable is False


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

    def test_calculate_hashes_streams_file_in_chunks(self):
        """calculate_hashes must hash the stored file with bounded reads.

        A 2.5 MiB stored file must be hashed in bounded chunks rather
        than one full read() into memory, and still produce the correct
        digests and file size.
        """
        content = bytes(range(256)) * (10 * 1024)  # 2.5 MiB
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="design.gds",
            is_active=False,
        )
        project_file.file.save("design.gds", ContentFile(content), save=True)

        # Re-fetch so the file is opened from storage, then wrap the
        # underlying file object to record every read() size.
        project_file = ProjectFile.objects.get(pk=project_file.pk)
        read_sizes: list[int] = []
        project_file.file.open("rb")
        project_file.file.file = ReadSizeRecorder(project_file.file.file, read_sizes)

        assert project_file.calculate_hashes() is True

        expected_md5 = hashlib.md5(content, usedforsecurity=False).hexdigest()
        expected_sha1 = hashlib.sha1(content, usedforsecurity=False).hexdigest()
        assert project_file.hash_md5 == expected_md5
        assert project_file.hash_sha1 == expected_sha1
        assert project_file.hash_sha256 == hashlib.sha256(content).hexdigest()
        assert project_file.file_size == len(content)
        assert read_sizes, "stored file was never read"
        chunk_limit = 4 * 1024 * 1024
        for size in read_sizes:
            assert 0 < size <= chunk_limit, f"unbounded read (size={size})"

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
        """Test DISPATCHING can transition to CANCELLING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHING,
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
            status=ManufacturabilityCheck.Status.DISPATCHING,
        )

        check.mark_cancelling(reason="New file submitted")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLING
        # Job ID preserved for cleanup task

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

    def test_mark_cancelled_from_cancelling_succeeds(self):
        """Test mark_cancelled works from CANCELLING state."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLING,
            processing_logs="CANCELLATION REQUESTED: User cancelled",
        )

        check.mark_cancelled()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED

    def test_mark_cancelled_sets_timestamp(self):
        """Test mark_cancelled completes successfully."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.CANCELLING,
        )

        check.mark_cancelled()

        check.refresh_from_db()

    def test_mark_cancelled_from_pending_raises(self):
        """Test mark_cancelled raises from PENDING.

        Must use mark_cancelling first.
        """
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        with pytest.raises(InvalidStateTransitionError):
            check.mark_cancelled()

    def test_mark_cancelled_from_dispatched_raises(self):
        """Test mark_cancelled raises from DISPATCHED.

        Must use mark_cancelling first.
        """
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHING,
        )

        with pytest.raises(InvalidStateTransitionError):
            check.mark_cancelled()

    def test_mark_cancelled_from_running_raises(self):
        """Test mark_cancelled raises from RUNNING.

        Must use mark_cancelling first.
        """
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        with pytest.raises(InvalidStateTransitionError):
            check.mark_cancelled()

    def test_mark_cancelled_from_finished_raises(self):
        """Cannot mark FINISHED check as CANCELLED (terminal state)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check.mark_cancelled()

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
            check.mark_cancelled()

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
            check.mark_cancelled()

        assert "cancelled" in str(exc_info.value).lower()

        # Verify status unchanged
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED

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
            status=ManufacturabilityCheck.Status.DISPATCHING,
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
        # Use new polling pathway to transition to RUNNING
        check.mark_dispatching(server_id="server-1")
        check.mark_starting(
            docker_image="test:latest",
            docker_image_digest="sha256:abc",
        )
        check.mark_running(
            docker_container_id="test-container",
            docker_command="precheck",
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

        # Create DISPATCHING check using state machine
        ManufacturabilityCheck.objects.create(
            project=project2,
            project_file=file2,
            status=ManufacturabilityCheck.Status.DISPATCHING,
        )

        # Create RUNNING check using state machine
        check3 = ManufacturabilityCheck.objects.create(
            project=project3,
            project_file=file3,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        # Use new polling pathway to transition to RUNNING
        check3.mark_dispatching(server_id="server-1")
        check3.mark_starting(
            docker_image="test:latest",
            docker_image_digest="sha256:abc",
        )
        check3.mark_running(
            docker_container_id="test-container",
            docker_command="precheck",
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
            ManufacturabilityCheck.Status.DISPATCHING,
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
        """PENDING can transition to DISPATCHING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        expected = ManufacturabilityCheck.Status.DISPATCHING
        assert check.can_transition_to(expected) is True

    def test_can_transition_pending_to_error(self):
        """PENDING can transition to ERROR."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.ERROR) is True

    def test_can_transition_pending_to_cancelling(self):
        """PENDING can transition to CANCELLING (not directly to CANCELLED)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.CANCELLING) is True
        # Cannot skip CANCELLING and go directly to CANCELLED
        assert check.can_transition_to(ManufacturabilityCheck.Status.CANCELLED) is False

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
        """STARTING can transition to RUNNING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.STARTING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.RUNNING) is True

    def test_can_transition_running_to_analyzing(self):
        """RUNNING can transition to ANALYZING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.ANALYZING) is True

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
        result = check.can_transition_to(ManufacturabilityCheck.Status.DISPATCHING)
        assert result is False


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
        """Can mark STARTING check as RUNNING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.STARTING,
        )
        check.mark_running(
            docker_container_id="test-container",
            docker_command="precheck",
        )

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.RUNNING

    def test_mark_running_sets_all_fields(self):
        """mark_running() sets all required fields."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.STARTING,
        )

        before = timezone.now()
        check.mark_running(
            docker_container_id="test-container-123",
            docker_command="precheck /path/to/file",
        )
        after = timezone.now()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.RUNNING
        assert check.docker_container_id == "test-container-123"
        assert check.docker_command == "precheck /path/to/file"
        assert check.container_started_at is not None
        assert before <= check.container_started_at <= after

    def test_mark_running_from_pending_raises(self):
        """Cannot mark PENDING check as RUNNING."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check.mark_running(
                docker_container_id="test-container",
                docker_command="precheck",
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
                docker_container_id="test-container",
                docker_command="precheck",
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
                docker_container_id="test-container",
                docker_command="precheck",
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
                docker_container_id="test-container",
                docker_command="precheck",
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
                docker_container_id="test-container",
                docker_command="precheck",
            )


@pytest.mark.django_db
class TestManufacturabilityCheckMarkRunningUpdated(TestCase):
    """Test updated mark_running transition method."""

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

    def test_mark_running_from_starting(self):
        """mark_running transitions STARTING -> RUNNING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.STARTING,
            project=self.project,
            project_file=self.project_file,
        )
        check.mark_running(
            docker_container_id="abc123",
            docker_command="precheck /input/design.gds",
        )
        assert check.status == ManufacturabilityCheck.Status.RUNNING

    def test_mark_running_sets_container_info(self):
        """mark_running stores container ID and command."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.STARTING,
            project=self.project,
            project_file=self.project_file,
        )
        check.mark_running(
            docker_container_id="abc123",
            docker_command="precheck /input/design.gds",
        )
        assert check.docker_container_id == "abc123"
        assert check.docker_command == "precheck /input/design.gds"

    def test_mark_running_sets_container_started_at(self):
        """mark_running sets container_started_at automatically."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.STARTING,
            project=self.project,
            project_file=self.project_file,
        )
        assert check.container_started_at is None
        check.mark_running(docker_container_id="abc123", docker_command="precheck")
        assert check.container_started_at is not None

    def test_mark_running_raises_for_invalid_transition(self):
        """mark_running raises for non-STARTING status."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            project=self.project,
            project_file=self.project_file,
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_running(docker_container_id="abc", docker_command="test")


@pytest.mark.django_db
class TestManufacturabilityCheckMarkAnalyzing(TestCase):
    """Test mark_analyzing transition method."""

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

    def test_mark_analyzing_changes_status(self):
        """mark_analyzing transitions RUNNING -> ANALYZING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            project=self.project,
            project_file=self.project_file,
        )
        check.mark_analyzing(docker_exit_code=0)
        assert check.status == ManufacturabilityCheck.Status.ANALYZING

    def test_mark_analyzing_sets_exit_code(self):
        """mark_analyzing stores container exit code."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            project=self.project,
            project_file=self.project_file,
        )
        check.mark_analyzing(docker_exit_code=1)
        assert check.docker_exit_code == 1

    def test_mark_analyzing_sets_container_finished_at(self):
        """mark_analyzing sets container_finished_at automatically."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            project=self.project,
            project_file=self.project_file,
        )
        assert check.container_finished_at is None
        check.mark_analyzing(docker_exit_code=0)
        assert check.container_finished_at is not None

    def test_mark_analyzing_raises_for_invalid_transition(self):
        """mark_analyzing raises for non-RUNNING status."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.STARTING,
            project=self.project,
            project_file=self.project_file,
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_analyzing(docker_exit_code=0)


@pytest.mark.django_db
class TestManufacturabilityCheckMarkFinishedUpdated(TestCase):
    """Test updated mark_finished transition method."""

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

    def test_mark_finished_from_analyzing(self):
        """mark_finished transitions ANALYZING -> FINISHED."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
            project=self.project,
            project_file=self.project_file,
        )
        check.mark_finished(
            is_manufacturable=True,
            errors=[],
            warnings=["minor issue"],
            tool_versions={"precheck": "1.0"},
        )
        assert check.status == ManufacturabilityCheck.Status.FINISHED

    def test_mark_finished_sets_results(self):
        """mark_finished stores analysis results."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
            project=self.project,
            project_file=self.project_file,
        )
        check.mark_finished(
            is_manufacturable=False,
            errors=["fatal error"],
            warnings=[],
            tool_versions={"precheck": "2.0"},
        )
        assert check.is_manufacturable is False
        assert check.errors == ["fatal error"]
        assert check.warnings == []
        assert check.tool_versions == {"precheck": "2.0"}

    def test_mark_finished_sets_analysis_completed_at(self):
        """mark_finished sets analysis_completed_at automatically."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.ANALYZING,
            project=self.project,
            project_file=self.project_file,
        )
        assert check.analysis_completed_at is None
        check.mark_finished(
            is_manufacturable=True,
            errors=[],
            warnings=[],
            tool_versions={},
        )
        assert check.analysis_completed_at is not None

    def test_mark_finished_raises_for_invalid_transition(self):
        """mark_finished raises for non-ANALYZING/RUNNING status."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.STARTING,
            project=self.project,
            project_file=self.project_file,
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_finished(
                is_manufacturable=True,
                errors=[],
                warnings=[],
                tool_versions={},
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

        assert project.slot_size == SlotSize.FULL
        assert project.slot_size == "1x1"

    def test_slot_size_choices_exist(self):
        """Test that all expected slot size choices exist."""
        choices = [choice[0] for choice in SlotSize.choices]
        assert "1x1" in choices
        assert "0p5x1" in choices
        assert "1x0p5" in choices
        assert "0p5x0p5" in choices

    def test_can_create_project_with_each_slot_size(self):
        """Test that projects can be created with each slot size."""
        for slot_size, _label in SlotSize.choices:
            project = Project.objects.create(
                user=self.user,
                name=f"Test Project {slot_size}",
                slot_size=slot_size,
            )
            project.refresh_from_db()
            assert project.slot_size == slot_size

    def test_slot_size_display_values(self):
        """Test that slot size display values are correct."""
        # Test short labels (default for display)
        assert SlotSize.FULL.label == "1×1"
        assert SlotSize.HALF_WIDTH.label == "0.5×1"
        assert SlotSize.HALF_HEIGHT.label == "1×0.5"
        assert SlotSize.QUARTER.label == "0.5×0.5"

        # Test full labels with dimensions (for project creation page)
        assert (
            SlotSize.FULL.full_label == "1×1 - Full Slot (3.88mm × 5.07mm = 19.67mm²)"
        )
        assert (
            SlotSize.HALF_WIDTH.full_label
            == "0.5×1 - Half Width (1.94mm × 5.07mm = 9.84mm²)"
        )
        assert (
            SlotSize.HALF_HEIGHT.full_label
            == "1×0.5 - Half Height (3.88mm × 2.535mm = 9.84mm²)"
        )
        assert (
            SlotSize.QUARTER.full_label
            == "0.5×0.5 - Quarter Slot (1.94mm × 2.535mm = 4.92mm²)"
        )

    def test_slot_size_is_immutable_fail_closed(self):
        """Test fail-closed validation when _current_user is not set.

        When _current_user is not set (e.g., background job, migration), the
        validation defaults to blocking core field changes. This is the
        fail-closed security behavior.

        Note: For tests of the normal non-staff path with _current_user set,
        see TestProjectCoreFieldImmutability.test_non_staff_cannot_modify_slot_size
        """
        project = Project.objects.create(
            user=self.user,
            name="Test Project",
            slot_size=SlotSize.FULL,
        )

        # Re-fetch from database (triggers from_db, sets _loaded_values)
        # Note: _current_user is NOT set - testing fail-closed behavior
        project = Project.objects.get(pk=project.pk)
        project.slot_size = SlotSize.QUARTER

        with pytest.raises(ValidationError) as exc_info:
            project.full_clean()

        assert "slot_size" in str(exc_info.value)


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
        """Can mark ANALYZING check as FINISHED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ANALYZING,
        )
        check.mark_finished(
            is_manufacturable=True,
            errors=[],
            warnings=[],
            tool_versions={"precheck": "1.0.0"},
        )

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FINISHED
        assert check.is_manufacturable is True
        assert check.analysis_completed_at is not None

    def test_mark_finished_sets_all_fields(self):
        """mark_finished() sets all required fields."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ANALYZING,
        )

        test_errors = ["Width violation"]
        test_warnings = ["Low metal density"]
        test_tool_versions = {"precheck": "1.0.0"}

        before = timezone.now()
        check.mark_finished(
            is_manufacturable=False,
            errors=test_errors,
            warnings=test_warnings,
            tool_versions=test_tool_versions,
        )
        after = timezone.now()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FINISHED
        assert check.is_manufacturable is False
        assert check.errors == test_errors
        assert check.warnings == test_warnings
        assert check.tool_versions == test_tool_versions
        assert check.analysis_completed_at is not None
        assert before <= check.analysis_completed_at <= after

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
                tool_versions={},
            )

        assert "pending" in str(exc_info.value).lower()
        assert "finished" in str(exc_info.value).lower()

    def test_mark_finished_from_dispatched_raises(self):
        """Cannot mark DISPATCHING check as FINISHED."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHING,
        )
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            check.mark_finished(
                is_manufacturable=True,
                errors=[],
                warnings=[],
                tool_versions={},
            )

        assert "dispatching" in str(exc_info.value).lower()
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
                tool_versions={},
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
                tool_versions={},
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
                tool_versions={},
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
        error_suffix = "\n\n=== SYSTEM ERROR - See error_message field ==="
        expected_logs = "Error starting container\nExit code: 1" + error_suffix
        assert check.processing_logs == expected_logs

    def test_mark_error_from_dispatched(self):
        """Can mark DISPATCHING check as ERROR."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHING,
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
        error_suffix = "\n\n=== SYSTEM ERROR - See error_message field ==="
        expected_logs = "Processing started\nStep 1 completed\nTimeout" + error_suffix
        assert check.processing_logs == expected_logs

    def test_mark_error_sets_all_fields(self):
        """mark_error() sets all required fields."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        test_error = "System error: out of memory"
        test_logs = "Started processing\nMemory usage: 95%\nOOM kill"

        check.mark_error(
            error_message=test_error,
            processing_logs=test_logs,
        )

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR
        assert check.error_message == test_error
        error_suffix = "\n\n=== SYSTEM ERROR - See error_message field ==="
        assert check.processing_logs == test_logs + error_suffix

    def test_mark_error_with_default_logs(self):
        """mark_error() appends error suffix even when no logs provided."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        # Don't provide processing_logs - should still get error suffix
        check.mark_error(error_message="Quick failure")

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR
        assert check.error_message == "Quick failure"
        # When logs are empty, append helper doesn't add leading newlines
        error_suffix = "=== SYSTEM ERROR - See error_message field ==="
        assert check.processing_logs == error_suffix

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


# NOTE: TestManufacturabilityCheckResetForRetry was removed as part of the
# multi-check refactor. The reset_for_retry() method was replaced by
# create_retry_check() which creates a new check instead of resetting the
# existing one. See wafer_space/projects/check_operations.py for the new
# implementation and wafer_space/projects/tests/test_services.py for tests.


@pytest.mark.django_db
class TestProjectHistory:
    """Test Project history tracking with django-simple-history."""

    def test_history_created_on_initial_save(self):
        """Verify that creating a Project creates a history record."""
        project = ProjectFactory(name="Test Project")

        assert project.history.count() == 1
        history_record = project.history.first()
        assert history_record.name == "Test Project"
        assert history_record.history_type == "+"  # Created

    def test_history_tracks_field_changes(self):
        """Verify that updating a Project creates a new history record."""
        project = ProjectFactory(name="Original Name")
        original_count = project.history.count()

        project.name = "Updated Name"
        project.save()

        assert project.history.count() == original_count + 1
        latest = project.history.first()
        assert latest.name == "Updated Name"
        assert latest.history_type == "~"  # Updated

    def test_history_tracks_user_when_set(self):
        """Verify that history records the user who made the change.

        Note: _history_user is the django-simple-history public API for setting
        the user who made the change, despite the underscore prefix.
        """
        user = UserFactory()
        project = ProjectFactory(name="Test")

        project.name = "Changed by user"
        project._history_user = user  # noqa: SLF001
        project.save()

        latest = project.history.first()
        assert latest.history_user == user

    def test_history_tracks_deletion(self):
        """Verify that deleting a Project creates a deletion history record."""
        project = ProjectFactory(name="To Be Deleted")
        project_id = project.id

        project.delete()

        history = Project.history.filter(id=project_id)
        assert history.exists()

        latest = history.first()
        assert latest.history_type == "-"  # Deleted

    def test_history_tracks_is_public_changes(self):
        """Verify that changes to is_public are tracked in history."""
        project = ProjectFactory(name="Test", is_public=False)
        initial_count = project.history.count()

        # Change visibility to public
        project.is_public = True
        project.save()

        assert project.history.count() == initial_count + 1
        latest = project.history.first()
        assert latest.is_public is True
        assert latest.history_type == "~"  # Updated


@pytest.mark.django_db
class TestProjectIsPublic:
    """Test Project is_public field behavior."""

    def test_is_public_defaults_to_false(self):
        """Verify that is_public defaults to False for new projects."""
        project = ProjectFactory()

        assert project.is_public is False

    def test_is_public_can_be_set_to_true(self):
        """Verify that is_public can be set to True."""
        project = ProjectFactory(is_public=True)

        assert project.is_public is True

    def test_is_public_can_be_toggled(self):
        """Verify that is_public can be toggled between True and False."""
        project = ProjectFactory(is_public=False)

        project.is_public = True
        project.save()
        project.refresh_from_db()
        assert project.is_public is True

        project.is_public = False
        project.save()
        project.refresh_from_db()
        assert project.is_public is False


@pytest.mark.django_db
class TestProjectLicenseFields:
    """Tests for project license tracking fields."""

    def test_default_license_type_is_proprietary(self, user):
        """New projects default to proprietary license."""
        project = Project.objects.create(
            user=user,
            name="Test Project",
            project_id="TEST",
        )
        assert project.license_type == LicenseType.PROPRIETARY

    def test_license_type_choices_include_common_licenses(self):
        """LicenseType enum includes expected common licenses."""
        license_values = [choice[0] for choice in LicenseType.choices]
        assert "MIT" in license_values
        assert "Apache-2.0" in license_values
        assert "proprietary" in license_values
        assert "other" in license_values

    def test_repository_url_is_optional(self, user):
        """Projects can be created without repository_url."""
        project = Project.objects.create(
            user=user,
            name="Test Project",
            project_id="TEST",
        )
        assert project.repository_url == ""

    def test_repository_url_can_be_set(self, user):
        """Repository URL can be set on project."""
        project = Project.objects.create(
            user=user,
            name="Test Project",
            project_id="TEST",
            repository_url="https://github.com/user/repo",
        )
        assert project.repository_url == "https://github.com/user/repo"

    def test_other_license_spdx_id_is_optional(self, user):
        """other_license_spdx_id is optional."""
        project = Project.objects.create(
            user=user,
            name="Test Project",
            project_id="TEST",
            license_type=LicenseType.MIT,
        )
        assert project.other_license_spdx_id == ""

    def test_proprietary_terms_fields_are_optional(self, user):
        """Proprietary terms fields are optional."""
        project = Project.objects.create(
            user=user,
            name="Test Project",
            project_id="TEST",
        )
        assert project.proprietary_terms_url == ""
        assert project.proprietary_terms_cached == ""
        assert project.proprietary_terms_cached_at is None


class TestManufacturabilityCheckStatusValues:
    """Test new status values exist."""

    def test_dispatching_status_exists(self) -> None:
        """DISPATCHING status should exist for image pulling phase."""
        assert ManufacturabilityCheck.Status.DISPATCHING == "dispatching"

    def test_starting_status_exists(self) -> None:
        """STARTING status should exist for container creation phase."""
        assert ManufacturabilityCheck.Status.STARTING == "starting"

    def test_analyzing_status_exists(self) -> None:
        """ANALYZING status should exist for post-container log analysis."""
        assert ManufacturabilityCheck.Status.ANALYZING == "analyzing"


class TestManufacturabilityCheckStatusClassification:
    """Test status classification methods."""

    def test_active_returns_processing_statuses(self) -> None:
        """active() returns statuses where check is actively being processed."""
        active = ManufacturabilityCheck.Status.active()
        assert ManufacturabilityCheck.Status.DISPATCHING in active
        assert ManufacturabilityCheck.Status.STARTING in active
        assert ManufacturabilityCheck.Status.RUNNING in active
        assert ManufacturabilityCheck.Status.ANALYZING in active
        assert ManufacturabilityCheck.Status.CANCELLING in active
        # These should NOT be in active:
        assert ManufacturabilityCheck.Status.PENDING not in active
        assert ManufacturabilityCheck.Status.FINISHED not in active

    def test_terminal_returns_completion_statuses(self) -> None:
        """terminal() returns statuses representing completion."""
        terminal = ManufacturabilityCheck.Status.terminal()
        assert ManufacturabilityCheck.Status.FINISHED in terminal
        assert ManufacturabilityCheck.Status.CANCELLED in terminal
        assert ManufacturabilityCheck.Status.ERROR in terminal
        # These should NOT be in terminal:
        assert ManufacturabilityCheck.Status.PENDING not in terminal
        assert ManufacturabilityCheck.Status.RUNNING not in terminal


@pytest.mark.django_db
class TestManufacturabilityCheckNewTransitions(TestCase):
    """Test new state transitions are allowed."""

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

    def test_pending_can_transition_to_dispatching(self):
        """PENDING -> DISPATCHING is allowed."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.DISPATCHING)

    def test_dispatching_can_transition_to_starting(self):
        """DISPATCHING -> STARTING is allowed."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.STARTING)

    def test_starting_can_transition_to_running(self):
        """STARTING -> RUNNING is allowed."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.STARTING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.RUNNING)

    def test_running_can_transition_to_analyzing(self):
        """RUNNING -> ANALYZING is allowed."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.ANALYZING)

    def test_analyzing_can_transition_to_finished(self):
        """ANALYZING -> FINISHED is allowed."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ANALYZING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.FINISHED)

    def test_analyzing_can_transition_to_error(self):
        """ANALYZING -> ERROR is allowed."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ANALYZING,
        )
        assert check.can_transition_to(ManufacturabilityCheck.Status.ERROR)


@pytest.mark.django_db
class TestManufacturabilityCheckServerField:
    """Test docker_server_id field."""

    def test_docker_server_id_field_exists(self) -> None:
        """Check should have docker_server_id field."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "docker_server_id")
        assert check.docker_server_id == ""  # Default is empty string

    def test_docker_server_id_can_be_set(self) -> None:
        """docker_server_id can store server identifier."""
        check = ManufacturabilityCheckFactory(docker_server_id="local")
        assert check.docker_server_id == "local"


@pytest.mark.django_db
class TestManufacturabilityCheckTimestampFields:
    """Test new granular timestamp fields."""

    def test_dispatching_started_at_field_exists(self) -> None:
        """Check should have dispatching_started_at field."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "dispatching_started_at")
        assert check.dispatching_started_at is None

    def test_starting_started_at_field_exists(self) -> None:
        """Check should have starting_started_at field."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "starting_started_at")
        assert check.starting_started_at is None

    def test_container_started_at_field_exists(self) -> None:
        """Check should have container_started_at field."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "container_started_at")
        assert check.container_started_at is None

    def test_container_finished_at_field_exists(self) -> None:
        """Check should have container_finished_at field."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "container_finished_at")
        assert check.container_finished_at is None

    def test_analysis_completed_at_field_exists(self) -> None:
        """Check should have analysis_completed_at field."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "analysis_completed_at")
        assert check.analysis_completed_at is None


@pytest.mark.django_db
class TestManufacturabilityCheckDockerFields:
    """Test Docker-related fields."""

    def test_docker_exit_code_field_exists(self) -> None:
        """Check should have docker_exit_code field."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "docker_exit_code")
        assert check.docker_exit_code is None

    def test_logs_downloaded_until_field_exists(self) -> None:
        """Check should have logs_downloaded_until field for incremental log fetch."""
        check = ManufacturabilityCheckFactory()
        assert hasattr(check, "logs_downloaded_until")
        assert check.logs_downloaded_until is None

    def test_logs_downloaded_until_stores_float(self) -> None:
        """logs_downloaded_until stores Unix timestamp with nanosecond precision."""
        check = ManufacturabilityCheckFactory()
        check.logs_downloaded_until = 1733400000.123456789
        check.save()
        check.refresh_from_db()
        # Float precision may vary, but should be close
        assert (
            abs(check.logs_downloaded_until - 1733400000.123456789)
            < FLOAT_PRECISION_TOLERANCE
        )


@pytest.mark.django_db
class TestManufacturabilityCheckMarkDispatching:
    """Test mark_dispatching transition method."""

    def test_mark_dispatching_changes_status(self) -> None:
        """mark_dispatching transitions PENDING -> DISPATCHING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        check.mark_dispatching(server_id="local")
        assert check.status == ManufacturabilityCheck.Status.DISPATCHING

    def test_mark_dispatching_sets_server_id(self) -> None:
        """mark_dispatching stores the assigned server ID."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        check.mark_dispatching(server_id="remote-1")
        assert check.docker_server_id == "remote-1"

    def test_mark_dispatching_sets_timestamp(self) -> None:
        """mark_dispatching sets dispatching_started_at automatically."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        assert check.dispatching_started_at is None
        check.mark_dispatching(server_id="local")
        assert check.dispatching_started_at is not None

    def test_mark_dispatching_saves_to_db(self) -> None:
        """mark_dispatching saves changes to database."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        check.mark_dispatching(server_id="local")
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.DISPATCHING
        assert check.docker_server_id == "local"

    def test_mark_dispatching_raises_for_invalid_transition(self) -> None:
        """mark_dispatching raises for non-PENDING status."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_dispatching(server_id="local")


@pytest.mark.django_db
class TestManufacturabilityCheckMarkStarting:
    """Test mark_starting transition method."""

    def test_mark_starting_changes_status(self) -> None:
        """mark_starting transitions DISPATCHING -> STARTING."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING
        )
        check.mark_starting(
            docker_image="ghcr.io/test:latest", docker_image_digest="sha256:abc123"
        )
        assert check.status == ManufacturabilityCheck.Status.STARTING

    def test_mark_starting_sets_image_info(self) -> None:
        """mark_starting stores image and digest."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING
        )
        check.mark_starting(
            docker_image="ghcr.io/test:latest", docker_image_digest="sha256:abc123"
        )
        assert check.docker_image == "ghcr.io/test:latest"
        assert check.docker_image_digest == "sha256:abc123"

    def test_mark_starting_sets_timestamp(self) -> None:
        """mark_starting sets starting_started_at automatically."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING
        )
        assert check.starting_started_at is None
        check.mark_starting(
            docker_image="ghcr.io/test:latest", docker_image_digest="sha256:abc123"
        )
        assert check.starting_started_at is not None

    def test_mark_starting_saves_to_db(self) -> None:
        """mark_starting saves changes to database."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING
        )
        check.mark_starting(
            docker_image="ghcr.io/test:latest", docker_image_digest="sha256:abc123"
        )
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.STARTING
        assert check.docker_image == "ghcr.io/test:latest"
        assert check.docker_image_digest == "sha256:abc123"

    def test_mark_starting_raises_for_invalid_transition(self) -> None:
        """mark_starting raises for non-DISPATCHING status."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        with pytest.raises(InvalidStateTransitionError):
            check.mark_starting(docker_image="test", docker_image_digest="sha256:abc")


@pytest.mark.django_db
class TestManufacturabilityCheckTriggerReason:
    """Tests for ManufacturabilityCheck.TriggerReason and trigger_reason field."""

    def test_trigger_reason_choices_exist(self):
        """TriggerReason enum has expected choices."""
        choices = ManufacturabilityCheck.TriggerReason.choices
        assert ("initial", "Initial Check") in choices
        assert ("drc_update", "DRC Rules Updated") in choices
        assert ("admin_rerun", "Admin Requested Re-run") in choices
        assert ("retry", "Retry After Error") in choices

    def test_trigger_reason_default_is_initial(self):
        """New checks default to INITIAL trigger reason."""
        check = ManufacturabilityCheckFactory()
        assert check.trigger_reason == ManufacturabilityCheck.TriggerReason.INITIAL

    def test_trigger_reason_can_be_set(self):
        """trigger_reason can be set to any valid choice."""
        check = ManufacturabilityCheckFactory(
            trigger_reason=ManufacturabilityCheck.TriggerReason.DRC_UPDATE
        )
        assert check.trigger_reason == ManufacturabilityCheck.TriggerReason.DRC_UPDATE


@pytest.mark.django_db
class TestCobChangeTriggerReason:
    """Tests for the COB_CHANGE trigger reason."""

    def test_cob_change_choice_exists(self):
        """COB_CHANGE is a valid TriggerReason."""
        reason = ManufacturabilityCheck.TriggerReason.COB_CHANGE
        assert reason.value == "cob_change"
        assert reason.label == "Chip-on-Board Option Changed"


@pytest.mark.django_db
class TestProjectCoreFieldImmutability:
    """Tests for Project core field immutability validation.

    Core fields (shuttle, project_id, slot_size) are immutable after creation
    except for staff users. This is enforced in clean() using values captured
    by from_db().
    """

    @pytest.fixture
    def shuttle(self):
        """Create a shuttle for testing."""
        return Shuttle.objects.create(
            name="G880",
            description="Test Shuttle for Immutability Tests",
            status=Shuttle.Status.OPEN,
        )

    @pytest.fixture
    def other_shuttle(self):
        """Create another shuttle for testing shuttle changes."""
        return Shuttle.objects.create(
            name="G881",
            description="Other Shuttle for Immutability Tests",
            status=Shuttle.Status.OPEN,
        )

    @pytest.fixture
    def user(self):
        """Create a regular user."""
        return UserFactory()

    @pytest.fixture
    def staff_user(self):
        """Create a staff user."""
        return UserFactory(is_staff=True)

    @pytest.fixture
    def project(self, user, shuttle):
        """Create a project for testing."""
        return Project.objects.create(
            user=user,
            name="Test Project",
            shuttle=shuttle,
            project_id="TEST",
            slot_size=SlotSize.FULL,
        )

    def test_from_db_captures_loaded_values(self, project):
        """from_db() sets _loaded_values when loading from database."""
        # Reload from database to trigger from_db()
        loaded_project = Project.objects.get(pk=project.pk)

        assert hasattr(loaded_project, "_loaded_values")
        loaded_values = loaded_project._loaded_values  # noqa: SLF001
        assert "project_id" in loaded_values
        assert "slot_size" in loaded_values
        assert "shuttle_id" in loaded_values
        assert loaded_values["project_id"] == "TEST"

    def test_fail_closed_blocks_modification_without_current_user(self, project):
        """Fail-closed: no _current_user blocks core field changes.

        When _current_user is not set (e.g., background job, migration),
        validation defaults to blocking all core field changes for security.
        This is different from the non-staff path which explicitly sets
        _current_user to a non-staff user.
        """
        loaded_project = Project.objects.get(pk=project.pk)
        # Explicitly NOT setting _current_user to test fail-closed behavior

        loaded_project.project_id = "FAIL"

        with pytest.raises(ValidationError) as exc_info:
            loaded_project.full_clean()

        assert "project_id" in str(exc_info.value)
        assert "Cannot modify" in str(exc_info.value)

    def test_non_staff_cannot_modify_project_id(self, project, user):
        """Non-staff user cannot modify project_id after creation."""
        # Reload to get _loaded_values via from_db()
        loaded_project = Project.objects.get(pk=project.pk)
        loaded_project._current_user = user  # noqa: SLF001

        # Try to change project_id
        loaded_project.project_id = "NEWI"

        with pytest.raises(ValidationError) as exc_info:
            loaded_project.full_clean()

        assert "project_id" in str(exc_info.value)
        assert "Cannot modify" in str(exc_info.value)

    def test_non_staff_cannot_modify_slot_size(self, project, user):
        """Non-staff user cannot modify slot_size after creation."""
        loaded_project = Project.objects.get(pk=project.pk)
        loaded_project._current_user = user  # noqa: SLF001

        loaded_project.slot_size = SlotSize.HALF_WIDTH

        with pytest.raises(ValidationError) as exc_info:
            loaded_project.full_clean()

        assert "slot_size" in str(exc_info.value)

    def test_non_staff_cannot_modify_shuttle(self, project, user, other_shuttle):
        """Non-staff user cannot modify shuttle after creation."""
        loaded_project = Project.objects.get(pk=project.pk)
        loaded_project._current_user = user  # noqa: SLF001

        loaded_project.shuttle = other_shuttle

        with pytest.raises(ValidationError) as exc_info:
            loaded_project.full_clean()

        assert "shuttle" in str(exc_info.value)

    def test_staff_can_modify_project_id(self, project, staff_user):
        """Staff user can modify project_id after creation."""
        loaded_project = Project.objects.get(pk=project.pk)
        loaded_project._current_user = staff_user  # noqa: SLF001

        loaded_project.project_id = "STAF"

        # Should not raise
        loaded_project.full_clean()
        loaded_project.save()

        # Verify change persisted
        reloaded = Project.objects.get(pk=project.pk)
        assert reloaded.project_id == "STAF"

    def test_staff_can_modify_slot_size(self, project, staff_user):
        """Staff user can modify slot_size after creation."""
        loaded_project = Project.objects.get(pk=project.pk)
        loaded_project._current_user = staff_user  # noqa: SLF001

        loaded_project.slot_size = SlotSize.HALF_WIDTH

        loaded_project.full_clean()
        loaded_project.save()

        reloaded = Project.objects.get(pk=project.pk)
        assert reloaded.slot_size == SlotSize.HALF_WIDTH

    def test_staff_can_modify_shuttle(self, project, staff_user, other_shuttle):
        """Staff user can modify shuttle after creation."""
        loaded_project = Project.objects.get(pk=project.pk)
        loaded_project._current_user = staff_user  # noqa: SLF001

        loaded_project.shuttle = other_shuttle

        loaded_project.full_clean()
        loaded_project.save()

        reloaded = Project.objects.get(pk=project.pk)
        assert reloaded.shuttle == other_shuttle

    def test_user_fields_can_be_modified_by_non_staff(self, project, user):
        """Non-staff user can modify user fields (name, description, etc.)."""
        loaded_project = Project.objects.get(pk=project.pk)
        loaded_project._current_user = user  # noqa: SLF001

        # Modify user fields
        loaded_project.name = "Updated Name"
        loaded_project.description = "Updated description"
        loaded_project.is_public = True

        # Should not raise
        loaded_project.full_clean()
        loaded_project.save()

        reloaded = Project.objects.get(pk=project.pk)
        assert reloaded.name == "Updated Name"
        assert reloaded.description == "Updated description"
        assert reloaded.is_public is True

    def test_new_project_allows_core_field_setting(self, user, shuttle):
        """New projects can set core fields without restriction."""
        project = Project(
            user=user,
            name="New Project",
            shuttle=shuttle,
            project_id="NEW1",
            slot_size=SlotSize.HALF_HEIGHT,
        )

        # Should not raise - new projects can set any field
        project.full_clean()
        project.save()

        assert project.project_id == "NEW1"
        assert project.slot_size == SlotSize.HALF_HEIGHT

    def test_validation_without_loaded_values_raises_error(self, user, shuttle):
        """Validation raises RuntimeError when _loaded_values is missing.

        If an existing instance doesn't have _loaded_values, it means it wasn't
        loaded via QuerySet - this is a programming error that should fail loudly.
        This can happen with bulk_create(), raw SQL, or manual construction.
        """
        # Create project via factory (save() now sets _loaded_values)
        project = ProjectFactory(user=user, shuttle=shuttle)

        # Manually delete _loaded_values to simulate edge case
        # (e.g., bulk_create, raw SQL, or manual object construction)
        del project._loaded_values  # noqa: SLF001

        # Manually set _current_user to non-staff
        project._current_user = user  # noqa: SLF001

        # Modify core field
        project.project_id = "MODI"

        # Should raise RuntimeError because _loaded_values is missing
        with pytest.raises(RuntimeError) as exc_info:
            project.full_clean()

        assert "missing _loaded_values" in str(exc_info.value)

    def test_multiple_core_field_changes_reported(self, project, user):
        """All changed core fields are reported in error message."""
        loaded_project = Project.objects.get(pk=project.pk)
        loaded_project._current_user = user  # noqa: SLF001

        # Change multiple core fields
        loaded_project.project_id = "MULT"
        loaded_project.slot_size = SlotSize.HALF_WIDTH

        with pytest.raises(ValidationError) as exc_info:
            loaded_project.full_clean()

        error_message = str(exc_info.value)
        assert "project_id" in error_message
        assert "slot_size" in error_message


@pytest.mark.django_db
class TestCreateCheckDrcUpdate:
    """Tests for ManufacturabilityCheck.create_check_drc_update()."""

    def setup_method(self):
        """Clear cache before each test."""
        cache.clear()

    def test_create_check_drc_update_success(self):
        """create_check_drc_update creates new check with correct attributes."""
        # Create a finished check with outdated digest
        old_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        # Create newer check to make old one outdated
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        new_check = old_check.create_check_drc_update()

        assert new_check.project == old_check.project
        assert new_check.project_file == old_check.project_file
        assert (
            new_check.trigger_reason == ManufacturabilityCheck.TriggerReason.DRC_UPDATE
        )
        assert new_check.parent_check == old_check
        assert new_check.status == ManufacturabilityCheck.Status.PENDING

    def test_create_check_drc_update_fails_not_latest_check(self):
        """create_check_drc_update raises ValueError if not latest check."""
        project_file = ProjectFileFactory()
        old_check = ManufacturabilityCheckFactory(
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
        )
        # Create newer check for same file
        ManufacturabilityCheckFactory(
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
        )

        with pytest.raises(ValueError, match="latest check"):
            old_check.create_check_drc_update()

    def test_create_check_drc_update_fails_no_digest(self):
        """create_check_drc_update raises ValueError if no digest."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING,
            docker_image_digest="",
        )

        with pytest.raises(ValueError, match="does not have a version"):
            check.create_check_drc_update()

    def test_create_check_drc_update_fails_already_latest(self):
        """create_check_drc_update raises ValueError if already using latest."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:latest123456789012345678901234567890123456789012345678901234",
            container_started_at=timezone.now(),
        )
        cache.clear()

        with pytest.raises(ValueError, match="already using latest"):
            check.create_check_drc_update()

    def test_create_check_drc_update_works_for_running_check(self):
        """create_check_drc_update works for in-progress checks with outdated digest."""
        # Create running check with outdated digest
        running_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=1),
        )
        # Create newer check to make running one outdated
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        new_check = running_check.create_check_drc_update()

        assert new_check.parent_check == running_check
        assert (
            new_check.trigger_reason == ManufacturabilityCheck.TriggerReason.DRC_UPDATE
        )


@pytest.mark.django_db
class TestCreateCheckCobChange:
    """Tests for ManufacturabilityCheck.create_check_cob_change()."""

    def test_creates_pending_cob_change_check(self):
        """Creates a PENDING check with COB_CHANGE reason chained to the source."""
        old_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED,
        )

        new_check = old_check.create_check_cob_change()

        assert new_check.project == old_check.project
        assert new_check.project_file == old_check.project_file
        assert (
            new_check.trigger_reason == ManufacturabilityCheck.TriggerReason.COB_CHANGE
        )
        assert new_check.parent_check == old_check
        assert new_check.status == ManufacturabilityCheck.Status.PENDING

    def test_finished_source_check_is_not_cancelled(self):
        """A FINISHED source check keeps its status (nothing to cancel)."""
        old_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED,
        )

        old_check.create_check_cob_change()

        old_check.refresh_from_db()
        assert old_check.status == ManufacturabilityCheck.Status.FINISHED

    def test_in_progress_source_check_is_marked_cancelling(self):
        """A RUNNING source check is explicitly marked CANCELLING."""
        running_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        new_check = running_check.create_check_cob_change()

        running_check.refresh_from_db()
        assert running_check.status == ManufacturabilityCheck.Status.CANCELLING
        assert "Chip-on-Board option changed" in running_check.processing_logs
        assert new_check.status == ManufacturabilityCheck.Status.PENDING

    def test_raises_when_not_latest_check(self):
        """Refuses to run on a check that is not the file's latest."""
        project_file = ProjectFileFactory()
        old_check = ManufacturabilityCheckFactory(
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        ManufacturabilityCheckFactory(
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )

        with pytest.raises(ValueError, match="latest check"):
            old_check.create_check_cob_change()

    def test_concurrent_finish_is_not_clobbered_by_stale_cancel(self):
        """A concurrent FINISH must not be overwritten from a stale source check.

        Reproduces the TOCTOU race: the source check is held in memory while
        RUNNING, but another worker transitions it to FINISHED in the database
        before the CoB re-check runs. The re-check must observe the committed
        FINISHED status via a locked re-read and leave it untouched, rather than
        clobbering it back to CANCELLING from the stale in-memory RUNNING value.
        """
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        # Concurrent worker finishes the check; the in-memory object is unaware.
        ManufacturabilityCheck.objects.filter(pk=check.pk).update(
            status=ManufacturabilityCheck.Status.FINISHED,
        )

        check.create_check_cob_change()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FINISHED


@pytest.mark.django_db
class TestProjectChipOnBoard:
    """Tests for the Project.chip_on_board flag."""

    def test_defaults_to_false(self):
        """chip_on_board defaults to False."""
        project = ProjectFactory()
        assert project.chip_on_board is False

    def test_is_editable_after_creation(self):
        """chip_on_board is a user field, not blocked by core-field immutability."""
        project = ProjectFactory()
        project.chip_on_board = True
        project.full_clean()  # core-field immutability is enforced in clean()
        project.save()
        # Fetch fresh from the DB: refresh_from_db() would leave the stale
        # in-memory attribute in place pre-implementation, hiding the RED.
        reloaded = Project.objects.get(pk=project.pk)
        assert reloaded.chip_on_board is True

    def test_is_a_user_field(self):
        """chip_on_board is in USER_FIELDS and not in CORE_FIELDS."""
        assert "chip_on_board" in Project.USER_FIELDS
        assert "chip_on_board" not in Project.CORE_FIELDS


class TestCrowdSupplyOrderId:
    """CrowdSupply order number validation and order-page URL property."""

    @pytest.mark.parametrize("value", ["327373", "0", "00123"])
    def test_validator_accepts_digit_strings(self, value):
        # Should not raise.
        validate_crowd_supply_order_id(value)

    @pytest.mark.parametrize(
        "value",
        ["abc", "3273 73", "#327373", "32.73", "-1", "٣٢٧"],
    )
    def test_validator_rejects_non_digits(self, value):
        # The final case is Arabic-Indic digits: str.isdigit() alone accepts
        # them, so the validator must also require ASCII.
        with pytest.raises(ValidationError):
            validate_crowd_supply_order_id(value)

    @pytest.mark.django_db
    def test_blank_order_id_is_valid(self):
        # Field is optional: blank must pass full_clean (validators skipped on blank).
        # NOTE: reload via objects.get() first. Project.clean() runs
        # _validate_core_fields_immutable() on saved instances, which requires
        # _loaded_values (only populated by from_db()); a bare factory instance
        # would raise RuntimeError otherwise. This mirrors the existing pattern
        # used elsewhere in test_models.py.
        project = ProjectFactory()
        loaded_project = Project.objects.get(pk=project.pk)
        loaded_project.crowd_supply_order_id = ""
        loaded_project.full_clean()  # must not raise

    @pytest.mark.django_db
    def test_url_property_returns_account_order_url(self):
        project = ProjectFactory(crowd_supply_order_id="327373")
        assert (
            project.crowd_supply_order_url
            == "https://www.crowdsupply.com/account/order/327373"
        )

    @pytest.mark.django_db
    def test_url_property_empty_when_unset(self):
        project = ProjectFactory(crowd_supply_order_id="")
        assert project.crowd_supply_order_url == ""

    @pytest.mark.django_db
    def test_order_id_round_trips(self):
        project = ProjectFactory(crowd_supply_order_id="314421")
        project.refresh_from_db()
        assert project.crowd_supply_order_id == "314421"
