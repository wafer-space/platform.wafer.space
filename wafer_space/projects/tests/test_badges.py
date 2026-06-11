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
