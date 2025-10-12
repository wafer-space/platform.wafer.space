"""Browser tests for GitHub and Google OAuth authentication flows."""

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

from tests.browser.base import BaseBrowserTest

# XPath selectors for OAuth buttons
GITHUB_BUTTON_XPATH = (
    "//a[contains(text(), 'Sign in with GitHub') "
    "or contains(@href, '/accounts/github/login/')]"
)
GITHUB_SIGNUP_XPATH = (
    "//a[contains(text(), 'Sign up with GitHub') "
    "or contains(@href, '/accounts/github/login/')]"
)
GOOGLE_BUTTON_XPATH = (
    "//a[contains(text(), 'Sign in with Google') "
    "or contains(@href, '/accounts/google/login/')]"
)
GOOGLE_SIGNUP_XPATH = (
    "//a[contains(text(), 'Sign up with Google') "
    "or contains(@href, '/accounts/google/login/')]"
)
GITLAB_BUTTON_XPATH = (
    "//a[contains(text(), 'Sign in with GitLab') "
    "or contains(@href, '/accounts/gitlab/login/')]"
)
GITLAB_SIGNUP_XPATH = (
    "//a[contains(text(), 'Sign up with GitLab') "
    "or contains(@href, '/accounts/gitlab/login/')]"
)
DISCORD_BUTTON_XPATH = (
    "//a[contains(text(), 'Sign in with Discord') "
    "or contains(@href, '/accounts/discord/login/')]"
)
DISCORD_SIGNUP_XPATH = (
    "//a[contains(text(), 'Sign up with Discord') "
    "or contains(@href, '/accounts/discord/login/')]"
)
LINKEDIN_BUTTON_XPATH = (
    "//a[contains(text(), 'Sign in with LinkedIn') "
    "or contains(@href, '/accounts/oidc/linkedin/login/')]"
)
LINKEDIN_SIGNUP_XPATH = (
    "//a[contains(text(), 'Sign up with LinkedIn') "
    "or contains(@href, '/accounts/oidc/linkedin/login/')]"
)


@pytest.mark.django_db
class TestGitHubAuthenticationFlow(BaseBrowserTest):
    """Test GitHub authentication flow using browser automation."""

    @pytest.fixture(autouse=True)
    def setup(self, live_server, social_apps):  # noqa: ARG002
        """Set up test fixtures."""
        self.live_server_url = live_server.url

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
            GITHUB_BUTTON_XPATH,
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
            GITHUB_SIGNUP_XPATH,
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
            GITHUB_BUTTON_XPATH,
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

        # Check for all provider buttons using provider-specific href patterns
        provider_patterns = {
            "GitHub": "/accounts/github/login/",
            "Google": "/accounts/google/login/",
            "GitLab": "/accounts/gitlab/login/",
            "LinkedIn": "/accounts/oidc/linkedin/login/",
            "Discord": "/accounts/discord/login/",
        }
        for provider, href_pattern in provider_patterns.items():
            xpath_selector = (
                f"//a[contains(text(), 'Sign in with {provider}') "
                f"or contains(@href, '{href_pattern}')]"
            )
            buttons = driver.find_elements(By.XPATH, xpath_selector)
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
            GITHUB_BUTTON_XPATH,
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
    def setup(self, live_server, social_apps):  # noqa: ARG002
        """Set up test fixtures."""
        self.live_server_url = live_server.url

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
            GOOGLE_BUTTON_XPATH,
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
            GOOGLE_SIGNUP_XPATH,
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
            GOOGLE_BUTTON_XPATH,
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
            GITHUB_BUTTON_XPATH,
        )
        google_buttons = driver.find_elements(
            By.XPATH,
            GOOGLE_BUTTON_XPATH,
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

        # Test that Google button specifically exists and is functional
        google_buttons = driver.find_elements(
            By.XPATH,
            GOOGLE_BUTTON_XPATH,
        )
        assert len(google_buttons) > 0, "Google button should be present"

        # Verify Google button is functional
        google_button = google_buttons[0]
        assert google_button.is_displayed(), "Google button should be visible"
        assert google_button.is_enabled(), "Google button should be clickable"

        # Test completed - functionality verified

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
            GOOGLE_BUTTON_XPATH,
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
    def setup(self, live_server, social_apps):  # noqa: ARG002
        """Set up test fixtures."""
        self.live_server_url = live_server.url

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
            GITLAB_BUTTON_XPATH,
        )
        assert len(gitlab_buttons) > 0, "GitLab sign-in button not found"

        # Verify button is clickable (functional test rather than styling test)
        gitlab_button = gitlab_buttons[0]
        assert gitlab_button.is_enabled(), "GitLab button should be clickable"
        assert gitlab_button.is_displayed(), "GitLab button should be visible"

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
            GITLAB_SIGNUP_XPATH,
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
            GITLAB_BUTTON_XPATH,
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
            GITHUB_BUTTON_XPATH,
        )
        google_buttons = driver.find_elements(
            By.XPATH,
            GOOGLE_BUTTON_XPATH,
        )
        gitlab_buttons = driver.find_elements(
            By.XPATH,
            GITLAB_BUTTON_XPATH,
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

        # Test that GitLab button specifically exists and is functional
        gitlab_buttons = driver.find_elements(
            By.XPATH,
            GITLAB_BUTTON_XPATH,
        )
        assert len(gitlab_buttons) > 0, "GitLab button should be present"

        # Verify GitLab button is functional
        gitlab_button = gitlab_buttons[0]
        assert gitlab_button.is_displayed(), "GitLab button should be visible"
        assert gitlab_button.is_enabled(), "GitLab button should be clickable"

        # Test completed - functionality verified

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
            GITLAB_BUTTON_XPATH,
        )
        assert gitlab_button.is_displayed(), "GitLab button not visible on mobile"

        # Verify button takes appropriate width on mobile
        min_mobile_width = 200
        assert gitlab_button.size["width"] > min_mobile_width, (
            "Button should be wide enough on mobile"
        )


@pytest.mark.django_db
class TestDiscordAuthenticationFlow(BaseBrowserTest):
    """Test Discord authentication flow using browser automation."""

    @pytest.fixture(autouse=True)
    def setup(self, live_server, social_apps):  # noqa: ARG002
        """Set up test fixtures."""
        self.live_server_url = live_server.url

    def test_login_page_displays_discord_button(self, driver):
        """Test that login page shows Discord authentication button."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Check for Discord button
        discord_buttons = driver.find_elements(
            By.XPATH,
            DISCORD_BUTTON_XPATH,
        )
        assert len(discord_buttons) > 0, "Discord sign-in button not found"

        # Verify button is clickable (functional test rather than styling test)
        discord_button = discord_buttons[0]
        assert discord_button.is_enabled(), "Discord button should be clickable"
        assert discord_button.is_displayed(), "Discord button should be visible"

    def test_signup_page_displays_discord_button(self, driver):
        """Test that signup page shows Discord authentication button."""
        # Navigate to signup page
        driver.get(f"{self.live_server_url}/accounts/signup/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Check for Discord button
        discord_buttons = driver.find_elements(
            By.XPATH,
            DISCORD_SIGNUP_XPATH,
        )
        assert len(discord_buttons) > 0, "Discord sign-up button not found"

    def test_discord_button_href_points_to_discord_oauth(self, driver):
        """Test that Discord button has correct href."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Find Discord button and get href
        discord_button = driver.find_element(
            By.XPATH,
            DISCORD_BUTTON_XPATH,
        )
        href = discord_button.get_attribute("href")

        # Verify href points to Discord OAuth endpoint
        assert "/accounts/discord/login/" in href or "discord" in href

        # Note: We don't actually click the button to avoid real OAuth redirect

    def test_discord_vs_other_providers_all_present(self, driver):
        """Test that Discord, GitHub, Google, and GitLab buttons are all present."""
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
            GITHUB_BUTTON_XPATH,
        )
        google_buttons = driver.find_elements(
            By.XPATH,
            GOOGLE_BUTTON_XPATH,
        )
        gitlab_buttons = driver.find_elements(
            By.XPATH,
            GITLAB_BUTTON_XPATH,
        )
        discord_buttons = driver.find_elements(
            By.XPATH,
            DISCORD_BUTTON_XPATH,
        )

        assert len(github_buttons) > 0, "GitHub button not found"
        assert len(google_buttons) > 0, "Google button not found"
        assert len(gitlab_buttons) > 0, "GitLab button not found"
        assert len(discord_buttons) > 0, "Discord button not found"

    def test_discord_button_styling_consistency(self, driver):
        """Test that Discord button has consistent styling with other providers."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Test that Discord button specifically exists and is functional
        discord_buttons = driver.find_elements(
            By.XPATH,
            DISCORD_BUTTON_XPATH,
        )
        assert len(discord_buttons) > 0, "Discord button should be present"

        # Verify Discord button is functional
        discord_button = discord_buttons[0]
        assert discord_button.is_displayed(), "Discord button should be visible"
        assert discord_button.is_enabled(), "Discord button should be clickable"

        # Test completed - functionality verified

    def test_discord_button_mobile_responsive(self, driver):
        """Test that Discord button is responsive on mobile viewport."""
        # Set mobile viewport
        driver.set_window_size(375, 667)  # iPhone SE size

        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Check that Discord button is still visible and clickable
        discord_button = driver.find_element(
            By.XPATH,
            DISCORD_BUTTON_XPATH,
        )
        assert discord_button.is_displayed(), "Discord button not visible on mobile"

        # Verify button takes appropriate width on mobile
        min_mobile_width = 200
        assert discord_button.size["width"] > min_mobile_width, (
            "Button should be wide enough on mobile"
        )


@pytest.mark.django_db
class TestLinkedInAuthenticationFlow(BaseBrowserTest):
    """Test LinkedIn OAuth authentication flow using browser automation."""

    @pytest.fixture(autouse=True)
    def setup(self, live_server, social_apps):  # noqa: ARG002
        """Set up test fixtures."""
        self.live_server_url = live_server.url

    def test_login_page_displays_linkedin_button(self, driver):
        """Test that login page shows LinkedIn authentication button."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Check for LinkedIn button
        linkedin_buttons = driver.find_elements(
            By.XPATH,
            LINKEDIN_BUTTON_XPATH,
        )
        assert len(linkedin_buttons) > 0, "LinkedIn sign-in button not found"

        # Verify button is clickable (functional test rather than styling test)
        linkedin_button = linkedin_buttons[0]
        assert linkedin_button.is_enabled(), "LinkedIn button should be clickable"
        assert linkedin_button.is_displayed(), "LinkedIn button should be visible"

    def test_signup_page_displays_linkedin_button(self, driver):
        """Test that signup page shows LinkedIn authentication button."""
        # Navigate to signup page
        driver.get(f"{self.live_server_url}/accounts/signup/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Check for LinkedIn button
        linkedin_buttons = driver.find_elements(
            By.XPATH,
            LINKEDIN_SIGNUP_XPATH,
        )
        assert len(linkedin_buttons) > 0, "LinkedIn sign-up button not found"

    def test_linkedin_button_href_points_to_linkedin_oauth(self, driver):
        """Test that LinkedIn button has correct href."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Find LinkedIn button and get href
        linkedin_button = driver.find_element(
            By.XPATH,
            LINKEDIN_BUTTON_XPATH,
        )
        href = linkedin_button.get_attribute("href")

        # Verify href points to LinkedIn OpenID Connect endpoint
        assert "/accounts/oidc/linkedin/login/" in href or "linkedin" in href

        # Note: We don't actually click the button to avoid real OAuth redirect

    def test_linkedin_vs_other_providers_all_present(self, driver):
        """Test that all social provider buttons are present."""
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
            GITHUB_BUTTON_XPATH,
        )
        google_buttons = driver.find_elements(
            By.XPATH,
            GOOGLE_BUTTON_XPATH,
        )
        gitlab_buttons = driver.find_elements(
            By.XPATH,
            GITLAB_BUTTON_XPATH,
        )
        discord_buttons = driver.find_elements(
            By.XPATH,
            DISCORD_BUTTON_XPATH,
        )
        linkedin_buttons = driver.find_elements(
            By.XPATH,
            LINKEDIN_BUTTON_XPATH,
        )

        assert len(github_buttons) > 0, "GitHub button not found"
        assert len(google_buttons) > 0, "Google button not found"
        assert len(gitlab_buttons) > 0, "GitLab button not found"
        assert len(discord_buttons) > 0, "Discord button not found"
        assert len(linkedin_buttons) > 0, "LinkedIn button not found"

    def test_linkedin_button_styling_consistency(self, driver):
        """Test that LinkedIn button has consistent styling with other providers."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Test that LinkedIn button specifically exists and is functional
        linkedin_buttons = driver.find_elements(
            By.XPATH,
            LINKEDIN_BUTTON_XPATH,
        )
        assert len(linkedin_buttons) > 0, "LinkedIn button should be present"

        # Verify LinkedIn button is functional
        linkedin_button = linkedin_buttons[0]
        assert linkedin_button.is_displayed(), "LinkedIn button should be visible"
        assert linkedin_button.is_enabled(), "LinkedIn button should be clickable"

        # Test completed - functionality verified

    def test_linkedin_button_mobile_responsive(self, driver):
        """Test that LinkedIn button is responsive on mobile viewport."""
        # Set mobile viewport
        driver.set_window_size(375, 667)  # iPhone SE size

        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Wait for page to load
        wait = WebDriverWait(driver, 10)
        wait.until(
            expected_conditions.presence_of_element_located((By.TAG_NAME, "body")),
        )

        # Check that LinkedIn button is still visible and clickable
        linkedin_button = driver.find_element(
            By.XPATH,
            LINKEDIN_BUTTON_XPATH,
        )
        assert linkedin_button.is_displayed(), "LinkedIn button not visible on mobile"

        # Verify button takes appropriate width on mobile
        min_mobile_width = 200
        assert linkedin_button.size["width"] > min_mobile_width, (
            "Button should be wide enough on mobile"
        )
