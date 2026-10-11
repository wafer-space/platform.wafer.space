"""Browser tests: Bootstrap tooltips and popovers render (issue #360).

Both need Popper. base.html used to load bootstrap.min.js, which has no
Popper, so showing any tooltip or popover threw "createPopper is not a
function" and nothing appeared.
"""

import pytest
from allauth.account.models import EmailAddress
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

from tests.browser.base import BaseBrowserTest
from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.users.models import User

TEST_USER_AUTH = "testpass123"  # Authentication credential for test users


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestBootstrapPopper(BaseBrowserTest):
    """Tooltips and popovers appear and log no Popper errors."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        """An owner with a project whose active file is still downloading."""
        self.driver = driver
        self.live_server_url = live_server.url

        self.user = User.objects.create_user(
            username="popper",
            email="popper@example.com",
            password=TEST_USER_AUTH,
        )
        EmailAddress.objects.create(
            user=self.user,
            email="popper@example.com",
            verified=True,
            primary=True,
        )
        tos = TermsOfService.get_active()
        if tos:
            TermsOfServiceAcceptance.objects.create(
                user=self.user,
                tos_version=tos,
                ip_address="127.0.0.1",
            )
        self.project = Project.objects.create(user=self.user, name="Popper project")
        ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/design.gds",
            is_active=True,
        )

    def login(self):
        """Log in as the owner."""
        self.navigate_to(self.driver, "/accounts/login/")
        username_input = self.wait_for_element(self.driver, (By.NAME, "login"))
        password_input = self.driver.find_element(By.NAME, "password")
        username_input.send_keys("popper")
        password_input.send_keys(TEST_USER_AUTH)
        current_url = self.driver.current_url
        self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        WebDriverWait(self.driver, 10).until(
            expected_conditions.url_changes(current_url),
        )

    def popper_errors(self):
        return [
            log
            for log in self.get_console_logs(self.driver)
            if log.get("level") == "SEVERE" and "createPopper" in log.get("message", "")
        ]

    def test_disabled_submit_reason_tooltip_shows(self):
        """Hovering the disabled Submit button shows why it is disabled."""
        self.login()
        self.navigate_to(self.driver, f"/projects/{self.project.pk}/")
        self.wait_for_page_load(self.driver)

        trigger = self.wait_for_element(
            self.driver,
            (By.CSS_SELECTOR, "[data-submit-disabled-reason]"),
        )
        ActionChains(self.driver).move_to_element(trigger).perform()
        tooltip = WebDriverWait(self.driver, 10).until(
            expected_conditions.visibility_of_element_located(
                (By.CSS_SELECTOR, ".tooltip.show"),
            ),
        )

        assert "download is not completed" in tooltip.text
        assert not self.popper_errors()

    def test_project_id_help_popover_shows_on_focus(self):
        """Focusing the Project ID field shows its help popover."""
        self.login()
        self.navigate_to(self.driver, "/projects/create/")
        self.wait_for_page_load(self.driver)

        self.wait_for_element(self.driver, (By.ID, "id_project_id")).click()
        popover = WebDriverWait(self.driver, 10).until(
            expected_conditions.visibility_of_element_located(
                (By.CSS_SELECTOR, ".popover.show"),
            ),
        )

        assert "Project ID Requirements" in popover.text
        assert not self.popper_errors()
