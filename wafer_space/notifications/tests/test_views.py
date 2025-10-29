"""Tests for notification views."""

from http import HTTPStatus

from django.test import Client
from django.test import TestCase
from django.urls import reverse

from wafer_space.notifications.models import Notification
from wafer_space.users.models import User

TEST_PASSWORD = "testpass123"  # noqa: S105


class NotificationViewsTest(TestCase):
    """Test notification views."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )

    def test_get_unread_count_api_authenticated(self):
        """Test that API returns correct unread count for authenticated users."""
        # Create 5 unread notifications
        for i in range(5):
            Notification.objects.create(
                user=self.user,
                notification_type=Notification.Type.DOWNLOAD_COMPLETE,
                title=f"Notification {i}",
                message="Test message",
                is_read=False,
            )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        response = self.client.get(reverse("notifications:unread_count"))

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {"unread_count": 5}

    def test_get_unread_count_api_unauthenticated(self):
        """Test that API requires authentication."""
        response = self.client.get(reverse("notifications:unread_count"))

        # Should redirect to login
        assert response.status_code == HTTPStatus.FOUND
        assert "/accounts/login/" in response.url  # type: ignore[attr-defined]
