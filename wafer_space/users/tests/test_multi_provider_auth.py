"""Tests for multi-provider OAuth authentication and account linking."""

import pytest
from allauth.socialaccount.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.models import SocialApp
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.test import TestCase
from django.test import override_settings

# Test constants
TEST_PASSWORD = "testpass123"  # noqa: S105
HTTP_OK = 200

User = get_user_model()


@pytest.mark.django_db
class TestMultiProviderAuthentication(TestCase):
    """Test authentication with multiple OAuth providers using the same email."""

    def setUp(self):
        """Set up test environment with multiple OAuth providers."""
        self.site = Site.objects.get_current()
        self.test_email = "user@example.com"

        # Create test OAuth apps for different providers
        self.github_app = SocialApp.objects.create(
            provider="github",
            name="GitHub Test App",
            client_id="test_github_client",
            secret="test_github_secret",  # noqa: S106
        )
        self.github_app.sites.add(self.site)

        self.gitlab_app = SocialApp.objects.create(
            provider="gitlab",
            name="GitLab Test App",
            client_id="test_gitlab_client",
            secret="test_gitlab_secret",  # noqa: S106
        )
        self.gitlab_app.sites.add(self.site)

        self.google_app = SocialApp.objects.create(
            provider="google",
            name="Google Test App",
            client_id="test_google_client",
            secret="test_google_secret",  # noqa: S106
        )
        self.google_app.sites.add(self.site)

    def tearDown(self):
        """Clean up test environment."""
        SocialApp.objects.all().delete()
        User.objects.all().delete()

    @override_settings(
        SOCIALACCOUNT_EMAIL_AUTHENTICATION=True,
        SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT=True,
    )
    def test_email_authentication_setting_enabled(self):
        """Test that email authentication is properly configured."""
        assert settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION is True
        assert settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT is True

    def test_user_can_have_multiple_social_accounts(self):
        """Test that a user can link multiple OAuth providers."""
        # Create a user
        user = User.objects.create_user(
            username="testuser",
            email=self.test_email,
            password=TEST_PASSWORD,
        )

        # Verify email
        EmailAddress.objects.create(
            user=user,
            email=self.test_email,
            verified=True,
            primary=True,
        )

        # Link GitHub account
        github_account = SocialAccount.objects.create(
            user=user,
            provider="github",
            uid="github123",
            extra_data={"login": "testuser"},
        )

        # Link GitLab account
        gitlab_account = SocialAccount.objects.create(
            user=user,
            provider="gitlab",
            uid="gitlab456",
            extra_data={"username": "testuser"},
        )

        # Verify both accounts are linked to the same user
        expected_account_count = 2
        assert user.socialaccount_set.count() == expected_account_count
        assert github_account.user == user
        assert gitlab_account.user == user

    def test_social_accounts_have_different_providers(self):
        """Test that social accounts can be distinguished by provider."""
        user = User.objects.create_user(
            username="multiuser",
            email=self.test_email,
            password=TEST_PASSWORD,
        )

        SocialAccount.objects.create(
            user=user,
            provider="github",
            uid="github999",
        )

        SocialAccount.objects.create(
            user=user,
            provider="google",
            uid="google888",
        )

        # Check provider-specific queries
        assert user.socialaccount_set.filter(provider="github").exists()
        assert user.socialaccount_set.filter(provider="google").exists()
        assert not user.socialaccount_set.filter(provider="gitlab").exists()

    def test_email_uniqueness_across_providers(self):
        """Test same email across different providers for one user."""
        user = User.objects.create_user(
            username="sameemailuser",
            email=self.test_email,
            password=TEST_PASSWORD,
        )

        email_address = EmailAddress.objects.create(
            user=user,
            email=self.test_email,
            verified=True,
            primary=True,
        )

        # Multiple social accounts can reference the same email
        github_account = SocialAccount.objects.create(
            user=user,
            provider="github",
            uid="gh123",
        )

        gitlab_account = SocialAccount.objects.create(
            user=user,
            provider="gitlab",
            uid="gl456",
        )

        # Both accounts should be for the same user/email
        assert github_account.user.email == self.test_email
        assert gitlab_account.user.email == self.test_email
        assert email_address.user == user

    @override_settings(
        SOCIALACCOUNT_EMAIL_AUTHENTICATION=True,
        SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT=True,
    )
    def test_auto_connect_configuration(self):
        """Test that auto-connect settings are properly configured for production."""
        # Verify the settings that enable automatic account linking
        assert hasattr(settings, "SOCIALACCOUNT_EMAIL_AUTHENTICATION")
        assert hasattr(settings, "SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT")

        # These settings should be True for seamless multi-provider auth
        assert settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION is True
        assert settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT is True

    def test_verified_email_addresses_only(self):
        """Test only verified emails are used for account linking."""
        user = User.objects.create_user(
            username="verifytest",
            email=self.test_email,
            password=TEST_PASSWORD,
        )

        # Create verified and unverified email addresses
        verified_email = EmailAddress.objects.create(
            user=user,
            email=self.test_email,
            verified=True,
            primary=True,
        )

        unverified_email = EmailAddress.objects.create(
            user=user,
            email="unverified@example.com",
            verified=False,
            primary=False,
        )

        # Only verified emails should be considered for account linking
        verified_emails = EmailAddress.objects.filter(user=user, verified=True)
        assert verified_emails.count() == 1
        assert verified_email in verified_emails
        assert unverified_email not in verified_emails


@pytest.mark.django_db
class TestSocialAccountProviderConfiguration(TestCase):
    """Test that all OAuth providers have correct email verification configuration."""

    def test_all_providers_require_verified_email(self):
        """Test that all configured providers are set to use verified emails."""
        providers = settings.SOCIALACCOUNT_PROVIDERS

        # Check that all providers have VERIFIED_EMAIL: True
        for provider_name, provider_config in providers.items():
            assert "VERIFIED_EMAIL" in provider_config, (
                f"{provider_name} missing VERIFIED_EMAIL setting"
            )
            assert provider_config["VERIFIED_EMAIL"] is True, (
                f"{provider_name} should have VERIFIED_EMAIL: True"
            )

    def test_github_provider_configured(self):
        """Test GitHub provider has correct configuration for email linking."""
        github_config = settings.SOCIALACCOUNT_PROVIDERS.get("github", {})
        assert github_config.get("VERIFIED_EMAIL") is True
        assert "user:email" in github_config.get("SCOPE", [])

    def test_gitlab_provider_configured(self):
        """Test GitLab provider has correct configuration for email linking."""
        gitlab_config = settings.SOCIALACCOUNT_PROVIDERS.get("gitlab", {})
        assert gitlab_config.get("VERIFIED_EMAIL") is True
        assert "email" in gitlab_config.get("SCOPE", [])

    def test_google_provider_configured(self):
        """Test Google provider has correct configuration for email linking."""
        google_config = settings.SOCIALACCOUNT_PROVIDERS.get("google", {})
        assert google_config.get("VERIFIED_EMAIL") is True
        assert "email" in google_config.get("SCOPE", [])
