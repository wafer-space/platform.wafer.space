"""Browser tests for slot-size option labels on the project form."""

import pytest
from allauth.account.models import EmailAddress
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait

from tests.browser.base import BaseBrowserTest
from wafer_space.core.enums import SlotSize
from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.models import User

# Test fixture constants
TEST_USER_AUTH = "testpass123"  # Authentication credential for test users


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestSlotSizeLabels(BaseBrowserTest):
    """Slot-size options keep their full labels when the shuttle changes."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        """Set up an authenticated user and two open shuttles."""
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

        self.first_shuttle = Shuttle.objects.create(
            name="G880",
            description="First open run",
            status=Shuttle.Status.OPEN,
        )
        self.second_shuttle = Shuttle.objects.create(
            name="G881",
            description="Second open run",
            status=Shuttle.Status.OPEN,
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

    def _slot_size_labels(self):
        """Return the visible text of every slot-size option."""
        select = Select(self.driver.find_element(By.ID, "id_slot_size"))
        return [option.text for option in select.options]

    def test_slot_size_labels_survive_shuttle_change(self):
        """Changing the shuttle keeps the full slot-size descriptions.

        Regression test for issue #283: the AJAX endpoint that repopulates
        the dropdown returned the short enum labels ("1×1") instead of the
        full labels the form initially renders.
        """
        self.login()
        self.navigate_to(self.driver, "/projects/create/")
        self.wait_for_page_load(self.driver)
        self.wait_for_element(self.driver, (By.ID, "id_slot_size"))

        full_labels = [size.full_label for size in SlotSize]
        assert self._slot_size_labels() == full_labels

        # Tag the initially rendered options so the AJAX rebuild (which
        # replaces every <option>) is detectable even when labels match.
        self.driver.execute_script(
            "document.querySelectorAll('#id_slot_size option')"
            ".forEach((o) => o.setAttribute('data-initial', '1'));"
        )

        shuttle_select = Select(self.driver.find_element(By.ID, "id_shuttle"))
        shuttle_select.select_by_value(str(self.second_shuttle.pk))

        wait = WebDriverWait(self.driver, 10)
        wait.until(
            lambda d: d.execute_script(
                "return document.querySelectorAll("
                "'#id_slot_size option:not([data-initial])').length > 0;"
            )
        )

        assert self._slot_size_labels() == full_labels
