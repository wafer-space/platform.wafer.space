"""
Base classes for browser tests.
"""

import time

from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait


class BaseBrowserTest:
    """Base class for browser tests with common utilities."""

    def setup_method(self):
        """Setup test method.

        Note: Display environment is already cleared at conftest.py import time.
        Browser is always headless unless --visible flag was passed.
        --visible flag is automatically blocked in Claude Code and CI environments.
        """
        self.errors = []

    def teardown_method(self):
        """Teardown test method."""
        # Report any collected errors
        if self.errors:
            error_msg = "\n".join(self.errors)
            msg = f"Test errors:\n{error_msg}"
            raise AssertionError(msg)

    def navigate_to(self, driver, path):
        """Navigate to a specific path on the live server."""
        url = f"{self.live_server_url}{path}"
        driver.get(url)
        return url

    def wait_for_element(self, driver, locator, timeout=10):
        """Wait for an element to be present and return it."""
        wait = WebDriverWait(driver, timeout)
        return wait.until(expected_conditions.presence_of_element_located(locator))

    def wait_for_element_clickable(self, driver, locator, timeout=10):
        """Wait for an element to be clickable and return it."""
        wait = WebDriverWait(driver, timeout)
        return wait.until(expected_conditions.element_to_be_clickable(locator))

    def wait_for_text_in_element(self, driver, locator, text, timeout=10):
        """Wait for specific text to appear in an element."""
        wait = WebDriverWait(driver, timeout)
        return wait.until(
            expected_conditions.text_to_be_present_in_element(locator, text),
        )

    def wait_for_url_contains(self, driver, url_part, timeout=10):
        """Wait for URL to contain specific text."""
        wait = WebDriverWait(driver, timeout)
        return wait.until(expected_conditions.url_contains(url_part))

    def wait_for_page_load(self, driver, timeout=10):
        """Wait for page to be fully loaded."""
        wait = WebDriverWait(driver, timeout)
        return wait.until(
            lambda d: d.execute_script("return document.readyState") == "complete",
        )

    def element_exists(self, driver, locator):
        """Check if an element exists on the page."""
        try:
            driver.find_element(*locator)
        except NoSuchElementException:
            return False
        else:
            return True

    def get_element_text(self, driver, locator):
        """Get text content of an element."""
        element = self.wait_for_element(driver, locator)
        return element.text

    def click_element(self, driver, locator):
        """Click an element after waiting for it to be clickable."""
        element = self.wait_for_element_clickable(driver, locator)
        element.click()

    def fill_input(self, driver, locator, value, *, clear=True):
        """Fill an input field with a value."""
        element = self.wait_for_element(driver, locator)
        if clear:
            element.clear()
        element.send_keys(value)

    def set_input_value(self, driver, locator, value, timeout=10, attempts=3):
        """Set an input's value and verify the text actually landed.

        send_keys can silently lose keystrokes when page JS is still
        initialising focus or event handlers while typing (issue #316);
        an unnoticed empty required field then makes the browser's
        client-side validation block the form submit. Verify the DOM
        value after typing and retype if it did not land.
        """
        last_value = None
        for _ in range(attempts):
            element = self.wait_for_element_clickable(driver, locator, timeout)
            element.click()
            element.clear()
            element.send_keys(value)
            try:
                WebDriverWait(driver, 2).until(
                    lambda d: d.find_element(*locator).get_attribute("value") == value,
                )
            except TimeoutException:
                last_value = driver.find_element(*locator).get_attribute("value")
                continue
            return
        msg = f"Input {locator} kept value {last_value!r}, expected {value!r}"
        raise AssertionError(msg)

    def submit_form(self, driver, form_locator=None):
        """Submit a form."""
        if form_locator:
            form = self.wait_for_element(driver, form_locator)
            form.submit()
        else:
            # Find and click the first submit button
            submit_button = driver.find_element(
                By.XPATH,
                "//button[@type='submit']",
            )
            submit_button.click()

    def get_page_title(self, driver):
        """Get the page title."""
        return driver.title

    def get_current_url(self, driver):
        """Get the current URL."""
        return driver.current_url

    def assert_element_text(self, driver, locator, expected_text):
        """Assert that an element contains specific text."""
        actual_text = self.get_element_text(driver, locator)
        assert expected_text in actual_text, (
            f"Expected text '{expected_text}' not found in element. "
            f"Actual text: '{actual_text}'"
        )

    def assert_page_title_contains(self, driver, expected_text):
        """Assert that the page title contains specific text."""
        actual_title = self.get_page_title(driver)
        assert expected_text in actual_title, (
            f"Expected text '{expected_text}' not found in page title. "
            f"Actual title: '{actual_title}'"
        )

    def assert_url_contains(self, driver, expected_text):
        """Assert that the current URL contains specific text."""
        actual_url = self.get_current_url(driver)
        assert expected_text in actual_url, (
            f"Expected text '{expected_text}' not found in URL. "
            f"Actual URL: '{actual_url}'"
        )

    def scroll_to_element(self, driver, locator):
        """Scroll to an element."""
        element = self.wait_for_element(driver, locator)
        driver.execute_script("arguments[0].scrollIntoView(true);", element)
        time.sleep(0.5)  # Brief pause for scroll animation

    def get_console_logs(self, driver):
        """Get browser console logs (Chrome only)."""
        if driver.name == "chrome":
            return driver.get_log("browser")
        return []

    def check_for_javascript_errors(self, driver):
        """Check for JavaScript errors in console."""
        logs = self.get_console_logs(driver)
        errors = [log for log in logs if log.get("level") == "SEVERE"]
        if errors:
            self.errors.append(f"JavaScript errors found: {errors}")


class AuthenticatedBrowserTest(BaseBrowserTest):
    """Base class for tests requiring authentication."""

    def login(self, driver, username, password):
        """Log in a user."""
        # Navigate to login page
        self.navigate_to(driver, "/accounts/login/")

        # Fill in credentials
        self.fill_input(driver, (By.NAME, "login"), username)
        self.fill_input(driver, (By.NAME, "password"), password)

        # Submit form
        self.submit_form(driver)

        # Wait for redirect
        self.wait_for_url_contains(driver, "/accounts/confirm-email/")
        # Or check for dashboard/home page depending on your app flow

    def logout(self, driver):
        """Log out the current user."""
        self.navigate_to(driver, "/accounts/logout/")

        # Confirm logout if there's a confirmation page
        sign_out_xpath = "//button[contains(text(), 'Sign Out')]"
        sign_out_locator = (By.XPATH, sign_out_xpath)
        if self.element_exists(driver, sign_out_locator):
            self.click_element(driver, sign_out_locator)

    def create_test_user(
        self,
        django_user_model,
        username="testuser",
        email="test@example.com",
        password=None,
    ):
        """Create a test user in the database."""
        if password is None:
            password = "testpass123"  # noqa: S105
        return django_user_model.objects.create_user(
            username=username,
            email=email,
            password=password,
        )

    def verify_authenticated_state(self, driver):
        """Verify that the user is authenticated."""
        # Check for common authenticated elements
        # This should be customized based on your app's UI
        authenticated_indicators = [
            (By.XPATH, "//a[contains(@href, '/accounts/logout/')]"),
            (By.XPATH, "//a[contains(@href, '/users/')]"),
            (By.CLASS_NAME, "navbar-user"),  # Adjust based on your template
        ]

        for indicator in authenticated_indicators:
            if self.element_exists(driver, indicator):
                return True

        return False
