"""Tests for notification context processors."""

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.test import TestCase

from wafer_space.notifications.context_processors import unread_notifications_count
from wafer_space.notifications.models import Notification
from wafer_space.users.models import User

TEST_PASSWORD = "testpass123"  # noqa: S105
EXPECTED_UNREAD_COUNT_THREE = 3
EXPECTED_UNREAD_COUNT_TWO = 2


class TestUnreadNotificationsCount(TestCase):
    """Test the unread_notifications_count context processor."""

    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )

    def test_returns_zero_for_unauthenticated_user(self):
        """Test that unauthenticated users get zero count."""
        request = self.factory.get("/")
        request.user = AnonymousUser()

        context = unread_notifications_count(request)

        assert context["unread_count"] == 0

    def test_returns_zero_when_no_notifications(self):
        """Test that users with no notifications get zero count."""
        request = self.factory.get("/")
        request.user = self.user

        context = unread_notifications_count(request)

        assert context["unread_count"] == 0

    def test_returns_correct_count_with_unread_notifications(self):
        """Test that unread notification count is correct."""
        # Create 3 unread notifications
        for i in range(3):
            Notification.objects.create(
                user=self.user,
                notification_type=Notification.Type.DOWNLOAD_COMPLETE,
                title=f"Notification {i}",
                message="Test message",
                is_read=False,
            )

        request = self.factory.get("/")
        request.user = self.user

        context = unread_notifications_count(request)

        assert context["unread_count"] == EXPECTED_UNREAD_COUNT_THREE

    def test_excludes_read_notifications(self):
        """Test that read notifications are not counted."""
        # Create 2 unread and 3 read notifications
        for i in range(2):
            Notification.objects.create(
                user=self.user,
                notification_type=Notification.Type.DOWNLOAD_COMPLETE,
                title=f"Unread {i}",
                message="Test message",
                is_read=False,
            )

        for i in range(3):
            Notification.objects.create(
                user=self.user,
                notification_type=Notification.Type.DOWNLOAD_FAILED,
                title=f"Read {i}",
                message="Test message",
                is_read=True,
            )

        request = self.factory.get("/")
        request.user = self.user

        context = unread_notifications_count(request)

        assert context["unread_count"] == EXPECTED_UNREAD_COUNT_TWO
