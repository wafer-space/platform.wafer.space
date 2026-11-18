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
from tests.browser.pages.project_list_page import ProjectListPage
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

        # The projects list shows the compact countdown in the shuttle column.
        self.navigate_to(self.driver, "/projects/")
        compact = self.wait_for_text(
            (By.CSS_SELECTOR, "[data-countdown-compact]"),
            " h left",
        )
        assert compact == "3 d 5 h left", compact

        severe = [
            log
            for log in self.get_console_logs(self.driver)
            if log.get("level") == "SEVERE" and "favicon" not in log.get("message", "")
        ]
        assert not severe, f"JS errors: {severe}"

    @pytest.mark.parametrize(
        "window_width",
        [1600, 800, 600, 390],
        ids=["wide", "tablet", "stacked", "phone"],
    )
    def test_compact_countdown_stays_inside_its_column(self, window_width):
        """The longest countdowns do not run over the state column (#465)."""
        now = timezone.now()
        remaining = {
            "G893": datetime.timedelta(days=128, hours=23, minutes=30),
            "G894": datetime.timedelta(days=29, hours=5, minutes=30),
            "G895": datetime.timedelta(hours=23, minutes=30),
        }
        projects = [
            self.project_with_deadline(name, now + left)
            for name, left in remaining.items()
        ]
        self.login_and_open(projects[0])
        self.driver.set_window_size(window_width, 900)

        page = ProjectListPage(self.driver, self.live_server_url).open()

        # The script has run (the page finished loading): these are its words.
        texts = page.compact_countdown_texts()
        assert {"128 d 23 h left", "29 d 5 h left"} < set(texts), texts
        assert any(re.fullmatch(r"23 h (29|30) m left", t) for t in texts), texts
        assert page.badges_outside_their_column() == []
        # One shuttle column for the whole list, not one per row.
        assert len(page.shuttle_column_lefts_and_widths()) == 1

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
