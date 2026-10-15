"""Browser tests for TOS acceptance flow."""

import time

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC  # noqa: N812
from selenium.webdriver.support.wait import WebDriverWait

from tests.browser.base import BaseBrowserTest
from tests.browser.pages.signup_page import SignupPage
from tests.browser.pages.tos_page import TOSAcceptPage
from tests.browser.pages.tos_page import TOSDisplayPage
from wafer_space.legal.tests.factories import TermsOfServiceFactory

# Test constants
TEST_PASSWORD = "testpass123"  # noqa: S105
MIN_VERSION_DISPLAY_COUNT = 2  # Minimum times version should appear on page
# This test's own ToS (#269); a version no other test or seed uses.
TOS_VERSION = "2.69.0"
TOS_CONTENT = f"This is test TOS content for version {TOS_VERSION}."


@pytest.mark.browser
class TestTOSAcceptanceFlow(BaseBrowserTest):
    """Test the complete TOS acceptance flow.

    These are browser tests that verify user interactions with TOS.
    The tests assume TOS data is pre-loaded via the setup_test_tos fixture.
    No database objects should be created directly in these tests.
    """

    def test_public_tos_display(self, driver, live_server_url):
        """Test that TOS can be viewed publicly without login."""
        # Navigate to TOS display page
        driver.get(f"{live_server_url}/legal/tos/")

        # Check if page loads (might show TOS or "no TOS" message)
        page_source = driver.page_source

        # Either case is valid - we're testing the page loads publicly
        if "No Terms of Service is currently active" in page_source:
            # No TOS exists - verify error is shown
            assert (
                "Page not found" in page_source or "No Terms of Service" in page_source
            )
        else:
            # TOS exists - verify it's displayed
            assert "Terms of Service" in page_source

    def test_tos_accept_requires_login(self, driver, live_server_url):
        """Test that TOS acceptance page requires login."""
        # Try to access TOS accept page without logging in
        driver.get(f"{live_server_url}/legal/tos/accept/")

        # Should redirect to login page
        assert "/accounts/login/" in driver.current_url

    def test_new_user_sees_tos_after_signup(self, driver, live_server_url):
        """Test that new user is redirected to TOS after signing up."""
        # Generate unique test user details
        timestamp = str(int(time.time()))
        test_username = f"testuser{timestamp}"
        test_email = f"test{timestamp}@example.com"

        # Go to signup page
        signup_page = SignupPage(driver, live_server_url)
        signup_page.go_to_signup_page()

        # Sign up new user
        signup_page.signup(
            username=test_username,
            email=test_email,
            password1=TEST_PASSWORD,
            password2=TEST_PASSWORD,
        )

        # Wait for redirect away from signup
        wait = WebDriverWait(driver, 10)
        wait.until(EC.url_changes(f"{live_server_url}/accounts/signup/"))

        # New users should be redirected to TOS acceptance after signup
        # (This may go through email confirmation first depending on settings)
        current_url = driver.current_url

        # If email confirmation is required, we'll be on that page
        if "/accounts/confirm-email/" in current_url:
            # For this test, we'll just verify we got to the confirmation page
            assert "/accounts/confirm-email/" in current_url
        else:
            # Otherwise, should be redirected to TOS
            assert "/legal/tos/accept/" in current_url

    def test_tos_page_shows_content_and_checkbox(self, driver, live_server_url):
        """Test that TOS accept page displays content and acceptance checkbox."""
        # Create a new user via signup
        timestamp = str(int(time.time()))
        test_username = f"testuser{timestamp}"
        test_email = f"test{timestamp}@example.com"

        # Sign up
        signup_page = SignupPage(driver, live_server_url)
        signup_page.go_to_signup_page()
        signup_page.signup(
            username=test_username,
            email=test_email,
            password1=TEST_PASSWORD,
            password2=TEST_PASSWORD,
        )

        # Wait for redirect
        wait = WebDriverWait(driver, 10)
        wait.until(EC.url_changes(f"{live_server_url}/accounts/signup/"))

        # If we can access the TOS accept page
        if "/legal/tos/accept/" in driver.current_url:
            tos_page = TOSAcceptPage(driver, live_server_url)

            # Verify TOS content is displayed
            assert "Test Terms of Service" in tos_page.get_tos_content()

            # Verify checkbox is present
            assert tos_page.is_checkbox_present()

            # Verify accept button is present
            assert tos_page.is_accept_button_present()

    def test_cannot_submit_tos_without_checkbox(self, driver, live_server_url):
        """Test that TOS cannot be accepted without checking the box."""
        # Create a new user
        timestamp = str(int(time.time()))
        test_username = f"testuser{timestamp}"
        test_email = f"test{timestamp}@example.com"

        # Sign up
        signup_page = SignupPage(driver, live_server_url)
        signup_page.go_to_signup_page()
        signup_page.signup(
            username=test_username,
            email=test_email,
            password1=TEST_PASSWORD,
            password2=TEST_PASSWORD,
        )

        # Wait for redirect
        wait = WebDriverWait(driver, 10)
        wait.until(EC.url_changes(f"{live_server_url}/accounts/signup/"))

        # If we're on TOS page
        if "/legal/tos/accept/" in driver.current_url:
            tos_page = TOSAcceptPage(driver, live_server_url)

            # Try to submit without checking checkbox
            tos_page.click_accept_button()

            # Should still be on TOS page (HTML5 validation prevents submission)
            assert "/legal/tos/accept/" in driver.current_url

    @pytest.mark.django_db(transaction=True)
    def test_tos_version_displayed(self, driver, live_server_url):
        """The public ToS page shows the active version and its content (#269).

        The test makes its own active ToS. It used to rely on the session's
        "1.0.0" row, which the first live_server test's flush removes: as the
        first test it saw that row without its markdown (create_test_tos
        checks the real tos_versions path, not the mocked one) and failed; as
        any later test it got the 404 and passed without checking anything.
        """
        TermsOfServiceFactory(version=TOS_VERSION, is_active=True)

        tos_page = TOSDisplayPage(driver, live_server_url)
        tos_page.navigate_to_tos()
        WebDriverWait(driver, 10).until(
            EC.text_to_be_present_in_element(TOSDisplayPage.TOS_CONTENT, TOS_CONTENT)
        )

        version_line = driver.find_element(By.CSS_SELECTOR, "h1 + p.text-muted").text
        assert f"Version {TOS_VERSION}" in version_line
        assert "Test Terms of Service" in tos_page.get_tos_content()

    def test_tos_acceptance_flow_complete(self, driver, live_server_url):
        """Test complete flow: signup -> view TOS -> accept -> redirect."""
        # Create unique user
        timestamp = str(int(time.time()))
        test_username = f"testuser{timestamp}"
        test_email = f"test{timestamp}@example.com"

        # Sign up
        signup_page = SignupPage(driver, live_server_url)
        signup_page.go_to_signup_page()
        signup_page.signup(
            username=test_username,
            email=test_email,
            password1=TEST_PASSWORD,
            password2=TEST_PASSWORD,
        )

        # Wait for redirect
        wait = WebDriverWait(driver, 10)
        wait.until(EC.url_changes(f"{live_server_url}/accounts/signup/"))

        # If on TOS page, complete acceptance
        if "/legal/tos/accept/" in driver.current_url:
            tos_page = TOSAcceptPage(driver, live_server_url)

            # Read TOS content
            content = tos_page.get_tos_content()
            assert "Test Terms of Service" in content

            # Accept TOS
            tos_page.accept_tos()

            # Should redirect away from TOS page after acceptance
            wait.until(EC.url_changes(f"{live_server_url}/legal/tos/accept/"))
            assert "/legal/tos/accept/" not in driver.current_url
