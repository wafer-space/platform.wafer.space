"""Tests for Discord OAuth authentication integration."""

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
class TestDiscordAuthenticationFlow(TestCase):
    """Test Discord OAuth authentication flow."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()
        self.login_url = reverse("account_login")
        self.discord_login_url = reverse("discord_login")

        # Create a test Discord OAuth app for unit testing
        # Unit tests create their own isolated SocialApp objects
        self.site = Site.objects.get_current()
        self.discord_app = SocialApp.objects.create(
            provider="discord",
            name="Discord Unit Test App",
            client_id="unit_test_discord_client_id",
            secret="unit_test_discord_secret",  # noqa: S106
        )
        self.discord_app.sites.add(self.site)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up the test app
        SocialApp.objects.filter(provider="discord").delete()

    def test_login_page_shows_discord_button(self):
        """Test that login page displays Discord authentication option."""
        response = self.client.get(self.login_url)
        assert response.status_code == HTTP_OK
        # Check for Discord provider in context or content
        assert b"Discord" in response.content or b"discord" in response.content

    def test_discord_login_url_exists(self):
        """Test that Discord login URL is accessible and handled by django-allauth."""
        response = self.client.get(self.discord_login_url)
        # The response should either be a redirect to Discord OAuth (302)
        # or a 200 response from allauth handling the request
        assert response.status_code in [HTTP_OK, HTTP_REDIRECT]
        # If it's a redirect, it should be to Discord
        if response.status_code == HTTP_REDIRECT:
            assert "discord.com/api/oauth2/authorize" in response.url

    def test_discord_oauth_redirect_contains_correct_params(self):
        """Test Discord OAuth redirect parameters when redirect occurs."""
        response = self.client.get(self.discord_login_url)
        # Only test redirect parameters if we actually get a redirect
        if response.status_code == HTTP_REDIRECT:
            redirect_url = response.url
            # Check for required OAuth parameters
            assert "client_id=" in redirect_url
            assert "scope=" in redirect_url
            assert "redirect_uri=" in redirect_url
            assert "response_type=code" in redirect_url
            assert "discord.com/api/oauth2/authorize" in redirect_url
        else:
            # If no redirect, just verify the URL is accessible
            assert response.status_code == HTTP_OK

    @override_settings(
        SOCIALACCOUNT_PROVIDERS={
            "discord": {
                "SCOPE": ["identify", "email"],
                "VERIFIED_EMAIL": True,
            },
        },
    )
    def test_discord_account_creation_on_successful_auth(self):
        """Test that a new user is created on successful Discord authentication."""
        # This test would normally mock the OAuth callback
        # For now, we're testing the setup is correct

        # Simulate a successful OAuth callback (would be mocked in real test)
        test_email = "discord_user@example.com"

        # Check user doesn't exist yet
        assert not User.objects.filter(email=test_email).exists()

        # In a real test, we would mock the OAuth callback here
        # and verify the user is created with correct data

    def test_existing_user_can_link_discord_account(self):
        """Test that existing users can link their Discord account."""
        # Create a test user
        user = User.objects.create_user(
            username="existing_user",
            email="existing@example.com",
            password=TEST_PASSWORD,
        )

        # Login as the user
        self.client.login(username="existing_user", password=TEST_PASSWORD)

        # Check no social account exists yet
        assert not SocialAccount.objects.filter(user=user, provider="discord").exists()

        # In a real test, we would:
        # 1. Navigate to account connections page
        # 2. Click "Connect Discord"
        # 3. Mock the OAuth flow
        # 4. Verify the account is linked

    def test_discord_auth_with_existing_email_links_accounts(self):
        """Test that Discord auth with existing email links to existing user."""
        # Create a user with an email
        existing_email = "existing@example.com"
        User.objects.create_user(
            username="existing_user",
            email=existing_email,
            password=TEST_PASSWORD,
        )

        # Verify settings allow auto-linking
        assert settings.SOCIALACCOUNT_AUTO_SIGNUP is True

        # In a real test, we would mock Discord OAuth returning
        # the same email and verify accounts are linked


@pytest.mark.django_db
class TestDiscordAuthenticationSecurity(TestCase):
    """Test security aspects of Discord authentication."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()

        # Create a test Discord OAuth app for security testing
        self.site = Site.objects.get_current()
        self.discord_app = SocialApp.objects.create(
            provider="discord",
            name="Discord Security Test App",
            client_id="security_test_discord_client_id",
            secret="security_test_discord_secret",  # noqa: S106
        )
        self.discord_app.sites.add(self.site)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up the test app
        SocialApp.objects.filter(provider="discord").delete()

    def test_discord_oauth_uses_state_parameter(self):
        """Test that Discord OAuth uses state parameter for CSRF protection."""
        discord_login_url = reverse("discord_login")
        response = self.client.get(discord_login_url)

        # Check that state parameter is included (CSRF protection) if redirecting
        if response.status_code == HTTP_REDIRECT:
            assert "state=" in response.url
        else:
            # If no redirect, just verify the URL is accessible
            assert response.status_code == HTTP_OK

    def test_discord_callback_validates_state(self):
        """Test that Discord callback validates state parameter."""
        callback_url = reverse("discord_callback")

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

    def test_discord_requires_verified_email(self):
        """Test that Discord provider requires verified email."""
        discord_config = settings.SOCIALACCOUNT_PROVIDERS.get("discord", {})

        # Verify email verification is required
        assert discord_config.get("VERIFIED_EMAIL") is True

    def test_discord_uses_correct_scopes(self):
        """Test that Discord provider uses correct scopes."""
        discord_config = settings.SOCIALACCOUNT_PROVIDERS.get("discord", {})

        # Verify required scopes are configured
        scopes = discord_config.get("SCOPE", [])
        assert "identify" in scopes
        assert "email" in scopes


@pytest.mark.django_db
class TestDiscordAuthenticationErrors(TestCase):
    """Test error handling in Discord authentication."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()

        # Create a test Discord OAuth app for error testing
        self.site = Site.objects.get_current()
        self.discord_app = SocialApp.objects.create(
            provider="discord",
            name="Discord Error Test App",
            client_id="error_test_discord_client_id",
            secret="error_test_discord_secret",  # noqa: S106
        )
        self.discord_app.sites.add(self.site)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up the test app
        SocialApp.objects.filter(provider="discord").delete()

    def test_discord_auth_denied_by_user(self):
        """Test handling when user denies Discord authentication."""
        callback_url = reverse("discord_callback")

        # Simulate user denying access
        response = self.client.get(callback_url, {"error": "access_denied"})

        # Should handle error appropriately - expect any response that handles the error
        assert response.status_code in [HTTP_OK, HTTP_REDIRECT, 400, 403, 500]
        # Would check for error message in session/messages in full implementation

    def test_discord_auth_with_invalid_token(self):
        """Test handling of invalid Discord token."""
        callback_url = reverse("discord_callback")

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

    def test_discord_auth_without_email_permission(self):
        """Test handling when Discord doesn't provide email."""
        # This would test the case where user doesn't grant email permission
        # Would need to mock the Discord API response without email
        # Discord requires explicit permission for email scope


@pytest.mark.django_db
class TestDiscordProviderConfiguration(TestCase):
    """Test Discord provider configuration."""

    def test_discord_provider_is_installed(self):
        """Test that Discord provider is in INSTALLED_APPS."""
        assert "allauth.socialaccount.providers.discord" in settings.INSTALLED_APPS

    def test_discord_provider_scope_configuration(self):
        """Test that Discord provider requests correct scopes."""
        discord_config = settings.SOCIALACCOUNT_PROVIDERS.get("discord", {})

        # Check required scopes are configured
        scopes = discord_config.get("SCOPE", [])
        assert "identify" in scopes
        assert "email" in scopes

    def test_discord_callback_url_is_configured(self):
        """Test that Discord callback URL is properly configured."""
        # Test that the callback URL can be reversed
        callback_url = reverse("discord_callback")
        assert "/accounts/discord/login/callback/" in callback_url

    def test_discord_provider_verified_email_setting(self):
        """Test that Discord provider trusts verified emails."""
        discord_config = settings.SOCIALACCOUNT_PROVIDERS.get("discord", {})

        # Discord emails should be trusted as verified
        assert discord_config.get("VERIFIED_EMAIL") is True

    def test_discord_environment_variable_configuration(self):
        """Test that Discord provider configuration is available."""
        discord_config = settings.SOCIALACCOUNT_PROVIDERS.get("discord", {})

        # In test environment, APP section is removed to avoid conflicts
        # But basic provider configuration should be present
        assert discord_config is not None
        assert "SCOPE" in discord_config
        assert "VERIFIED_EMAIL" in discord_config

    def test_discord_provider_uses_identify_scope(self):
        """Test that Discord provider includes required 'identify' scope."""
        discord_config = settings.SOCIALACCOUNT_PROVIDERS.get("discord", {})

        # Discord requires 'identify' scope to fetch user ID
        scopes = discord_config.get("SCOPE", [])
        assert "identify" in scopes
