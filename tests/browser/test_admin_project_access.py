"""Browser tests for admin project access functionality."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions

from tests.browser.base import AuthenticatedBrowserTest
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectAccessLog

User = get_user_model()

pytestmark = [pytest.mark.browser, pytest.mark.django_db]


TEST_PASSWORD = "testpass123"  # noqa: S105


@pytest.fixture
def owner(db):
    """Create project owner user."""
    return User.objects.create_user(
        username="owner",
        email="owner@example.com",
        password=TEST_PASSWORD,
    )


@pytest.fixture
def staff_user(db):
    """Create staff user."""
    return User.objects.create_user(
        username="admin",
        email="admin@example.com",
        password=TEST_PASSWORD,
        is_staff=True,
    )


@pytest.fixture
def project(owner):
    """Create test project."""
    return Project.objects.create(
        user=owner,
        name="Test Project",
        description="Test description",
    )


class TestAdminProjectAccess(AuthenticatedBrowserTest):
    """Test admin access to other users' projects."""

    @pytest.fixture(autouse=True)
    def setup(self, live_server):
        """Set up test fixtures."""
        self.live_server_url = live_server.url

    def perform_login(self, driver, username, password, wait):
        """Perform login using Django test client to establish session cookie.

        This approach is more reliable than Selenium form submission because:
        1. Django test client creates a proper session in the database
        2. We extract the session cookie and transfer it to Selenium
        3. Session persists reliably across page navigation
        """
        # Create Django test client
        client = Client()

        # Perform login using Django test client (creates session in database)
        login_successful = client.login(username=username, password=password)
        if not login_successful:
            msg = f"Failed to login user {username}"
            raise AssertionError(msg)

        # Extract session cookie from Django test client
        session_cookie = client.cookies.get("sessionid")
        if not session_cookie:
            msg = "No session cookie found after login"
            raise AssertionError(msg)

        # Navigate to the site first (required to set cookie)
        driver.get(f"{self.live_server_url}/")

        # Transfer session cookie to Selenium WebDriver
        driver.add_cookie(
            {
                "name": "sessionid",
                "value": session_cookie.value,
                "path": "/",
                "secure": False,
                "httpOnly": True,
            }
        )

        # Verify session is active by navigating to a page that requires auth
        driver.get(f"{self.live_server_url}/accounts/confirm-email/")

    def test_staff_user_sees_warning_banner(self, driver, staff_user, project, wait):
        """Test that staff user sees warning banner on other user's project."""
        # Login as staff user
        self.perform_login(driver, "admin", TEST_PASSWORD, wait)

        # Navigate to owner's project
        driver.get(f"{self.live_server_url}/projects/{project.pk}/")

        # Verify warning banner visible
        banner = wait.until(
            expected_conditions.presence_of_element_located(
                (By.CSS_SELECTOR, ".alert-warning")
            )
        )
        assert "Admin Mode" in banner.text
        assert "owner's project" in banner.text
        assert "logged for audit purposes" in banner.text

    def test_owner_does_not_see_warning_banner(self, driver, owner, project, wait):
        """Test that project owner does NOT see warning banner."""
        # Login as owner
        self.perform_login(driver, "owner", TEST_PASSWORD, wait)

        # Navigate to own project
        driver.get(f"{self.live_server_url}/projects/{project.pk}/")

        # Verify NO warning banner
        banners = driver.find_elements(By.CSS_SELECTOR, ".alert-warning")
        assert len(banners) == 0

    def test_staff_user_sees_all_projects_in_list(
        self, driver, staff_user, project, wait
    ):
        """Test that staff user sees all users' projects in list view."""
        # Create another project for staff user
        Project.objects.create(
            user=staff_user,
            name="Admin Project",
            description="Admin description",
        )

        # Login as staff user
        self.perform_login(driver, "admin", TEST_PASSWORD, wait)

        # Navigate to project list
        driver.get(f"{self.live_server_url}/projects/")

        # Verify both projects visible
        page_text = driver.find_element(By.TAG_NAME, "body").text
        assert "Test Project" in page_text
        assert "Admin Project" in page_text

    def test_regular_user_sees_only_own_projects(self, driver, owner, staff_user, wait):
        """Test that regular user only sees their own projects in list."""
        # Create projects for both users
        Project.objects.create(
            user=owner,
            name="Owner Project",
            description="Owner description",
        )
        Project.objects.create(
            user=staff_user,
            name="Admin Project",
            description="Admin description",
        )

        # Login as owner
        self.perform_login(driver, "owner", TEST_PASSWORD, wait)

        # Navigate to project list
        driver.get(f"{self.live_server_url}/projects/")

        # Verify only own project visible
        page_text = driver.find_element(By.TAG_NAME, "body").text
        assert "Owner Project" in page_text
        assert "Admin Project" not in page_text

    def test_staff_user_can_edit_other_users_project(
        self, driver, staff_user, project, wait
    ):
        """Test that staff user can edit another user's project."""
        # Login as staff user
        self.perform_login(driver, "admin", TEST_PASSWORD, wait)

        # Navigate to update page
        driver.get(f"{self.live_server_url}/projects/{project.pk}/update/")

        # Verify warning banner present
        banner = wait.until(
            expected_conditions.presence_of_element_located(
                (By.CSS_SELECTOR, ".alert-warning")
            )
        )
        assert "Admin Mode" in banner.text

        # Edit project name
        name_field = driver.find_element(By.ID, "id_name")
        name_field.clear()
        name_field.send_keys("Updated by Admin")

        # Submit form
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

        # Wait for redirect to detail page with success message
        success_alert = wait.until(
            expected_conditions.presence_of_element_located(
                (By.CSS_SELECTOR, ".alert-success")
            )
        )

        # Verify success message contains the updated project name
        assert "Updated by Admin" in success_alert.text

    def test_audit_log_created_on_staff_user_access(
        self, driver, staff_user, project, wait
    ):
        """Test that audit log is created when staff user views project."""
        # Verify no logs initially
        assert ProjectAccessLog.objects.count() == 0

        # Login as staff user
        self.perform_login(driver, "admin", TEST_PASSWORD, wait)

        # Navigate to owner's project
        driver.get(f"{self.live_server_url}/projects/{project.pk}/")

        # Verify audit log created
        logs = ProjectAccessLog.objects.filter(
            project=project,
            admin_user=staff_user,
        )
        assert logs.count() == 1

        log = logs.first()
        assert log.action == ProjectAccessLog.Action.VIEW
        assert log.view_name == "ProjectDetailView"

    def test_regular_user_denied_access_not_logged(self, driver, owner, project, wait):
        """Test that regular user denied access is NOT logged.

        Only staff users being denied should create audit logs because:
        1. Regular users being denied is expected behavior (not their project)
        2. ProjectAccessLog.admin_user has on_delete=PROTECT which would make
           all logged users undeletable
        """
        # Create another regular user
        User.objects.create_user(
            username="otheruser",
            email="otheruser@example.com",
            password=TEST_PASSWORD,
        )

        # Verify no logs initially
        assert ProjectAccessLog.objects.count() == 0

        # Login as other user (not owner)
        self.perform_login(driver, "otheruser", TEST_PASSWORD, wait)

        # Attempt to navigate to owner's project (will be denied with 403)
        driver.get(f"{self.live_server_url}/projects/{project.pk}/")

        # Verify NO denied access log created for regular user
        assert ProjectAccessLog.objects.count() == 0
