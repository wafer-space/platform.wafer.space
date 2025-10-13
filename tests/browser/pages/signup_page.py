"""Page Object Model for the signup page."""

from selenium.webdriver.common.by import By

from .base_page import BasePage


class SignupPage(BasePage):
    """Page Object Model for the signup page."""

    # Locators
    USERNAME_INPUT = (By.ID, "id_username")
    EMAIL_INPUT = (By.ID, "id_email")
    PASSWORD1_INPUT = (By.ID, "id_password1")
    PASSWORD2_INPUT = (By.ID, "id_password2")
    SUBMIT_BUTTON = (By.XPATH, "//button[@type='submit']")

    # Error messages
    ERROR_MESSAGE = (By.CLASS_NAME, "alert-danger")
    FIELD_ERROR = (By.CLASS_NAME, "invalid-feedback")

    def __init__(self, driver, live_server_url):
        super().__init__(driver, live_server_url)
        self.path = "/accounts/signup/"

    def go_to_signup_page(self):
        """Navigate to the signup page."""
        return self.navigate_to(self.path)

    def enter_username(self, username):
        """Enter username in the signup form."""
        return self.fill_input(self.USERNAME_INPUT, username)

    def enter_email(self, email):
        """Enter email in the signup form."""
        return self.fill_input(self.EMAIL_INPUT, email)

    def enter_password1(self, password):
        """Enter password in the first password field."""
        return self.fill_input(self.PASSWORD1_INPUT, password)

    def enter_password2(self, password):
        """Enter password in the confirmation field."""
        return self.fill_input(self.PASSWORD2_INPUT, password)

    def click_submit(self):
        """Click the submit button."""
        self.click(self.SUBMIT_BUTTON)
        return self

    def signup(self, username, email, password1, password2):
        """Perform complete signup flow."""
        self.enter_username(username)
        self.enter_email(email)
        self.enter_password1(password1)
        self.enter_password2(password2)
        self.click_submit()
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

    def verify_page_loaded(self):
        """Verify that the signup page has loaded correctly."""
        assert self.is_displayed(self.USERNAME_INPUT), "Username input not found"
        assert self.is_displayed(self.EMAIL_INPUT), "Email input not found"
        assert self.is_displayed(self.PASSWORD1_INPUT), "Password1 input not found"
        assert self.is_displayed(self.PASSWORD2_INPUT), "Password2 input not found"
        assert self.is_displayed(self.SUBMIT_BUTTON), "Submit button not found"
        return True
