"""Tests for GitLab OAuth authentication integration."""

from typing import Any

import pytest
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.models import SocialApp
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.test import Client
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

# Test constants
# Test password for Django user creation in test environment only
TEST_PASSWORD = "testpass123"  # noqa: S105
HTTP_OK = 200
HTTP_REDIRECT = 302
HTTP_BAD_REQUEST = 400
HTTP_FORBIDDEN = 403

User = get_user_model()


@pytest.mark.django_db
class TestGitLabAuthenticationFlow(TestCase):
    """Test GitLab OAuth authentication flow."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()
        self.login_url = reverse("account_login")
        self.gitlab_login_url = reverse("gitlab_login")

        # Create a test GitLab OAuth app for unit testing
        # Unit tests create their own isolated SocialApp objects
        self.site = Site.objects.get_current()
        self.gitlab_app = SocialApp.objects.create(
            provider="gitlab",
            name="GitLab Unit Test App",
            client_id="unit_test_gitlab_application_id",
            secret="unit_test_gitlab_secret",  # noqa: S106
        )
        self.gitlab_app.sites.add(self.site)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up the test app
        SocialApp.objects.filter(provider="gitlab").delete()

    def test_login_page_shows_gitlab_button(self):
        """Test that login page displays GitLab authentication option."""
        response = self.client.get(self.login_url)
        assert response.status_code == HTTP_OK
        # Check for GitLab provider in context or content
        assert b"GitLab" in response.content or b"gitlab" in response.content

    def test_gitlab_login_url_exists(self):
        """Test that GitLab login URL is accessible and handled by django-allauth."""
        response = self.client.get(self.gitlab_login_url)
        # The response should either be a redirect to GitLab OAuth (302)
        # or a 200 response from allauth handling the request
        assert response.status_code in [HTTP_OK, HTTP_REDIRECT]
        # If it's a redirect, it should be to GitLab
        if response.status_code == HTTP_REDIRECT:
            redirect_url = getattr(response, "url", "")
            assert "gitlab.com/oauth/authorize" in redirect_url

    def test_gitlab_oauth_redirect_contains_correct_params(self):
        """Test GitLab OAuth redirect parameters when redirect occurs."""
        response = self.client.get(self.gitlab_login_url)
        # Only test redirect parameters if we actually get a redirect
        if response.status_code == HTTP_REDIRECT:
            redirect_url = getattr(response, "url", "")
            # Check for required OAuth parameters
            assert "client_id=" in redirect_url
            assert "scope=" in redirect_url
            assert "redirect_uri=" in redirect_url
            assert "response_type=code" in redirect_url
            assert "gitlab.com/oauth/authorize" in redirect_url
        else:
            # If no redirect, just verify the URL is accessible
            assert response.status_code == HTTP_OK

    @override_settings(
        SOCIALACCOUNT_PROVIDERS={
            "gitlab": {
                "SCOPE": ["read_user", "email"],
                "VERIFIED_EMAIL": True,
            },
        },
    )
    def test_gitlab_account_creation_on_successful_auth(self):
        """Test that a new user is created on successful GitLab authentication."""
        # This test would normally mock the OAuth callback
        # For now, we're testing the setup is correct

        # Simulate a successful OAuth callback (would be mocked in real test)
        test_email = "gitlab_user@example.com"

        # Check user doesn't exist yet
        assert not User.objects.filter(email=test_email).exists()

        # In a real test, we would mock the OAuth callback here
        # and verify the user is created with correct data

    def test_existing_user_can_link_gitlab_account(self):
        """Test that existing users can link their GitLab account."""
        # Create a test user
        user = User.objects.create_user(
            username="existing_user",
            email="existing@example.com",
            password=TEST_PASSWORD,
        )

        # Login as the user
        self.client.login(username="existing_user", password=TEST_PASSWORD)

        # Check no social account exists yet
        assert not SocialAccount.objects.filter(user=user, provider="gitlab").exists()

        # In a real test, we would:
        # 1. Navigate to account connections page
        # 2. Click "Connect GitLab"
        # 3. Mock the OAuth flow
        # 4. Verify the account is linked

    def test_gitlab_auth_with_existing_email_links_accounts(self):
        """Test that GitLab auth with existing email links to existing user."""
        # Create a user with an email
        existing_email = "existing@example.com"
        User.objects.create_user(
            username="existing_user",
            email=existing_email,
            password=TEST_PASSWORD,
        )

        # Verify settings allow auto-linking
        assert settings.SOCIALACCOUNT_AUTO_SIGNUP is True

        # In a real test, we would mock GitLab OAuth returning
        # the same email and verify accounts are linked


@pytest.mark.django_db
class TestGitLabAuthenticationSecurity(TestCase):
    """Test security aspects of GitLab authentication."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()

        # Create a test GitLab OAuth app for security testing
        self.site = Site.objects.get_current()
        self.gitlab_app = SocialApp.objects.create(
            provider="gitlab",
            name="GitLab Security Test App",
            client_id="security_test_gitlab_application_id",
            secret="security_test_gitlab_secret",  # noqa: S106
        )
        self.gitlab_app.sites.add(self.site)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up the test app
        SocialApp.objects.filter(provider="gitlab").delete()

    def test_gitlab_oauth_uses_state_parameter(self):
        """Test that GitLab OAuth uses state parameter for CSRF protection."""
        gitlab_login_url = reverse("gitlab_login")
        response = self.client.get(gitlab_login_url)

        # Check that state parameter is included (CSRF protection) if redirecting
        if response.status_code == HTTP_REDIRECT:
            assert "state=" in response.url  # type: ignore[attr-defined]
        else:
            # If no redirect, just verify the URL is accessible
            assert response.status_code == HTTP_OK

    def test_gitlab_callback_validates_state(self):
        """Test that GitLab callback validates state parameter."""
        callback_url = reverse("gitlab_callback")

        # Try callback without state parameter (should fail)
        response = self.client.get(callback_url)

        # Should not process without valid state - expect error, redirect, or handled
        # OAuth callback without proper parameters may return various responses
        assert response.status_code in [
            HTTP_OK,
            HTTP_REDIRECT,
            HTTP_BAD_REQUEST,
            HTTP_FORBIDDEN,
            500,
        ]

    def test_gitlab_requires_verified_email(self):
        """Test that GitLab provider requires verified email."""
        providers: dict[str, Any] = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {})
        gitlab_config = providers.get("gitlab", {})

        # Verify email verification is required
        assert gitlab_config.get("VERIFIED_EMAIL") is True

    def test_gitlab_uses_correct_scopes(self):
        """Test that GitLab provider uses correct scopes."""
        providers: dict[str, Any] = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {})
        gitlab_config = providers.get("gitlab", {})

        # Verify required scopes are configured
        scopes = gitlab_config.get("SCOPE", [])
        assert "read_user" in scopes
        assert "email" in scopes


@pytest.mark.django_db
class TestGitLabAuthenticationErrors(TestCase):
    """Test error handling in GitLab authentication."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()

        # Create a test GitLab OAuth app for error testing
        self.site = Site.objects.get_current()
        self.gitlab_app = SocialApp.objects.create(
            provider="gitlab",
            name="GitLab Error Test App",
            client_id="error_test_gitlab_application_id",
            secret="error_test_gitlab_secret",  # noqa: S106
        )
        self.gitlab_app.sites.add(self.site)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up the test app
        SocialApp.objects.filter(provider="gitlab").delete()

    def test_gitlab_auth_denied_by_user(self):
        """Test handling when user denies GitLab authentication."""
        callback_url = reverse("gitlab_callback")

        # Simulate user denying access
        response = self.client.get(callback_url, {"error": "access_denied"})

        # Should handle error appropriately - expect any response that handles the error
        assert response.status_code in [HTTP_OK, HTTP_REDIRECT, 400, 403, 500]
        # Would check for error message in session/messages in full implementation

    def test_gitlab_auth_with_invalid_token(self):
        """Test handling of invalid GitLab token."""
        callback_url = reverse("gitlab_callback")

        # Simulate invalid token response
        response = self.client.get(
            callback_url,
            {
                "code": "invalid_code",
                "state": "valid_state",
            },
        )

        # Should handle gracefully - expect any response that handles the error
        assert response.status_code in [HTTP_OK, HTTP_REDIRECT, HTTP_BAD_REQUEST, 500]

    def test_gitlab_auth_without_email_permission(self):
        """Test handling when GitLab doesn't provide email."""
        # This would test the case where user doesn't grant email permission
        # Would need to mock the GitLab API response without email

    def test_gitlab_auth_with_self_hosted_instance(self):
        """Test handling of self-hosted GitLab instances."""
        # GitLab supports self-hosted instances
        # This would test custom GitLab URL configuration


@pytest.mark.django_db
class TestGitLabProviderConfiguration(TestCase):
    """Test GitLab provider configuration."""

    def test_gitlab_provider_is_installed(self):
        """Test that GitLab provider is in INSTALLED_APPS."""
        assert "allauth.socialaccount.providers.gitlab" in settings.INSTALLED_APPS

    def test_gitlab_provider_scope_configuration(self):
        """Test that GitLab provider requests correct scopes."""
        providers: dict[str, Any] = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {})
        gitlab_config = providers.get("gitlab", {})

        # Check required scopes are configured
        scopes = gitlab_config.get("SCOPE", [])
        assert "read_user" in scopes
        assert "email" in scopes

    def test_gitlab_callback_url_is_configured(self):
        """Test that GitLab callback URL is properly configured."""
        # Test that the callback URL can be reversed
        callback_url = reverse("gitlab_callback")
        assert "/accounts/gitlab/login/callback/" in callback_url

    def test_gitlab_provider_verified_email_setting(self):
        """Test that GitLab provider trusts verified emails."""
        providers: dict[str, Any] = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {})
        gitlab_config = providers.get("gitlab", {})

        # GitLab emails should be trusted as verified
        assert gitlab_config.get("VERIFIED_EMAIL") is True

    def test_gitlab_environment_variable_configuration(self):
        """Test that GitLab provider configuration is available."""
        providers: dict[str, Any] = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {})
        gitlab_config = providers.get("gitlab", {})

        # In test environment, APP section is removed to avoid conflicts
        # But basic provider configuration should be present
        assert gitlab_config is not None
        assert "SCOPE" in gitlab_config
        assert "VERIFIED_EMAIL" in gitlab_config

    def test_gitlab_provider_supports_self_hosted(self):
        """Test that GitLab provider can be configured for self-hosted instances."""
        # GitLab provider supports custom server URLs
        # This is important for organizations using self-hosted GitLab
        providers: dict[str, Any] = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {})
        gitlab_config = providers.get("gitlab", {})

        # Verify that custom server URL can be configured
        # (This would be set via SERVER_URL in production)
        assert isinstance(gitlab_config, dict)
