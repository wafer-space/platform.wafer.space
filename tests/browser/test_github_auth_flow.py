"""Browser tests for GitHub and Google OAuth authentication flows."""

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

from tests.browser.base import BaseBrowserTest


@pytest.mark.django_db
class TestGitHubAuthenticationFlow(BaseBrowserTest):
    """Test GitHub authentication flow using browser automation."""

    @pytest.fixture(autouse=True)
    def setup(self, live_server):
        """Set up test fixtures."""
        self.live_server_url = live_server.url

    def test_login_page_displays_github_button(self, driver):
        """Test that login page shows GitHub authentication button."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Check for GitHub button
        github_buttons = driver.find_elements(
            By.XPATH,
            "//a[contains(text(), 'Sign in with GitHub')]",
        )
        assert len(github_buttons) > 0, "GitHub sign-in button not found"

        # Verify button has correct class
        github_button = github_buttons[0]
        assert "btn" in github_button.get_attribute("class")

        # Verify GitHub icon is present
        github_icons = driver.find_elements(By.CLASS_NAME, "bi-github")
        assert len(github_icons) > 0, "GitHub icon not found"

    def test_signup_page_displays_github_button(self, driver):
        """Test that signup page shows GitHub authentication button."""
        # Navigate to signup page
        driver.get(f"{self.live_server_url}/accounts/signup/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Check for GitHub button
        github_buttons = driver.find_elements(
            By.XPATH,
            "//a[contains(text(), 'Sign up with GitHub')]",
        )
        assert len(github_buttons) > 0, "GitHub sign-up button not found"

    def test_github_button_redirects_to_oauth(self, driver):
        """Test that clicking GitHub button initiates OAuth flow."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Find and get GitHub button href
        github_button = driver.find_element(
            By.XPATH,
            "//a[contains(text(), 'Sign in with GitHub')]",
        )
        href = github_button.get_attribute("href")

        # Verify href points to GitHub OAuth endpoint
        assert "/accounts/github/login/" in href or "github" in href

        # Note: We don't actually click the button to avoid real OAuth redirect
        # In a real test with mocked OAuth, we would click and verify the redirect

    def test_all_social_providers_displayed(self, driver):
        """Test that all configured social providers are shown."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Check for all provider buttons
        providers = ["GitHub", "Google", "GitLab", "LinkedIn"]
        for provider in providers:
            buttons = driver.find_elements(
                By.XPATH,
                f"//a[contains(text(), 'Sign in with {provider}')]",
            )
            assert len(buttons) > 0, f"{provider} sign-in button not found"

    def test_social_login_section_styling(self, driver):
        """Test that social login section is properly styled."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Check for social providers section
        social_sections = driver.find_elements(By.CLASS_NAME, "socialaccount_providers")
        assert len(social_sections) > 0, "Social providers section not found"

        # Check for OR divider
        dividers = driver.find_elements(By.XPATH, "//div[contains(text(), 'OR')]")
        assert len(dividers) > 0, "OR divider not found between social and email login"

    def test_login_form_below_social_buttons(self, driver):
        """Test that traditional login form appears below social buttons."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Check for login form
        login_form = driver.find_element(By.CSS_SELECTOR, "form.login")
        assert login_form is not None, "Login form not found"

        # Check for username/email field
        login_field = driver.find_element(By.NAME, "login")
        assert login_field is not None, "Login field not found"

        # Check for password field
        password_field = driver.find_element(By.NAME, "password")
        assert password_field is not None, "Password field not found"

        # Check for submit button
        submit_buttons = driver.find_elements(
            By.XPATH,
            "//button[@type='submit' and contains(text(), 'Sign In')]",
        )
        assert len(submit_buttons) > 0, "Submit button not found"

    def test_responsive_social_buttons(self, driver):
        """Test that social buttons are responsive on mobile viewport."""
        # Set mobile viewport
        driver.set_window_size(375, 667)  # iPhone SE size

        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Check that GitHub button is still visible and clickable
        github_button = driver.find_element(
            By.XPATH,
            "//a[contains(text(), 'Sign in with GitHub')]",
        )
        assert github_button.is_displayed(), "GitHub button not visible on mobile"

        # Verify button takes full width (Bootstrap's d-grid)
        parent_div = github_button.find_element(By.XPATH, "./..")
        # Check if button uses Bootstrap grid or is wide enough
        min_mobile_button_width = 300
        assert (
            "d-grid" in parent_div.get_attribute("class")
            or github_button.size["width"] > min_mobile_button_width
        ), "Button not full width on mobile"

    def test_login_page_has_signup_link(self, driver):
        """Test that login page has link to signup page."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Check for signup link
        signup_links = driver.find_elements(
            By.XPATH,
            "//a[contains(text(), 'Sign up')]",
        )
        assert len(signup_links) > 0, "Sign up link not found on login page"

        # Verify link points to signup page
        signup_link = signup_links[0]
        href = signup_link.get_attribute("href")
        assert "/accounts/signup/" in href, "Sign up link has incorrect href"


@pytest.mark.django_db
class TestGoogleAuthenticationFlow(BaseBrowserTest):
    """Test Google authentication flow using browser automation."""

    @pytest.fixture(autouse=True)
    def setup(self, live_server):
        """Set up test fixtures."""
        self.live_server_url = live_server.url

    def test_login_page_displays_google_button(self, driver):
        """Test that login page shows Google authentication button."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Check for Google button
        google_buttons = driver.find_elements(
            By.XPATH,
            "//a[contains(text(), 'Sign in with Google')]",
        )
        assert len(google_buttons) > 0, "Google sign-in button not found"

        # Verify button has correct class
        google_button = google_buttons[0]
        assert "btn" in google_button.get_attribute("class")

        # Verify Google icon is present
        google_icons = driver.find_elements(By.CLASS_NAME, "bi-google")
        assert len(google_icons) > 0, "Google icon not found"

    def test_signup_page_displays_google_button(self, driver):
        """Test that signup page shows Google authentication button."""
        # Navigate to signup page
        driver.get(f"{self.live_server_url}/accounts/signup/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Check for Google button
        google_buttons = driver.find_elements(
            By.XPATH,
            "//a[contains(text(), 'Sign up with Google')]",
        )
        assert len(google_buttons) > 0, "Google sign-up button not found"

    def test_google_button_href_points_to_google_oauth(self, driver):
        """Test that Google button has correct href."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Find Google button and get href
        google_button = driver.find_element(
            By.XPATH,
            "//a[contains(text(), 'Sign in with Google')]",
        )
        href = google_button.get_attribute("href")

        # Verify href points to Google OAuth endpoint
        assert "/accounts/google/login/" in href or "google" in href

        # Note: We don't actually click the button to avoid real OAuth redirect

    def test_google_vs_github_buttons_both_present(self, driver):
        """Test that both Google and GitHub buttons are present."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Check for both provider buttons
        github_buttons = driver.find_elements(
            By.XPATH,
            "//a[contains(text(), 'Sign in with GitHub')]",
        )
        google_buttons = driver.find_elements(
            By.XPATH,
            "//a[contains(text(), 'Sign in with Google')]",
        )

        assert len(github_buttons) > 0, "GitHub button not found"
        assert len(google_buttons) > 0, "Google button not found"

    def test_google_button_styling_consistency(self, driver):
        """Test that Google button has consistent styling with other providers."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Get all social provider buttons
        social_buttons = driver.find_elements(
            By.XPATH,
            "//a[contains(@class, 'btn') and contains(text(), 'Sign in with')]",
        )

        # Should have at least GitHub and Google buttons
        expected_min_buttons = 2
        assert len(social_buttons) >= expected_min_buttons, (
            "Should have at least GitHub and Google buttons"
        )

        # Check that all buttons have consistent classes
        button_classes = [btn.get_attribute("class") for btn in social_buttons]

        # All should be bootstrap buttons
        for classes in button_classes:
            assert "btn" in classes, "All social buttons should have 'btn' class"
            assert "btn-outline-secondary" in classes, (
                "All should have same button style"
            )

    def test_google_button_mobile_responsive(self, driver):
        """Test that Google button is responsive on mobile viewport."""
        # Set mobile viewport
        driver.set_window_size(375, 667)  # iPhone SE size

        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Check that Google button is still visible and clickable
        google_button = driver.find_element(
            By.XPATH,
            "//a[contains(text(), 'Sign in with Google')]",
        )
        assert google_button.is_displayed(), "Google button not visible on mobile"

        # Verify button takes appropriate width on mobile
        min_mobile_width = 200
        assert google_button.size["width"] > min_mobile_width, (
            "Button should be wide enough on mobile"
        )
