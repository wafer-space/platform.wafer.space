"""Unit tests for notification services."""

import pytest
from django.contrib.contenttypes.models import ContentType

from wafer_space.notifications.models import Notification
from wafer_space.notifications.services import NotificationService
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.users.models import User

# Test fixture constants
TEST_USER_AUTH = "testpass123"  # Authentication credential for test users
EXPECTED_NOTIFICATION_COUNT = 2
EXPECTED_TYPE_COUNT = 2


@pytest.mark.django_db
class TestNotificationService:
    """Test NotificationService class."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_USER_AUTH,
        )

        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project for notifications",
        )

        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="test_design.gds",
            file_size=1048576,
            is_active=True,
        )

    def test_create_download_complete_notification(self):
        """Test creating download complete notification."""
        notification = NotificationService.create_download_complete_notification(
            user=self.user,
            project_file=self.project_file,
        )

        assert notification is not None
        assert notification.user == self.user
        assert notification.notification_type == Notification.Type.DOWNLOAD_COMPLETE
        assert "test_design.gds" in notification.title
        assert "successfully downloaded" in notification.message
        assert notification.is_read is False

        # Verify content object is linked
        content_type = ContentType.objects.get_for_model(ProjectFile)
        assert notification.content_type == content_type
        assert notification.object_id == self.project_file.id

    def test_create_download_failed_notification(self):
        """Test creating download failed notification."""
        error_message = "Connection timeout after 3 retries"

        notification = NotificationService.create_download_failed_notification(
            user=self.user,
            project_file=self.project_file,
            error_message=error_message,
        )

        assert notification is not None
        assert notification.user == self.user
        assert notification.notification_type == Notification.Type.DOWNLOAD_FAILED
        assert "test_design.gds" in notification.title
        assert error_message in notification.message
        assert notification.is_read is False

    def test_create_checksum_verified_notification(self):
        """Test creating checksum verified notification."""
        notification = NotificationService.create_checksum_verified_notification(
            user=self.user,
            project_file=self.project_file,
        )

        assert notification is not None
        assert notification.user == self.user
        assert (
            notification.notification_type == Notification.Type.CHECKSUM_VERIFIED
        )
        assert "test_design.gds" in notification.title
        assert "integrity verified" in notification.message.lower()
        assert notification.is_read is False

    def test_create_checksum_mismatch_notification(self):
        """Test creating checksum mismatch notification."""
        errors = [
            "MD5 mismatch: expected abc123, got def456",
            "SHA1 mismatch: expected xyz789, got uvw012",
        ]

        notification = NotificationService.create_checksum_mismatch_notification(
            user=self.user,
            project_file=self.project_file,
            errors=errors,
        )

        assert notification is not None
        assert notification.user == self.user
        assert (
            notification.notification_type == Notification.Type.CHECKSUM_MISMATCH
        )
        assert "test_design.gds" in notification.title
        assert "MD5 mismatch" in notification.message
        assert "SHA1 mismatch" in notification.message
        assert notification.is_read is False

    def test_checksum_mismatch_notification_with_empty_errors(self):
        """Test checksum mismatch notification with no error details."""
        notification = NotificationService.create_checksum_mismatch_notification(
            user=self.user,
            project_file=self.project_file,
            errors=[],
        )

        assert notification is not None
        assert "verification failed" in notification.message.lower()

    def test_notification_linked_to_correct_project_file(self):
        """Test that notification is correctly linked via generic foreign key."""
        # Mark first file inactive (only one active file per project allowed)
        self.project_file.is_active = False
        self.project_file.save()

        # Create a second project file
        second_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/other.gds",
            source_url="https://example.com/other.gds",
            original_filename="other_design.gds",
            file_size=2097152,
            is_active=True,
        )

        # Create notification for first file
        notification1 = NotificationService.create_download_complete_notification(
            user=self.user,
            project_file=self.project_file,
        )

        # Create notification for second file
        notification2 = NotificationService.create_download_complete_notification(
            user=self.user,
            project_file=second_file,
        )

        # Verify they're linked to different files
        assert notification1.content_object == self.project_file
        assert notification2.content_object == second_file
        assert notification1.object_id != notification2.object_id

    def test_multiple_notifications_for_same_user(self):
        """Test creating multiple notifications for the same user."""
        # Create multiple notifications
        NotificationService.create_download_complete_notification(
            user=self.user,
            project_file=self.project_file,
        )

        NotificationService.create_checksum_verified_notification(
            user=self.user,
            project_file=self.project_file,
        )

        # Verify both were created
        notifications = Notification.objects.filter(user=self.user)
        assert notifications.count() == EXPECTED_NOTIFICATION_COUNT

        # Verify they have different types
        types = {n.notification_type for n in notifications}
        assert len(types) == EXPECTED_TYPE_COUNT

    def test_notification_for_different_users(self):
        """Test that notifications are user-specific."""
        # Create second user
        user2 = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password=TEST_USER_AUTH,
        )

        # Create notifications for both users
        notification1 = NotificationService.create_download_complete_notification(
            user=self.user,
            project_file=self.project_file,
        )

        notification2 = NotificationService.create_download_complete_notification(
            user=user2,
            project_file=self.project_file,
        )

        # Verify each user has their own notification
        assert Notification.objects.filter(user=self.user).count() == 1
        assert Notification.objects.filter(user=user2).count() == 1

        # Verify they're different notifications
        assert notification1.id != notification2.id
