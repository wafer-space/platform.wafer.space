"""Browser test: staff submit a project despite a failed precheck (#252)."""

import pytest
from allauth.account.models import EmailAddress
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

from tests.browser.base import BaseBrowserTest
from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.projects.tests.test_models_submit_override import make_failed_project
from wafer_space.users.models import User

TEST_USER_AUTH = "testpass123"  # Authentication credential for test users
REASON = "False DRC error on the seal ring; checked by hand."
BANNER = (By.CSS_SELECTOR, "[data-submission-override-banner]")


def make_login_ready(user: User) -> None:
    user.set_password(TEST_USER_AUTH)
    user.save()
    # UserFactory may already have created the primary address.
    if not EmailAddress.objects.filter(user=user).update(verified=True):
        EmailAddress.objects.create(
            user=user,
            email=user.email,
            verified=True,
            primary=True,
        )
    tos = TermsOfService.get_active()
    if tos:
        TermsOfServiceAcceptance.objects.create(
            user=user,
            tos_version=tos,
            ip_address="127.0.0.1",
        )


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestSubmitOverride(BaseBrowserTest):
    """Staff override-submit; the owner sees the banner."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        self.driver = driver
        self.live_server_url = live_server.url
        self.project = make_failed_project()
        self.owner = self.project.user
        make_login_ready(self.owner)
        self.staff = User.objects.create_user(
            username="overrider",
            email="overrider@example.com",
            is_staff=True,
        )
        make_login_ready(self.staff)

    def login(self, user: User) -> None:
        self.navigate_to(self.driver, "/accounts/login/")
        self.wait_for_element(self.driver, (By.NAME, "login")).send_keys(
            user.username,
        )
        self.driver.find_element(By.NAME, "password").send_keys(TEST_USER_AUTH)
        current_url = self.driver.current_url
        self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        WebDriverWait(self.driver, 10).until(
            expected_conditions.url_changes(current_url),
        )

    def click_centered(self, locator: tuple[str, str]) -> None:
        """Scroll the element to the middle of the viewport, then click it."""
        element = self.wait_for_element(self.driver, locator)
        self.driver.execute_script(
            # Bootstrap sets scroll-behavior: smooth; scroll instantly so the
            # click does not land mid-animation.
            "arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});",
            element,
        )
        WebDriverWait(self.driver, 10).until(
            expected_conditions.element_to_be_clickable(locator),
        ).click()

    def logout(self) -> None:
        """Sign out and wait until the sign-out has completed.

        Navigating on before the POST finishes leaves the session logged in,
        and the next login page then redirects away.
        """
        self.navigate_to(self.driver, "/accounts/logout/")
        current_url = self.driver.current_url
        self.wait_for_element(
            self.driver,
            (By.CSS_SELECTOR, 'form button[type="submit"]'),
        ).click()
        WebDriverWait(self.driver, 10).until(
            expected_conditions.url_changes(current_url),
        )

    def test_staff_override_then_owner_sees_banner(self):
        self.login(self.staff)
        self.navigate_to(self.driver, f"/projects/{self.project.pk}/")
        self.wait_for_page_load(self.driver)

        self.click_centered(
            (By.XPATH, "//button[contains(., 'Submit anyway (staff override)')]"),
        )
        # Wait for Bootstrap's collapse animation to finish: clicking while
        # the form is still sliding open hits the wrong element.
        WebDriverWait(self.driver, 10).until(
            expected_conditions.presence_of_element_located(
                (By.CSS_SELECTOR, "#submit-override-form.collapse.show"),
            ),
        )
        reason = self.driver.find_element(
            By.CSS_SELECTOR,
            "#submit-override-form textarea",
        )
        reason.send_keys(REASON)
        self.driver.execute_script("window.confirm = () => true;")
        self.click_centered(
            (By.CSS_SELECTOR, '#submit-override-form button[type="submit"]'),
        )

        banner = self.wait_for_element(self.driver, BANNER)
        assert "overrider" in banner.text
        assert REASON in banner.text
        syntax_errors = [
            log
            for log in self.get_console_logs(self.driver)
            if log.get("level") == "SEVERE" and "SyntaxError" in log.get("message", "")
        ]
        assert not syntax_errors

        self.logout()
        self.login(self.owner)
        self.navigate_to(self.driver, f"/projects/{self.project.pk}/")
        assert REASON in self.wait_for_element(self.driver, BANNER).text
