import json
from http import HTTPStatus

import pytest
from django.urls import reverse

from wafer_space.core.enums import SlotSize
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.shuttles.tests.factories import ShuttleFactory
from wafer_space.users.tests.factories import UserFactory


@pytest.mark.django_db
class TestShuttleAssignmentView:
    """Test shuttle assignment dashboard view."""

    def test_staff_can_access(self, client):
        """Staff users should access assignment dashboard."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G810")

        url = reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        assert "G810" in response.content.decode()

    def test_regular_user_cannot_access(self, client):
        """Regular users should be denied access."""
        user = UserFactory(is_staff=False)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G802")

        url = reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        response = client.get(url)

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_context_includes_statistics(self, client):
        """Context should include assignment statistics by size."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G803")

        # Create slots
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=1,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        assigned_slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=1,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )

        # Assign project to one slot
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)
        assigned_slot.project = project
        assigned_slot.save()

        url = reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        stats = response.context["stats"]

        # Should have stats for FULL size
        full_stats = stats[SlotSize.FULL]
        expected_total_slots = 3
        expected_available_slots = 2
        assert full_stats["total_slots"] == expected_total_slots
        assert full_stats["available_slots"] == expected_available_slots
        assert full_stats["projects_count"] == 1
        assert full_stats["assigned_count"] == 1

    def test_context_includes_projects(self, client):
        """Context should include all projects on shuttle."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G804")

        project1 = ProjectFactory(shuttle=shuttle, name="Project One")
        project2 = ProjectFactory(shuttle=shuttle, name="Project Two")

        url = reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        projects = response.context["projects"]
        expected_project_count = 2
        assert len(projects) == expected_project_count
        assert project1 in projects
        assert project2 in projects

    def test_stats_include_crowd_supply_and_cob_counts(self, client):
        """Stats should count CrowdSupply-order and CoB projects per size."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G806")
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        assigned = ProjectFactory(
            shuttle=shuttle,
            slot_size=SlotSize.FULL,
            crowd_supply_order_id="327373",
            chip_on_board=True,
        )
        slot.project = assigned
        slot.save()

        # Unassigned project with a CrowdSupply order, no CoB
        ProjectFactory(
            shuttle=shuttle,
            slot_size=SlotSize.FULL,
            crowd_supply_order_id="654321",
        )
        # Project with neither
        ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)

        url = reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        full_stats = response.context["stats"][SlotSize.FULL]
        expected_cs_order_total = 2
        assert full_stats["cs_order_assigned"] == 1
        assert full_stats["cs_order_total"] == expected_cs_order_total
        assert full_stats["cob_count"] == 1

    def test_summary_table_has_cs_and_cob_columns(self, client):
        """Summary table should have CS# and CoB column headers."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G807")
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )

        url = reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "CS#" in content
        assert "CoB" in content

    def test_assignment_table_shows_cs_order_link_and_cob(self, client):
        """Assignment table should link CS orders and flag CoB projects."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G808")
        ProjectFactory(
            shuttle=shuttle,
            crowd_supply_order_id="327373",
            chip_on_board=True,
        )

        url = reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "https://www.crowdsupply.com/account/order/327373" in content
        assert 'aria-label="Chip-on-Board packaging"' in content

    def test_grid_tooltip_shows_packaging_and_cs_order(self, client):
        """Grid cell tooltip should include packaging and CS order info."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G809")
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        project = ProjectFactory(
            shuttle=shuttle,
            slot_size=SlotSize.FULL,
            crowd_supply_order_id="327373",
            chip_on_board=True,
        )
        slot.project = project
        slot.save()

        url = reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "Packaging: CoB" in content
        assert "CS Order: 327373" in content

    def test_grid_tooltip_shows_bare_without_cs_order(self, client):
        """Tooltip shows Bare and omits CS Order when neither is set."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G814")
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)
        slot.project = project
        slot.save()

        url = reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "Packaging: Bare" in content
        assert "Bare Die" not in content
        assert "CS Order:" not in content


@pytest.mark.django_db
class TestGridPreviewView:
    """Test grid preview view."""

    def test_renders_grid(self, client):
        """Should render HTML table with grid positions."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G811")

        # Create 2x2 grid
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=1,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=1,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        assigned_slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=1,
            column=1,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )

        # Assign project to one slot
        project = ProjectFactory(shuttle=shuttle, project_id="TEST")
        assigned_slot.project = project
        assigned_slot.save()

        url = reverse("shuttles:grid_preview", kwargs={"name": shuttle.name})
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()

        # Should have table with correct structure
        assert "<table" in content
        assert "A1" in content or ">A<" in content  # Column header or cell
        assert "TEST" in content  # Project ID should appear

    def test_shows_empty_cells(self, client):
        """Empty cells should be visually distinct."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G805")

        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )

        url = reverse("shuttles:grid_preview", kwargs={"name": shuttle.name})
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "bg-secondary" in content or "Empty" in content or "empty" in content


@pytest.mark.django_db
class TestAssignProjectView:
    """Test project assignment endpoint."""

    def test_assign_project_to_slot(self, client):
        """Should assign project to available slot."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G812")
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)

        url = reverse("shuttles:assign_project", kwargs={"name": shuttle.name})
        response = client.post(
            url,
            data=json.dumps({"project_pk": str(project.pk), "slot_id": slot.pk}),
            content_type="application/json",
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["success"] is True

        # Verify slot assigned
        slot.refresh_from_db()
        assert slot.project == project
        assert slot.reserved_by == user
        assert slot.status == ShuttleSlot.Status.RESERVED

    def test_warn_on_size_mismatch(self, client):
        """Should warn but allow assignment on size mismatch."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G802")
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.QUARTER)

        url = reverse("shuttles:assign_project", kwargs={"name": shuttle.name})
        response = client.post(
            url,
            data=json.dumps({"project_pk": str(project.pk), "slot_id": slot.pk}),
            content_type="application/json",
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["success"] is True
        assert "warning" in data
        assert "Size mismatch" in data["warning"]

    def test_reassign_slot_replaces_project(self, client):
        """Should allow reassigning a slot to a different project."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G803")
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        old_project = ProjectFactory(shuttle=shuttle, project_id="OLD1")
        slot.project = old_project
        slot.save()

        new_project = ProjectFactory(shuttle=shuttle, project_id="NEW1")

        url = reverse("shuttles:assign_project", kwargs={"name": shuttle.name})
        response = client.post(
            url,
            data=json.dumps({"project_pk": str(new_project.pk), "slot_id": slot.pk}),
            content_type="application/json",
        )

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["success"] is True

        # Verify slot now has new project
        slot.refresh_from_db()
        assert slot.project == new_project

    def test_reject_occupied_slot(self, client):
        """Should reject assignment to occupied (non-reassignable) slots."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G804")
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.OCCUPIED,
        )
        slot.project = ProjectFactory(shuttle=shuttle)
        slot.save()

        new_project = ProjectFactory(shuttle=shuttle)

        url = reverse("shuttles:assign_project", kwargs={"name": shuttle.name})
        response = client.post(
            url,
            data=json.dumps({"project_pk": str(new_project.pk), "slot_id": slot.pk}),
            content_type="application/json",
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        data = response.json()
        assert data["success"] is False
        assert "not available" in data["error"]


@pytest.mark.django_db
class TestRemoveAssignmentView:
    """Test slot assignment removal endpoint."""

    def test_remove_assignment(self, client):
        """Should remove project from slot."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G813")
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        project = ProjectFactory(shuttle=shuttle)
        slot.project = project
        slot.reserved_by = user
        slot.save()

        url = reverse(
            "shuttles:remove_assignment",
            kwargs={"name": shuttle.name, "slot_id": slot.pk},
        )
        response = client.post(url)

        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["success"] is True

        # Verify slot cleared
        slot.refresh_from_db()
        assert slot.project is None
        assert slot.reserved_by is None
        assert slot.status == ShuttleSlot.Status.AVAILABLE
