"""Browser tests for notification UI functionality."""

import time

import pytest
from allauth.account.models import EmailAddress
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait

from tests.browser.base import BaseBrowserTest
from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.notifications.models import Notification
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.users.models import User

# Test fixture constants
TEST_USER_AUTH = "testpass123"  # Authentication credential for test users


@pytest.mark.browser
class TestNotificationUI(BaseBrowserTest):
    """Test notification UI displays and interactions."""

    @pytest.fixture(autouse=True)
    def setup(self, driver, live_server):
        """Set up test with authenticated user and notifications."""
        self.driver = driver
        self.live_server_url = live_server.url

        # Create test user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_USER_AUTH,
        )

        # Verify email address (required for login)
        EmailAddress.objects.create(
            user=self.user,
            email="test@example.com",
            verified=True,
            primary=True,
        )

        # Accept TOS for test user
        tos = TermsOfService.get_active()
        if tos:
            TermsOfServiceAcceptance.objects.create(
                user=self.user,
                tos_version=tos,
                ip_address="127.0.0.1",
            )

        # Create test project and file for notifications
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project for notifications",
        )

        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            original_filename="test.gds",
            file_size=1024,
            is_active=True,
        )

    def login(self):
        """Log in as test user."""
        self.navigate_to(self.driver, "/accounts/login/")
        username_input = self.wait_for_element(self.driver, (By.NAME, "login"))
        password_input = self.driver.find_element(By.NAME, "password")

        username_input.send_keys("testuser")
        password_input.send_keys(TEST_USER_AUTH)

        # Capture current URL before submitting
        current_url = self.driver.current_url

        submit_button = self.driver.find_element(
            By.CSS_SELECTOR,
            'button[type="submit"]',
        )
        submit_button.click()

        # Wait for redirect away from login page (login success)
        wait = WebDriverWait(self.driver, 10)
        wait.until(expected_conditions.url_changes(current_url))

    def test_notification_bell_displays_in_navbar(self):
        """Test that notification bell icon displays in navbar when authenticated."""
        self.login()
        self.navigate_to(self.driver, "/")

        # Check for notification bell icon (SVG)
        bell_icon = self.wait_for_element(
            self.driver,
            (By.CSS_SELECTOR, "svg.bi-bell"),
        )
        assert bell_icon.is_displayed()

    def test_notification_bell_shows_unread_count(self):
        """Test that notification bell is accessible (no badge for now)."""
        # Create unread notification
        Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_COMPLETE,
            title="Test Notification",
            message="Test message",
            is_read=False,
        )

        self.login()
        self.navigate_to(self.driver, "/")

        # Check that notification link is accessible
        bell_link = self.wait_for_element(
            self.driver,
            (By.CSS_SELECTOR, "a[href='/notifications/']"),
        )
        assert bell_link.is_displayed()

    def test_notification_bell_no_badge_when_all_read(self):
        """Test that notification link is accessible when all notifications are read."""
        # Create read notification
        Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_COMPLETE,
            title="Test Notification",
            message="Test message",
            is_read=True,
        )

        self.login()
        self.navigate_to(self.driver, "/")

        # Check that notification link is accessible
        bell_link = self.wait_for_element(
            self.driver,
            (By.CSS_SELECTOR, "a[href='/notifications/']"),
        )
        assert bell_link.is_displayed()

    def test_notification_list_page_accessible(self):
        """Test that notification list page is accessible."""
        self.login()
        self.navigate_to(self.driver, "/notifications/")

        # Check page loaded successfully
        heading = self.wait_for_element(self.driver, (By.TAG_NAME, "h2"))
        assert "Notifications" in heading.text

    def test_notification_list_shows_notifications(self):
        """Test that notification list displays notifications."""
        # Create test notification
        Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_COMPLETE,
            title="Download Complete",
            message="Your file has been downloaded",
            is_read=False,
        )

        self.login()
        self.navigate_to(self.driver, "/notifications/")

        # Check notification appears in list
        notification_item = self.wait_for_element(
            self.driver,
            (By.CSS_SELECTOR, ".list-group-item"),
        )
        assert "Download Complete" in notification_item.text

    def test_unread_notification_highlighted(self):
        """Test that unread notifications are visually highlighted."""
        # Create unread notification
        Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_COMPLETE,
            title="Unread Notification",
            message="Test message",
            is_read=False,
        )

        self.login()
        self.navigate_to(self.driver, "/notifications/")

        # Check notification has highlighted styling
        notification_item = self.wait_for_element(
            self.driver,
            (By.CSS_SELECTOR, ".list-group-item-primary"),
        )
        assert "Unread Notification" in notification_item.text

    def test_clicking_notification_marks_as_read(self):
        """Test that clicking a notification marks it as read."""
        # Create unread notification
        notification = Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_COMPLETE,
            title="Test Notification",
            message="Test message",
            is_read=False,
        )

        self.login()
        self.navigate_to(self.driver, "/notifications/")

        # Click notification
        notification_link = self.wait_for_element(
            self.driver,
            (By.CSS_SELECTOR, ".list-group-item"),
        )
        notification_link.click()

        # Verify notification was marked as read in database
        notification.refresh_from_db()
        assert notification.is_read is True
        assert notification.read_at is not None

    def test_mark_all_as_read_button_displays(self):
        """Test mark all as read button displays when there are unread notifications."""
        # Create unread notifications
        Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_COMPLETE,
            title="Notification 1",
            message="Test message 1",
            is_read=False,
        )

        self.login()
        self.navigate_to(self.driver, "/notifications/")

        # Check for mark all as read button
        mark_all_button = self.wait_for_element(
            self.driver,
            (By.CSS_SELECTOR, 'button[type="submit"]'),
        )
        assert "Mark All as Read" in mark_all_button.text

    def test_mark_all_as_read_functionality(self):
        """Test that mark all as read button works correctly."""
        # Create multiple unread notifications
        Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_COMPLETE,
            title="Notification 1",
            message="Test message 1",
            is_read=False,
        )
        Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_FAILED,
            title="Notification 2",
            message="Test message 2",
            is_read=False,
        )

        self.login()
        self.navigate_to(self.driver, "/notifications/")

        # Click mark all as read
        mark_all_button = self.wait_for_element(
            self.driver,
            (By.CSS_SELECTOR, 'button[type="submit"]'),
        )
        mark_all_button.click()

        # Wait for page to reload and database to update
        # Retry up to 5 times with 1 second delay
        max_retries = 5
        for _attempt in range(max_retries):
            time.sleep(1)
            unread_count = Notification.objects.filter(
                user=self.user,
                is_read=False,
            ).count()
            if unread_count == 0:
                break

        # Final verification
        error_msg = (
            f"Expected 0 unread, got {unread_count} after {max_retries} attempts"
        )
        assert unread_count == 0, error_msg

    def test_filter_tabs_display(self):
        """Test that filter tabs (All, Unread, Read) display correctly."""
        self.login()
        self.navigate_to(self.driver, "/notifications/")

        # Check for filter tabs
        tabs = self.driver.find_elements(By.CSS_SELECTOR, ".nav-tabs .nav-link")
        tab_texts = [tab.text for tab in tabs]

        assert "All" in tab_texts
        assert any("Unread" in text for text in tab_texts)
        assert "Read" in tab_texts

    def test_unread_filter_shows_only_unread(self):
        """Test that unread filter shows only unread notifications."""
        # Create one read and one unread notification
        Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_COMPLETE,
            title="Unread Notification",
            message="Test message",
            is_read=False,
        )
        Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_FAILED,
            title="Read Notification",
            message="Test message",
            is_read=True,
        )

        self.login()
        self.navigate_to(self.driver, "/notifications/?status=unread")

        # Check only unread notification appears
        notification_items = self.driver.find_elements(
            By.CSS_SELECTOR,
            ".list-group-item",
        )
        assert len(notification_items) == 1
        assert "Unread Notification" in notification_items[0].text

    def test_empty_state_displays_when_no_notifications(self):
        """Test that empty state message displays when user has no notifications."""
        self.login()
        self.navigate_to(self.driver, "/notifications/")

        # Check for empty state alert
        alert = self.wait_for_element(self.driver, (By.CSS_SELECTOR, ".alert-info"))
        assert "No notifications" in alert.text

    def test_notification_type_badge_displays(self):
        """Test that notification type badge displays with correct styling."""
        # Create notification
        Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_COMPLETE,
            title="Test Notification",
            message="Test message",
            is_read=False,
        )

        self.login()
        self.navigate_to(self.driver, "/notifications/")

        # Check for badge with notification type (more specific selector)
        badges = self.driver.find_elements(By.CSS_SELECTOR, ".list-group-item .badge")
        badge_texts = [badge.text for badge in badges]
        assert "Download Complete" in badge_texts
