import datetime
import html
import json
import re
from http import HTTPStatus

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from wafer_space.core.enums import SlotSize
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.projects.tests.factories import ProjectFileFactory
from wafer_space.projects.tests.html_elements import parse_html
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.shuttles.tests.factories import ShuttleFactory
from wafer_space.users.tests.factories import UserFactory

from .test_shuttle_state_display import visible_text

SUBMITTED_ICON = 'aria-label="File submitted for manufacturing"'
NOT_SUBMITTED_ICON = 'aria-label="No file submitted for manufacturing"'
LATEST_LABEL = 'title="Latest file revision">L:'
SUBMITTED_LABEL = 'title="Submitted for manufacturing">S:'


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

    def test_grid_tooltip_shows_latest_revision_status(self, client):
        """Tooltip carries the same status text as the Status column."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G815")
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)
        project_file = ProjectFileFactory(project=project)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        slot.project = project
        slot.save()

        url = reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "Status: Passed" in content

    def test_grid_tooltip_shows_both_revisions_when_submitted_differs(self, client):
        """Tooltip shows Latest and Submitted lines like the Status column."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G816")
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)
        submitted_file = ProjectFileFactory(project=project, is_active=False)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=submitted_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        latest_file = ProjectFileFactory(project=project)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=latest_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=False,
        )
        project.submitted_file = submitted_file
        project.save()
        slot.project = project
        slot.save()

        url = reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        response = client.get(url)

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert "Latest: Failed" in content
        assert "Submitted: Passed" in content


@pytest.mark.django_db
class TestAssignmentPageRevisionStatus:
    """Status/Submitted columns follow docs/manufacturable_vs_submitted.md.

    The Status column always shows the precheck status of the latest file
    revision, plus a second line for the submitted revision when that is
    a different (older) revision. The Submitted column reflects
    Project.submitted_file, never Project.status.
    """

    def _get_content(self, client, shuttle):
        user = UserFactory(is_staff=True)
        client.force_login(user)
        url = reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        response = client.get(url)
        assert response.status_code == HTTPStatus.OK
        return response.content.decode()

    def test_unsubmitted_project_shows_latest_revision_check(self, client):
        """A passing check on the latest revision shows even before submit."""
        shuttle = ShuttleFactory(name="G820")
        project = ProjectFactory(shuttle=shuttle)
        project_file = ProjectFileFactory(project=project)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

        content = self._get_content(client, shuttle)

        assert "Passed" in content
        assert "No check" not in content
        assert NOT_SUBMITTED_ICON in content

    def test_submitted_latest_revision_shows_single_status_line(self, client):
        """No Latest/Submitted labels when the submitted revision is latest."""
        shuttle = ShuttleFactory(name="G821")
        project = ProjectFactory(shuttle=shuttle)
        project_file = ProjectFileFactory(project=project)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        project.submitted_file = project_file
        project.save()

        content = self._get_content(client, shuttle)

        assert "Passed" in content
        assert LATEST_LABEL not in content
        assert SUBMITTED_LABEL not in content
        assert SUBMITTED_ICON in content

    def test_submitted_older_revision_shows_both_status_lines(self, client):
        """Both revisions' statuses show when submitted is not latest."""
        shuttle = ShuttleFactory(name="G822")
        project = ProjectFactory(shuttle=shuttle)
        submitted_file = ProjectFileFactory(project=project, is_active=False)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=submitted_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        latest_file = ProjectFileFactory(project=project)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=latest_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=False,
        )
        project.submitted_file = submitted_file
        project.save()

        content = self._get_content(client, shuttle)

        assert LATEST_LABEL in content
        assert SUBMITTED_LABEL in content
        assert "Passed" in content
        assert "Failed" in content

    def test_submitted_column_ignores_project_status(self, client):
        """Submitted icon keyed on submitted_file even when status moved on.

        A later check completion overwrites Project.status (SUBMITTED ->
        MANUFACTURABLE), which must not make the submitted marker vanish.
        """
        shuttle = ShuttleFactory(name="G823")
        project = ProjectFactory(shuttle=shuttle)
        project_file = ProjectFileFactory(project=project)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        project.submitted_file = project_file
        project.status = project.Status.MANUFACTURABLE
        project.save()

        content = self._get_content(client, shuttle)

        assert SUBMITTED_ICON in content
        assert NOT_SUBMITTED_ICON not in content


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

    def test_assign_succeeds_on_closed_shuttle_with_warning(self, client):
        """Assignment on a closed shuttle succeeds with a warning (#312)."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = ShuttleFactory(name="G815", status=Shuttle.Status.LOCKED)
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
        assert "not open" in data["warning"]

        slot.refresh_from_db()
        assert slot.project == project

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


# The detail page's labels for the schedule dates removed by #346.
DROPPED_DATE_LABELS = ("Production Start", "Est. Completion", "Actual Completion")


@pytest.mark.django_db
class TestShuttleDatesDisplay:
    """Shuttle pages show dates as wafer.space publishes them."""

    # 16 Dec 2026 23:59:59 AoE (UTC-12), stored as 17 Dec 11:59:59 UTC.
    DEADLINE_UTC = datetime.datetime(2026, 12, 17, 11, 59, 59, tzinfo=datetime.UTC)
    PUBLISHED_DEADLINE = "16 December 2026 @ 11:59 PM AoE"

    def _staff_client(self, client):
        client.force_login(UserFactory(is_staff=True))
        return client

    def test_detail_shows_deadline_in_aoe(self, client):
        shuttle = ShuttleFactory(name="G860", submission_deadline=self.DEADLINE_UTC)

        response = self._staff_client(client).get(
            reverse("shuttles:detail", kwargs={"name": shuttle.name})
        )

        assert self.PUBLISHED_DEADLINE in visible_text(response.content.decode())

    def test_list_shows_deadline_in_aoe(self, client):
        ShuttleFactory(name="G861", submission_deadline=self.DEADLINE_UTC)

        response = self._staff_client(client).get(reverse("shuttles:list"))

        assert self.PUBLISHED_DEADLINE in visible_text(response.content.decode())

    def test_detail_shows_only_the_gds_deadline(self, client):
        """The other schedule dates are gone (#346): only the deadline stays."""
        shuttle = ShuttleFactory(name="G862", submission_deadline=self.DEADLINE_UTC)

        response = self._staff_client(client).get(
            reverse("shuttles:detail", kwargs={"name": shuttle.name})
        )

        text = visible_text(response.content.decode())
        assert [label for label in DROPPED_DATE_LABELS if label in text] == []


@pytest.mark.django_db
def test_assignment_page_omits_archived_projects(client) -> None:
    """Archived projects are not listed, counted or offered (issue #307)."""
    client.force_login(UserFactory(is_staff=True))
    shuttle = Shuttle.objects.create(name="G882", description="Archive test")
    active = ProjectFactory(shuttle=shuttle, name="Active one")
    ProjectFactory(
        shuttle=shuttle,
        name="Archived one",
        archived_at=timezone.now(),
    )
    response = client.get(reverse("shuttles:assignment", args=[shuttle.name]))
    listed = {p.pk for p in response.context["projects"]}
    offered = {d["pk"] for d in response.context["projects_data"]}
    counted = sum(s["projects_count"] for s in response.context["stats"].values())
    assert listed == {active.pk}
    assert offered == {active.pk}
    assert counted == 1


@pytest.mark.django_db
def test_assign_project_view_refuses_archived_project(client) -> None:
    """The assign endpoint answers 400 and leaves the slot free (issue #307)."""
    client.force_login(UserFactory(is_staff=True))
    shuttle = Shuttle.objects.create(name="G883", description="Archive test")
    slot = ShuttleSlot.objects.create(shuttle=shuttle)
    project = ProjectFactory(shuttle=shuttle, archived_at=timezone.now())
    response = client.post(
        reverse("shuttles:assign_project", args=[shuttle.name]),
        data=json.dumps({"project_pk": str(project.pk), "slot_id": slot.pk}),
        content_type="application/json",
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert "archived" in response.json()["error"]
    slot.refresh_from_db()
    assert slot.project is None


@pytest.mark.django_db
class TestAssignmentShowFilter:
    """The "Show" filter on the assignment page (#342)."""

    def _get(self, client, shuttle):
        client.force_login(UserFactory(is_staff=True))
        return client.get(reverse("shuttles:assignment", args=[shuttle.name]))

    @staticmethod
    def _selected_option(response) -> str | None:
        """Value of the selected option of the #show-filter select."""
        in_select = False
        for tag, attrs in parse_html(response.content.decode()).elements:
            if tag == "select":
                in_select = attrs.get("id") == "show-filter"
            elif in_select and tag == "option" and "selected" in attrs:
                return attrs["value"]
        return None

    @staticmethod
    def _row_flags(response) -> list[tuple[str | None, ...]]:
        """(assigned, cs-order, manufacturable) of each project-table row."""
        return [
            (
                attrs["data-assigned"],
                attrs["data-cs-order"],
                attrs["data-manufacturable"],
            )
            for tag, attrs in parse_html(response.content.decode()).elements
            if tag == "tr" and "data-assigned" in attrs
        ]

    def test_open_shuttle_defaults_to_all_projects(self, client):
        """An open shuttle shows every project at first."""
        shuttle = ShuttleFactory(name="G884", status=Shuttle.Status.OPEN)
        response = self._get(client, shuttle)
        assert response.context["show_filter_default"] == "all"
        assert self._selected_option(response) == "all"

    def test_locked_shuttle_defaults_to_assigned_only(self, client):
        """A shuttle that is no longer open shows only assigned projects."""
        shuttle = ShuttleFactory(name="G885", status=Shuttle.Status.LOCKED)
        response = self._get(client, shuttle)
        assert response.context["show_filter_default"] == "assigned"
        assert self._selected_option(response) == "assigned"

    def test_open_shuttle_past_deadline_defaults_to_assigned_only(self, client):
        """Past its GDS deadline an OPEN-status shuttle is closed too (#320)."""
        shuttle = ShuttleFactory(
            name="G886",
            status=Shuttle.Status.OPEN,
            submission_deadline=timezone.now() - datetime.timedelta(days=1),
        )
        response = self._get(client, shuttle)
        assert response.context["show_filter_default"] == "assigned"
        assert self._selected_option(response) == "assigned"

    def test_offers_every_filter_from_the_issue(self, client):
        """All, assigned, unassigned and the unassigned subsets are offered."""
        shuttle = ShuttleFactory(name="G887")
        response = self._get(client, shuttle)
        values = [value for value, _ in response.context["show_filter_choices"]]
        assert values == [
            "all",
            "assigned",
            "unassigned",
            "unassigned-cs",
            "unassigned-mfg",
            "unassigned-ready",
            "outdated",
        ]

    def test_rows_carry_assigned_cs_order_and_manufacturable(self, client):
        """Each row exposes what the filter needs as data attributes."""
        shuttle = ShuttleFactory(name="G888")
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        ready = ProjectFactory(
            shuttle=shuttle,
            slot_size=SlotSize.FULL,
            crowd_supply_order_id="327373",
        )
        project_file = ProjectFileFactory(project=ready)
        ManufacturabilityCheckFactory(
            project=ready,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        slot.project = ready
        slot.save()
        ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)

        flags = self._row_flags(self._get(client, shuttle))

        assert sorted(flags) == [("false", "false", "false"), ("true", "true", "true")]


CURRENT_DIGEST = "sha256:" + "a" * 64
OUTDATED_DIGEST = "sha256:" + "b" * 64
_ATTR = re.compile(r'([\w-]+)="([^"]*)"')


def marked(content: str, marker: str) -> list[tuple[dict[str, str], str]]:
    """(attributes, visible text) of each element carrying ``marker``."""
    found = re.findall(
        rf"<(\w+)([^>]*\s{marker}\b[^>]*)>(.*?)</\1>",
        content,
        re.DOTALL,
    )
    return [
        (dict(_ATTR.findall(attrs)), visible_text(body)) for _, attrs, body in found
    ]


@pytest.mark.django_db
class TestAssignmentPrecheckVersion:
    """Which precheck version each project passed on, and when (#203)."""

    @pytest.fixture(autouse=True)
    def _fresh_latest_digest(self):
        # The latest precheck digest is cached for a minute.
        cache.clear()
        yield
        cache.clear()

    @staticmethod
    def checked_project(shuttle, *, digest, passed=True, completed_at=None):
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)
        started = timezone.now() - (
            datetime.timedelta(0)
            if digest == CURRENT_DIGEST
            else datetime.timedelta(days=30)
        )
        ManufacturabilityCheckFactory(
            project=project,
            project_file=ProjectFileFactory(project=project),
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=passed,
            docker_image_digest=digest,
            container_started_at=started,
            analysis_completed_at=completed_at or started,
        )
        return project

    @staticmethod
    def get(client, shuttle):
        client.force_login(UserFactory(is_staff=True))
        response = client.get(
            reverse("shuttles:assignment", kwargs={"name": shuttle.name}),
        )
        assert response.status_code == HTTPStatus.OK
        return response

    def test_stats_count_projects_passed_on_an_outdated_version(self, client):
        shuttle = ShuttleFactory(name="G830")
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        self.checked_project(shuttle, digest=CURRENT_DIGEST)
        slot.project = self.checked_project(shuttle, digest=OUTDATED_DIGEST)
        slot.save()
        self.checked_project(shuttle, digest=OUTDATED_DIGEST)
        # A failure on an outdated version is not manufacturable at all.
        self.checked_project(shuttle, digest=OUTDATED_DIGEST, passed=False)

        stats = self.get(client, shuttle).context["stats"][SlotSize.FULL]

        assert (
            stats["manufacturable_total"],
            stats["outdated_assigned"],
            stats["outdated_total"],
        ) == (3, 1, 2)

    def test_a_version_that_cannot_be_compared_is_not_outdated(self, client):
        shuttle = ShuttleFactory(name="G831")
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        self.checked_project(shuttle, digest="")

        stats = self.get(client, shuttle).context["stats"][SlotSize.FULL]

        assert (stats["manufacturable_total"], stats["outdated_total"]) == (1, 0)

    def test_summary_shows_the_outdated_column(self, client):
        shuttle = ShuttleFactory(name="G832")
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        self.checked_project(shuttle, digest=CURRENT_DIGEST)
        self.checked_project(shuttle, digest=OUTDATED_DIGEST)

        content = self.get(client, shuttle).content.decode()
        [(_, text)] = marked(content, "data-outdated")

        assert text == "0/1"

    def test_status_shows_when_the_check_finished(self, client):
        shuttle = ShuttleFactory(name="G833")
        finished = datetime.datetime(2026, 10, 3, 9, 4, 5, tzinfo=datetime.UTC)
        self.checked_project(shuttle, digest=CURRENT_DIGEST, completed_at=finished)

        content = self.get(client, shuttle).content.decode()
        [(attrs, text)] = marked(content, "data-check-date")

        assert (text, html.unescape(attrs["title"])) == (
            "2026-10-03",
            "Check finished 2026-10-03 09:04:05 UTC",
        )

    def test_rows_say_whether_they_passed_on_an_outdated_version(self, client):
        """The "outdated" show filter reads data-precheck-outdated."""
        shuttle = ShuttleFactory(name="G835")
        current = self.checked_project(shuttle, digest=CURRENT_DIGEST)
        outdated = self.checked_project(shuttle, digest=OUTDATED_DIGEST)
        failed = self.checked_project(shuttle, digest=OUTDATED_DIGEST, passed=False)

        content = self.get(client, shuttle).content.decode()
        flags = {
            text.split()[0]: attrs["data-precheck-outdated"]
            for attrs, text in marked(content, "data-precheck-outdated")
        }

        assert flags == {
            current.full_id: "false",
            outdated.full_id: "true",
            failed.full_id: "false",
        }

    def test_a_check_still_running_shows_no_date(self, client):
        shuttle = ShuttleFactory(name="G834")
        project = ProjectFactory(shuttle=shuttle)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=ProjectFileFactory(project=project),
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        content = self.get(client, shuttle).content.decode()

        assert marked(content, "data-check-date") == []
