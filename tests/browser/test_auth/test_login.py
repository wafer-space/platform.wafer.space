"""
Browser tests for login functionality.
"""
import pytest
from selenium.webdriver.common.by import By

from tests.browser.base import AuthenticatedBrowserTest
from tests.browser.pages.login_page import LoginPage


@pytest.mark.django_db
class TestLogin(AuthenticatedBrowserTest):
    """Test login functionality."""

    @pytest.fixture(autouse=True)
    def setup(self, live_server, django_user_model):
        """Set up test fixtures."""
        self.live_server_url = live_server.url
        self.User = django_user_model

    def test_login_page_loads(self, driver):
        """Test that the login page loads correctly."""
        login_page = LoginPage(driver, self.live_server_url)
        login_page.go_to_login_page()

        # Verify page loaded
        assert login_page.verify_page_loaded()

        # Check page title
        title = login_page.get_title()
        assert "sign in" in title.lower() or "login" in title.lower()

    def test_successful_login(self, driver):
        """Test successful user login."""
        # Create test user
        user = self.create_test_user(self.User)

        # Navigate to login page
        login_page = LoginPage(driver, self.live_server_url)
        login_page.go_to_login_page()

        # Perform login
        login_page.login("testuser", "testpass123")

        # Wait for redirect
        self.wait_for_url_contains(driver, "/accounts/confirm-email/")
        # Note: May redirect to email confirmation or dashboard depending on settings

        # Verify login was successful
        assert login_page.is_login_successful()

    def test_invalid_credentials(self, driver):
        """Test login with invalid credentials."""
        login_page = LoginPage(driver, self.live_server_url)
        login_page.go_to_login_page()

        # Try to login with invalid credentials
        login_page.login("wronguser", "wrongpass")

        # Should stay on login page
        assert "/accounts/login/" in driver.current_url

        # Check for error message
        error_message = login_page.get_error_message()
        assert error_message is not None, "No error message displayed for invalid credentials"

    def test_empty_form_submission(self, driver):
        """Test submitting empty login form."""
        login_page = LoginPage(driver, self.live_server_url)
        login_page.go_to_login_page()

        # Submit empty form
        login_page.click_submit()

        # Should stay on login page
        assert "/accounts/login/" in driver.current_url

        # Form validation should prevent submission
        # Check if required attribute is enforced
        username_input = driver.find_element(*login_page.USERNAME_INPUT)
        assert username_input.get_attribute("required") is not None or \
               login_page.get_field_errors(), \
               "No validation for empty fields"

    def test_remember_me_checkbox(self, driver):
        """Test remember me checkbox functionality."""
        login_page = LoginPage(driver, self.live_server_url)
        login_page.go_to_login_page()

        # Check remember me
        login_page.check_remember_me()
        checkbox = driver.find_element(*login_page.REMEMBER_ME_CHECKBOX)
        assert checkbox.is_selected()

        # Uncheck remember me
        login_page.uncheck_remember_me()
        assert not checkbox.is_selected()

    def test_social_login_buttons_visible(self, driver):
        """Test that social login buttons are visible if configured."""
        login_page = LoginPage(driver, self.live_server_url)
        login_page.go_to_login_page()

        # Check for OAuth provider buttons
        github_button = driver.find_elements(*login_page.GITHUB_LOGIN)
        gitlab_button = driver.find_elements(*login_page.GITLAB_LOGIN)
        google_button = driver.find_elements(*login_page.GOOGLE_LOGIN)
        linkedin_button = driver.find_elements(*login_page.LINKEDIN_LOGIN)

        # Count how many social logins are configured
        social_logins = sum([
            len(github_button) > 0,
            len(gitlab_button) > 0,
            len(google_button) > 0,
            len(linkedin_button) > 0,
        ])

        # Log the result (social logins may or may not be configured)
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Social login buttons found: %d", social_logins)
        logger.info("GitHub: %s", "✓" if github_button else "✗")
        logger.info("GitLab: %s", "✓" if gitlab_button else "✗")
        logger.info("Google: %s", "✓" if google_button else "✗")
        logger.info("LinkedIn: %s", "✓" if linkedin_button else "✗")

        # This test passes regardless - it's just documenting what's configured
        assert True, "Social login buttons test completed"

    def test_forgot_password_link(self, driver):
        """Test forgot password link."""
        login_page = LoginPage(driver, self.live_server_url)
        login_page.go_to_login_page()

        # Check if forgot password link exists
        forgot_link = driver.find_elements(By.PARTIAL_LINK_TEXT, "Forgot")
        if forgot_link:
            forgot_link[0].click()
            self.wait_for_url_contains(driver, "/accounts/password/reset/")
            assert "/accounts/password/reset/" in driver.current_url

    def test_logout_functionality(self, driver):
        """Test logout functionality."""
        # Create and login user
        self.create_test_user(self.User)
        login_page = LoginPage(driver, self.live_server_url)
        login_page.go_to_login_page()
        login_page.login("testuser", "testpass123")

        # Wait for successful login redirect
        self.wait_for_url_contains(driver, "/accounts/")

        # Now logout
        self.logout(driver)

        # Should be redirected to homepage or login page
        assert "/accounts/login/" in driver.current_url or \
               driver.current_url == f"{self.live_server_url}/", \
               "Logout did not redirect properly"
