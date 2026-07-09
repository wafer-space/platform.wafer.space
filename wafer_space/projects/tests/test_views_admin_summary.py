"""Tests for ProjectAdminSummaryView."""

import pytest
from django.urls import reverse

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.users.tests.factories import UserFactory

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_OK
from .factories import ProjectFactory
from .factories import ProjectFileFactory


@pytest.mark.django_db
class TestProjectAdminSummaryView:
    """Tests for the admin summary view."""

    def test_staff_can_access(self, client):
        """Staff users can access the summary page."""
        staff_user = UserFactory(is_staff=True)
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        assert response.status_code == HTTP_OK

    def test_non_staff_cannot_access(self, client):
        """Non-staff users are forbidden."""
        regular_user = UserFactory(is_staff=False)
        client.force_login(regular_user)

        response = client.get(reverse("projects:admin_summary"))

        assert response.status_code == HTTP_FORBIDDEN

    def test_anonymous_redirected_to_login(self, client):
        """Anonymous users are redirected to login."""
        response = client.get(reverse("projects:admin_summary"))

        assert response.status_code == HTTP_FOUND
        assert "/accounts/login/" in response.url

    def test_displays_project_data(self, client):
        """Summary page displays project data in table."""
        staff_user = UserFactory(is_staff=True)
        # Create a project with known data
        owner = UserFactory(username="testowner", email="owner@example.com")
        ProjectFactory(
            name="Test Project",
            user=owner,
            slot_size="1x1",
        )
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "Test Project" in content
        assert "testowner" in content
        assert "owner@example.com" in content
        assert (
            "1×1" in content
        )  # Uses × (multiplication sign) from get_slot_size_display

    def test_displays_all_projects(self, client):
        """Summary page shows all projects, not just user's own."""
        staff_user = UserFactory(is_staff=True)
        other_user = UserFactory()
        ProjectFactory(name="Staff Project", user=staff_user)
        ProjectFactory(name="Other Project", user=other_user)
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        content = response.content.decode()
        assert "Staff Project" in content
        assert "Other Project" in content

    def test_displays_precheck_status(self, client):
        """Summary page displays manufacturability check status."""
        staff_user = UserFactory(is_staff=True)
        project = ProjectFactory(name="Checked Project")
        # Create active file with manufacturability check
        project_file = ProjectFileFactory(project=project, is_active=True)
        ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        content = response.content.decode()
        assert "Finished" in content

    def test_default_sort_by_name(self, client):
        """Default sort is by name ascending."""
        staff_user = UserFactory(is_staff=True)
        ProjectFactory(name="Zebra Project")
        ProjectFactory(name="Alpha Project")
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        content = response.content.decode()
        alpha_pos = content.find("Alpha Project")
        zebra_pos = content.find("Zebra Project")
        assert alpha_pos < zebra_pos, "Alpha should appear before Zebra"

    def test_sort_by_name_descending(self, client):
        """Sort by name descending with -name parameter."""
        staff_user = UserFactory(is_staff=True)
        ProjectFactory(name="Zebra Project")
        ProjectFactory(name="Alpha Project")
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary") + "?sort=-name")

        content = response.content.decode()
        alpha_pos = content.find("Alpha Project")
        zebra_pos = content.find("Zebra Project")
        assert zebra_pos < alpha_pos, "Zebra should appear before Alpha"

    def test_sort_by_owner(self, client):
        """Sort by owner username."""
        staff_user = UserFactory(is_staff=True)
        user_a = UserFactory(username="alice")
        user_z = UserFactory(username="zack")
        ProjectFactory(name="Zack Project", user=user_z)
        ProjectFactory(name="Alice Project", user=user_a)
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary") + "?sort=owner")

        content = response.content.decode()
        alice_pos = content.find("Alice Project")
        zack_pos = content.find("Zack Project")
        assert alice_pos < zack_pos, "Alice's project should appear first"

    def test_sort_indicator_in_header(self, client):
        """Current sort column shows indicator."""
        staff_user = UserFactory(is_staff=True)
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary") + "?sort=name")

        content = response.content.decode()
        # Should have ascending indicator on name column and toggle link
        assert "▲" in content, "Sort indicator should be visible"
        assert "sort=-name" in content, "Toggle link should point to descending sort"

    def test_displays_crowd_supply_order_link(self, client):
        """Projects with a CrowdSupply order link to the CS order page."""
        staff_user = UserFactory(is_staff=True)
        ProjectFactory(name="CS Project", crowd_supply_order_id="327373")
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        content = response.content.decode()
        assert "https://www.crowdsupply.com/account/order/327373" in content
        assert "327373" in content

    def test_displays_cob_indicator(self, client):
        """Chip-on-Board projects show a CoB check in the table."""
        staff_user = UserFactory(is_staff=True)
        ProjectFactory(name="CoB Project", chip_on_board=True)
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        content = response.content.decode()
        assert "CoB" in content, "CoB column header should be present"
        assert 'aria-label="Chip-on-Board packaging"' in content

    def test_sort_by_cs_order(self, client):
        """Sort by CrowdSupply order number."""
        staff_user = UserFactory(is_staff=True)
        ProjectFactory(name="Order Niner", crowd_supply_order_id="999999")
        ProjectFactory(name="Order Wun", crowd_supply_order_id="111111")
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary") + "?sort=cs_order")

        content = response.content.decode()
        wun_pos = content.find("Order Wun")
        niner_pos = content.find("Order Niner")
        assert wun_pos < niner_pos, "Lower order number should appear first"

    def test_summary_stats_include_cs_and_cob_counts(self, client):
        """Top-of-page summary includes CS order and CoB project counts."""
        staff_user = UserFactory(is_staff=True)
        ProjectFactory(name="CS One", crowd_supply_order_id="111111")
        ProjectFactory(
            name="CS Two CoB",
            crowd_supply_order_id="222222",
            chip_on_board=True,
        )
        ProjectFactory(name="Plain Project")
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary"))

        summary = response.context["summary"]
        expected_cs_order_count = 2
        assert summary["cs_order_count"] == expected_cs_order_count
        assert summary["cob_count"] == 1
        content = response.content.decode()
        assert "CrowdSupply" in content

    def test_sort_by_cob(self, client):
        """Sort by Chip-on-Board flag descending puts CoB projects first."""
        staff_user = UserFactory(is_staff=True)
        # Name the CoB project so the default name-sort fallback would put
        # it last: the test only passes when -cob sorting actually works.
        ProjectFactory(name="Zebra Packaged Project", chip_on_board=True)
        ProjectFactory(name="Alpha Plain Project", chip_on_board=False)
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_summary") + "?sort=-cob")

        content = response.content.decode()
        cob_pos = content.find("Zebra Packaged Project")
        bare_pos = content.find("Alpha Plain Project")
        assert cob_pos < bare_pos, "CoB project should appear first"


@pytest.mark.django_db
class TestManufacturabilityCheckAdminStatusView:
    """Tests for the manufacturability check status view."""

    def test_active_sections_in_context(self, client):
        """View provides active_sections list with all non-terminal statuses."""
        staff_user = UserFactory(is_staff=True)
        project = ProjectFactory()
        project_file = ProjectFileFactory(project=project)

        # Create checks for each non-terminal status
        ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.ANALYZING,
        )
        ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.DISPATCHING,
        )
        ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.STARTING,
        )
        ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.CANCELLING,
        )

        client.force_login(staff_user)
        response = client.get(reverse("projects:admin_check_status"))

        assert response.status_code == HTTP_OK
        assert "active_sections" in response.context

        active_sections = response.context["active_sections"]
        # Should have sections for each non-terminal status:
        # RUNNING, ANALYZING, STARTING, DISPATCHING, PENDING, CANCELLING
        expected_section_count = 6
        assert len(active_sections) == expected_section_count

        # Verify each section has required fields
        for section in active_sections:
            assert "status" in section
            assert "label" in section
            assert "color" in section
            assert "icon" in section
            assert "show_spinner" in section
            assert "checks" in section
            assert "count" in section

        # Verify statuses are present
        statuses = {section["status"] for section in active_sections}
        expected_statuses = {
            ManufacturabilityCheck.Status.RUNNING,
            ManufacturabilityCheck.Status.ANALYZING,
            ManufacturabilityCheck.Status.STARTING,
            ManufacturabilityCheck.Status.DISPATCHING,
            ManufacturabilityCheck.Status.PENDING,
            ManufacturabilityCheck.Status.CANCELLING,
        }
        assert statuses == expected_statuses

    def test_active_checks_show_cs_order_and_cob(self, client):
        """Active check rows show the project's CS order link and CoB flag."""
        staff_user = UserFactory(is_staff=True)
        project = ProjectFactory(
            crowd_supply_order_id="327373",
            chip_on_board=True,
        )
        project_file = ProjectFileFactory(project=project)
        ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_check_status"))

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "https://www.crowdsupply.com/account/order/327373" in content
        assert 'aria-label="Chip-on-Board packaging"' in content

    def test_recent_checks_show_cs_order_and_cob(self, client):
        """Recent (terminal) check rows show CS order link and CoB flag."""
        staff_user = UserFactory(is_staff=True)
        project = ProjectFactory(
            crowd_supply_order_id="654321",
            chip_on_board=True,
        )
        project_file = ProjectFileFactory(project=project)
        # Terminal status: appears only in the Recent Checks table
        ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        client.force_login(staff_user)

        response = client.get(reverse("projects:admin_check_status"))

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "https://www.crowdsupply.com/account/order/654321" in content
        assert 'aria-label="Chip-on-Board packaging"' in content
