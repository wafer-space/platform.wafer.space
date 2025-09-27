"""Browser tests for GitHub and Google OAuth authentication flows."""

import pytest
from allauth.socialaccount.models import SocialApp
from django.contrib.sites.models import Site
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

from tests.browser.base import BaseBrowserTest


@pytest.fixture
def social_apps():
    """Create SocialApp objects for all OAuth providers so buttons appear in UI."""
    # Clean up any existing apps to avoid conflicts
    SocialApp.objects.all().delete()

    # Get the current site
    site = Site.objects.get_current()

    # Create test SocialApp objects for all providers
    github_app = SocialApp.objects.create(
        provider="github",
        name="GitHub Test App",
        client_id="test_github_client_id",
        secret="github_test_secret",  # noqa: S106
    )
    github_app.sites.add(site)

    google_app = SocialApp.objects.create(
        provider="google",
        name="Google Test App",
        client_id="test_google_client_id.apps.googleusercontent.com",
        secret="google_test_secret",  # noqa: S106
    )
    google_app.sites.add(site)

    gitlab_app = SocialApp.objects.create(
        provider="gitlab",
        name="GitLab Test App",
        client_id="test_gitlab_application_id",
        secret="gitlab_test_secret",  # noqa: S106
    )
    gitlab_app.sites.add(site)

    linkedin_app = SocialApp.objects.create(
        provider="linkedin_oauth2",
        name="LinkedIn Test App",
        client_id="test_linkedin_client_id",
        secret="linkedin_test_secret",  # noqa: S106
    )
    linkedin_app.sites.add(site)

    return {
        "github": github_app,
        "google": google_app,
        "gitlab": gitlab_app,
        "linkedin": linkedin_app,
    }


@pytest.mark.django_db
class TestGitHubAuthenticationFlow(BaseBrowserTest):
    """Test GitHub authentication flow using browser automation."""

    @pytest.fixture(autouse=True)
    def setup(self, live_server):
        """Set up test fixtures and create SocialApp objects for OAuth buttons to appear."""
        self.live_server_url = live_server.url

        # Clean up any existing apps to avoid conflicts
        SocialApp.objects.all().delete()

        # Get the current site
        site = Site.objects.get_current()

        # Create test SocialApp objects for all providers so buttons appear in UI
        self.github_app = SocialApp.objects.create(
            provider="github",
            name="GitHub Test App",
            client_id="test_github_client_id",
            secret="github_test_secret",  # noqa: S106
        )
        self.github_app.sites.add(site)

        self.google_app = SocialApp.objects.create(
            provider="google",
            name="Google Test App",
            client_id="test_google_client_id.apps.googleusercontent.com",
            secret="google_test_secret",  # noqa: S106
        )
        self.google_app.sites.add(site)

        self.gitlab_app = SocialApp.objects.create(
            provider="gitlab",
            name="GitLab Test App",
            client_id="test_gitlab_application_id",
            secret="gitlab_test_secret",  # noqa: S106
        )
        self.gitlab_app.sites.add(site)

        self.linkedin_app = SocialApp.objects.create(
            provider="linkedin_oauth2",
            name="LinkedIn Test App",
            client_id="test_linkedin_client_id",
            secret="linkedin_test_secret",  # noqa: S106
        )
        self.linkedin_app.sites.add(site)

    def test_login_page_displays_github_button(self, driver):
        """Test that login page shows GitHub authentication button."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
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
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
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
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
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
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
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
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
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
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
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
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
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
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
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
        """Set up test fixtures and create SocialApp objects for OAuth buttons to appear."""
        self.live_server_url = live_server.url

        # Clean up any existing apps to avoid conflicts
        SocialApp.objects.all().delete()

        # Get the current site
        site = Site.objects.get_current()

        # Create test SocialApp objects for all providers so buttons appear in UI
        self.github_app = SocialApp.objects.create(
            provider="github",
            name="GitHub Test App",
            client_id="test_github_client_id",
            secret="github_test_secret",  # noqa: S106
        )
        self.github_app.sites.add(site)

        self.google_app = SocialApp.objects.create(
            provider="google",
            name="Google Test App",
            client_id="test_google_client_id.apps.googleusercontent.com",
            secret="google_test_secret",  # noqa: S106
        )
        self.google_app.sites.add(site)

        self.gitlab_app = SocialApp.objects.create(
            provider="gitlab",
            name="GitLab Test App",
            client_id="test_gitlab_application_id",
            secret="gitlab_test_secret",  # noqa: S106
        )
        self.gitlab_app.sites.add(site)

        self.linkedin_app = SocialApp.objects.create(
            provider="linkedin_oauth2",
            name="LinkedIn Test App",
            client_id="test_linkedin_client_id",
            secret="linkedin_test_secret",  # noqa: S106
        )
        self.linkedin_app.sites.add(site)

    def test_login_page_displays_google_button(self, driver):
        """Test that login page shows Google authentication button."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
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
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
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
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
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
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
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
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
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
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
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


@pytest.mark.django_db
class TestGitLabAuthenticationFlow(BaseBrowserTest):
    """Test GitLab authentication flow using browser automation."""

    @pytest.fixture(autouse=True)
    def setup(self, live_server):
        """Set up test fixtures and create SocialApp objects for OAuth buttons to appear."""
        self.live_server_url = live_server.url

        # Clean up any existing apps to avoid conflicts
        SocialApp.objects.all().delete()

        # Get the current site
        site = Site.objects.get_current()

        # Create test SocialApp objects for all providers so buttons appear in UI
        self.github_app = SocialApp.objects.create(
            provider="github",
            name="GitHub Test App",
            client_id="test_github_client_id",
            secret="github_test_secret",  # noqa: S106
        )
        self.github_app.sites.add(site)

        self.google_app = SocialApp.objects.create(
            provider="google",
            name="Google Test App",
            client_id="test_google_client_id.apps.googleusercontent.com",
            secret="google_test_secret",  # noqa: S106
        )
        self.google_app.sites.add(site)

        self.gitlab_app = SocialApp.objects.create(
            provider="gitlab",
            name="GitLab Test App",
            client_id="test_gitlab_application_id",
            secret="gitlab_test_secret",  # noqa: S106
        )
        self.gitlab_app.sites.add(site)

        self.linkedin_app = SocialApp.objects.create(
            provider="linkedin_oauth2",
            name="LinkedIn Test App",
            client_id="test_linkedin_client_id",
            secret="linkedin_test_secret",  # noqa: S106
        )
        self.linkedin_app.sites.add(site)

    def test_login_page_displays_gitlab_button(self, driver):
        """Test that login page shows GitLab authentication button."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Check for GitLab button
        gitlab_buttons = driver.find_elements(
            By.XPATH,
            "//a[contains(text(), 'Sign in with GitLab')]",
        )
        assert len(gitlab_buttons) > 0, "GitLab sign-in button not found"

        # Verify button has correct class
        gitlab_button = gitlab_buttons[0]
        assert "btn" in gitlab_button.get_attribute("class")

        # Verify GitLab icon is present (using generic SVG since no specific bi-gitlab)
        xpath_selector = "//svg[contains(@viewBox, '0 0 16 16')]"
        gitlab_icons = driver.find_elements(By.XPATH, xpath_selector)
        assert len(gitlab_icons) > 0, "GitLab icon not found"

    def test_signup_page_displays_gitlab_button(self, driver):
        """Test that signup page shows GitLab authentication button."""
        # Navigate to signup page
        driver.get(f"{self.live_server_url}/accounts/signup/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Check for GitLab button
        gitlab_buttons = driver.find_elements(
            By.XPATH,
            "//a[contains(text(), 'Sign up with GitLab')]",
        )
        assert len(gitlab_buttons) > 0, "GitLab sign-up button not found"

    def test_gitlab_button_href_points_to_gitlab_oauth(self, driver):
        """Test that GitLab button has correct href."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Find GitLab button and get href
        gitlab_button = driver.find_element(
            By.XPATH,
            "//a[contains(text(), 'Sign in with GitLab')]",
        )
        href = gitlab_button.get_attribute("href")

        # Verify href points to GitLab OAuth endpoint
        assert "/accounts/gitlab/login/" in href or "gitlab" in href

        # Note: We don't actually click the button to avoid real OAuth redirect

    def test_gitlab_vs_other_providers_all_present(self, driver):
        """Test that GitLab, GitHub, and Google buttons are all present."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Check for all provider buttons
        github_buttons = driver.find_elements(
            By.XPATH,
            "//a[contains(text(), 'Sign in with GitHub')]",
        )
        google_buttons = driver.find_elements(
            By.XPATH,
            "//a[contains(text(), 'Sign in with Google')]",
        )
        gitlab_buttons = driver.find_elements(
            By.XPATH,
            "//a[contains(text(), 'Sign in with GitLab')]",
        )

        assert len(github_buttons) > 0, "GitHub button not found"
        assert len(google_buttons) > 0, "Google button not found"
        assert len(gitlab_buttons) > 0, "GitLab button not found"

    def test_gitlab_button_styling_consistency(self, driver):
        """Test that GitLab button has consistent styling with other providers."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Get all social provider buttons
        social_buttons = driver.find_elements(
            By.XPATH,
            "//a[contains(@class, 'btn') and contains(text(), 'Sign in with')]",
        )

        # Should have at least GitHub, Google, and GitLab buttons
        expected_min_buttons = 3
        assert len(social_buttons) >= expected_min_buttons, (
            "Should have at least GitHub, Google, and GitLab buttons"
        )

        # Check that all buttons have consistent classes
        button_classes = [btn.get_attribute("class") for btn in social_buttons]

        # All should be bootstrap buttons
        for classes in button_classes:
            assert "btn" in classes, "All social buttons should have 'btn' class"
            assert "btn-outline-secondary" in classes, (
                "All should have same button style"
            )

    def test_gitlab_button_mobile_responsive(self, driver):
        """Test that GitLab button is responsive on mobile viewport."""
        # Set mobile viewport
        driver.set_window_size(375, 667)  # iPhone SE size

        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Check that GitLab button is still visible and clickable
        gitlab_button = driver.find_element(
            By.XPATH,
            "//a[contains(text(), 'Sign in with GitLab')]",
        )
        assert gitlab_button.is_displayed(), "GitLab button not visible on mobile"

        # Verify button takes appropriate width on mobile
        min_mobile_width = 200
        assert gitlab_button.size["width"] > min_mobile_width, (
            "Button should be wide enough on mobile"
        )
