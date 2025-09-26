"""
Page Object Model for the homepage.
"""
from selenium.webdriver.common.by import By

from .base_page import BasePage


class HomePage(BasePage):
    """Page Object Model for the homepage."""

    # Locators
    NAVBAR_BRAND = (By.CLASS_NAME, "navbar-brand")
    NAVBAR_TOGGLER = (By.CLASS_NAME, "navbar-toggler")
    SIGN_IN_LINK = (By.LINK_TEXT, "Sign In")
    SIGN_UP_LINK = (By.LINK_TEXT, "Sign Up")
    ABOUT_LINK = (By.LINK_TEXT, "About")
    HOME_LINK = (By.LINK_TEXT, "Home")

    # Page content
    PAGE_TITLE = (By.TAG_NAME, "h1")
    PAGE_CONTENT = (By.CLASS_NAME, "content")

    # Footer elements (if any)
    FOOTER = (By.TAG_NAME, "footer")

    def __init__(self, driver, live_server_url):
        super().__init__(driver, live_server_url)
        self.path = "/"

    def go_to_home_page(self):
        """Navigate to the homepage."""
        return self.navigate_to(self.path)

    def is_navbar_visible(self):
        """Check if navbar is visible."""
        return self.is_displayed(self.NAVBAR_BRAND)

    def click_sign_in(self):
        """Click the Sign In link."""
        self.click(self.SIGN_IN_LINK)
        from .login_page import LoginPage
        return LoginPage(self.driver, self.live_server_url)

    def click_sign_up(self):
        """Click the Sign Up link."""
        self.click(self.SIGN_UP_LINK)
        # Return SignUpPage when implemented
        return self

    def click_about(self):
        """Click the About link."""
        self.click(self.ABOUT_LINK)
        return self

    def get_page_heading(self):
        """Get the main page heading text."""
        return self.get_text(self.PAGE_TITLE)

    def is_user_logged_in(self):
        """Check if a user is logged in by looking for logout link."""
        logout_link = (By.LINK_TEXT, "Sign Out")
        return self.is_displayed(logout_link)

    def get_username_display(self):
        """Get the displayed username if logged in."""
        username_element = (By.CLASS_NAME, "navbar-username")
        if self.is_displayed(username_element):
            return self.get_text(username_element)
        return None

    def click_navbar_toggle(self):
        """Click the navbar toggle for mobile view."""
        if self.is_displayed(self.NAVBAR_TOGGLER):
            self.click(self.NAVBAR_TOGGLER)
        return self

    def verify_page_loaded(self):
        """Verify that the homepage has loaded correctly."""
        assert self.is_navbar_visible(), "Navbar is not visible"
        assert "wafer.space" in self.get_title().lower(), "Page title doesn't contain 'wafer.space'"
        return True
