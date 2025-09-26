"""
Base Page Object Model for all pages.
"""
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait


class BasePage:
    """Base page class containing common page interactions."""

    def __init__(self, driver, live_server_url):
        self.driver = driver
        self.live_server_url = live_server_url
        self.wait = WebDriverWait(driver, 10)

    def navigate_to(self, path=""):
        """Navigate to a specific path."""
        url = f"{self.live_server_url}{path}"
        self.driver.get(url)
        return self

    def get_title(self):
        """Get the page title."""
        return self.driver.title

    def get_current_url(self):
        """Get the current URL."""
        return self.driver.current_url

    def find_element(self, locator):
        """Find an element on the page."""
        return self.wait.until(expected_conditions.presence_of_element_located(locator))

    def find_elements(self, locator):
        """Find multiple elements on the page."""
        return self.wait.until(expected_conditions.presence_of_all_elements_located(locator))

    def click(self, locator):
        """Click an element."""
        element = self.wait.until(expected_conditions.element_to_be_clickable(locator))
        element.click()
        return self

    def fill_input(self, locator, value):
        """Fill an input field."""
        element = self.find_element(locator)
        element.clear()
        element.send_keys(value)
        return self

    def get_text(self, locator):
        """Get text from an element."""
        element = self.find_element(locator)
        return element.text

    def is_displayed(self, locator):
        """Check if an element is displayed."""
        try:
            element = self.driver.find_element(*locator)
            return element.is_displayed()
        except NoSuchElementException:
            return False

    def wait_for_url_to_contain(self, text):
        """Wait for URL to contain specific text."""
        self.wait.until(expected_conditions.url_contains(text))
        return self

    def wait_for_element_visible(self, locator):
        """Wait for an element to be visible."""
        return self.wait.until(expected_conditions.visibility_of_element_located(locator))

    def wait_for_element_invisible(self, locator):
        """Wait for an element to become invisible."""
        return self.wait.until(expected_conditions.invisibility_of_element_located(locator))

    def scroll_to_element(self, locator):
        """Scroll to an element."""
        element = self.find_element(locator)
        self.driver.execute_script("arguments[0].scrollIntoView(true);", element)
        return self

    def submit_form(self):
        """Submit the current form."""
        submit_button = self.driver.find_element(
            By.XPATH, "//button[@type='submit']",
        )
        submit_button.click()
        return self

    def get_alert_text(self):
        """Get text from an alert box."""
        alert = self.wait.until(expected_conditions.alert_is_present())
        return alert.text

    def accept_alert(self):
        """Accept an alert box."""
        alert = self.wait.until(expected_conditions.alert_is_present())
        alert.accept()
        return self

    def dismiss_alert(self):
        """Dismiss an alert box."""
        alert = self.wait.until(expected_conditions.alert_is_present())
        alert.dismiss()
        return self
