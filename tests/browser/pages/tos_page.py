"""Page Object Model for TOS pages."""

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from .base_page import BasePage


class TOSDisplayPage(BasePage):
    """Page object for TOS display page."""

    # Locators
    TOS_CONTENT = (By.CLASS_NAME, "tos-content")
    VERSION_TEXT = (By.CLASS_NAME, "text-muted")

    def navigate_to_tos(self):
        """Navigate to TOS display page."""
        return self.navigate_to("/legal/tos/")

    def get_tos_content(self):
        """Get TOS content text."""
        return self.get_text(self.TOS_CONTENT)

    def get_version(self):
        """Get TOS version."""
        return self.get_text(self.VERSION_TEXT)


class TOSAcceptPage(BasePage):
    """Page object for TOS acceptance page."""

    # Locators
    AGREE_CHECKBOX = (By.ID, "agree")
    ACCEPT_BUTTON = (By.CSS_SELECTOR, "button[type='submit']")
    TOS_CONTENT = (By.CLASS_NAME, "tos-content")
    ALERT_MESSAGE = (By.CLASS_NAME, "alert")

    def navigate_to_accept(self):
        """Navigate to TOS accept page."""
        return self.navigate_to("/legal/tos/accept/")

    def get_tos_content(self):
        """Get TOS content text."""
        return self.get_text(self.TOS_CONTENT)

    def check_agree_checkbox(self):
        """Check the agreement checkbox."""
        self.click(self.AGREE_CHECKBOX)
        return self

    def click_accept_button(self):
        """Click the accept button."""
        self.click(self.ACCEPT_BUTTON)
        return self

    def accept_tos(self):
        """Complete TOS acceptance flow."""
        self.check_agree_checkbox()
        self.click_accept_button()
        return self

    def get_alert_message(self):
        """Get alert message text."""
        try:
            return self.get_text(self.ALERT_MESSAGE)
        except NoSuchElementException:
            return None

    def is_checkbox_present(self):
        """Check if agree checkbox is present."""
        try:
            self.find_element(self.AGREE_CHECKBOX)
        except NoSuchElementException:
            return False
        else:
            return True
