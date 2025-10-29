"""Browser tests for notification badge functionality."""

import pytest
from allauth.account.models import EmailAddress
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait

from tests.browser.base import BaseBrowserTest
from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.notifications.models import Notification
from wafer_space.users.models import User

TEST_USER_AUTH = "testpass123"


@pytest.mark.browser
class TestNotificationBadge(BaseBrowserTest):
    """Test notification badge display and behavior."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        """Set up test with authenticated user."""
        self.driver = driver
        self.live_server_url = live_server.url

        # Create test user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_USER_AUTH,
        )

        # Verify email
        EmailAddress.objects.create(
            user=self.user,
            email="test@example.com",
            verified=True,
            primary=True,
        )

        # Accept TOS
        tos = TermsOfService.get_active()
        if tos:
            TermsOfServiceAcceptance.objects.create(
                user=self.user,
                tos_version=tos,
                ip_address="127.0.0.1",
            )

    def login(self):
        """Log in as test user."""
        self.navigate_to(self.driver, "/accounts/login/")
        username_input = self.wait_for_element(self.driver, (By.NAME, "login"))
        password_input = self.driver.find_element(By.NAME, "password")

        username_input.send_keys("testuser")
        password_input.send_keys(TEST_USER_AUTH)

        current_url = self.driver.current_url
        submit_button = self.driver.find_element(
            By.CSS_SELECTOR,
            'button[type="submit"]',
        )
        submit_button.click()

        wait = WebDriverWait(self.driver, 10)
        wait.until(expected_conditions.url_changes(current_url))

    def test_badge_not_displayed_when_zero_unread(self):
        """Test that badge is hidden when there are no unread notifications."""
        self.login()
        self.navigate_to(self.driver, "/")

        # Check that bell exists but badge does not
        bell = self.wait_for_element(self.driver, (By.ID, "notification-bell"))
        assert bell is not None

        # Badge should not exist
        badges = self.driver.find_elements(By.ID, "notification-badge")
        assert len(badges) == 0

    def test_badge_displays_with_unread_count(self):
        """Test that badge displays with correct count."""
        # Create 3 unread notifications
        for i in range(3):
            Notification.objects.create(
                user=self.user,
                notification_type=Notification.Type.DOWNLOAD_COMPLETE,
                title=f"Notification {i}",
                message="Test message",
                is_read=False,
            )

        self.login()
        self.navigate_to(self.driver, "/")

        # Check badge exists and shows correct count
        badge = self.wait_for_element(self.driver, (By.ID, "notification-badge"))
        assert "3" in badge.text

    def test_badge_displays_99_plus_for_large_counts(self):
        """Test that badge shows '99+' for counts over 99."""
        # Create 105 unread notifications
        for i in range(105):
            Notification.objects.create(
                user=self.user,
                notification_type=Notification.Type.DOWNLOAD_COMPLETE,
                title=f"Notification {i}",
                message="Test message",
                is_read=False,
            )

        self.login()
        self.navigate_to(self.driver, "/")

        # Check badge shows 99+
        badge = self.wait_for_element(self.driver, (By.ID, "notification-badge"))
        assert "99+" in badge.text

    def test_bell_icon_color_changes_with_unread(self):
        """Test that bell icon changes color when there are unread notifications."""
        # Create 1 unread notification
        Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_COMPLETE,
            title="Test Notification",
            message="Test message",
            is_read=False,
        )

        self.login()
        self.navigate_to(self.driver, "/")

        # Check bell has 'has-unread' class
        bell = self.wait_for_element(self.driver, (By.ID, "notification-bell"))
        assert "has-unread" in bell.get_attribute("class")
