"""Browser tests for the locked core fields on the project edit page."""

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

# Test fixture constants
TEST_USER_AUTH = "testpass123"  # Authentication credential for test users


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestLockedCoreFields(BaseBrowserTest):
    """Non-staff owners see locked core fields as static values (issue #297)."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        """Set up an owner whose project sits on a completed shuttle."""
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

        self.open_shuttle = Shuttle.objects.create(
            name="G880",
            description="Open run",
            status=Shuttle.Status.OPEN,
        )
        self.completed_shuttle = Shuttle.objects.create(
            name="G890",
            description="Completed run",
            status=Shuttle.Status.COMPLETED,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Locked Fields Project",
            shuttle=self.completed_shuttle,
            project_id="LOCK",
        )

    def login(self):
        """Log in as the project owner."""
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

    def test_locked_fields_show_static_values_and_save_works(self):
        """The edit page shows the real shuttle as static text and still saves.

        Regression test for issue #297: the page used to render the locked
        shuttle as a dropdown showing the first OPEN shuttle instead of the
        project's own (completed) shuttle, and saving failed with "Select a
        valid choice".
        """
        self.login()
        self.navigate_to(self.driver, f"/projects/{self.project.pk}/update/")
        self.wait_for_page_load(self.driver)
        self.wait_for_element(self.driver, (By.ID, "id_name"))

        # Locked core fields render as static text, not form inputs.
        assert not self.driver.find_elements(By.ID, "id_shuttle")
        assert not self.driver.find_elements(By.ID, "id_project_id")
        assert not self.driver.find_elements(By.ID, "id_slot_size")

        # The static display shows the project's own (completed) shuttle,
        # not the first open shuttle, with a lock icon per field.
        page_text = self.driver.find_element(By.TAG_NAME, "body").text
        assert "G890 - Completed run" in page_text
        assert "G880 - Open run" not in page_text
        card = self.driver.find_element(By.CSS_SELECTOR, ".card-body")
        lock_icons = card.find_elements(By.CSS_SELECTOR, "i.bi-lock")
        min_lock_icons = 4  # banner + shuttle + project ID + slot size
        assert len(lock_icons) >= min_lock_icons

        # User fields still save even though the shuttle is closed.
        # Typed-and-verified: a lost keystroke leaves the required name
        # empty and client-side validation silently blocks the submit.
        self.set_input_value(self.driver, (By.ID, "id_name"), "Renamed Via Browser")
        current_url = self.driver.current_url
        submit_button = self.driver.find_element(
            By.CSS_SELECTOR, 'button[type="submit"]'
        )
        # JS click: the button can sit below the fold behind fixed UI
        # (same approach as test_admin_project_access).
        self.driver.execute_script("arguments[0].click();", submit_button)

        wait = WebDriverWait(self.driver, 10)
        wait.until(expected_conditions.url_changes(current_url))

        self.project.refresh_from_db()
        assert self.project.name == "Renamed Via Browser"
        assert self.project.shuttle == self.completed_shuttle
