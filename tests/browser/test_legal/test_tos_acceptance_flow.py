"""Browser tests for TOS acceptance flow."""

import pytest
from django.contrib.auth import get_user_model

from tests.browser.base import BaseBrowserTest
from tests.browser.pages.login_page import LoginPage
from tests.browser.pages.tos_page import TOSAcceptPage
from tests.browser.pages.tos_page import TOSDisplayPage
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.legal.tests.factories import TermsOfServiceAcceptanceFactory
from wafer_space.legal.tests.factories import TermsOfServiceFactory
from wafer_space.users.tests.factories import UserFactory

User = get_user_model()

# Test constants
TEST_PASSWORD = "testpass123"  # noqa: S105
MIN_VERSION_DISPLAY_COUNT = 2  # Minimum times version should appear on page


@pytest.fixture
def active_tos(django_db_blocker):
    """Create active TOS with transaction committed for live_server visibility."""
    with django_db_blocker.unblock():
        return TermsOfServiceFactory(
            is_active=True,
            version="1.0.0",
            content="You must accept these terms",
        )


@pytest.fixture
def test_user(django_db_blocker):
    """Create test user with transaction committed for live_server visibility."""
    with django_db_blocker.unblock():
        user = UserFactory()
        user.set_password(TEST_PASSWORD)
        user.save()
        return user


@pytest.fixture
def test_user_with_acceptance(django_db_blocker, active_tos):
    """Create test user who has already accepted TOS."""
    with django_db_blocker.unblock():
        user = UserFactory()
        user.set_password(TEST_PASSWORD)
        user.save()
        TermsOfServiceAcceptanceFactory(user=user, tos_version=active_tos)
        return user


@pytest.mark.django_db
@pytest.mark.browser
class TestTOSAcceptanceFlow(BaseBrowserTest):
    """Test the complete TOS acceptance flow."""

    def test_public_tos_display(self, driver, live_server_url):
        """Test that TOS can be viewed publicly without login."""
        # Create active TOS
        TermsOfServiceFactory(
            is_active=True,
            version="1.0.0",
            content="Test TOS Content Lorem Ipsum",
        )

        # Navigate to TOS display page
        tos_page = TOSDisplayPage(driver, live_server_url)
        tos_page.navigate_to_tos()

        # Verify content is displayed
        assert "Test TOS Content" in tos_page.get_tos_content()
        assert "1.0.0" in tos_page.get_version()

    def test_tos_accept_requires_login(self, driver, live_server_url):
        """Test that TOS acceptance page requires login."""
        # Create active TOS
        TermsOfServiceFactory(is_active=True)

        # Try to access TOS accept page
        driver.get(f"{live_server_url}/legal/tos/accept/")

        # Should redirect to login page
        assert "/accounts/login/" in driver.current_url

    @pytest.mark.xfail(
        reason="TOS middleware transaction isolation: middleware in live_server thread "
        "cannot see TOS data created in test thread (SQLite file-based limitation). "
        "Pre-existing failure since commit 922df1e. Requires architectural fix: "
        "either use PostgreSQL for browser tests or create data via Django admin UI."
    )
    def test_new_user_redirected_to_tos(
        self, driver, live_server_url, active_tos, test_user
    ):
        """Test that new user is redirected to TOS after login."""
        # Login with user created by fixture
        login_page = LoginPage(driver, live_server_url)
        login_page.go_to_login_page()
        login_page.login(test_user.username, TEST_PASSWORD)

        # Should be redirected to TOS acceptance page
        assert "/legal/tos/accept/" in driver.current_url

    @pytest.mark.xfail(
        reason="TOS middleware transaction isolation: middleware in live_server thread "
        "cannot see TOS data created in test thread (SQLite file-based limitation). "
        "Pre-existing failure since commit 922df1e. Requires architectural fix: "
        "either use PostgreSQL for browser tests or create data via Django admin UI."
    )
    def test_user_can_accept_tos(self, driver, live_server_url, django_user_model):
        """Test that user can accept TOS."""
        # Create active TOS
        tos = TermsOfServiceFactory(
            is_active=True,
            version="1.0.0",
            content="Test TOS Content",
        )

        # Create and login user
        test_password = TEST_PASSWORD
        user = UserFactory()
        user.set_password(test_password)
        user.save()

        login_page = LoginPage(driver, live_server_url)
        login_page.go_to_login_page()
        login_page.login(user.username, test_password)

        # Should be on TOS accept page
        assert "/legal/tos/accept/" in driver.current_url

        # Accept TOS
        tos_page = TOSAcceptPage(driver, live_server_url)
        assert "Test TOS Content" in tos_page.get_tos_content()
        assert "1.0.0" in driver.page_source

        tos_page.accept_tos()

        # Should be redirected away from TOS page
        assert "/legal/tos/accept/" not in driver.current_url

        # Verify acceptance was recorded
        assert TermsOfServiceAcceptance.objects.filter(
            user=user,
            tos_version=tos,
        ).exists()

    def test_user_with_acceptance_not_blocked(
        self, driver, live_server_url, django_user_model
    ):
        """Test that user who has accepted TOS can access site."""
        # Create active TOS
        tos = TermsOfServiceFactory(is_active=True)

        # Create user and acceptance
        test_password = TEST_PASSWORD
        user = UserFactory()
        user.set_password(test_password)
        user.save()

        TermsOfServiceAcceptance.objects.create(
            user=user,
            tos_version=tos,
            ip_address="127.0.0.1",
        )

        # Login
        login_page = LoginPage(driver, live_server_url)
        login_page.go_to_login_page()
        login_page.login(user.username, test_password)

        # Should NOT be redirected to TOS accept page
        assert "/legal/tos/accept/" not in driver.current_url

        # Try to navigate to other pages - should work
        driver.get(f"{live_server_url}/about/")
        assert "/legal/tos/accept/" not in driver.current_url

    @pytest.mark.xfail(
        reason="TOS middleware transaction isolation: middleware in live_server thread "
        "cannot see TOS data created in test thread (SQLite file-based limitation). "
        "Pre-existing failure since commit 922df1e. Requires architectural fix: "
        "either use PostgreSQL for browser tests or create data via Django admin UI."
    )
    def test_cannot_submit_without_checkbox(
        self, driver, live_server_url, django_user_model
    ):
        """Test that TOS cannot be accepted without checking the box."""
        # Create active TOS
        TermsOfServiceFactory(is_active=True)

        # Create and login user
        test_password = TEST_PASSWORD
        user = UserFactory()
        user.set_password(test_password)
        user.save()

        login_page = LoginPage(driver, live_server_url)
        login_page.go_to_login_page()
        login_page.login(user.username, test_password)

        # On TOS accept page
        tos_page = TOSAcceptPage(driver, live_server_url)

        # Try to submit without checking checkbox
        tos_page.click_accept_button()

        # HTML5 validation should prevent submission
        # User should still be on TOS page
        assert "/legal/tos/accept/" in driver.current_url

        # Verify acceptance was NOT created
        assert not TermsOfServiceAcceptance.objects.filter(user=user).exists()

    @pytest.mark.xfail(
        reason="TOS middleware transaction isolation: middleware in live_server thread "
        "cannot see TOS data created in test thread (SQLite file-based limitation). "
        "Pre-existing failure since commit 922df1e. Requires architectural fix: "
        "either use PostgreSQL for browser tests or create data via Django admin UI."
    )
    def test_tos_blocks_all_site_access(
        self, driver, live_server_url, django_user_model
    ):
        """Test that TOS blocks access to all non-exempt pages."""
        # Create active TOS
        TermsOfServiceFactory(is_active=True)

        # Create and login user
        test_password = TEST_PASSWORD
        user = UserFactory()
        user.set_password(test_password)
        user.save()

        login_page = LoginPage(driver, live_server_url)
        login_page.go_to_login_page()
        login_page.login(user.username, test_password)

        # Should be on TOS page
        assert "/legal/tos/accept/" in driver.current_url

        # Try to navigate to other pages
        driver.get(f"{live_server_url}/about/")

        # Should be redirected back to TOS page
        assert "/legal/tos/accept/" in driver.current_url

    @pytest.mark.xfail(
        reason="TOS middleware transaction isolation: middleware in live_server thread "
        "cannot see TOS data created in test thread (SQLite file-based limitation). "
        "Pre-existing failure since commit 922df1e. Requires architectural fix: "
        "either use PostgreSQL for browser tests or create data via Django admin UI."
    )
    def test_redirect_after_acceptance(
        self, driver, live_server_url, django_user_model
    ):
        """Test that user is redirected to original page after accepting TOS."""
        # Create active TOS
        TermsOfServiceFactory(is_active=True)

        # Create and login user
        test_password = TEST_PASSWORD
        user = UserFactory()
        user.set_password(test_password)
        user.save()

        login_page = LoginPage(driver, live_server_url)
        login_page.go_to_login_page()
        login_page.login(user.username, test_password)

        # User is redirected to TOS page
        # Now accept TOS
        tos_page = TOSAcceptPage(driver, live_server_url)
        tos_page.accept_tos()

        # Try to access a specific page
        driver.get(f"{live_server_url}/about/")

        # Should successfully reach the about page
        assert "/about/" in driver.current_url
        assert "/legal/tos/accept/" not in driver.current_url

    @pytest.mark.xfail(
        reason="TOS middleware transaction isolation: middleware in live_server thread "
        "cannot see TOS data created in test thread (SQLite file-based limitation). "
        "Pre-existing failure since commit 922df1e. Requires architectural fix: "
        "either use PostgreSQL for browser tests or create data via Django admin UI."
    )
    def test_tos_version_displayed_on_accept_page(
        self, driver, live_server_url, django_user_model
    ):
        """Test that TOS version is clearly displayed on accept page."""
        # Create active TOS with specific version
        TermsOfServiceFactory(
            is_active=True,
            version="2.5.3",
            content="Updated terms and conditions",
        )

        # Create and login user
        test_password = TEST_PASSWORD
        user = UserFactory()
        user.set_password(test_password)
        user.save()

        login_page = LoginPage(driver, live_server_url)
        login_page.go_to_login_page()
        login_page.login(user.username, test_password)

        # On TOS accept page
        assert "/legal/tos/accept/" in driver.current_url

        # Version should be displayed multiple times
        page_source = driver.page_source
        assert "2.5.3" in page_source
        assert page_source.count("2.5.3") >= MIN_VERSION_DISPLAY_COUNT
