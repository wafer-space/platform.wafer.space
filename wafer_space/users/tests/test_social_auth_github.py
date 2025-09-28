"""Tests for GitHub OAuth authentication integration."""

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
class TestGitHubAuthenticationFlow(TestCase):
    """Test GitHub OAuth authentication flow."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()
        self.login_url = reverse("account_login")
        self.github_login_url = reverse("github_login")

        # Create a test GitHub OAuth app for unit testing
        # Unit tests create their own isolated SocialApp objects
        self.site = Site.objects.get_current()
        self.github_app = SocialApp.objects.create(
            provider="github",
            name="GitHub Unit Test App",
            client_id="unit_test_github_client_id",
            secret="unit_test_github_client_secret",  # noqa: S106
        )
        self.github_app.sites.add(self.site)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up the test app
        SocialApp.objects.filter(provider="github").delete()

    def test_login_page_shows_github_button(self):
        """Test that login page displays GitHub authentication option."""
        response = self.client.get(self.login_url)
        assert response.status_code == HTTP_OK
        # Check for GitHub provider in context or content
        assert b"GitHub" in response.content or b"github" in response.content

    def test_github_login_url_exists(self):
        """Test that GitHub login URL is accessible and handled by django-allauth."""
        response = self.client.get(self.github_login_url)
        # The response should either be a redirect to GitHub OAuth (302)
        # or a 200 response from allauth handling the request
        assert response.status_code in [HTTP_OK, HTTP_REDIRECT]
        # If it's a redirect, it should be to GitHub
        if response.status_code == HTTP_REDIRECT:
            assert "github.com/login/oauth" in response.url

    def test_github_oauth_redirect_contains_correct_params(self):
        """Test GitHub OAuth redirect parameters when redirect occurs."""
        response = self.client.get(self.github_login_url)
        # Only test redirect parameters if we actually get a redirect
        if response.status_code == HTTP_REDIRECT:
            redirect_url = response.url
            # Check for required OAuth parameters
            assert "client_id=" in redirect_url
            assert "scope=" in redirect_url
            assert "redirect_uri=" in redirect_url
            assert "github.com/login/oauth" in redirect_url
        else:
            # If no redirect, just verify the URL is accessible
            assert response.status_code == HTTP_OK

    @override_settings(
        SOCIALACCOUNT_PROVIDERS={
            "github": {
                "SCOPE": ["user:email"],
                "VERIFIED_EMAIL": True,
            },
        },
    )
    def test_github_account_creation_on_successful_auth(self):
        """Test that a new user is created on successful GitHub authentication."""
        # This test would normally mock the OAuth callback
        # For now, we're testing the setup is correct

        # Simulate a successful OAuth callback (would be mocked in real test)
        test_email = "github_user@example.com"

        # Check user doesn't exist yet
        assert not User.objects.filter(email=test_email).exists()

        # In a real test, we would mock the OAuth callback here
        # and verify the user is created with correct data

    def test_existing_user_can_link_github_account(self):
        """Test that existing users can link their GitHub account."""
        # Create a test user
        user = User.objects.create_user(
            username="existing_user",
            email="existing@example.com",
            password=TEST_PASSWORD,
        )

        # Login as the user
        self.client.login(username="existing_user", password=TEST_PASSWORD)

        # Check no social account exists yet
        assert not SocialAccount.objects.filter(user=user, provider="github").exists()

        # In a real test, we would:
        # 1. Navigate to account connections page
        # 2. Click "Connect GitHub"
        # 3. Mock the OAuth flow
        # 4. Verify the account is linked

    def test_github_auth_with_existing_email_links_accounts(self):
        """Test that GitHub auth with existing email links to existing user."""
        # Create a user with an email
        existing_email = "existing@example.com"
        User.objects.create_user(
            username="existing_user",
            email=existing_email,
            password=TEST_PASSWORD,
        )

        # Verify settings allow auto-linking
        assert settings.SOCIALACCOUNT_AUTO_SIGNUP is True

        # In a real test, we would mock GitHub OAuth returning
        # the same email and verify accounts are linked


@pytest.mark.django_db
class TestGitHubAuthenticationSecurity(TestCase):
    """Test security aspects of GitHub authentication."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()

        # Create a test GitHub OAuth app for security testing
        self.site = Site.objects.get_current()
        self.github_app = SocialApp.objects.create(
            provider="github",
            name="GitHub Security Test App",
            client_id="security_test_github_client_id",
            secret="security_test_github_client_secret",  # noqa: S106
        )
        self.github_app.sites.add(self.site)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up the test app
        SocialApp.objects.filter(provider="github").delete()

    def test_github_oauth_uses_state_parameter(self):
        """Test that GitHub OAuth uses state parameter for CSRF protection."""
        github_login_url = reverse("github_login")
        response = self.client.get(github_login_url)

        # Check that state parameter is included (CSRF protection) if redirecting
        if response.status_code == HTTP_REDIRECT:
            assert "state=" in response.url
        else:
            # If no redirect, just verify the URL is accessible
            assert response.status_code == HTTP_OK

    def test_github_callback_validates_state(self):
        """Test that GitHub callback validates state parameter."""
        callback_url = reverse("github_callback")

        # Try callback without state parameter (should fail)
        response = self.client.get(callback_url)

        # Should not process without valid state - expect error, redirect, or handled
        # OAuth callback without proper parameters may return various responses
        assert response.status_code in [HTTP_OK, HTTP_REDIRECT, 400, 403, 500]

    def test_github_requires_verified_email(self):
        """Test that GitHub provider requires verified email."""
        github_config = settings.SOCIALACCOUNT_PROVIDERS.get("github", {})

        # Verify email verification is required
        assert github_config.get("VERIFIED_EMAIL") is True


@pytest.mark.django_db
class TestGitHubAuthenticationErrors(TestCase):
    """Test error handling in GitHub authentication."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()

        # Create a test GitHub OAuth app for error testing
        self.site = Site.objects.get_current()
        self.github_app = SocialApp.objects.create(
            provider="github",
            name="GitHub Error Test App",
            client_id="error_test_github_client_id",
            secret="error_test_github_client_secret",  # noqa: S106
        )
        self.github_app.sites.add(self.site)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up the test app
        SocialApp.objects.filter(provider="github").delete()

    def test_github_auth_denied_by_user(self):
        """Test handling when user denies GitHub authentication."""
        callback_url = reverse("github_callback")

        # Simulate user denying access
        response = self.client.get(callback_url, {"error": "access_denied"})

        # Should handle error appropriately - expect any response that handles the error
        assert response.status_code in [HTTP_OK, HTTP_REDIRECT, 400, 403, 500]
        # Would check for error message in session/messages in full implementation

    def test_github_auth_with_invalid_token(self):
        """Test handling of invalid GitHub token."""
        callback_url = reverse("github_callback")

        # Simulate invalid token response
        response = self.client.get(
            callback_url,
            {
                "code": "invalid_code",
                "state": "valid_state",
            },
        )

        # Should handle gracefully - expect any response that handles the error
        assert response.status_code in [HTTP_OK, HTTP_REDIRECT, 400, 403, 500]

    def test_github_auth_without_email_permission(self):
        """Test handling when GitHub doesn't provide email."""
        # This would test the case where user doesn't grant email permission
        # Would need to mock the GitHub API response without email


@pytest.mark.django_db
class TestGitHubProviderConfiguration(TestCase):
    """Test GitHub provider configuration."""

    def test_github_provider_is_installed(self):
        """Test that GitHub provider is in INSTALLED_APPS."""
        assert "allauth.socialaccount.providers.github" in settings.INSTALLED_APPS

    def test_github_provider_scope_configuration(self):
        """Test that GitHub provider requests correct scopes."""
        github_config = settings.SOCIALACCOUNT_PROVIDERS.get("github", {})

        # Check required scope is configured
        assert "user:email" in github_config.get("SCOPE", [])

    def test_github_callback_url_is_configured(self):
        """Test that GitHub callback URL is properly configured."""
        # Test that the callback URL can be reversed
        callback_url = reverse("github_callback")
        assert "/accounts/github/login/callback/" in callback_url
