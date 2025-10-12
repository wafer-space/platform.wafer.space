"""Tests for Celery tasks."""

import pytest
from django.core import mail
from django.test import override_settings

from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.legal.models import TermsOfServiceNotification
from wafer_space.legal.tasks import send_bulk_tos_notifications
from wafer_space.legal.tasks import send_tos_update_email
from wafer_space.users.tests.factories import UserFactory

from .factories import TermsOfServiceFactory
from .factories import TermsOfServiceNotificationFactory

# Test constants
EXPECTED_BULK_USER_COUNT = 3
EXPECTED_SPECIFIC_USER_COUNT = 2


@pytest.mark.django_db
class TestSendTOSUpdateEmail:
    """Tests for send_tos_update_email task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_send_email_success(self):
        """Test successful email sending."""
        user = UserFactory(email="test@example.com")
        tos = TermsOfServiceFactory(version="1.0.0", is_active=True)
        notification = TermsOfServiceNotificationFactory(
            user=user,
            tos_version=tos,
            status=TermsOfServiceNotification.Status.PENDING,
        )

        # Send email
        result = send_tos_update_email(notification.id)

        assert result["status"] == "success"
        assert "test@example.com" in result["message"]

        # Check email was sent
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert "test@example.com" in email.to
        assert "Updated Terms of Service" in email.subject
        assert "1.0.0" in email.subject
        assert "wafer.space" in email.body

        # Check notification was marked as sent
        notification.refresh_from_db()
        assert notification.status == TermsOfServiceNotification.Status.SENT
        assert notification.sent_at is not None

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_send_email_already_sent(self):
        """Test skipping already sent notifications."""
        user = UserFactory()
        tos = TermsOfServiceFactory()
        notification = TermsOfServiceNotificationFactory(
            user=user,
            tos_version=tos,
            status=TermsOfServiceNotification.Status.SENT,
        )

        result = send_tos_update_email(notification.id)

        assert result["status"] == "skipped"
        assert "already sent" in result["message"].lower()

        # No email should be sent
        assert len(mail.outbox) == 0

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_send_email_nonexistent_notification(self):
        """Test handling of nonexistent notification."""
        result = send_tos_update_email(99999)

        assert result["status"] == "error"
        assert "does not exist" in result["message"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_email_contains_correct_content(self):
        """Test that email contains the correct content."""
        user = UserFactory(username="testuser")
        tos = TermsOfServiceFactory(version="2.0.0", is_active=True)
        notification = TermsOfServiceNotificationFactory(
            user=user,
            tos_version=tos,
        )

        send_tos_update_email(notification.id)

        assert len(mail.outbox) == 1
        email = mail.outbox[0]

        # Check HTML content
        html_content = email.alternatives[0][0]
        assert "testuser" in html_content
        assert "2.0.0" in html_content
        assert "wafer.space" in html_content
        assert "/legal/tos/" in html_content
        assert "/legal/tos/accept/" in html_content


@pytest.mark.django_db
class TestSendBulkTOSNotifications:
    """Tests for send_bulk_tos_notifications task."""

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_send_bulk_notifications(self):
        """Test sending bulk notifications to all users."""
        # Create users who haven't accepted TOS
        users = [UserFactory() for _ in range(EXPECTED_BULK_USER_COUNT)]
        tos = TermsOfServiceFactory(is_active=True)

        # Send bulk notifications only to these specific users
        user_ids = [u.id for u in users]
        result = send_bulk_tos_notifications(tos.id, user_ids=user_ids)

        assert result["created"] == EXPECTED_BULK_USER_COUNT
        assert result["queued"] == EXPECTED_BULK_USER_COUNT
        assert result["total_users"] == EXPECTED_BULK_USER_COUNT

        # Check notifications were created
        assert (
            TermsOfServiceNotification.objects.filter(tos_version=tos).count()
            == EXPECTED_BULK_USER_COUNT
        )

        # Check emails were queued (sent in eager mode)
        assert len(mail.outbox) == EXPECTED_BULK_USER_COUNT

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_send_bulk_to_specific_users(self):
        """Test sending bulk notifications to specific users."""
        user1 = UserFactory()
        user2 = UserFactory()
        user3 = UserFactory()

        tos = TermsOfServiceFactory(is_active=True)

        # Send only to user1 and user2
        result = send_bulk_tos_notifications(tos.id, user_ids=[user1.id, user2.id])

        assert result["queued"] == EXPECTED_SPECIFIC_USER_COUNT

        # Check only specific number of notifications were created
        assert (
            TermsOfServiceNotification.objects.filter(tos_version=tos).count()
            == EXPECTED_SPECIFIC_USER_COUNT
        )
        assert TermsOfServiceNotification.objects.filter(
            user=user1,
            tos_version=tos,
        ).exists()
        assert TermsOfServiceNotification.objects.filter(
            user=user2,
            tos_version=tos,
        ).exists()
        assert not TermsOfServiceNotification.objects.filter(
            user=user3,
            tos_version=tos,
        ).exists()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_bulk_skips_existing_notifications(self):
        """Test that bulk send doesn't create duplicate notifications."""
        user = UserFactory()
        tos = TermsOfServiceFactory(is_active=True)

        # Create existing notification
        TermsOfServiceNotificationFactory(
            user=user,
            tos_version=tos,
            status=TermsOfServiceNotification.Status.PENDING,
        )

        # Try to send bulk notifications
        result = send_bulk_tos_notifications(tos.id, user_ids=[user.id])

        # No new notifications should be created
        assert result["created"] == 0
        # But existing one should still be queued
        assert result["queued"] == 1

        # Still only one notification
        assert TermsOfServiceNotification.objects.filter(
            user=user,
            tos_version=tos,
        ).count() == 1

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_bulk_excludes_users_who_accepted(self):
        """Test that bulk send excludes users who already accepted."""
        user1 = UserFactory()
        user2 = UserFactory()
        tos = TermsOfServiceFactory(is_active=True)

        # User1 has already accepted
        TermsOfServiceAcceptance.objects.create(
            user=user1,
            tos_version=tos,
        )

        # Send bulk notifications only to these specific users
        user_ids = [user1.id, user2.id]
        result = send_bulk_tos_notifications(tos.id, user_ids=user_ids)

        # Only user2 should receive notification
        assert result["queued"] == 1

        assert TermsOfServiceNotification.objects.filter(
            user=user2,
            tos_version=tos,
        ).exists()
        assert not TermsOfServiceNotification.objects.filter(
            user=user1,
            tos_version=tos,
        ).exists()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_bulk_nonexistent_tos(self):
        """Test bulk send with nonexistent TOS."""
        result = send_bulk_tos_notifications(99999)

        assert result["queued"] == 0
        assert "error" in result
        assert "does not exist" in result["error"].lower()

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_bulk_resends_failed_notifications(self):
        """Test that bulk send resends failed notifications."""
        user = UserFactory()
        tos = TermsOfServiceFactory(is_active=True)

        # Create failed notification
        TermsOfServiceNotificationFactory(
            user=user,
            tos_version=tos,
            status=TermsOfServiceNotification.Status.FAILED,
        )

        # Send bulk notifications
        result = send_bulk_tos_notifications(tos.id, user_ids=[user.id])

        # Should queue the failed notification
        assert result["queued"] == 1

        # Check email was sent
        assert len(mail.outbox) == 1
