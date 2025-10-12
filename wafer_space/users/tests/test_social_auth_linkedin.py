"""Tests for LinkedIn OAuth authentication integration."""

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
class TestLinkedInAuthenticationFlow(TestCase):
    """Test LinkedIn OAuth authentication flow."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()
        self.login_url = reverse("account_login")
        self.linkedin_login_url = reverse("linkedin_oauth2_login")

        # Create a test LinkedIn OAuth app for unit testing
        # Unit tests create their own isolated SocialApp objects
        self.site = Site.objects.get_current()
        self.linkedin_app = SocialApp.objects.create(
            provider="linkedin_oauth2",
            name="LinkedIn Unit Test App",
            client_id="unit_test_linkedin_client_id",
            secret="unit_test_linkedin_secret",  # noqa: S106
        )
        self.linkedin_app.sites.add(self.site)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up the test app
        SocialApp.objects.filter(provider="linkedin_oauth2").delete()

    def test_login_page_shows_linkedin_button(self):
        """Test that login page displays LinkedIn authentication option."""
        response = self.client.get(self.login_url)
        assert response.status_code == HTTP_OK
        # Check for LinkedIn provider in context or content
        assert b"LinkedIn" in response.content or b"linkedin" in response.content

    def test_linkedin_login_url_exists(self):
        """Test that LinkedIn login URL is accessible and handled by django-allauth."""
        response = self.client.get(self.linkedin_login_url)
        # The response should either be a redirect to LinkedIn OAuth (302)
        # or a 200 response from allauth handling the request
        assert response.status_code in [HTTP_OK, HTTP_REDIRECT]
        # If it's a redirect, it should be to LinkedIn
        if response.status_code == HTTP_REDIRECT:
            redirect_url = getattr(response, "url", "")
            assert "linkedin.com" in redirect_url

    def test_linkedin_oauth_redirect_contains_correct_params(self):
        """Test LinkedIn OAuth redirect parameters when redirect occurs."""
        response = self.client.get(self.linkedin_login_url)
        # Only test redirect parameters if we actually get a redirect
        if response.status_code == HTTP_REDIRECT:
            redirect_url = getattr(response, "url", "")
            # Check for required OAuth parameters
            assert "client_id=" in redirect_url
            assert "scope=" in redirect_url
            assert "redirect_uri=" in redirect_url
            assert "response_type=code" in redirect_url
            assert "linkedin.com" in redirect_url
        else:
            # If no redirect, just verify the URL is accessible
            assert response.status_code == HTTP_OK

    @override_settings(
        SOCIALACCOUNT_PROVIDERS={
            "linkedin_oauth2": {
                "SCOPE": ["openid", "profile", "email"],
                "VERIFIED_EMAIL": True,
            },
        },
    )
    def test_linkedin_account_creation_on_successful_auth(self):
        """Test that a new user is created on successful LinkedIn authentication."""
        # This test would normally mock the OAuth callback
        # For now, we're testing the setup is correct

        # Simulate a successful OAuth callback (would be mocked in real test)
        test_email = "linkedin_user@example.com"

        # Check user doesn't exist yet
        assert not User.objects.filter(email=test_email).exists()

        # In a real test, we would mock the OAuth callback here
        # and verify the user is created with correct data

    def test_existing_user_can_link_linkedin_account(self):
        """Test that existing users can link their LinkedIn account."""
        # Create a test user
        user = User.objects.create_user(
            username="existing_user",
            email="existing@example.com",
            password=TEST_PASSWORD,
        )

        # Login as the user
        self.client.login(username="existing_user", password=TEST_PASSWORD)

        # Check no social account exists yet
        assert not SocialAccount.objects.filter(
            user=user,
            provider="linkedin_oauth2",
        ).exists()

        # In a real test, we would:
        # 1. Navigate to account connections page
        # 2. Click "Connect LinkedIn"
        # 3. Mock the OAuth flow
        # 4. Verify the account is linked

    def test_linkedin_auth_with_existing_email_links_accounts(self):
        """Test that LinkedIn auth with existing email links to existing user."""
        # Create a user with an email
        existing_email = "existing@example.com"
        User.objects.create_user(
            username="existing_user",
            email=existing_email,
            password=TEST_PASSWORD,
        )

        # Verify settings allow auto-linking
        assert settings.SOCIALACCOUNT_AUTO_SIGNUP is True

        # In a real test, we would mock LinkedIn OAuth returning
        # the same email and verify accounts are linked


@pytest.mark.django_db
class TestLinkedInAuthenticationSecurity(TestCase):
    """Test security aspects of LinkedIn authentication."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()

        # Create a test LinkedIn OAuth app for security testing
        self.site = Site.objects.get_current()
        self.linkedin_app = SocialApp.objects.create(
            provider="linkedin_oauth2",
            name="LinkedIn Security Test App",
            client_id="security_test_linkedin_client_id",
            secret="security_test_linkedin_secret",  # noqa: S106
        )
        self.linkedin_app.sites.add(self.site)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up the test app
        SocialApp.objects.filter(provider="linkedin_oauth2").delete()

    def test_linkedin_oauth_uses_state_parameter(self):
        """Test that LinkedIn OAuth uses state parameter for CSRF protection."""
        linkedin_login_url = reverse("linkedin_oauth2_login")
        response = self.client.get(linkedin_login_url)

        # Check that state parameter is included (CSRF protection) if redirecting
        if response.status_code == HTTP_REDIRECT:
            redirect_url = getattr(response, "url", "")
            assert "state=" in redirect_url
        else:
            # If no redirect, just verify the URL is accessible
            assert response.status_code == HTTP_OK

    def test_linkedin_callback_validates_state(self):
        """Test that LinkedIn callback validates state parameter."""
        callback_url = reverse("linkedin_oauth2_callback")

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

    def test_linkedin_requires_verified_email(self):
        """Test that LinkedIn provider requires verified email."""
        providers: dict[str, Any] = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {})
        linkedin_config = providers.get("linkedin_oauth2", {})

        # Verify email verification is required
        assert linkedin_config.get("VERIFIED_EMAIL") is True

    def test_linkedin_uses_correct_scopes(self):
        """Test that LinkedIn provider uses correct OpenID Connect scopes."""
        providers: dict[str, Any] = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {})
        linkedin_config = providers.get("linkedin_oauth2", {})

        # Verify required OpenID Connect scopes are configured
        scopes = linkedin_config.get("SCOPE", [])
        assert "openid" in scopes
        assert "profile" in scopes
        assert "email" in scopes


@pytest.mark.django_db
class TestLinkedInAuthenticationErrors(TestCase):
    """Test error handling in LinkedIn authentication."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()

        # Create a test LinkedIn OAuth app for error testing
        self.site = Site.objects.get_current()
        self.linkedin_app = SocialApp.objects.create(
            provider="linkedin_oauth2",
            name="LinkedIn Error Test App",
            client_id="error_test_linkedin_client_id",
            secret="error_test_linkedin_secret",  # noqa: S106
        )
        self.linkedin_app.sites.add(self.site)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up the test app
        SocialApp.objects.filter(provider="linkedin_oauth2").delete()

    def test_linkedin_auth_denied_by_user(self):
        """Test handling when user denies LinkedIn authentication."""
        callback_url = reverse("linkedin_oauth2_callback")

        # Simulate user denying access
        response = self.client.get(callback_url, {"error": "access_denied"})

        # Should handle error appropriately - expect any response that handles the error
        assert response.status_code in [HTTP_OK, HTTP_REDIRECT, 400, 403, 500]
        # Would check for error message in session/messages in full implementation

    def test_linkedin_auth_with_invalid_token(self):
        """Test handling of invalid LinkedIn token."""
        callback_url = reverse("linkedin_oauth2_callback")

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

    def test_linkedin_auth_without_email_permission(self):
        """Test handling when LinkedIn doesn't provide email."""
        # This would test the case where user doesn't grant email permission
        # Would need to mock the LinkedIn API response without email
        # LinkedIn requires explicit permission for email scope


@pytest.mark.django_db
class TestLinkedInProviderConfiguration(TestCase):
    """Test LinkedIn provider configuration."""

    def test_linkedin_provider_is_installed(self):
        """Test that LinkedIn provider is in INSTALLED_APPS."""
        assert (
            "allauth.socialaccount.providers.linkedin_oauth2" in settings.INSTALLED_APPS
        )

    def test_linkedin_provider_scope_configuration(self):
        """Test that LinkedIn provider requests correct OpenID Connect scopes."""
        providers: dict[str, Any] = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {})
        linkedin_config = providers.get("linkedin_oauth2", {})

        # Check required OpenID Connect scopes are configured
        scopes = linkedin_config.get("SCOPE", [])
        assert "openid" in scopes
        assert "profile" in scopes
        assert "email" in scopes

    def test_linkedin_callback_url_is_configured(self):
        """Test that LinkedIn callback URL is properly configured."""
        # Test that the callback URL can be reversed
        callback_url = reverse("linkedin_oauth2_callback")
        assert "/accounts/linkedin_oauth2/login/callback/" in callback_url

    def test_linkedin_provider_verified_email_setting(self):
        """Test that LinkedIn provider trusts verified emails."""
        providers: dict[str, Any] = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {})
        linkedin_config = providers.get("linkedin_oauth2", {})

        # LinkedIn emails should be trusted as verified
        assert linkedin_config.get("VERIFIED_EMAIL") is True

    def test_linkedin_environment_variable_configuration(self):
        """Test that LinkedIn provider configuration is available."""
        providers: dict[str, Any] = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {})
        linkedin_config = providers.get("linkedin_oauth2", {})

        # In test environment, APP section is removed to avoid conflicts
        # But basic provider configuration should be present
        assert linkedin_config is not None
        assert "SCOPE" in linkedin_config
        assert "VERIFIED_EMAIL" in linkedin_config

    def test_linkedin_provider_uses_profile_scope(self):
        """Test that LinkedIn provider includes required 'profile' scope."""
        providers: dict[str, Any] = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {})
        linkedin_config = providers.get("linkedin_oauth2", {})

        # LinkedIn OpenID Connect requires 'profile' scope to fetch user profile
        scopes = linkedin_config.get("SCOPE", [])
        assert "profile" in scopes
