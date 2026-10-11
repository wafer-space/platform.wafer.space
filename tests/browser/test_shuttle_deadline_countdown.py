"""Browser test: deadline local time and countdown (issue #349)."""

import datetime
import re
from zoneinfo import ZoneInfo

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
READER_ZONE = "Australia/Adelaide"
LOCAL_TIME = (By.CSS_SELECTOR, "[data-shuttle-deadline] time[data-local-time]")
COUNTDOWN = (By.CSS_SELECTOR, "[data-shuttle-deadline] [data-countdown]")


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestShuttleDeadlineCountdown(BaseBrowserTest):
    """An owner sees the GDS deadline in their own zone, counting down."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        self.driver = driver
        self.live_server_url = live_server.url
        # The reader's browser is in Adelaide (ACDT in December).
        self.driver.execute_cdp_cmd(
            "Emulation.setTimezoneOverride",
            {"timezoneId": READER_ZONE},
        )
        self.user = User.objects.create_user(
            username="deadline_owner",
            email="deadline_owner@example.com",
            password=TEST_USER_AUTH,
        )
        EmailAddress.objects.create(
            user=self.user,
            email="deadline_owner@example.com",
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

    def project_with_deadline(self, name: str, deadline: datetime.datetime) -> Project:
        shuttle = Shuttle.objects.create(
            name=name,
            description="Open run",
            status=Shuttle.Status.OPEN,
            submission_deadline=deadline,
        )
        return Project.objects.create(user=self.user, name="Deadline", shuttle=shuttle)

    def login_and_open(self, project: Project) -> None:
        self.navigate_to(self.driver, "/accounts/login/")
        self.wait_for_element(self.driver, (By.NAME, "login")).send_keys(
            "deadline_owner",
        )
        self.driver.find_element(By.NAME, "password").send_keys(TEST_USER_AUTH)
        current_url = self.driver.current_url
        self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        WebDriverWait(self.driver, 10).until(
            expected_conditions.url_changes(current_url),
        )
        self.navigate_to(self.driver, f"/projects/{project.pk}/")
        self.wait_for_page_load(self.driver)

    def wait_for_text(self, locator: tuple[str, str], marker: str) -> str:
        """Wait until the element's text contains marker (set by the script)."""

        def text_with_marker(driver):
            text = driver.find_element(*locator).text
            return text if marker in text else False

        return WebDriverWait(self.driver, 10).until(text_with_marker)

    def test_local_time_and_ticking_countdown(self):
        deadline = (
            timezone.now() + datetime.timedelta(days=3, hours=5, minutes=30)
        ).replace(microsecond=0)
        project = self.project_with_deadline("G891", deadline)
        self.login_and_open(project)

        local = deadline.astimezone(ZoneInfo(READER_ZONE))
        expected_local = f"{local.day} {local:%B %Y}, {local:%H:%M}"
        local_text = self.wait_for_text(LOCAL_TIME, "(")
        assert expected_local in local_text, local_text
        assert f"({READER_ZONE})" in local_text

        first = self.wait_for_text(COUNTDOWN, " s left")
        assert re.match(r"3 days 5 h (29|30) m \d+ s left", first), first
        WebDriverWait(self.driver, 5).until(
            lambda d: d.find_element(*COUNTDOWN).text != first,
        )

        severe = [
            log
            for log in self.get_console_logs(self.driver)
            if log.get("level") == "SEVERE" and "favicon" not in log.get("message", "")
        ]
        assert not severe, f"JS errors: {severe}"

    def test_countdown_switches_to_deadline_passed(self):
        deadline = timezone.now() + datetime.timedelta(seconds=20)
        project = self.project_with_deadline("G892", deadline)
        self.login_and_open(project)

        WebDriverWait(self.driver, 40).until(
            lambda d: d.find_elements(
                By.CSS_SELECTOR,
                "[data-shuttle-deadline] [data-deadline-passed]",
            ),
        )
        badge = self.driver.find_element(
            By.CSS_SELECTOR,
            "[data-shuttle-deadline] [data-deadline-passed]",
        )
        assert badge.text == "Deadline passed"
        assert not self.driver.find_elements(*COUNTDOWN)
