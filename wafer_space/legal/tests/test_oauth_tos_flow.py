"""Tests for OAuth users and TOS acceptance flow."""

from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from wafer_space.legal.models import TermsOfServiceAcceptance

from .factories import TermsOfServiceFactory

User = get_user_model()


@pytest.mark.django_db
class TestOAuthUserTOSFlow:
    """Test TOS flow for users signing in via OAuth providers."""

    @pytest.fixture
    def client(self):
        """Test client fixture."""
        return Client()

    @pytest.fixture
    def active_tos(self):
        """Create active TOS for testing."""
        return TermsOfServiceFactory(version="1.0.0", is_active=True)

    def test_oauth_new_user_redirected_to_tos(self, client, active_tos):
        """Test that new OAuth user is redirected to TOS acceptance.

        Simulates the flow after OAuth callback when a new user is created.
        """
        # Create a user as if they just authenticated via OAuth
        # (In real flow, django-allauth creates the user)
        user = User.objects.create_user(
            username="githubuser123",
            email="github@example.com",
        )

        # Log the user in (simulating post-OAuth state)
        client.force_login(user)

        # User has not accepted TOS
        assert not TermsOfServiceAcceptance.has_accepted_active(user)

        # Try to access a protected page (user profile requires auth)
        response = client.get(f"/users/{user.username}/", follow=False)

        # Should be redirected to TOS acceptance
        assert response.status_code == HTTPStatus.FOUND
        assert response.url == reverse("legal:tos_accept")

    def test_oauth_existing_user_new_tos_version(self, client):
        """Test OAuth user with old TOS acceptance needs to accept new version."""
        # Create user (existing OAuth user)
        user = User.objects.create_user(
            username="existingoauthuser",
            email="existing@example.com",
        )

        # User previously accepted v1.0.0
        old_tos = TermsOfServiceFactory(version="1.0.0", is_active=False)
        TermsOfServiceAcceptance.objects.create(
            user=user,
            tos_version=old_tos,
        )

        # New version is now active
        TermsOfServiceFactory(version="2.0.0", is_active=True)

        # User logs in via OAuth (simulated)
        client.force_login(user)

        # Try to access site (user profile page)
        response = client.get(f"/users/{user.username}/", follow=False)

        # Should be redirected to accept new TOS
        assert response.status_code == HTTPStatus.FOUND
        assert response.url == reverse("legal:tos_accept")

        # User should not have accepted new version yet
        assert not TermsOfServiceAcceptance.has_accepted_active(user)

    def test_oauth_user_accepts_tos_can_access_site(self, client, active_tos):
        """Test OAuth user can access site after accepting TOS."""
        # Create OAuth user
        user = User.objects.create_user(
            username="oauthuser",
            email="oauth@example.com",
        )
        client.force_login(user)

        # Accept TOS
        response = client.post(
            reverse("legal:tos_accept"),
            {"agree": "on"},
            follow=False,
        )

        # Should redirect to home or intended destination
        assert response.status_code == HTTPStatus.FOUND

        # User should now have accepted
        assert TermsOfServiceAcceptance.has_accepted_active(user)

        # Can now access protected pages
        response = client.get(f"/users/{user.username}/")
        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize(("provider", "username_prefix"), [
        ("github", "gh_"),
        ("google", "google_"),
        ("gitlab", "gl_"),
        ("discord", "discord_"),
        ("linkedin", "li_"),
    ])
    def test_all_oauth_providers_require_tos(
        self, client, active_tos, provider, username_prefix
    ):
        """Test that users from all OAuth providers must accept TOS."""
        # Create user as if authenticated via specific provider
        user = User.objects.create_user(
            username=f"{username_prefix}user123",
            email=f"{provider}@example.com",
        )

        # Log in the OAuth user
        client.force_login(user)

        # Try to access protected page (user profile)
        response = client.get(f"/users/{user.username}/", follow=False)

        # All OAuth users should be redirected to TOS
        assert response.status_code == HTTPStatus.FOUND
        assert response.url == reverse("legal:tos_accept")

        # No provider gets special treatment
        assert not TermsOfServiceAcceptance.has_accepted_active(user)


@pytest.mark.django_db
class TestSessionPreservation:
    """Test that intended destination is preserved during TOS redirect."""

    @pytest.fixture
    def client(self):
        """Test client fixture."""
        return Client()

    def test_redirect_preserves_intended_destination(self, client):
        """Test user returns to intended page after accepting TOS."""
        # Setup
        TermsOfServiceFactory(version="1.0.0", is_active=True)
        test_password = "testpass123"  # noqa: S105
        User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=test_password,
        )

        # User logs in and tries to access /projects/create/
        client.login(username="testuser", password=test_password)

        # Manually set the intended destination in session
        session = client.session
        session["tos_redirect_after_accept"] = "/projects/create/"
        session.save()

        # Go to TOS accept page
        response = client.get(reverse("legal:tos_accept"))
        assert response.status_code == HTTPStatus.OK

        # Accept TOS
        response = client.post(
            reverse("legal:tos_accept"),
            {"agree": "on"},
            follow=False,
        )

        # Should redirect to originally intended destination
        assert response.status_code == HTTPStatus.FOUND
        assert response.url == "/projects/create/"

        # Session key should be cleared
        session = client.session
        assert "tos_redirect_after_accept" not in session

    def test_redirect_defaults_to_home_without_session(self, client):
        """Test redirect goes to home if no destination in session."""
        TermsOfServiceFactory(version="1.0.0", is_active=True)
        test_password = "testpass123"  # noqa: S105
        User.objects.create_user(
            username="testuser2",
            email="test2@example.com",
            password=test_password,
        )

        client.login(username="testuser2", password=test_password)

        # No destination set in session
        response = client.post(
            reverse("legal:tos_accept"),
            {"agree": "on"},
            follow=False,
        )

        # Should redirect to home
        assert response.status_code == HTTPStatus.FOUND
        assert response.url == reverse("home")


@pytest.mark.django_db
class TestIPAndUserAgentRecording:
    """Test that IP address and user agent are properly recorded."""

    @pytest.fixture
    def client(self):
        """Test client fixture."""
        return Client()

    def test_ip_address_recorded(self, client):
        """Test that IP address is recorded with acceptance."""
        TermsOfServiceFactory(version="1.0.0", is_active=True)
        test_password = "testpass123"  # noqa: S105
        user = User.objects.create_user(
            username="iptest",
            email="ip@example.com",
            password=test_password,
        )

        client.login(username="iptest", password=test_password)

        # Accept TOS with specific IP
        client.post(
            reverse("legal:tos_accept"),
            {"agree": "on"},
            REMOTE_ADDR="192.168.1.100",
        )

        # Check acceptance was created with IP
        acceptance = TermsOfServiceAcceptance.objects.get(user=user)
        assert acceptance.ip_address == "192.168.1.100"

    def test_forwarded_ip_recorded(self, client):
        """Test that forwarded IP (proxy) is recorded correctly."""
        TermsOfServiceFactory(version="1.0.0", is_active=True)
        test_password = "testpass123"  # noqa: S105
        user = User.objects.create_user(
            username="proxytest",
            email="proxy@example.com",
            password=test_password,
        )

        client.login(username="proxytest", password=test_password)

        # Accept with X-Forwarded-For header (proxy scenario)
        client.post(
            reverse("legal:tos_accept"),
            {"agree": "on"},
            HTTP_X_FORWARDED_FOR="203.0.113.195, 70.41.3.18, 150.172.238.178",
        )

        # Should record the first (original client) IP
        acceptance = TermsOfServiceAcceptance.objects.get(user=user)
        assert acceptance.ip_address == "203.0.113.195"

    def test_user_agent_recorded(self, client):
        """Test that user agent string is recorded."""
        TermsOfServiceFactory(version="1.0.0", is_active=True)
        test_password = "testpass123"  # noqa: S105
        user = User.objects.create_user(
            username="uatest",
            email="ua@example.com",
            password=test_password,
        )

        client.login(username="uatest", password=test_password)

        # Accept with specific user agent
        test_ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        client.post(
            reverse("legal:tos_accept"),
            {"agree": "on"},
            HTTP_USER_AGENT=test_ua,
        )

        # Check user agent was recorded
        acceptance = TermsOfServiceAcceptance.objects.get(user=user)
        assert acceptance.user_agent == test_ua
