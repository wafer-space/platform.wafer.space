"""Browser tests for the CrowdSupply campaign link on the project form."""

import pytest
from allauth.account.models import EmailAddress
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait

from tests.browser.base import BaseBrowserTest
from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.models import User

# Test fixture constants
TEST_USER_AUTH = "testpass123"  # Authentication credential for test users

RUN_1_URL = "https://www.crowdsupply.com/wafer-space/gf180mcu-run-1/"
RUN_2_URL = "https://www.crowdsupply.com/wafer-space/gf180mcu-run-2/"


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestCrowdSupplyCampaignLink(BaseBrowserTest):
    """The form's CrowdSupply label link follows the shuttle selection."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        """Set up an authenticated user and shuttles with/without URLs."""
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

        self.linked_shuttle = Shuttle.objects.create(
            name="G870",
            description="Linked run one",
            status=Shuttle.Status.OPEN,
            crowd_supply_url=RUN_1_URL,
        )
        self.plain_shuttle = Shuttle.objects.create(
            name="G871",
            description="Run without campaign",
            status=Shuttle.Status.OPEN,
        )
        self.other_linked_shuttle = Shuttle.objects.create(
            name="G872",
            description="Linked run two",
            status=Shuttle.Status.OPEN,
            crowd_supply_url=RUN_2_URL,
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

    def _select_shuttle(self, shuttle):
        """Pick a shuttle in the form's dropdown by primary key."""
        select = Select(self.driver.find_element(By.ID, "id_shuttle"))
        select.select_by_value(str(shuttle.pk))

    def _campaign_link_href(self):
        """Return the label anchor's href, or None when it has none."""
        link = self.driver.find_element(By.ID, "crowd-supply-campaign-link")
        return link.get_attribute("href")

    def test_label_link_follows_shuttle_selection(self):
        """Changing the shuttle retargets (or clears) the label link."""
        self.login()
        self.navigate_to(self.driver, "/projects/create/")
        self.wait_for_page_load(self.driver)
        self.wait_for_element(self.driver, (By.ID, "crowd-supply-campaign-link"))

        wait = WebDriverWait(self.driver, 10)

        self._select_shuttle(self.linked_shuttle)
        wait.until(lambda _: self._campaign_link_href() == RUN_1_URL)

        self._select_shuttle(self.plain_shuttle)
        wait.until(lambda _: self._campaign_link_href() is None)

        self._select_shuttle(self.other_linked_shuttle)
        wait.until(lambda _: self._campaign_link_href() == RUN_2_URL)

    def test_no_javascript_syntax_errors_on_create_page(self):
        """The create page loads without JS syntax errors.

        Regression guard: a duplicate 'const shuttleField' declaration once
        raised an uncaught SyntaxError that killed the whole inline script
        block (including the pre-existing slot-size and project-id logic).
        """
        self.login()
        self.navigate_to(self.driver, "/projects/create/")
        self.wait_for_page_load(self.driver)

        logs = self.get_console_logs(self.driver)
        syntax_errors = [
            log
            for log in logs
            if log.get("level") == "SEVERE" and "SyntaxError" in log.get("message", "")
        ]
        assert not syntax_errors, f"JS syntax errors on page: {syntax_errors}"
