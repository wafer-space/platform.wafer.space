"""Browser test: owners are warned near the GDS deadline (issue #347)."""

import datetime

import pytest
from allauth.account.models import EmailAddress
from django.utils import timezone
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
BANNER = (By.CSS_SELECTOR, '[data-deadline-warning="urgent"]')


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestDeadlineWarning(BaseBrowserTest):
    """A project due in two days, with nothing submitted."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        self.driver = driver
        self.live_server_url = live_server.url
        self.user = User.objects.create_user(
            username="late_owner",
            email="late_owner@example.com",
            password=TEST_USER_AUTH,
        )
        EmailAddress.objects.create(
            user=self.user,
            email="late_owner@example.com",
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
        shuttle = Shuttle.objects.create(
            name="G895",
            description="Open run",
            status=Shuttle.Status.OPEN,
            submission_deadline=timezone.now() + datetime.timedelta(days=2),
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Nearly late",
            shuttle=shuttle,
        )

    def login(self):
        self.navigate_to(self.driver, "/accounts/login/")
        self.wait_for_element(self.driver, (By.NAME, "login")).send_keys("late_owner")
        self.driver.find_element(By.NAME, "password").send_keys(TEST_USER_AUTH)
        current_url = self.driver.current_url
        self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        WebDriverWait(self.driver, 10).until(
            expected_conditions.url_changes(current_url),
        )

    def test_banner_on_project_page_and_alert_on_list(self):
        self.login()
        self.navigate_to(self.driver, f"/projects/{self.project.pk}/")
        banner = self.wait_for_element(self.driver, BANNER)
        assert "no file submitted for manufacturing yet" in banner.text
        assert "Submit a file URL" in banner.text
        WebDriverWait(self.driver, 10).until(
            lambda d: " s left" in d.find_element(*BANNER).text,
        )

        self.navigate_to(self.driver, "/projects/")
        alert = self.wait_for_element(
            self.driver,
            (By.CSS_SELECTOR, "[data-deadline-alert]"),
        )
        assert "Nearly late" in alert.text
        assert "Urgent" in alert.text
