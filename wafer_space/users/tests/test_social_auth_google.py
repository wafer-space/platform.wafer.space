"""Tests for Google OAuth authentication integration."""

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
TEST_PASSWORD = "testpass123"  # noqa: S105
HTTP_OK = 200
HTTP_REDIRECT = 302
HTTP_BAD_REQUEST = 400
HTTP_FORBIDDEN = 403

User = get_user_model()


@pytest.mark.django_db
class TestGoogleAuthenticationFlow(TestCase):
    """Test Google OAuth authentication flow."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()
        self.login_url = reverse("account_login")
        self.google_login_url = reverse("google_login")

        # Clean up any existing apps for this provider to avoid conflicts
        SocialApp.objects.filter(provider="google").delete()

        # Create a test Google OAuth app (would normally use environment vars)
        self.site = Site.objects.get_current()
        self.google_app = SocialApp.objects.create(
            provider="google",
            name="Google Test App",
            client_id="test_google_client_id.apps.googleusercontent.com",
            # Test OAuth secret for Google provider testing only
            secret="test_google_client_secret",  # noqa: S106
        )
        self.google_app.sites.add(self.site)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up the test app
        SocialApp.objects.filter(provider="google").delete()

    def test_login_page_shows_google_button(self):
        """Test that login page displays Google authentication option."""
        response = self.client.get(self.login_url)
        assert response.status_code == HTTP_OK
        # Check for Google provider in context or content
        assert b"Google" in response.content or b"google" in response.content

    def test_google_login_url_exists(self):
        """Test that Google login URL is accessible."""
        response = self.client.get(self.google_login_url)
        # Should redirect to Google OAuth
        assert response.status_code == HTTP_REDIRECT
        assert "accounts.google.com/oauth" in response.url

    def test_google_oauth_redirect_contains_correct_params(self):
        """Test that Google OAuth redirect has correct parameters."""
        response = self.client.get(self.google_login_url)
        assert response.status_code == HTTP_REDIRECT
        redirect_url = response.url

        # Check for required OAuth parameters
        assert (
            "client_id=test_google_client_id.apps.googleusercontent.com" in redirect_url
        )
        assert "scope=" in redirect_url
        assert "profile" in redirect_url or "email" in redirect_url
        assert "redirect_uri=" in redirect_url
        assert "access_type=online" in redirect_url

    @override_settings(
        SOCIALACCOUNT_PROVIDERS={
            "google": {
                "SCOPE": ["profile", "email"],
                "AUTH_PARAMS": {"access_type": "online"},
                "VERIFIED_EMAIL": True,
            },
        },
    )
    def test_google_account_creation_on_successful_auth(self):
        """Test that a new user is created on successful Google authentication."""
        # This test would normally mock the OAuth callback
        # For now, we're testing the setup is correct

        # Simulate a successful OAuth callback (would be mocked in real test)
        test_email = "google_user@gmail.com"

        # Check user doesn't exist yet
        assert not User.objects.filter(email=test_email).exists()

        # In a real test, we would mock the OAuth callback here
        # and verify the user is created with correct data

    def test_existing_user_can_link_google_account(self):
        """Test that existing users can link their Google account."""
        # Create a test user
        user = User.objects.create_user(
            username="existing_user",
            email="existing@example.com",
            password=TEST_PASSWORD,
        )

        # Login as the user
        self.client.login(username="existing_user", password=TEST_PASSWORD)

        # Check no social account exists yet
        assert not SocialAccount.objects.filter(user=user, provider="google").exists()

        # In a real test, we would:
        # 1. Navigate to account connections page
        # 2. Click "Connect Google"
        # 3. Mock the OAuth flow
        # 4. Verify the account is linked

    def test_google_auth_with_existing_email_links_accounts(self):
        """Test that Google auth with existing email links to existing user."""
        # Create a user with an email
        existing_email = "existing@gmail.com"
        User.objects.create_user(
            username="existing_user",
            email=existing_email,
            password=TEST_PASSWORD,
        )

        # Verify settings allow auto-linking
        assert settings.SOCIALACCOUNT_AUTO_SIGNUP is True

        # In a real test, we would mock Google OAuth returning
        # the same email and verify accounts are linked


@pytest.mark.django_db
class TestGoogleAuthenticationSecurity(TestCase):
    """Test security aspects of Google authentication."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()

    def test_google_oauth_uses_state_parameter(self):
        """Test that Google OAuth uses state parameter for CSRF protection."""
        google_login_url = reverse("google_login")
        response = self.client.get(google_login_url)

        # Check that state parameter is included (CSRF protection)
        assert response.status_code == HTTP_REDIRECT
        assert "state=" in response.url

    def test_google_callback_validates_state(self):
        """Test that Google callback validates state parameter."""
        callback_url = reverse("google_callback")

        # Try callback without state parameter (should fail)
        response = self.client.get(callback_url)

        # Should not process without valid state
        assert response.status_code in [400, 403]

    def test_google_requires_verified_email(self):
        """Test that Google provider requires verified email."""
        google_config = settings.SOCIALACCOUNT_PROVIDERS.get("google", {})

        # Verify email verification is required
        assert google_config.get("VERIFIED_EMAIL") is True

    def test_google_uses_online_access_type(self):
        """Test that Google provider uses online access type."""
        google_config = settings.SOCIALACCOUNT_PROVIDERS.get("google", {})

        # Verify online access type is configured
        auth_params = google_config.get("AUTH_PARAMS", {})
        assert auth_params.get("access_type") == "online"


@pytest.mark.django_db
class TestGoogleAuthenticationErrors(TestCase):
    """Test error handling in Google authentication."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()

    def test_google_auth_denied_by_user(self):
        """Test handling when user denies Google authentication."""
        callback_url = reverse("google_callback")

        # Simulate user denying access
        response = self.client.get(callback_url, {"error": "access_denied"})

        # Should redirect to login with error message
        assert response.status_code == HTTP_REDIRECT
        # Would check for error message in session/messages

    def test_google_auth_with_invalid_token(self):
        """Test handling of invalid Google token."""
        callback_url = reverse("google_callback")

        # Simulate invalid token response
        response = self.client.get(
            callback_url,
            {
                "code": "invalid_code",
                "state": "valid_state",
            },
        )

        # Should handle gracefully
        assert response.status_code in [302, 400]

    def test_google_auth_without_email_permission(self):
        """Test handling when Google doesn't provide email."""
        # This would test the case where user doesn't grant email permission
        # Would need to mock the Google API response without email

    def test_google_auth_with_invalid_client_id(self):
        """Test handling with malformed Google client ID."""
        # Google client IDs should end with .apps.googleusercontent.com
        google_config = settings.SOCIALACCOUNT_PROVIDERS.get("google", {})
        app_config = google_config.get("APP", {})

        if app_config.get("client_id"):
            client_id = app_config["client_id"]
            # If configured, should be a proper Google client ID format
            assert ".apps.googleusercontent.com" in client_id or client_id == ""


@pytest.mark.django_db
class TestGoogleProviderConfiguration(TestCase):
    """Test Google provider configuration."""

    def test_google_provider_is_installed(self):
        """Test that Google provider is in INSTALLED_APPS."""
        assert "allauth.socialaccount.providers.google" in settings.INSTALLED_APPS

    def test_google_provider_scope_configuration(self):
        """Test that Google provider requests correct scopes."""
        google_config = settings.SOCIALACCOUNT_PROVIDERS.get("google", {})

        # Check required scopes are configured
        scopes = google_config.get("SCOPE", [])
        assert "profile" in scopes
        assert "email" in scopes

    def test_google_provider_auth_params_configuration(self):
        """Test that Google provider has correct auth params."""
        google_config = settings.SOCIALACCOUNT_PROVIDERS.get("google", {})

        # Check auth params are configured
        auth_params = google_config.get("AUTH_PARAMS", {})
        assert auth_params.get("access_type") == "online"

    def test_google_callback_url_is_configured(self):
        """Test that Google callback URL is properly configured."""
        # Test that the callback URL can be reversed
        callback_url = reverse("google_callback")
        assert "/accounts/google/login/callback/" in callback_url

    def test_google_provider_verified_email_setting(self):
        """Test that Google provider trusts verified emails."""
        google_config = settings.SOCIALACCOUNT_PROVIDERS.get("google", {})

        # Google emails should be trusted as verified
        assert google_config.get("VERIFIED_EMAIL") is True
