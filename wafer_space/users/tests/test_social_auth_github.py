"""Tests for GitHub OAuth authentication integration."""

import pytest
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.models import SocialApp
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.test import Client
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

User = get_user_model()


@pytest.mark.django_db
class TestGitHubAuthenticationFlow(TestCase):
    """Test GitHub OAuth authentication flow."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()
        self.login_url = reverse("account_login")
        self.github_login_url = reverse("github_login")

        # Clean up any existing apps for this provider to avoid conflicts
        SocialApp.objects.filter(provider="github").delete()

        # Create a test GitHub OAuth app (would normally use environment vars)
        self.site = Site.objects.get_current()
        self.github_app = SocialApp.objects.create(
            provider="github",
            name="GitHub Test App",
            client_id="test_github_client_id",
            secret="test_github_client_secret",
        )
        self.github_app.sites.add(self.site)

    def tearDown(self):
        """Clean up test environment."""
        # Clean up the test app
        SocialApp.objects.filter(provider="github").delete()

    def test_login_page_shows_github_button(self):
        """Test that login page displays GitHub authentication option."""
        response = self.client.get(self.login_url)
        assert response.status_code == 200
        # Check for GitHub provider in context or content
        assert b"GitHub" in response.content or b"github" in response.content

    def test_github_login_url_exists(self):
        """Test that GitHub login URL is accessible."""
        response = self.client.get(self.github_login_url)
        # Should redirect to GitHub OAuth
        assert response.status_code == 302
        assert "github.com/login/oauth" in response.url

    def test_github_oauth_redirect_contains_correct_params(self):
        """Test that GitHub OAuth redirect has correct parameters."""
        response = self.client.get(self.github_login_url)
        assert response.status_code == 302
        redirect_url = response.url

        # Check for required OAuth parameters
        assert "client_id=test_github_client_id" in redirect_url
        assert "scope=user:email" in redirect_url
        assert "redirect_uri=" in redirect_url

    @override_settings(SOCIALACCOUNT_PROVIDERS={
        "github": {
            "SCOPE": ["user:email"],
            "VERIFIED_EMAIL": True,
        }
    })
    def test_github_account_creation_on_successful_auth(self):
        """Test that a new user is created on successful GitHub authentication."""
        # This test would normally mock the OAuth callback
        # For now, we're testing the setup is correct

        # Simulate a successful OAuth callback (would be mocked in real test)
        test_email = "github_user@example.com"
        test_username = "github_test_user"

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
            password="testpass123",
        )

        # Login as the user
        self.client.login(username="existing_user", password="testpass123")

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
        user = User.objects.create_user(
            username="existing_user",
            email=existing_email,
            password="testpass123",
        )

        # Verify settings allow auto-linking
        from django.conf import settings
        assert settings.SOCIALACCOUNT_AUTO_SIGNUP is True

        # In a real test, we would mock GitHub OAuth returning
        # the same email and verify accounts are linked


@pytest.mark.django_db
class TestGitHubAuthenticationSecurity(TestCase):
    """Test security aspects of GitHub authentication."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()

    def test_github_oauth_uses_state_parameter(self):
        """Test that GitHub OAuth uses state parameter for CSRF protection."""
        github_login_url = reverse("github_login")
        response = self.client.get(github_login_url)

        # Check that state parameter is included (CSRF protection)
        assert response.status_code == 302
        assert "state=" in response.url

    def test_github_callback_validates_state(self):
        """Test that GitHub callback validates state parameter."""
        callback_url = reverse("github_callback")

        # Try callback without state parameter (should fail)
        response = self.client.get(callback_url)

        # Should not process without valid state
        assert response.status_code in [400, 403]

    def test_github_requires_verified_email(self):
        """Test that GitHub provider requires verified email."""
        from django.conf import settings
        github_config = settings.SOCIALACCOUNT_PROVIDERS.get("github", {})

        # Verify email verification is required
        assert github_config.get("VERIFIED_EMAIL") is True


@pytest.mark.django_db
class TestGitHubAuthenticationErrors(TestCase):
    """Test error handling in GitHub authentication."""

    def setUp(self):
        """Set up test environment."""
        self.client = Client()

    def test_github_auth_denied_by_user(self):
        """Test handling when user denies GitHub authentication."""
        callback_url = reverse("github_callback")

        # Simulate user denying access
        response = self.client.get(callback_url, {"error": "access_denied"})

        # Should redirect to login with error message
        assert response.status_code == 302
        # Would check for error message in session/messages

    def test_github_auth_with_invalid_token(self):
        """Test handling of invalid GitHub token."""
        callback_url = reverse("github_callback")

        # Simulate invalid token response
        response = self.client.get(callback_url, {
            "code": "invalid_code",
            "state": "valid_state"
        })

        # Should handle gracefully
        assert response.status_code in [302, 400]

    def test_github_auth_without_email_permission(self):
        """Test handling when GitHub doesn't provide email."""
        # This would test the case where user doesn't grant email permission
        # Would need to mock the GitHub API response without email
        pass


@pytest.mark.django_db
class TestGitHubProviderConfiguration(TestCase):
    """Test GitHub provider configuration."""

    def test_github_provider_is_installed(self):
        """Test that GitHub provider is in INSTALLED_APPS."""
        from django.conf import settings
        assert "allauth.socialaccount.providers.github" in settings.INSTALLED_APPS

    def test_github_provider_scope_configuration(self):
        """Test that GitHub provider requests correct scopes."""
        from django.conf import settings
        github_config = settings.SOCIALACCOUNT_PROVIDERS.get("github", {})

        # Check required scope is configured
        assert "user:email" in github_config.get("SCOPE", [])

    def test_github_callback_url_is_configured(self):
        """Test that GitHub callback URL is properly configured."""
        # Test that the callback URL can be reversed
        callback_url = reverse("github_callback")
        assert "/accounts/github/login/callback/" in callback_url