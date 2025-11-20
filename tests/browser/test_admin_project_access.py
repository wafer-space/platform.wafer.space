"""Browser tests for admin project access functionality."""

import pytest
from django.contrib.auth import get_user_model
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
def superuser(db):
    """Create superuser."""
    return User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password=TEST_PASSWORD,
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
        """Perform login and wait for redirect."""
        # Navigate to login page
        driver.get(f"{self.live_server_url}/accounts/login/")

        # Fill in credentials
        username_field = wait.until(
            expected_conditions.presence_of_element_located((By.NAME, "login"))
        )
        username_field.send_keys(username)

        password_field = driver.find_element(By.NAME, "password")
        password_field.send_keys(password)

        # Submit form
        submit_button = driver.find_element(By.XPATH, "//button[@type='submit']")
        submit_button.click()

        # Wait for redirect after successful login
        wait.until(
            expected_conditions.url_changes(f"{self.live_server_url}/accounts/login/")
        )

    def test_superuser_sees_warning_banner(self, driver, superuser, project, wait):
        """Test that superuser sees warning banner on other user's project."""
        # Login as superuser
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

    def test_superuser_sees_all_projects_in_list(
        self, driver, superuser, project, wait
    ):
        """Test that superuser sees all users' projects in list view."""
        # Create another project for superuser
        Project.objects.create(
            user=superuser,
            name="Admin Project",
            description="Admin description",
        )

        # Login as superuser
        self.perform_login(driver, "admin", TEST_PASSWORD, wait)

        # Navigate to project list
        driver.get(f"{self.live_server_url}/projects/")

        # Verify both projects visible
        page_text = driver.find_element(By.TAG_NAME, "body").text
        assert "Test Project" in page_text
        assert "Admin Project" in page_text

    def test_regular_user_sees_only_own_projects(self, driver, owner, superuser, wait):
        """Test that regular user only sees their own projects in list."""
        # Create projects for both users
        Project.objects.create(
            user=owner,
            name="Owner Project",
            description="Owner description",
        )
        Project.objects.create(
            user=superuser,
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

    def test_superuser_can_edit_other_users_project(
        self, driver, superuser, project, wait
    ):
        """Test that superuser can edit another user's project."""
        # Login as superuser
        self.perform_login(driver, "admin", TEST_PASSWORD, wait)

        # Navigate to edit page
        driver.get(f"{self.live_server_url}/projects/{project.pk}/edit/")

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

        # Verify project updated
        project.refresh_from_db()
        assert project.name == "Updated by Admin"

    def test_audit_log_created_on_superuser_access(
        self, driver, superuser, project, wait
    ):
        """Test that audit log is created when superuser views project."""
        # Verify no logs initially
        assert ProjectAccessLog.objects.count() == 0

        # Login as superuser
        self.perform_login(driver, "admin", TEST_PASSWORD, wait)

        # Navigate to owner's project
        driver.get(f"{self.live_server_url}/projects/{project.pk}/")

        # Verify audit log created
        logs = ProjectAccessLog.objects.filter(
            project=project,
            admin_user=superuser,
        )
        assert logs.count() == 1

        log = logs.first()
        assert log.action == ProjectAccessLog.Action.VIEW
        assert log.view_name == "ProjectDetailView"
