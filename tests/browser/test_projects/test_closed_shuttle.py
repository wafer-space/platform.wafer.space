"""Browser tests: an owner on a closed shuttle (#320, #350)."""

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
RUN_PAGE = "https://wafer.space/ws-run1/"


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestClosedShuttle(BaseBrowserTest):
    """An owner sees a closed shuttle plainly and cannot pick or upload to it."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        """Owner with a project on a closed shuttle; one open shuttle."""
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

        self.closed_shuttle = Shuttle.objects.create(
            name="G892",
            description="Past run",
            status=Shuttle.Status.COMPLETED,
            website_url=RUN_PAGE,
        )
        self.open_shuttle = Shuttle.objects.create(
            name="G893",
            description="Current run",
            status=Shuttle.Status.OPEN,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Closed run design",
            shuttle=self.closed_shuttle,
            project_id="CLSD",
            slot_size="1x1",
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

    def test_project_page_says_closed_and_offers_no_upload(self):
        """The project page shows "Closed", the run page link, and no upload."""
        self.login()
        self.navigate_to(self.driver, f"/projects/{self.project.pk}/")
        state = self.wait_for_element(self.driver, (By.CSS_SELECTOR, ".shuttle-state"))

        upload_links = self.driver.find_elements(
            By.CSS_SELECTOR, 'a[href*="/submit-url/"]'
        )
        run_page = state.find_element(By.LINK_TEXT, "Run page")
        assert (
            "Closed" in state.text,
            run_page.get_attribute("href"),
            upload_links,
        ) == (True, RUN_PAGE, [])

    def test_create_form_offers_only_the_open_shuttle(self):
        """The new-project shuttle list has the open run and not the closed one."""
        self.login()
        self.navigate_to(self.driver, "/projects/create/")
        select = Select(self.wait_for_element(self.driver, (By.ID, "id_shuttle")))

        offered = {option.get_attribute("value") for option in select.options}

        assert (
            str(self.open_shuttle.pk) in offered,
            str(self.closed_shuttle.pk) in offered,
        ) == (True, False)
