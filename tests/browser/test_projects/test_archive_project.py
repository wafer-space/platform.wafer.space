"""Browser test: archive and unarchive a project (issue #307)."""

from datetime import timedelta

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
from wafer_space.users.models import User

TEST_USER_AUTH = "testpass123"  # Authentication credential for test users

PROJECT_TITLES = (By.CSS_SELECTOR, ".list-group-item h5 a.stretched-link")
ARCHIVED_BANNER = (By.CSS_SELECTOR, "[data-archived-banner]")


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestArchiveProject(BaseBrowserTest):
    """An owner archives a project and unarchives it again."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        """Create a logged-in-able owner with two projects."""
        self.driver = driver
        self.live_server_url = live_server.url

        self.user = User.objects.create_user(
            username="archiver",
            email="archiver@example.com",
            password=TEST_USER_AUTH,
        )
        EmailAddress.objects.create(
            user=self.user,
            email="archiver@example.com",
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

        now = timezone.now()
        self.newer = Project.objects.create(user=self.user, name="Keep me")
        self.older = Project.objects.create(user=self.user, name="Older one")
        Project.objects.filter(pk=self.newer.pk).update(created_at=now)
        Project.objects.filter(pk=self.older.pk).update(
            created_at=now - timedelta(days=1),
        )

    def login(self):
        """Log in as the owner."""
        self.navigate_to(self.driver, "/accounts/login/")
        username_input = self.wait_for_element(self.driver, (By.NAME, "login"))
        password_input = self.driver.find_element(By.NAME, "password")
        username_input.send_keys("archiver")
        password_input.send_keys(TEST_USER_AUTH)
        current_url = self.driver.current_url
        self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        WebDriverWait(self.driver, 10).until(
            expected_conditions.url_changes(current_url),
        )

    def listed_titles(self):
        """Project names on /projects/, in page order."""
        self.navigate_to(self.driver, "/projects/")
        self.wait_for_element(self.driver, PROJECT_TITLES)
        return [e.text for e in self.driver.find_elements(*PROJECT_TITLES)]

    def open_project(self, project):
        self.navigate_to(self.driver, f"/projects/{project.pk}/")
        self.wait_for_page_load(self.driver)

    def test_archive_round_trip(self):
        """Archive moves the project last and locks it; unarchive undoes it."""
        self.login()
        assert self.listed_titles() == ["Keep me", "Older one"]

        # Archive the newest project from its page (accept the confirm).
        self.open_project(self.newer)
        self.driver.execute_script("window.confirm = () => true;")
        self.driver.find_element(
            By.CSS_SELECTOR,
            f'form[action="/projects/{self.newer.pk}/archive/"] button',
        ).click()
        self.wait_for_element(self.driver, ARCHIVED_BANNER)

        # Read-only: Edit is a disabled button, not a link.
        edit = self.driver.find_element(
            By.XPATH,
            "//div[contains(@class,'card-header')]//button[contains(., 'Edit')]",
        )
        assert edit.get_attribute("disabled") is not None

        # Listed last, with the badge.
        assert self.listed_titles() == ["Older one", "Keep me"]
        badges = self.driver.find_elements(By.CSS_SELECTOR, "[data-archived-badge]")
        assert len(badges) == 1

        # Unarchive from the banner; the project returns to first place.
        self.open_project(self.newer)
        self.driver.find_element(
            By.CSS_SELECTOR,
            f'form[action="/projects/{self.newer.pk}/unarchive/"] button',
        ).click()
        WebDriverWait(self.driver, 10).until(
            lambda d: not d.find_elements(*ARCHIVED_BANNER),
        )
        assert self.listed_titles() == ["Keep me", "Older one"]

        # No JavaScript errors on the project page.
        self.open_project(self.newer)
        severe = [
            log
            for log in self.get_console_logs(self.driver)
            if log.get("level") == "SEVERE" and "favicon" not in log.get("message", "")
        ]
        assert not severe, f"JS errors on project page: {severe}"
