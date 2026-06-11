"""Tests for badge methods on project models."""

from __future__ import annotations

import pytest

from wafer_space.core.badges import BadgeType
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.users.models import User


class TestProjectStatusBadge:
    """Tests for Project.get_status_badge() method."""

    @pytest.fixture(autouse=True)
    def setup(self, db):
        """Set up test fixtures."""
        # No password needed - these tests never authenticate
        self.user = User.objects.create_user(
            username="testuser_project",
            email="project@example.com",
        )

    def test_draft_returns_neutral_badge(self) -> None:
        project = Project.objects.create(
            user=self.user,
            name="Draft Project",
            status=Project.Status.DRAFT,
        )
        badge = project.get_status_badge()

        assert badge.badge_type == BadgeType.NEUTRAL
        assert badge.text == "Draft"

    def test_submitted_returns_info_badge(self) -> None:
        project = Project.objects.create(
            user=self.user,
            name="Submitted Project",
            status=Project.Status.SUBMITTED,
        )
        badge = project.get_status_badge()

        assert badge.badge_type == BadgeType.INFO
        assert badge.text == "Submitted"

    def test_checking_returns_processing_badge(self) -> None:
        project = Project.objects.create(
            user=self.user,
            name="Checking Project",
            status=Project.Status.CHECKING,
        )
        badge = project.get_status_badge()

        assert badge.badge_type == BadgeType.PROCESSING
        assert badge.text == "Checking"

    def test_manufacturable_returns_success_badge(self) -> None:
        project = Project.objects.create(
            user=self.user,
            name="Manufacturable Project",
            status=Project.Status.MANUFACTURABLE,
        )
        badge = project.get_status_badge()

        assert badge.badge_type == BadgeType.SUCCESS
        assert badge.text == "Manufacturable"

    def test_not_manufacturable_returns_danger_badge(self) -> None:
        project = Project.objects.create(
            user=self.user,
            name="Not Manufacturable Project",
            status=Project.Status.NOT_MANUFACTURABLE,
        )
        badge = project.get_status_badge()

        assert badge.badge_type == BadgeType.DANGER
        assert badge.text == "Not Manufacturable"

    def test_assigned_returns_info_badge(self) -> None:
        project = Project.objects.create(
            user=self.user,
            name="Assigned Project",
            status=Project.Status.ASSIGNED_TO_SHUTTLE,
        )
        badge = project.get_status_badge()

        assert badge.badge_type == BadgeType.INFO
        assert badge.text == "Assigned to Shuttle"

    def test_in_production_returns_processing_badge(self) -> None:
        project = Project.objects.create(
            user=self.user,
            name="Production Project",
            status=Project.Status.IN_PRODUCTION,
        )
        badge = project.get_status_badge()

        assert badge.badge_type == BadgeType.PROCESSING
        assert badge.text == "In Production"

    def test_completed_returns_success_badge(self) -> None:
        project = Project.objects.create(
            user=self.user,
            name="Completed Project",
            status=Project.Status.COMPLETED,
        )
        badge = project.get_status_badge()

        assert badge.badge_type == BadgeType.SUCCESS
        assert badge.text == "Completed"

    def test_cancelled_returns_neutral_badge(self) -> None:
        project = Project.objects.create(
            user=self.user,
            name="Cancelled Project",
            status=Project.Status.CANCELLED,
        )
        badge = project.get_status_badge()

        assert badge.badge_type == BadgeType.NEUTRAL
        assert badge.text == "Cancelled"


class TestDownloadAttemptBadge:
    """Tests for DownloadAttempt.get_badge() method."""

    @pytest.fixture(autouse=True)
    def setup(self, db):
        """Set up test fixtures."""
        # No password needed - these tests never authenticate
        self.user = User.objects.create_user(
            username="testuser_attempt",
            email="attempt@example.com",
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project Attempt",
            description="Test project",
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
        )

    def test_pending_returns_neutral_badge(self) -> None:
        attempt = DownloadAttempt.objects.create(
            project_file=self.project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.PENDING,
        )
        badge = attempt.get_badge()

        assert badge.badge_type == BadgeType.NEUTRAL
        assert badge.text == "Pending"
        assert badge.icon == "bi-clock"

    def test_downloading_returns_processing_badge(self) -> None:
        attempt = DownloadAttempt.objects.create(
            project_file=self.project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )
        badge = attempt.get_badge()

        assert badge.badge_type == BadgeType.PROCESSING
        assert badge.text == "Downloading"
        assert badge.icon is None  # Processing badges use spinner, not icon

    def test_completed_returns_success_badge(self) -> None:
        attempt = DownloadAttempt.objects.create(
            project_file=self.project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )
        badge = attempt.get_badge()

        assert badge.badge_type == BadgeType.SUCCESS
        assert badge.text == "Completed"
        assert badge.icon == "bi-check-circle"

    def test_failed_returns_danger_badge(self) -> None:
        attempt = DownloadAttempt.objects.create(
            project_file=self.project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.FAILED,
        )
        badge = attempt.get_badge()

        assert badge.badge_type == BadgeType.DANGER
        assert badge.text == "Failed"
        assert badge.icon == "bi-exclamation-triangle"


class TestProjectFileDownloadBadge:
    """Tests for ProjectFile.get_download_badge() method."""

    @pytest.fixture(autouse=True)
    def setup(self, db):
        """Set up test fixtures."""
        # No password needed - these tests never authenticate
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
        )

    def test_pending_returns_neutral_badge(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
        )
        # No download attempts = PENDING status
        badge = file.get_download_badge()

        assert badge.badge_type == BadgeType.NEUTRAL
        assert "Pending" in badge.text

    def test_queued_returns_neutral_badge(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
            download_task_id="task-123",
        )
        # No download attempts but has task_id = QUEUED status
        badge = file.get_download_badge()

        assert badge.badge_type == BadgeType.NEUTRAL

    def test_downloading_returns_processing_badge(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
        )
        DownloadAttempt.objects.create(
            project_file=file,
            attempt_number=1,
            status="downloading",
        )
        badge = file.get_download_badge()

        assert badge.badge_type == BadgeType.PROCESSING

    def test_completed_returns_success_badge(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
        )
        DownloadAttempt.objects.create(
            project_file=file,
            attempt_number=1,
            status="completed",
        )
        badge = file.get_download_badge()

        assert badge.badge_type == BadgeType.SUCCESS
        assert badge.icon == "bi-check-circle"

    def test_failed_returns_danger_badge(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
        )
        DownloadAttempt.objects.create(
            project_file=file,
            attempt_number=1,
            status="failed",
        )
        badge = file.get_download_badge()

        assert badge.badge_type == BadgeType.DANGER


class TestProjectFileHashBadge:
    """Tests for ProjectFile.get_hash_badge() method."""

    @pytest.fixture(autouse=True)
    def setup(self, db):
        """Set up test fixtures."""
        # No password needed - these tests never authenticate
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
        )

    def test_verified_returns_success_badge(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
            expected_hash_md5="abc123",
            hash_md5="abc123",
            hash_verified=True,
        )
        DownloadAttempt.objects.create(
            project_file=file,
            attempt_number=1,
            status="completed",
        )
        badge = file.get_hash_badge()

        assert badge is not None
        assert badge.badge_type == BadgeType.SUCCESS
        assert badge.icon == "bi-shield-check"

    def test_mismatch_returns_danger_badge(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
            expected_hash_md5="abc123",
            hash_md5="def456",
        )
        DownloadAttempt.objects.create(
            project_file=file,
            attempt_number=1,
            status="completed",
        )
        badge = file.get_hash_badge()

        assert badge is not None
        assert badge.badge_type == BadgeType.DANGER
        assert badge.icon == "bi-shield-x"

    def test_no_expected_hash_returns_none(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
            hash_md5="abc123",
        )
        DownloadAttempt.objects.create(
            project_file=file,
            attempt_number=1,
            status="completed",
        )
        badge = file.get_hash_badge()

        assert badge is None


class TestProjectFileInlineHashBadge:
    """Tests for ProjectFile.get_inline_hash_badge() method."""

    @pytest.fixture(autouse=True)
    def setup(self, db):
        """Set up test fixtures."""
        # No password needed - these tests never authenticate
        self.user = User.objects.create_user(
            username="testuser_inline_hash",
            email="inline_hash@example.com",
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project Inline Hash",
            description="Test project",
        )

    def test_md5_verified_returns_success_badge(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
            hash_md5="abc123def456",
            expected_hash_md5="ABC123DEF456",  # Case insensitive match
        )
        badge = file.get_inline_hash_badge("md5")

        assert badge is not None
        assert badge.badge_type == BadgeType.SUCCESS
        assert badge.text == "Verified"
        assert badge.icon == "bi-check-circle"

    def test_md5_mismatch_returns_danger_badge(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
            hash_md5="abc123",
            expected_hash_md5="different",
        )
        badge = file.get_inline_hash_badge("md5")

        assert badge is not None
        assert badge.badge_type == BadgeType.DANGER
        assert badge.text == "Mismatch"
        assert badge.icon == "bi-x-circle"

    def test_sha1_verified_returns_success_badge(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
            hash_sha1="abc123",
            expected_hash_sha1="abc123",
        )
        badge = file.get_inline_hash_badge("sha1")

        assert badge is not None
        assert badge.badge_type == BadgeType.SUCCESS

    def test_sha256_mismatch_returns_danger_badge(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
            hash_sha256="abc123",
            expected_hash_sha256="xyz789",
        )
        badge = file.get_inline_hash_badge("sha256")

        assert badge is not None
        assert badge.badge_type == BadgeType.DANGER

    def test_no_expected_hash_returns_none(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
            hash_md5="abc123",
            # No expected_hash_md5 set
        )
        badge = file.get_inline_hash_badge("md5")

        assert badge is None

    def test_no_actual_hash_returns_mismatch(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
            expected_hash_md5="abc123",
            # No hash_md5 set (download not complete)
        )
        badge = file.get_inline_hash_badge("md5")

        assert badge is not None
        assert badge.badge_type == BadgeType.DANGER
        assert badge.text == "Mismatch"


class TestProjectFileGetBadges:
    """Tests for ProjectFile.get_badges() pipeline method."""

    @pytest.fixture(autouse=True)
    def setup(self, db):
        """Set up test fixtures."""
        # No password needed - these tests never authenticate
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
        )

    def test_failed_download_stops_pipeline(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
        )
        DownloadAttempt.objects.create(
            project_file=file,
            attempt_number=1,
            status="failed",
        )
        badges = file.get_badges()

        # Only the download badge - the hash stage never runs
        assert len(badges) == 1
        assert badges[0].badge_type == BadgeType.DANGER

    def test_completed_download_includes_hash_badge(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
            expected_hash_md5="abc123",
            hash_md5="abc123",
            hash_verified=True,
        )
        DownloadAttempt.objects.create(
            project_file=file,
            attempt_number=1,
            status="completed",
        )
        badges = file.get_badges()

        # Download + Hash badges
        expected_badges = 2
        assert len(badges) == expected_badges
        badge_types = [b.badge_type for b in badges]
        assert BadgeType.SUCCESS in badge_types

    def test_hash_mismatch_included_in_pipeline(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
            expected_hash_md5="abc123",
            hash_md5="def456",
        )
        DownloadAttempt.objects.create(
            project_file=file,
            attempt_number=1,
            status="completed",
        )
        badges = file.get_badges()

        # Download + Hash mismatch badges
        expected_badges = 2
        assert len(badges) == expected_badges
        assert badges[1].badge_type == BadgeType.DANGER


class TestProjectGetBadges:
    """Tests for Project.get_badges() method."""

    @pytest.fixture(autouse=True)
    def setup(self, db):
        """Set up test fixtures."""
        # No password needed - these tests never authenticate
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
        )

    def test_project_with_active_file_delegates_to_file(self) -> None:
        file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
            is_active=True,
        )
        DownloadAttempt.objects.create(
            project_file=file,
            attempt_number=1,
            status="completed",
        )

        badges = self.project.get_badges()

        # Should have at least the download badge from the file
        assert len(badges) >= 1
        assert badges[0].badge_type == BadgeType.SUCCESS

    def test_project_without_active_file_returns_empty(self) -> None:
        # Create a project with no files
        badges = self.project.get_badges()

        assert badges == []
