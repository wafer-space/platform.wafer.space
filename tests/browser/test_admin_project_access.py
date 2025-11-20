"""Browser tests for admin project access functionality."""

import pytest
from django.contrib.auth import get_user_model
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions

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


def test_superuser_sees_warning_banner(driver, live_server, superuser, project, wait):
    """Test that superuser sees warning banner on other user's project."""
    # Login as superuser
    driver.get(f"{live_server.url}/accounts/login/")
    driver.find_element(By.ID, "id_login").send_keys("admin")
    driver.find_element(By.ID, "id_password").send_keys("testpass123")
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

    # Wait for login to complete
    wait.until(expected_conditions.url_changes(f"{live_server.url}/accounts/login/"))

    # Navigate to owner's project
    driver.get(f"{live_server.url}/projects/{project.pk}/")

    # Verify warning banner visible
    banner = wait.until(
        expected_conditions.presence_of_element_located(
            (By.CSS_SELECTOR, ".alert-warning")
        )
    )
    assert "Admin Mode" in banner.text
    assert "owner's project" in banner.text
    assert "logged for audit purposes" in banner.text


def test_owner_does_not_see_warning_banner(driver, live_server, owner, project, wait):
    """Test that project owner does NOT see warning banner."""
    # Login as owner
    driver.get(f"{live_server.url}/accounts/login/")
    driver.find_element(By.ID, "id_login").send_keys("owner")
    driver.find_element(By.ID, "id_password").send_keys("testpass123")
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

    # Wait for login to complete
    wait.until(expected_conditions.url_changes(f"{live_server.url}/accounts/login/"))

    # Navigate to own project
    driver.get(f"{live_server.url}/projects/{project.pk}/")

    # Verify NO warning banner
    banners = driver.find_elements(By.CSS_SELECTOR, ".alert-warning")
    assert len(banners) == 0


def test_superuser_sees_all_projects_in_list(
    driver, live_server, superuser, project, wait
):
    """Test that superuser sees all users' projects in list view."""
    # Create another project for superuser
    Project.objects.create(
        user=superuser,
        name="Admin Project",
        description="Admin description",
    )

    # Login as superuser
    driver.get(f"{live_server.url}/accounts/login/")
    driver.find_element(By.ID, "id_login").send_keys("admin")
    driver.find_element(By.ID, "id_password").send_keys("testpass123")
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

    # Wait for login to complete
    wait.until(expected_conditions.url_changes(f"{live_server.url}/accounts/login/"))

    # Navigate to project list
    driver.get(f"{live_server.url}/projects/")

    # Verify both projects visible
    page_text = driver.find_element(By.TAG_NAME, "body").text
    assert "Test Project" in page_text
    assert "Admin Project" in page_text


def test_regular_user_sees_only_own_projects(
    driver, live_server, owner, superuser, wait
):
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
    driver.get(f"{live_server.url}/accounts/login/")
    driver.find_element(By.ID, "id_login").send_keys("owner")
    driver.find_element(By.ID, "id_password").send_keys("testpass123")
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

    # Wait for login to complete
    wait.until(expected_conditions.url_changes(f"{live_server.url}/accounts/login/"))

    # Navigate to project list
    driver.get(f"{live_server.url}/projects/")

    # Verify only own project visible
    page_text = driver.find_element(By.TAG_NAME, "body").text
    assert "Owner Project" in page_text
    assert "Admin Project" not in page_text


def test_superuser_can_edit_other_users_project(
    driver, live_server, superuser, project, wait
):
    """Test that superuser can edit another user's project."""
    # Login as superuser
    driver.get(f"{live_server.url}/accounts/login/")
    driver.find_element(By.ID, "id_login").send_keys("admin")
    driver.find_element(By.ID, "id_password").send_keys("testpass123")
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

    # Wait for login to complete
    wait.until(expected_conditions.url_changes(f"{live_server.url}/accounts/login/"))

    # Navigate to edit page
    driver.get(f"{live_server.url}/projects/{project.pk}/edit/")

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
    driver, live_server, superuser, project, wait
):
    """Test that audit log is created when superuser views project."""
    # Verify no logs initially
    assert ProjectAccessLog.objects.count() == 0

    # Login as superuser
    driver.get(f"{live_server.url}/accounts/login/")
    driver.find_element(By.ID, "id_login").send_keys("admin")
    driver.find_element(By.ID, "id_password").send_keys("testpass123")
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

    # Wait for login to complete
    wait.until(expected_conditions.url_changes(f"{live_server.url}/accounts/login/"))

    # Navigate to owner's project
    driver.get(f"{live_server.url}/projects/{project.pk}/")

    # Verify audit log created
    logs = ProjectAccessLog.objects.filter(
        project=project,
        admin_user=superuser,
    )
    assert logs.count() == 1

    log = logs.first()
    assert log.action == ProjectAccessLog.Action.VIEW
    assert log.view_name == "ProjectDetailView"
