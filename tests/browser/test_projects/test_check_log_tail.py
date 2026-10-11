"""Browser test: a running check shows only its log tail (issue #308)."""

from http import HTTPStatus

import pytest
from allauth.account.models import EmailAddress
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

from tests.browser.base import BaseBrowserTest
from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.users.models import User

TEST_USER_AUTH = "testpass123"  # Authentication credential for test users
TAIL_CHARS = 2000
POLL_WAIT_SECONDS = 20  # the page polls every 5 seconds
FIRST_LINE = "FIRST LINE OF THE RUN"
LAST_LINE = "LAST LINE SO FAR"
NEW_LINE = "A LINE WRITTEN WHILE THE PAGE WAS OPEN"
FETCH_FULL_LOG = """
const done = arguments[arguments.length - 1];
const link = document.querySelector('[data-full-log-link]');
fetch(link.href, {credentials: 'same-origin'})
  .then(async (r) => done({status: r.status, body: await r.text()}))
  .catch((e) => done({error: String(e)}));
"""


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestCheckLogTail(BaseBrowserTest):
    """The page and its polling carry the tail; the link serves the rest."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server, settings):
        settings.LOG_TAIL_CHARS = TAIL_CHARS
        self.driver = driver
        self.live_server_url = live_server.url
        self.user = User.objects.create_user(
            username="logwatcher",
            email="logwatcher@example.com",
            password=TEST_USER_AUTH,
        )
        EmailAddress.objects.create(
            user=self.user,
            email="logwatcher@example.com",
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
        self.project = Project.objects.create(user=self.user, name="Long log")
        revision = ProjectFile.objects.create(
            project=self.project,
            source_url="https://example.com/chip_top.gds",
            original_filename="chip_top.gds",
            is_active=True,
        )
        self.logs = FIRST_LINE + "\n" + "drc step\n" * 1000 + LAST_LINE + "\n"
        self.check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=revision,
            status=ManufacturabilityCheck.Status.RUNNING,
            processing_logs=self.logs,
        )

    def login(self):
        self.navigate_to(self.driver, "/accounts/login/")
        self.wait_for_element(self.driver, (By.NAME, "login")).send_keys("logwatcher")
        self.driver.find_element(By.NAME, "password").send_keys(TEST_USER_AUTH)
        current_url = self.driver.current_url
        self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        WebDriverWait(self.driver, 10).until(
            expected_conditions.url_changes(current_url),
        )

    def _open_project(self) -> str:
        self.login()
        self.navigate_to(self.driver, f"/projects/{self.project.pk}/")
        return self.wait_for_element(
            self.driver, (By.ID, "processing-logs")
        ).get_attribute("textContent")

    def test_page_shows_only_the_tail_with_a_note(self):
        """The newest lines are shown; the start is behind the Full log link."""
        shown = self._open_project()
        note = self.driver.find_element(By.ID, "processing-logs-truncated")

        assert (LAST_LINE in shown, FIRST_LINE in shown, note.is_displayed()) == (
            True,
            False,
            True,
        )

    def test_full_log_link_serves_the_whole_log(self):
        """The link returns every line, through the permission check."""
        self._open_project()

        result = self.driver.execute_async_script(FETCH_FULL_LOG)

        assert (result.get("status"), result.get("body")) == (
            HTTPStatus.OK,
            self.logs,
        ), result

    def test_polling_replaces_the_tail(self):
        """Lines written while the page is open appear without a reload."""
        self._open_project()
        ManufacturabilityCheck.objects.filter(pk=self.check.pk).update(
            processing_logs=self.logs + NEW_LINE + "\n"
        )

        WebDriverWait(self.driver, POLL_WAIT_SECONDS).until(
            expected_conditions.text_to_be_present_in_element(
                (By.ID, "processing-logs"), NEW_LINE
            )
        )
