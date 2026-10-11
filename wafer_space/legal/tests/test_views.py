"""Tests for legal app views."""

from http import HTTPStatus

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.test import override_settings
from django.urls import reverse

from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.users.tests.factories import UserFactory

from .factories import TermsOfServiceAcceptanceFactory
from .factories import TermsOfServiceFactory


@pytest.fixture
def client():
    """Django test client."""
    return Client()


@pytest.mark.django_db
class TestTOSDisplayView:
    """Tests for TOS display view."""

    def test_display_active_tos(self, client):
        """Test displaying active TOS."""
        TermsOfServiceFactory(
            is_active=True,
            version="1.0.0",
        )

        response = client.get(reverse("legal:tos_display"))

        assert response.status_code == HTTPStatus.OK
        # Check for content from the markdown file
        assert "Terms of Service" in response.content.decode()
        assert "1.0.0" in response.content.decode()

    def test_display_no_active_tos(self, client):
        """Test displaying when no TOS is active."""
        # Create inactive TOS
        TermsOfServiceFactory(is_active=False)

        response = client.get(reverse("legal:tos_display"))

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_display_public_access(self, client):
        """Test that TOS display is publicly accessible."""
        TermsOfServiceFactory(is_active=True)

        # No login required
        response = client.get(reverse("legal:tos_display"))

        assert response.status_code == HTTPStatus.OK


@pytest.mark.django_db
class TestTOSAcceptView:
    """Tests for TOS acceptance view."""

    def test_accept_view_requires_login(self, client):
        """Test that TOS accept view requires login."""
        response = client.get(reverse("legal:tos_accept"))

        assert response.status_code == HTTPStatus.FOUND
        assert "/accounts/login/" in response.url

    def test_accept_view_get(self, client):
        """Test GET request to TOS accept view."""
        user = UserFactory()
        TermsOfServiceFactory(
            is_active=True,
            version="1.0.0",
        )

        client.force_login(user)
        response = client.get(reverse("legal:tos_accept"))

        assert response.status_code == HTTPStatus.OK
        # Check for content from the markdown file
        assert "Terms of Service" in response.content.decode()
        assert "1.0.0" in response.content.decode()
        assert "agree" in response.content.decode().lower()

    def test_accept_view_post_success(self, client):
        """Test successful TOS acceptance."""
        user = UserFactory()
        active_tos = TermsOfServiceFactory(is_active=True, version="1.0.0")

        client.force_login(user)

        # Store redirect URL in session
        session = client.session
        session["tos_redirect_after_accept"] = "/about/"
        session.save()

        response = client.post(
            reverse("legal:tos_accept"),
            {"agree": "on"},
            follow=True,
        )

        assert response.status_code == HTTPStatus.OK
        assert response.redirect_chain[-1][0] == "/about/"

        # Check acceptance was created
        acceptance = TermsOfServiceAcceptance.objects.get(
            user=user,
            tos_version=active_tos,
        )
        assert acceptance.user == user
        assert acceptance.tos_version == active_tos
        assert acceptance.ip_address
        # User agent may be empty string if not provided
        assert isinstance(acceptance.user_agent, str)

        # Success message should have been displayed during redirect
        # (messages are consumed during redirect, so we just verify acceptance worked)

    def test_accept_view_post_without_checkbox(self, client):
        """Test POST without checking the agreement box."""
        user = UserFactory()
        TermsOfServiceFactory(is_active=True)

        client.force_login(user)
        response = client.post(reverse("legal:tos_accept"), {})

        assert response.status_code == HTTPStatus.OK

        # Check error message
        messages = list(get_messages(response.wsgi_request))
        assert any("must agree" in str(m).lower() for m in messages)

        # Check acceptance was NOT created
        assert not TermsOfServiceAcceptance.objects.filter(user=user).exists()

    def test_accept_view_already_accepted(self, client):
        """Test accessing accept view when already accepted."""
        user = UserFactory()
        active_tos = TermsOfServiceFactory(is_active=True)
        TermsOfServiceAcceptanceFactory(user=user, tos_version=active_tos)

        client.force_login(user)
        response = client.get(reverse("legal:tos_accept"), follow=True)

        assert response.status_code == HTTPStatus.OK

        # Check info message
        messages = list(get_messages(response.wsgi_request))
        assert any("already accepted" in str(m).lower() for m in messages)

    def test_accept_view_no_active_tos(self, client):
        """Test accessing accept view when no TOS is active."""
        user = UserFactory()
        TermsOfServiceFactory(is_active=False)

        client.force_login(user)
        response = client.get(reverse("legal:tos_accept"), follow=True)

        assert response.status_code == HTTPStatus.OK

        # Check error message
        messages = list(get_messages(response.wsgi_request))
        assert any("no terms of service" in str(m).lower() for m in messages)

    def test_accept_view_records_ip_address(self, client):
        """Test that IP address is recorded correctly."""
        user = UserFactory()
        TermsOfServiceFactory(is_active=True)

        client.force_login(user)
        client.post(
            reverse("legal:tos_accept"),
            {"agree": "on"},
            REMOTE_ADDR="192.168.1.100",
        )

        acceptance = TermsOfServiceAcceptance.objects.get(user=user)
        assert acceptance.ip_address == "192.168.1.100"

    def test_accept_view_records_user_agent(self, client):
        """Test that user agent is recorded correctly."""
        user = UserFactory()
        TermsOfServiceFactory(is_active=True)

        client.force_login(user)
        client.post(
            reverse("legal:tos_accept"),
            {"agree": "on"},
            HTTP_USER_AGENT="Mozilla/5.0 Test Browser",
        )

        acceptance = TermsOfServiceAcceptance.objects.get(user=user)
        assert "Mozilla/5.0" in acceptance.user_agent

    def test_accept_view_ignores_x_forwarded_for(self, client):
        """A client-supplied X-Forwarded-For is spoofable and must be ignored."""
        user = UserFactory()
        TermsOfServiceFactory(is_active=True)

        client.force_login(user)
        client.post(
            reverse("legal:tos_accept"),
            {"agree": "on"},
            REMOTE_ADDR="192.168.1.1",
            HTTP_X_FORWARDED_FOR="10.0.0.1, 192.168.1.1",
        )

        acceptance = TermsOfServiceAcceptance.objects.get(user=user)
        assert acceptance.ip_address == "192.168.1.1"

    @override_settings(TRUST_X_REAL_IP=True)
    def test_accept_view_records_x_real_ip_when_trusted(self, client):
        """Behind nginx (TRUST_X_REAL_IP) the X-Real-IP visitor is recorded."""
        user = UserFactory()
        TermsOfServiceFactory(is_active=True)

        client.force_login(user)
        client.post(
            reverse("legal:tos_accept"),
            {"agree": "on"},
            REMOTE_ADDR="",
            HTTP_X_REAL_IP="198.51.100.23",
        )

        acceptance = TermsOfServiceAcceptance.objects.get(user=user)
        assert acceptance.ip_address == "198.51.100.23"

    def test_accept_view_default_redirect(self, client):
        """Test default redirect when no redirect URL in session."""
        user = UserFactory()
        TermsOfServiceFactory(is_active=True)

        client.force_login(user)
        response = client.post(
            reverse("legal:tos_accept"),
            {"agree": "on"},
            follow=True,
        )

        # Should redirect to home
        assert response.redirect_chain[-1][0] == "/"
