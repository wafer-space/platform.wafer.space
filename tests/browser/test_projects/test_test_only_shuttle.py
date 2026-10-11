"""Browser test: an owner creates a project on a test-only shuttle (#221)."""

import pytest
from allauth.account.models import EmailAddress
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait

from tests.browser.base import BaseBrowserTest
from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.projects.models import Project
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.models import User

# Test fixture constants
TEST_USER_AUTH = "testpass123"  # Authentication credential for test users
TEST_ONLY_LABEL = "G898 - Test shuttle (test only, not manufactured)"


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestTestOnlyShuttle(BaseBrowserTest):
    """An owner picks the test-only shuttle knowingly and sees "Test only"."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        """Owner; one real open shuttle and one test-only shuttle."""
        self.driver = driver
        self.live_server_url = live_server.url

        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_USER_AUTH,
        )
        EmailAddress.objects.create(
            user=self.user,
            email="test@example.com",
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

        Shuttle.objects.create(
            name="G897", description="Real run", status=Shuttle.Status.OPEN
        )
        self.test_shuttle = Shuttle.objects.create(
            name="G898",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
            is_test_only=True,
        )

    def login(self):
        """Log in as the test user."""
        self.navigate_to(self.driver, "/accounts/login/")
        username_input = self.wait_for_element(self.driver, (By.NAME, "login"))
        password_input = self.driver.find_element(By.NAME, "password")

        username_input.send_keys("testuser")
        password_input.send_keys(TEST_USER_AUTH)

        current_url = self.driver.current_url
        submit_button = self.driver.find_element(
            By.CSS_SELECTOR, 'button[type="submit"]'
        )
        submit_button.click()

        wait = WebDriverWait(self.driver, 10)
        wait.until(expected_conditions.url_changes(current_url))

    def test_create_project_on_test_only_shuttle(self):
        """Pick the "(test only, not manufactured)" choice; the page says so."""
        self.login()
        self.navigate_to(self.driver, "/projects/create/")
        shuttle = Select(self.wait_for_element(self.driver, (By.ID, "id_shuttle")))
        shuttle.select_by_visible_text(TEST_ONLY_LABEL)
        self.set_input_value(self.driver, (By.ID, "id_name"), "Test design")
        self.set_input_value(self.driver, (By.ID, "id_project_id"), "TEST")
        create_url = self.driver.current_url

        self.submit_form(self.driver, (By.XPATH, "//form[.//select[@id='id_shuttle']]"))
        WebDriverWait(self.driver, 10).until(
            expected_conditions.url_changes(create_url)
        )
        state = self.wait_for_element(self.driver, (By.CSS_SELECTOR, ".shuttle-state"))

        project = Project.objects.get(user=self.user)
        assert (project.shuttle, "Test only" in state.text) == (
            self.test_shuttle,
            True,
        )
