from http import HTTPStatus

import pytest
from django.urls import reverse

from wafer_space.core.enums import SlotSize
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.users.tests.factories import UserFactory


@pytest.mark.django_db
class TestShuttleAssignmentView:
    """Test shuttle assignment dashboard view."""

    def test_staff_can_access(self, client):
        """Staff users should access assignment dashboard."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="TEST01",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=100,
        )

        url = reverse("shuttles:assignment", kwargs={"pk": shuttle.pk})
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        assert "TEST01" in response.content.decode()

    def test_regular_user_cannot_access(self, client):
        """Regular users should be denied access."""
        user = UserFactory(is_staff=False)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="TEST02",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=100,
        )

        url = reverse("shuttles:assignment", kwargs={"pk": shuttle.pk})
        response = client.get(url)

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_context_includes_statistics(self, client):
        """Context should include assignment statistics by size."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="TEST03",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=100,
        )

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

        url = reverse("shuttles:assignment", kwargs={"pk": shuttle.pk})
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

        shuttle = Shuttle.objects.create(
            name="TEST04",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=100,
        )

        project1 = ProjectFactory(shuttle=shuttle, name="Project One")
        project2 = ProjectFactory(shuttle=shuttle, name="Project Two")

        url = reverse("shuttles:assignment", kwargs={"pk": shuttle.pk})
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        projects = response.context["projects"]
        expected_project_count = 2
        assert len(projects) == expected_project_count
        assert project1 in projects
        assert project2 in projects


@pytest.mark.django_db
class TestGridPreviewView:
    """Test grid preview view."""

    def test_renders_grid(self, client):
        """Should render HTML table with grid positions."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="TEST01",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=100,
        )

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

        url = reverse("shuttles:grid_preview", kwargs={"pk": shuttle.pk})
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

        shuttle = Shuttle.objects.create(
            name="TEST02",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=100,
        )

        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )

        url = reverse("shuttles:grid_preview", kwargs={"pk": shuttle.pk})
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "bg-secondary" in content or "Empty" in content or "empty" in content
