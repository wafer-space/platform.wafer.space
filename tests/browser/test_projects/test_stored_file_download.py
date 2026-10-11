"""Browser test: download the stored input layout (issue #254)."""

from http import HTTPStatus

import pytest
from allauth.account.models import EmailAddress
from django.core.files.base import ContentFile
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

from tests.browser.base import BaseBrowserTest
from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.users.models import User

TEST_USER_AUTH = "testpass123"  # Authentication credential for test users
CONTENT = "GDSII stand-in bytes"
FETCH_LINK = """
const done = arguments[arguments.length - 1];
const link = document.querySelector('[data-stored-file-download]');
fetch(link.href, {credentials: 'same-origin'})
  .then(async (r) => done({
    status: r.status,
    disposition: r.headers.get('Content-Disposition'),
    body: await r.text(),
  }))
  .catch((e) => done({error: String(e)}));
"""


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestStoredFileDownload(BaseBrowserTest):
    """The project page links the stored copy and the link serves it."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        self.driver = driver
        self.live_server_url = live_server.url
        self.user = User.objects.create_user(
            username="downloader",
            email="downloader@example.com",
            password=TEST_USER_AUTH,
        )
        EmailAddress.objects.create(
            user=self.user,
            email="downloader@example.com",
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
        self.project = Project.objects.create(user=self.user, name="Stored layout")
        revision = ProjectFile.objects.create(
            project=self.project,
            source_url="https://example.com/chip_top.gds",
            original_filename="chip_top.gds",
            is_active=True,
        )
        revision.file.save("chip_top.gds", ContentFile(CONTENT.encode()), save=True)

    def login(self):
        self.navigate_to(self.driver, "/accounts/login/")
        self.wait_for_element(self.driver, (By.NAME, "login")).send_keys("downloader")
        self.driver.find_element(By.NAME, "password").send_keys(TEST_USER_AUTH)
        current_url = self.driver.current_url
        self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        WebDriverWait(self.driver, 10).until(
            expected_conditions.url_changes(current_url),
        )

    def test_link_serves_stored_copy(self):
        self.login()
        self.navigate_to(self.driver, f"/projects/{self.project.pk}/")
        self.wait_for_element(
            self.driver,
            (By.CSS_SELECTOR, "[data-stored-file-download]"),
        )

        result = self.driver.execute_async_script(FETCH_LINK)

        assert result.get("status") == HTTPStatus.OK, result
        assert result["body"] == CONTENT
        assert result["disposition"] == 'attachment; filename="chip_top.gds"'
