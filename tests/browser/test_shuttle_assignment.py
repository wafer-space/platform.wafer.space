"""Browser tests for shuttle slot assignment functionality."""

import time

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions

from tests.browser.base import AuthenticatedBrowserTest
from wafer_space.core.enums import SlotSize
from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectComplianceCertification
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot

User = get_user_model()

pytestmark = [pytest.mark.browser, pytest.mark.django_db]


TEST_PASSWORD = "testpass123"  # noqa: S105


@pytest.fixture
def tos(db):
    """Get or create active TOS version."""
    # Note: Content comes from markdown files, only set required fields
    # Use get_or_create since conftest may have already created one
    tos, _ = TermsOfService.objects.get_or_create(
        version="1.0.0",
        defaults={"is_active": True},
    )
    return tos


@pytest.fixture
def staff_user(db, tos):
    """Create staff user with TOS accepted."""
    user = User.objects.create_user(
        username="staffuser",
        email="staff@example.com",
        password=TEST_PASSWORD,
        is_staff=True,
    )
    TermsOfServiceAcceptance.objects.create(user=user, tos_version=tos)
    return user


@pytest.fixture
def regular_user(db, tos):
    """Create regular user with TOS accepted."""
    user = User.objects.create_user(
        username="regularuser",
        email="regular@example.com",
        password=TEST_PASSWORD,
    )
    TermsOfServiceAcceptance.objects.create(user=user, tos_version=tos)
    return user


@pytest.fixture
def shuttle(db):
    """Create test shuttle with grid."""
    shuttle = Shuttle.objects.create(
        name="G894",
        description="Test Shuttle for Browser Tests",
        status=Shuttle.Status.OPEN,
    )
    # Create a small 2x2 grid
    for row in range(2):
        for col in range(2):
            ShuttleSlot.objects.create(
                shuttle=shuttle,
                row=row,
                column=col,
                slot_size=SlotSize.FULL,
                status=ShuttleSlot.Status.AVAILABLE,
            )
    return shuttle


@pytest.fixture
def project_with_compliance(staff_user, shuttle):
    """Create project with compliance certification."""
    project = Project.objects.create(
        user=staff_user,
        name="Compliant Project",
        description="Test project with compliance",
        shuttle=shuttle,
        project_id="COMP",
        slot_size=SlotSize.FULL,
    )
    ProjectComplianceCertification.objects.create(
        project=project,
        export_control_compliant=True,
        not_restricted_entity=True,
        end_use_statement="Test end use statement",
        certified_by=staff_user,
    )
    return project


class TestShuttleAssignmentDashboard(AuthenticatedBrowserTest):
    """Test shuttle assignment dashboard functionality."""

    @pytest.fixture(autouse=True)
    def setup_test(self, live_server):
        """Set up test fixtures."""
        self.live_server_url = live_server.url

    def perform_login(self, driver, username, password):
        """Perform login using Django test client."""
        client = Client()
        login_successful = client.login(username=username, password=password)
        if not login_successful:
            msg = f"Failed to login user {username}"
            raise AssertionError(msg)

        session_cookie = client.cookies.get("sessionid")
        if not session_cookie:
            msg = "No session cookie found after login"
            raise AssertionError(msg)

        driver.get(f"{self.live_server_url}/")
        driver.add_cookie(
            {
                "name": "sessionid",
                "value": session_cookie.value,
                "path": "/",
            }
        )

    def test_staff_can_view_assignment_dashboard(
        self, driver, wait, staff_user, shuttle
    ):
        """Test that staff users can access the assignment dashboard."""
        self.perform_login(driver, staff_user.username, TEST_PASSWORD)

        # Navigate to assignment dashboard
        driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

        # Verify page loaded with shuttle name
        wait.until(
            expected_conditions.presence_of_element_located(
                (By.XPATH, f"//*[contains(text(), '{shuttle.name}')]")
            )
        )

        # Verify grid table exists
        grid_table = wait.until(
            expected_conditions.presence_of_element_located((By.ID, "grid-table"))
        )
        assert grid_table is not None

    def test_regular_user_cannot_access_dashboard(
        self, driver, wait, regular_user, shuttle
    ):
        """Test that regular users cannot access the assignment dashboard."""
        self.perform_login(driver, regular_user.username, TEST_PASSWORD)

        # Try to navigate to assignment dashboard
        driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

        # Should show 403 Forbidden page or redirect to login
        # Check that the grid table is NOT present (access denied)
        page_source = driver.page_source
        assert (
            "Forbidden" in page_source
            or "403" in page_source
            or "grid-table" not in page_source
        )

    def test_grid_shows_available_slots(self, driver, wait, staff_user, shuttle):
        """Test that grid displays available slots."""
        self.perform_login(driver, staff_user.username, TEST_PASSWORD)

        driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

        # Wait for grid to load
        grid_table = wait.until(
            expected_conditions.presence_of_element_located((By.ID, "grid-table"))
        )

        # Check that slot cells exist (should have 4 slots in 2x2 grid)
        expected_slot_count = 4  # 2x2 grid
        slot_cells = grid_table.find_elements(By.CSS_SELECTOR, "td[data-slot-id]")
        assert len(slot_cells) == expected_slot_count

    def test_grid_shows_assigned_projects(
        self, driver, wait, staff_user, shuttle, project_with_compliance
    ):
        """Test that grid shows assigned projects correctly."""
        # First assign the project to a slot
        slot = shuttle.slots.first()
        slot.reserve(project_with_compliance, staff_user)

        self.perform_login(driver, staff_user.username, TEST_PASSWORD)

        driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

        # Wait for grid to load
        grid_table = wait.until(
            expected_conditions.presence_of_element_located((By.ID, "grid-table"))
        )

        # Find the assigned slot (should have table-success class)
        assigned_slots = grid_table.find_elements(
            By.CSS_SELECTOR, "td.table-success[data-slot-id]"
        )
        assert len(assigned_slots) == 1

        # Verify project ID is shown
        assert project_with_compliance.project_id in assigned_slots[0].text

    def test_projects_table_shows_unassigned_projects(
        self, driver, wait, staff_user, shuttle, project_with_compliance
    ):
        """Test that projects table shows unassigned projects."""
        self.perform_login(driver, staff_user.username, TEST_PASSWORD)

        driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

        # Wait for projects table to load
        projects_table = wait.until(
            expected_conditions.presence_of_element_located((By.ID, "projects-table"))
        )

        # Check project is listed
        assert project_with_compliance.project_id in projects_table.text

    def test_slot_modal_opens_on_click(
        self, driver, wait, staff_user, shuttle, project_with_compliance
    ):
        """Test that clicking a slot opens the assignment modal."""
        self.perform_login(driver, staff_user.username, TEST_PASSWORD)

        driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

        # Wait for grid to load and click first available slot
        slot_cell = wait.until(
            expected_conditions.element_to_be_clickable(
                (By.CSS_SELECTOR, "td[data-slot-id]")
            )
        )
        slot_cell.click()

        # Verify modal opens
        modal = wait.until(
            expected_conditions.visibility_of_element_located((By.ID, "slotModal"))
        )
        assert modal.is_displayed()

        # Verify modal contains slot position
        modal_title = modal.find_element(By.CLASS_NAME, "modal-title")
        assert "Slot" in modal_title.text

    def test_assignment_summary_statistics(
        self, driver, wait, staff_user, shuttle, project_with_compliance
    ):
        """Test that assignment summary shows correct statistics."""
        self.perform_login(driver, staff_user.username, TEST_PASSWORD)

        driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

        # Wait for page to load - look for the Summary card header
        wait.until(
            expected_conditions.presence_of_element_located(
                (By.XPATH, "//strong[text()='Summary']")
            )
        )

        # Check for statistics table headers (Proj and Slots columns)
        page_source = driver.page_source
        assert ">Proj<" in page_source
        assert ">Slots<" in page_source

    def test_projects_table_shows_owner_column(
        self, driver, wait, staff_user, shuttle, project_with_compliance
    ):
        """Test that projects table shows owner column."""
        self.perform_login(driver, staff_user.username, TEST_PASSWORD)

        driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

        # Wait for projects table to load
        projects_table = wait.until(
            expected_conditions.presence_of_element_located((By.ID, "projects-table"))
        )

        # Check that Owner column header exists
        headers = projects_table.find_elements(By.CSS_SELECTOR, "thead th")
        header_texts = [h.text for h in headers]
        assert "Owner" in header_texts

        # Check that the owner username is shown in the table
        assert staff_user.username in projects_table.text

    def test_summary_shows_manufacturable_column(
        self, driver, wait, staff_user, shuttle, project_with_compliance
    ):
        """Test that summary table shows manufacturable column."""
        # Mark project as manufacturable
        project_with_compliance.is_manufacturable = True
        project_with_compliance.save()

        self.perform_login(driver, staff_user.username, TEST_PASSWORD)

        driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

        # Wait for page to load
        wait.until(
            expected_conditions.presence_of_element_located(
                (By.XPATH, "//strong[text()='Summary']")
            )
        )

        # Check for Mfg column header in summary table
        page_source = driver.page_source
        assert ">Mfg<" in page_source or "Mfg</th>" in page_source

    def test_grid_shows_manufacturing_indicators(
        self, driver, wait, staff_user, shuttle, project_with_compliance
    ):
        """Test that grid cells show manufacturing status indicators."""
        # Mark project as manufacturable and assign to slot
        project_with_compliance.is_manufacturable = True
        project_with_compliance.save()
        slot = shuttle.slots.first()
        slot.reserve(project_with_compliance, staff_user)

        self.perform_login(driver, staff_user.username, TEST_PASSWORD)

        driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

        # Wait for grid to load
        grid_table = wait.until(
            expected_conditions.presence_of_element_located((By.ID, "grid-table"))
        )

        # Find the assigned slot and check for manufacturing indicator
        assigned_slot = grid_table.find_element(
            By.CSS_SELECTOR, "td.table-success[data-slot-id]"
        )
        indicator = assigned_slot.find_element(By.CSS_SELECTOR, ".mfg-indicator")
        assert indicator is not None
        assert "✓" in indicator.text or "mfg-pass" in indicator.get_attribute("class")

    def test_table_columns_are_sortable(
        self, driver, wait, staff_user, shuttle, project_with_compliance
    ):
        """Test that clicking column headers sorts the table."""
        # Create a second project for sorting
        project2 = Project.objects.create(
            user=staff_user,
            name="Alpha Project",
            description="First alphabetically",
            shuttle=shuttle,
            project_id="ALPH",
            slot_size=SlotSize.FULL,
        )
        ProjectComplianceCertification.objects.create(
            project=project2,
            export_control_compliant=True,
            not_restricted_entity=True,
            end_use_statement="Test",
            certified_by=staff_user,
        )

        self.perform_login(driver, staff_user.username, TEST_PASSWORD)

        driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

        # Wait for projects table to load
        wait.until(
            expected_conditions.presence_of_element_located((By.ID, "projects-table"))
        )

        # Find the Name header and click to sort
        name_header = driver.find_element(
            By.XPATH, "//table[@id='projects-table']//th[contains(text(), 'Name')]"
        )
        assert "sortable" in name_header.get_attribute(
            "class"
        ) or name_header.get_attribute("data-sortable")

        name_header.click()

        # Wait a moment for sort to apply
        time.sleep(0.1)

        # Get first row's name - should be "Alpha Project" (alphabetically first)
        first_row = driver.find_element(
            By.CSS_SELECTOR, "#projects-table tbody tr:first-child"
        )
        assert "Alpha" in first_row.text

    def test_grid_uses_template_partial(self, driver, wait, staff_user, shuttle):
        """Test that grid renders correctly (implies template partial works)."""
        self.perform_login(driver, staff_user.username, TEST_PASSWORD)

        driver.get(f"{self.live_server_url}/shuttles/{shuttle.name}/assign/")

        # Wait for grid to load
        grid_table = wait.until(
            expected_conditions.presence_of_element_located((By.ID, "grid-table"))
        )

        # Verify grid has click handler attribute on cells
        slot_cells = grid_table.find_elements(By.CSS_SELECTOR, "td[data-slot-id]")
        assert len(slot_cells) > 0

        # All cells should have data-click-handler attribute
        for cell in slot_cells:
            assert cell.get_attribute("data-click-handler") is not None
