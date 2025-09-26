"""
Page Object Model for the login page.
"""

from selenium.webdriver.common.by import By

from .base_page import BasePage


class LoginPage(BasePage):
    """Page Object Model for the login page."""

    # Locators
    USERNAME_INPUT = (By.NAME, "login")
    PASSWORD_INPUT = (By.NAME, "password")
    SUBMIT_BUTTON = (By.XPATH, "//button[@type='submit']")
    REMEMBER_ME_CHECKBOX = (By.NAME, "remember")
    FORGOT_PASSWORD_LINK = (By.LINK_TEXT, "Forgot Password?")
    SIGN_UP_LINK = (By.PARTIAL_LINK_TEXT, "sign up")

    # Social login buttons
    GITHUB_LOGIN = (By.XPATH, "//a[contains(@href, '/accounts/github/login/')]")
    GITLAB_LOGIN = (By.XPATH, "//a[contains(@href, '/accounts/gitlab/login/')]")
    GOOGLE_LOGIN = (By.XPATH, "//a[contains(@href, '/accounts/google/login/')]")
    LINKEDIN_LOGIN = (
        By.XPATH,
        "//a[contains(@href, '/accounts/linkedin_oauth2/login/')]",
    )

    # Error messages
    ERROR_MESSAGE = (By.CLASS_NAME, "alert-danger")
    FIELD_ERROR = (By.CLASS_NAME, "invalid-feedback")

    def __init__(self, driver, live_server_url):
        super().__init__(driver, live_server_url)
        self.path = "/accounts/login/"

    def go_to_login_page(self):
        """Navigate to the login page."""
        return self.navigate_to(self.path)

    def enter_username(self, username):
        """Enter username in the login form."""
        return self.fill_input(self.USERNAME_INPUT, username)

    def enter_password(self, password):
        """Enter password in the login form."""
        return self.fill_input(self.PASSWORD_INPUT, password)

    def check_remember_me(self):
        """Check the remember me checkbox."""
        checkbox = self.find_element(self.REMEMBER_ME_CHECKBOX)
        if not checkbox.is_selected():
            checkbox.click()
        return self

    def uncheck_remember_me(self):
        """Uncheck the remember me checkbox."""
        checkbox = self.find_element(self.REMEMBER_ME_CHECKBOX)
        if checkbox.is_selected():
            checkbox.click()
        return self

    def click_submit(self):
        """Click the submit button."""
        self.click(self.SUBMIT_BUTTON)
        return self

    def login(self, username, password, *, remember_me=False):
        """Perform complete login flow."""
        self.enter_username(username)
        self.enter_password(password)

        if remember_me:
            self.check_remember_me()
        else:
            self.uncheck_remember_me()

        self.click_submit()
        return self

    def click_forgot_password(self):
        """Click the forgot password link."""
        self.click(self.FORGOT_PASSWORD_LINK)
        return self

    def click_sign_up_link(self):
        """Click the sign up link."""
        self.click(self.SIGN_UP_LINK)
        return self

    def login_with_github(self):
        """Click the GitHub login button."""
        self.click(self.GITHUB_LOGIN)
        return self

    def login_with_gitlab(self):
        """Click the GitLab login button."""
        self.click(self.GITLAB_LOGIN)
        return self

    def login_with_google(self):
        """Click the Google login button."""
        self.click(self.GOOGLE_LOGIN)
        return self

    def login_with_linkedin(self):
        """Click the LinkedIn login button."""
        self.click(self.LINKEDIN_LOGIN)
        return self

    def get_error_message(self):
        """Get the error message if present."""
        if self.is_displayed(self.ERROR_MESSAGE):
            return self.get_text(self.ERROR_MESSAGE)
        return None

    def get_field_errors(self):
        """Get all field error messages."""
        errors = []
        if self.is_displayed(self.FIELD_ERROR):
            error_elements = self.find_elements(self.FIELD_ERROR)
            errors = [elem.text for elem in error_elements]
        return errors

    def is_login_successful(self):
        """Check if login was successful by checking URL change."""
        # After successful login, user should be redirected away from login page
        return "/accounts/login/" not in self.get_current_url()

    def verify_page_loaded(self):
        """Verify that the login page has loaded correctly."""
        assert self.is_displayed(self.USERNAME_INPUT), "Username input not found"
        assert self.is_displayed(self.PASSWORD_INPUT), "Password input not found"
        assert self.is_displayed(self.SUBMIT_BUTTON), "Submit button not found"
        return True
