"""Browser test: the project description renders as safe markdown (#285)."""

import pytest
from allauth.account.models import EmailAddress
from django.urls import reverse
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

from tests.browser.base import BaseBrowserTest
from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.projects.models import Project
from wafer_space.users.models import User

TEST_USER_AUTH = "testpass123"  # Authentication credential for test users

# Every vector sets window.pwned if the browser ever runs it.
DESCRIPTION = (
    "A **ring oscillator** with *three* stages.\n\n"
    "- see [docs](https://wafer.space/)\n"
    "- [click me](javascript:window.pwned=1)\n\n"
    "<script>window.pwned=1</script>\n\n"
    '<img src=x onerror="window.pwned=1">'
)
LIST_ITEMS = 2  # The two bullets in DESCRIPTION.
DESCRIPTION_BODY = (
    By.XPATH,
    "//strong[normalize-space()='Description:']/following-sibling::div",
)


@pytest.mark.browser
@pytest.mark.django_db(transaction=True)
class TestDescriptionMarkdown(BaseBrowserTest):
    """The owner's page shows formatted text and runs none of the payloads."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        self.driver = driver
        self.live_server_url = live_server.url

        self.user = User.objects.create_user(
            username="describer",
            email="describer@example.com",
            password=TEST_USER_AUTH,
        )
        EmailAddress.objects.create(
            user=self.user,
            email="describer@example.com",
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
        self.project = Project.objects.create(
            user=self.user, name="Oscillator", description=DESCRIPTION
        )

    def login(self):
        self.navigate_to(self.driver, "/accounts/login/")
        username_input = self.wait_for_element(self.driver, (By.NAME, "login"))
        password_input = self.driver.find_element(By.NAME, "password")
        username_input.send_keys("describer")
        password_input.send_keys(TEST_USER_AUTH)
        current_url = self.driver.current_url
        self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
        WebDriverWait(self.driver, 10).until(
            expected_conditions.url_changes(current_url),
        )

    def pwned(self):
        return self.driver.execute_script("return window.pwned === 1;")

    def test_detail_page_renders_markdown_and_runs_no_payload(self):
        self.login()
        self.navigate_to(self.driver, f"/projects/{self.project.pk}/")
        body = self.wait_for_element(self.driver, DESCRIPTION_BODY)

        assert body.find_element(By.TAG_NAME, "strong").text == "ring oscillator"
        assert body.find_element(By.TAG_NAME, "em").text == "three"
        assert len(body.find_elements(By.TAG_NAME, "li")) == LIST_ITEMS
        docs = body.find_element(By.LINK_TEXT, "docs")
        assert docs.get_attribute("rel") == "nofollow noopener noreferrer"

        # Typed HTML is visible text, not elements.
        assert "<script>window.pwned=1</script>" in body.text
        assert body.find_elements(By.TAG_NAME, "img") == []

        # The javascript: link lost its href; clicking it runs nothing.
        body.find_element(By.XPATH, ".//a[normalize-space()='click me']").click()
        assert not self.pwned()

    def test_list_page_shows_a_plain_excerpt(self):
        self.login()
        self.navigate_to(self.driver, reverse("projects:list"))
        excerpt = self.wait_for_element(
            self.driver, (By.CSS_SELECTOR, ".list-group-item p.mb-1")
        )
        assert excerpt.text.startswith("A ring oscillator with three stages.")
        assert not self.pwned()
