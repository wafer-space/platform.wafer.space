"""Browser test: the edit page does not flag the project's own ID (#306)."""

import pytest
from allauth.account.models import EmailAddress
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

from tests.browser.base import BaseBrowserTest
from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.projects.models import Project
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.models import User

TEST_USER_AUTH = "testpass123"  # Authentication credential for test users

FEEDBACK = (
    By.CSS_SELECTOR,
    "#id_project_id ~ .valid-feedback, #id_project_id ~ .invalid-feedback",
)


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestOwnProjectIdAvailable(BaseBrowserTest):
    """Staff editing a project see its unchanged ID as available."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        """A staff user, a project with ID VRFY, and another with TAKN."""
        self.driver = driver
        self.live_server_url = live_server.url

        self.staff = User.objects.create_user(
            username="staffer",
            email="staffer@example.com",
            password=TEST_USER_AUTH,
            is_staff=True,
        )
        EmailAddress.objects.create(
            user=self.staff,
            email="staffer@example.com",
            verified=True,
            primary=True,
        )
        tos = TermsOfService.get_active()
        if tos:
            TermsOfServiceAcceptance.objects.create(
                user=self.staff,
                tos_version=tos,
                ip_address="127.0.0.1",
            )

        self.shuttle = Shuttle.objects.create(
            name="G884",
            description="Open run",
            status=Shuttle.Status.OPEN,
        )
        self.project = Project.objects.create(
            user=self.staff,
            name="Edited project",
            shuttle=self.shuttle,
            project_id="VRFY",
        )
        Project.objects.create(
            user=self.staff,
            name="Other project",
            shuttle=self.shuttle,
            project_id="TAKN",
        )

    def login(self):
        """Log in as the staff user."""
        self.navigate_to(self.driver, "/accounts/login/")
        username_input = self.wait_for_element(self.driver, (By.NAME, "login"))
        password_input = self.driver.find_element(By.NAME, "password")
        username_input.send_keys("staffer")
        password_input.send_keys(TEST_USER_AUTH)
        current_url = self.driver.current_url
        self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        WebDriverWait(self.driver, 10).until(
            expected_conditions.url_changes(current_url),
        )

    def retype_project_id(self, value):
        """Replace the project ID field's value and wait for the checker."""
        field = self.wait_for_element(self.driver, (By.ID, "id_project_id"))
        field.clear()
        field.send_keys(value)
        WebDriverWait(self.driver, 10).until(
            lambda d: any(value in e.text for e in d.find_elements(*FEEDBACK)),
        )
        return " ".join(e.text for e in self.driver.find_elements(*FEEDBACK))

    def test_own_id_available_other_id_taken(self):
        """Own unchanged ID reads available; another project's ID taken."""
        self.login()
        self.navigate_to(self.driver, f"/projects/{self.project.pk}/update/")
        self.wait_for_page_load(self.driver)

        assert self.retype_project_id("VRFY") == "ID VRFY is available"
        assert self.retype_project_id("TAKN") == "ID TAKN is taken"

        # The form's inline script shares one scope: a SyntaxError would kill
        # all of it, including the checker this test exercises.
        syntax_errors = [
            log
            for log in self.get_console_logs(self.driver)
            if log.get("level") == "SEVERE" and "SyntaxError" in log.get("message", "")
        ]
        assert not syntax_errors, f"JS syntax errors on edit page: {syntax_errors}"
