"""Tests for legal app models."""

import pytest
from django.db import IntegrityError

from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.legal.models import TermsOfServiceNotification
from wafer_space.users.tests.factories import UserFactory

from .factories import TermsOfServiceAcceptanceFactory
from .factories import TermsOfServiceFactory
from .factories import TermsOfServiceNotificationFactory


@pytest.mark.django_db
class TestTermsOfService:
    """Tests for TermsOfService model."""

    def test_create_tos(self):
        """Test creating a Terms of Service."""
        tos = TermsOfServiceFactory()
        assert tos.version
        assert tos.content
        assert not tos.is_active
        assert tos.created_at
        assert str(tos) == f"TOS v{tos.version}"

    def test_create_active_tos(self):
        """Test creating an active Terms of Service."""
        tos = TermsOfServiceFactory(is_active=True)
        assert tos.is_active
        assert " (Active)" in str(tos)

    def test_only_one_active_tos(self):
        """Test that only one TOS can be active at a time."""
        tos1 = TermsOfServiceFactory(is_active=True)
        assert tos1.is_active

        # Creating a second active TOS should deactivate the first
        tos2 = TermsOfServiceFactory(is_active=True)
        assert tos2.is_active

        # Refresh tos1 from database
        tos1.refresh_from_db()
        assert not tos1.is_active

    def test_get_active(self):
        """Test getting the active TOS version."""
        # No active TOS
        assert TermsOfService.get_active() is None

        # Create inactive TOS
        TermsOfServiceFactory(is_active=False)
        assert TermsOfService.get_active() is None

        # Create active TOS
        active_tos = TermsOfServiceFactory(is_active=True)
        assert TermsOfService.get_active() == active_tos

    def test_version_unique(self):
        """Test that version numbers must be unique."""
        tos1 = TermsOfServiceFactory(version="1.0.0")
        with pytest.raises(IntegrityError):
            TermsOfServiceFactory(version="1.0.0")


@pytest.mark.django_db
class TestTermsOfServiceAcceptance:
    """Tests for TermsOfServiceAcceptance model."""

    def test_create_acceptance(self):
        """Test creating a TOS acceptance."""
        user = UserFactory()
        tos = TermsOfServiceFactory()
        acceptance = TermsOfServiceAcceptanceFactory(
            user=user,
            tos_version=tos,
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
        )

        assert acceptance.user == user
        assert acceptance.tos_version == tos
        assert acceptance.ip_address == "192.168.1.1"
        assert acceptance.user_agent == "Mozilla/5.0"
        assert acceptance.accepted_at
        assert f"{user.username} accepted TOS v{tos.version}" in str(acceptance)

    def test_unique_user_version(self):
        """Test that a user can only accept a specific version once."""
        user = UserFactory()
        tos = TermsOfServiceFactory()

        # First acceptance should work
        TermsOfServiceAcceptanceFactory(user=user, tos_version=tos)

        # Second acceptance of same version should fail
        with pytest.raises(IntegrityError):
            TermsOfServiceAcceptanceFactory(user=user, tos_version=tos)

    def test_user_can_accept_multiple_versions(self):
        """Test that a user can accept multiple TOS versions."""
        user = UserFactory()
        tos1 = TermsOfServiceFactory(version="1.0.0")
        tos2 = TermsOfServiceFactory(version="2.0.0")

        # User can accept both versions
        acceptance1 = TermsOfServiceAcceptanceFactory(user=user, tos_version=tos1)
        acceptance2 = TermsOfServiceAcceptanceFactory(user=user, tos_version=tos2)

        assert acceptance1.user == user
        assert acceptance2.user == user
        assert acceptance1.tos_version != acceptance2.tos_version

    def test_has_accepted_active(self, user):
        """Test checking if user has accepted active TOS."""
        # No active TOS
        assert TermsOfServiceAcceptance.has_accepted_active(user)

        # Create active TOS but user hasn't accepted
        active_tos = TermsOfServiceFactory(is_active=True)
        assert not TermsOfServiceAcceptance.has_accepted_active(user)

        # User accepts TOS
        TermsOfServiceAcceptanceFactory(user=user, tos_version=active_tos)
        assert TermsOfServiceAcceptance.has_accepted_active(user)

    def test_has_accepted_active_anonymous(self):
        """Test that anonymous users return False."""
        from django.contrib.auth.models import AnonymousUser

        anonymous = AnonymousUser()
        assert not TermsOfServiceAcceptance.has_accepted_active(anonymous)


@pytest.mark.django_db
class TestTermsOfServiceNotification:
    """Tests for TermsOfServiceNotification model."""

    def test_create_notification(self):
        """Test creating a TOS notification."""
        user = UserFactory()
        tos = TermsOfServiceFactory()
        notification = TermsOfServiceNotificationFactory(
            user=user,
            tos_version=tos,
            status=TermsOfServiceNotification.Status.PENDING,
        )

        assert notification.user == user
        assert notification.tos_version == tos
        assert notification.status == TermsOfServiceNotification.Status.PENDING
        assert notification.created_at
        assert notification.sent_at is None
        assert user.username in str(notification)
        assert tos.version in str(notification)
        assert "pending" in str(notification).lower()

    def test_mark_as_sent(self):
        """Test marking notification as sent."""
        notification = TermsOfServiceNotificationFactory(
            status=TermsOfServiceNotification.Status.PENDING,
        )

        notification.mark_as_sent()
        notification.refresh_from_db()

        assert notification.status == TermsOfServiceNotification.Status.SENT
        assert notification.sent_at is not None
        assert notification.error_message == ""

    def test_mark_as_failed(self):
        """Test marking notification as failed."""
        notification = TermsOfServiceNotificationFactory(
            status=TermsOfServiceNotification.Status.PENDING,
        )

        error_message = "SMTP connection failed"
        notification.mark_as_failed(error_message)
        notification.refresh_from_db()

        assert notification.status == TermsOfServiceNotification.Status.FAILED
        assert notification.error_message == error_message

    def test_unique_user_version(self):
        """Test that each user can only have one notification per version."""
        user = UserFactory()
        tos = TermsOfServiceFactory()

        # First notification should work
        TermsOfServiceNotificationFactory(user=user, tos_version=tos)

        # Second notification for same user and version should fail
        with pytest.raises(IntegrityError):
            TermsOfServiceNotificationFactory(user=user, tos_version=tos)

    def test_status_choices(self):
        """Test notification status choices."""
        assert TermsOfServiceNotification.Status.PENDING == "pending"
        assert TermsOfServiceNotification.Status.SENT == "sent"
        assert TermsOfServiceNotification.Status.FAILED == "failed"
