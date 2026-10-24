"""G804 (GF180MCU Run #4) as created before its dates are known.

Tim, 11 Oct 2026: "We don't have dates yet, but should still create the
new entry in the platform with the same config as Run #3." G804 is created
per environment in PLANNING status with no dates and the grid G803 had at
the time, which is G802's 6 x 9 grid (see docs/shuttle_creation.md); these
tests cover that state. G803's own grid later changed to the published
Run #3 allocation (shuttles/G803-layout.yaml, test_run3_layout.py).
"""

from collections import Counter
from http import HTTPStatus
from pathlib import Path

import pytest
from django import forms
from django.core.management import call_command
from django.urls import reverse

from wafer_space.core.enums import SlotSize
from wafer_space.projects.admin import DuplicateProjectForm
from wafer_space.projects.forms import ProjectForm
from wafer_space.shuttles.config import GridConfig
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.templatetags.shuttle_dates import aoe_deadline
from wafer_space.users.tests.factories import UserFactory

LAYOUT_DIR = Path("shuttles")


def _offered_names(field: forms.Field) -> set[str]:
    assert isinstance(field, forms.ModelChoiceField)
    queryset = field.queryset
    assert queryset is not None
    return set(queryset.values_list("name", flat=True))


def _create_g804() -> Shuttle:
    # Mirrors the runbook: explicit name (never ShuttleFactory's G8XX
    # sequence), PLANNING, no dates, no CrowdSupply URL yet.
    return Shuttle.objects.create(
        name="G804",
        description="GF180MCU Shuttle Run 4",
        status=Shuttle.Status.PLANNING,
    )


class TestG804Layout:
    """G804's grid is the Run 2 grid that Run #3 started with."""

    def test_layout_matches_g802(self):
        g802 = GridConfig.from_file(LAYOUT_DIR / "G802-layout.yaml")
        g804 = GridConfig.from_file(LAYOUT_DIR / "G804-layout.yaml")

        assert (g804.row_heights, g804.column_widths) == (
            g802.row_heights,
            g802.column_widths,
        )

    def test_layout_names_g804(self):
        g804 = GridConfig.from_file(LAYOUT_DIR / "G804-layout.yaml")

        assert g804.shuttle_name == "G804"


@pytest.mark.django_db
class TestG804GridGeneration:
    """generate_shuttle_grid G804 works on a dateless PLANNING shuttle."""

    def test_creates_run_2_slot_mix(self):
        shuttle = _create_g804()

        call_command("generate_shuttle_grid", "G804")

        sizes = Counter(shuttle.slots.values_list("slot_size", flat=True))
        assert sizes == {
            SlotSize.FULL: 18,
            SlotSize.HALF_HEIGHT: 18,
            SlotSize.HALF_WIDTH: 9,
            SlotSize.QUARTER: 9,
        }


@pytest.mark.django_db
class TestPlanningShuttlePages:
    """Every page that shows shuttles renders a dateless PLANNING G804."""

    @pytest.fixture
    def staff_client(self, client):
        _create_g804()
        call_command("generate_shuttle_grid", "G804")
        client.force_login(UserFactory(is_staff=True))
        return client

    @pytest.mark.parametrize(
        ("url_name", "kwargs", "marker"),
        [
            ("shuttles:list", {}, "G804"),
            ("shuttles:detail", {"name": "G804"}, "G804"),
            ("shuttles:assignment", {"name": "G804"}, "G804"),
            # The embeddable preview has no title; its ninth column is "I".
            (
                "shuttles:grid_preview",
                {"name": "G804"},
                '<th class="column-header">I</th>',
            ),
        ],
    )
    def test_page_renders(self, staff_client, url_name, kwargs, marker):
        response = staff_client.get(reverse(url_name, kwargs=kwargs))

        assert response.status_code == HTTPStatus.OK
        assert marker in response.content.decode()

    def test_detail_shows_no_dates(self, staff_client):
        response = staff_client.get(reverse("shuttles:detail", kwargs={"name": "G804"}))

        content = response.content.decode()
        date_labels = ("Submission Deadline", "Production Start", "Est. Completion")
        assert [label for label in date_labels if label in content] == []


@pytest.mark.django_db
class TestPlanningShuttleSelection:
    """Owners cannot pick G804 yet; staff can duplicate projects onto it."""

    def test_project_form_does_not_offer_planning_shuttle(self):
        Shuttle.objects.create(
            name="G803", description="Run 3", status=Shuttle.Status.OPEN
        )
        _create_g804()

        form = ProjectForm(user=UserFactory())

        assert _offered_names(form.fields["shuttle"]) == {"G803"}

    def test_duplicate_form_offers_planning_shuttle(self):
        source = Shuttle.objects.create(
            name="G803", description="Run 3", status=Shuttle.Status.OPEN
        )
        _create_g804()

        form = DuplicateProjectForm(source_shuttle=source)

        assert "G804" in _offered_names(form.fields["target_shuttle"])


class TestAoeDeadlineWithoutDate:
    """A missing deadline is a template bug: the filter fails loudly."""

    def test_none_raises(self):
        with pytest.raises(ValueError, match="no date"):
            aoe_deadline(None)
