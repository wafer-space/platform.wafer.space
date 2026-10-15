"""Browser tests for TOS acceptance flow."""

import re
import time
from urllib.parse import urlparse

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC  # noqa: N812
from selenium.webdriver.support.wait import WebDriverWait

from tests.browser.base import BaseBrowserTest
from tests.browser.pages.signup_page import SignupPage
from tests.browser.pages.tos_page import TOSAcceptPage
from tests.browser.pages.tos_page import TOSDisplayPage
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.legal.tests.factories import TermsOfServiceFactory
from wafer_space.users.tests.factories import UserFactory

# Test constants
TEST_PASSWORD = "testpass123"  # noqa: S105
# This test's own ToS (#269); a version no other test or seed uses.
TOS_VERSION = "2.69.0"
# One version per test (#418), so none collides with the session's "1.0.0"
# seed or with another test's ToS in the same session.
TOS_VERSION_PUBLIC = "4.18.1"
TOS_VERSION_SIGNUP = "4.18.2"
TOS_VERSION_CONTENT = "4.18.3"
TOS_VERSION_UNTICKED = "4.18.4"
TOS_VERSION_COMPLETE = "4.18.5"
CONFIRM_LINK = re.compile(r"https?://\S+/accounts/confirm-email/\S+/")


def tos_content(version):
    """The paragraph TermsOfServiceFactory writes into a version's markdown."""
    return f"This is test TOS content for version {version}."


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestTOSAcceptanceFlow(BaseBrowserTest):
    """Test the complete TOS acceptance flow.

    These are browser tests that verify user interactions with TOS.
    Each test that needs a ToS creates its own active one: the session's
    ensure_test_tos_exists row is flushed after the first live_server test,
    so relying on it let these tests pass without checking anything
    (#269, #418).
    """

    def _wait_for_accept_page(self, driver, live_server_url, version):
        """Wait for /legal/tos/accept/ to show the given version's content."""
        WebDriverWait(driver, 10).until(EC.url_contains("/legal/tos/accept/"))
        WebDriverWait(driver, 10).until(
            EC.text_to_be_present_in_element(
                TOSAcceptPage.TOS_CONTENT, tos_content(version)
            )
        )
        return TOSAcceptPage(driver, live_server_url)

    def _log_in_new_user(self, driver, live_server_url):
        """Log in a user with a verified email who hasn't accepted any ToS."""
        user = UserFactory(password=TEST_PASSWORD)
        driver.get(f"{live_server_url}/accounts/login/")
        self.set_input_value(driver, (By.NAME, "login"), user.username)
        self.set_input_value(driver, (By.NAME, "password"), TEST_PASSWORD)
        self.submit_form(driver)
        return user

    def test_public_tos_display(self, driver, live_server_url):
        """An anonymous visitor sees the active ToS's version and content."""
        TermsOfServiceFactory(version=TOS_VERSION_PUBLIC, is_active=True)

        tos_page = TOSDisplayPage(driver, live_server_url)
        tos_page.navigate_to_tos()
        WebDriverWait(driver, 10).until(
            EC.text_to_be_present_in_element(
                TOSDisplayPage.TOS_CONTENT, tos_content(TOS_VERSION_PUBLIC)
            )
        )

        assert "/accounts/login/" not in driver.current_url
        version_line = driver.find_element(By.CSS_SELECTOR, "h1 + p.text-muted").text
        assert f"Version {TOS_VERSION_PUBLIC}" in version_line

    def test_tos_accept_requires_login(self, driver, live_server_url):
        """Test that TOS acceptance page requires login."""
        # Try to access TOS accept page without logging in
        driver.get(f"{live_server_url}/legal/tos/accept/")

        # Should redirect to login page
        assert "/accounts/login/" in driver.current_url

    def test_new_user_sees_tos_after_signup(self, driver, live_server_url, mailoutbox):
        """Signing up, then confirming the email, leads to the ToS page.

        Email verification is mandatory, so signup stops at confirm-email.
        The test follows the link from the confirmation email, as a new
        user would, and expects the ToS acceptance page next.
        """
        TermsOfServiceFactory(version=TOS_VERSION_SIGNUP, is_active=True)
        timestamp = str(int(time.time()))
        test_username = f"testuser{timestamp}"
        test_email = f"test{timestamp}@example.com"

        signup_page = SignupPage(driver, live_server_url)
        signup_page.go_to_signup_page()
        signup_page.signup(
            username=test_username,
            email=test_email,
            password1=TEST_PASSWORD,
            password2=TEST_PASSWORD,
        )
        WebDriverWait(driver, 10).until(EC.url_contains("/accounts/confirm-email/"))

        [email] = [m for m in mailoutbox if test_email in m.to]
        link = CONFIRM_LINK.search(email.body)
        assert link, email.body
        driver.get(f"{live_server_url}{urlparse(link.group(0)).path}")
        confirm = (By.CSS_SELECTOR, "form button[type='submit']")
        self.wait_for_element_clickable(driver, confirm).click()

        # Confirming doesn't log the user in (allauth's default
        # ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = False): it lands on Sign In.
        WebDriverWait(driver, 10).until(EC.url_contains("/accounts/login/"))
        assert f"You have confirmed {test_email}" in driver.page_source
        self.set_input_value(driver, (By.NAME, "login"), test_username)
        self.set_input_value(driver, (By.NAME, "password"), TEST_PASSWORD)
        self.submit_form(driver)

        self._wait_for_accept_page(driver, live_server_url, TOS_VERSION_SIGNUP)

    def test_tos_page_shows_content_and_checkbox(self, driver, live_server_url):
        """A user who hasn't accepted is sent to the ToS with a checkbox."""
        TermsOfServiceFactory(version=TOS_VERSION_CONTENT, is_active=True)
        self._log_in_new_user(driver, live_server_url)

        tos_page = self._wait_for_accept_page(
            driver, live_server_url, TOS_VERSION_CONTENT
        )

        assert "Test Terms of Service" in tos_page.get_tos_content()
        assert tos_page.is_checkbox_present()
        assert tos_page.is_accept_button_present()

    def test_cannot_submit_tos_without_checkbox(self, driver, live_server_url):
        """The browser refuses to submit the form with the box unticked."""
        TermsOfServiceFactory(version=TOS_VERSION_UNTICKED, is_active=True)
        user = self._log_in_new_user(driver, live_server_url)
        tos_page = self._wait_for_accept_page(
            driver, live_server_url, TOS_VERSION_UNTICKED
        )

        tos_page.click_accept_button()

        checkbox = driver.find_element(*TOSAcceptPage.AGREE_CHECKBOX)
        assert driver.execute_script(
            "return arguments[0].validity.valueMissing;", checkbox
        )
        assert "/legal/tos/accept/" in driver.current_url
        assert "You must agree" not in driver.page_source
        assert not TermsOfServiceAcceptance.objects.filter(user=user).exists()

    def test_tos_version_displayed(self, driver, live_server_url):
        """The public ToS page shows the active version and its content (#269).

        The test makes its own active ToS. It used to rely on the session's
        "1.0.0" row, which the first live_server test's flush removes: as the
        first test it saw that row without its markdown (create_test_tos
        checks the real tos_versions path, not the mocked one) and failed; as
        any later test it got the 404 and passed without checking anything.
        """
        TermsOfServiceFactory(version=TOS_VERSION, is_active=True)

        tos_page = TOSDisplayPage(driver, live_server_url)
        tos_page.navigate_to_tos()
        WebDriverWait(driver, 10).until(
            EC.text_to_be_present_in_element(
                TOSDisplayPage.TOS_CONTENT, tos_content(TOS_VERSION)
            )
        )

        version_line = driver.find_element(By.CSS_SELECTOR, "h1 + p.text-muted").text
        assert f"Version {TOS_VERSION}" in version_line
        assert "Test Terms of Service" in tos_page.get_tos_content()

    def test_tos_acceptance_flow_complete(self, driver, live_server_url):
        """Ticking the box and accepting records it and leaves the ToS page."""
        tos = TermsOfServiceFactory(version=TOS_VERSION_COMPLETE, is_active=True)
        user = self._log_in_new_user(driver, live_server_url)
        tos_page = self._wait_for_accept_page(
            driver, live_server_url, TOS_VERSION_COMPLETE
        )

        tos_page.accept_tos()

        WebDriverWait(driver, 10).until(
            EC.url_changes(f"{live_server_url}/legal/tos/accept/")
        )
        assert "/legal/tos/accept/" not in driver.current_url
        assert TermsOfServiceAcceptance.objects.filter(
            user=user, tos_version=tos
        ).exists()
