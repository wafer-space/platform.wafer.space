"""Tests for shuttle models."""

import datetime
import importlib

import pytest
from django.apps import apps
from django.utils import timezone

from wafer_space.core.enums import SlotSize
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.shuttles.tests.factories import ShuttleFactory
from wafer_space.users.tests.factories import UserFactory

G801_URL = "https://www.crowdsupply.com/wafer-space/gf180mcu-run-1/"
G802_URL = "https://www.crowdsupply.com/wafer-space/gf180mcu-run-2/"
G803_URL = "https://www.crowdsupply.com/wafer-space/gf180mcu-run-3/"

MIGRATION_MODULE = "wafer_space.shuttles.migrations.0008_shuttle_crowd_supply_url"


@pytest.mark.django_db
class TestShuttleCrowdSupplyUrl:
    """The CrowdSupply campaign URL on Shuttle."""

    def test_field_defaults_to_blank(self):
        shuttle = Shuttle.objects.create(name="G850", description="Test run")
        assert shuttle.crowd_supply_url == ""

    def test_migration_runs_after_g801_seed(self):
        # projects/0041 seeds the G801 shuttle; shuttles/0008 must declare a
        # dependency on it so its data step finds G801 on freshly built
        # databases. (The seeded row itself cannot be asserted here: browser
        # tests use live_server, which flushes the database on teardown and
        # wipes migration-seeded rows before this test runs in a full suite.)
        migration = importlib.import_module(MIGRATION_MODULE)
        dependency = ("projects", "0041_populate_shuttle_and_project_ids")
        assert dependency in migration.Migration.dependencies

    def test_data_step_sets_all_three_urls(self):
        # Ensure the three known runs exist (earlier transactional tests may
        # have flushed the migration-seeded G801), then run the forward data
        # function from the migration module.
        for name, run in (("G801", 1), ("G802", 2), ("G803", 3)):
            Shuttle.objects.get_or_create(
                name=name,
                defaults={"description": f"Run {run}"},
            )
        migration = importlib.import_module(MIGRATION_MODULE)

        migration.set_crowd_supply_urls(apps, None)

        urls = dict(
            Shuttle.objects.filter(name__in=["G801", "G802", "G803"]).values_list(
                "name", "crowd_supply_url"
            )
        )
        assert urls == {"G801": G801_URL, "G802": G802_URL, "G803": G803_URL}


def _slot(shuttle: Shuttle, **overrides) -> ShuttleSlot:
    defaults = {
        "row": 0,
        "column": 0,
        "slot_size": SlotSize.FULL,
        "status": ShuttleSlot.Status.AVAILABLE,
    }
    defaults.update(overrides)
    return ShuttleSlot.objects.create(shuttle=shuttle, **defaults)


@pytest.mark.django_db
class TestSlotReserveAlwaysPossible:
    """Staff slot assignment must work regardless of shuttle state (#312).

    Slot assignment is a staff-only operation that legitimately happens
    after the submission deadline (between GDS close and foundry delivery),
    so shuttle status and deadline must never block it.
    """

    def test_reserve_succeeds_after_submission_deadline(self):
        shuttle = ShuttleFactory(
            name="G860",
            status=Shuttle.Status.OPEN,
            submission_deadline=timezone.now() - datetime.timedelta(days=2),
        )
        slot = _slot(shuttle)
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)

        slot.reserve(project, UserFactory(is_staff=True))

        slot.refresh_from_db()
        assert slot.project == project
        assert slot.status == ShuttleSlot.Status.RESERVED

    @pytest.mark.parametrize(
        "status",
        [
            Shuttle.Status.PLANNING,
            Shuttle.Status.FULL,
            Shuttle.Status.LOCKED,
            Shuttle.Status.IN_PRODUCTION,
            Shuttle.Status.COMPLETED,
            Shuttle.Status.CANCELLED,
        ],
    )
    def test_reserve_succeeds_regardless_of_shuttle_status(self, status):
        shuttle = ShuttleFactory(name="G861", status=status)
        slot = _slot(shuttle)
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)

        slot.reserve(project, UserFactory(is_staff=True))

        slot.refresh_from_db()
        assert slot.project == project

    def test_reassign_succeeds_after_deadline_on_locked_shuttle(self):
        shuttle = ShuttleFactory(
            name="G862",
            status=Shuttle.Status.LOCKED,
            submission_deadline=timezone.now() - datetime.timedelta(days=2),
        )
        first = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)
        slot = _slot(shuttle, status=ShuttleSlot.Status.RESERVED, project=first)
        replacement = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)

        slot.reserve(replacement, UserFactory(is_staff=True))

        slot.refresh_from_db()
        assert slot.project == replacement

    @pytest.mark.parametrize(
        "slot_status",
        [ShuttleSlot.Status.OCCUPIED, ShuttleSlot.Status.CANCELLED],
    )
    def test_reserve_still_refuses_unassignable_slot_statuses(self, slot_status):
        shuttle = ShuttleFactory(name="G863", status=Shuttle.Status.OPEN)
        slot = _slot(shuttle, status=slot_status)
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)

        with pytest.raises(ValueError, match="Slot is not available"):
            slot.reserve(project, UserFactory(is_staff=True))

    def test_reserve_warns_when_shuttle_not_open(self):
        shuttle = ShuttleFactory(name="G864", status=Shuttle.Status.LOCKED)
        slot = _slot(shuttle)
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)

        warning = slot.reserve(project, UserFactory(is_staff=True))

        assert warning is not None
        assert "not open" in warning.lower()

    def test_reserve_warns_when_deadline_passed(self):
        shuttle = ShuttleFactory(
            name="G865",
            status=Shuttle.Status.OPEN,
            submission_deadline=timezone.now() - datetime.timedelta(days=2),
        )
        slot = _slot(shuttle)
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)

        warning = slot.reserve(project, UserFactory(is_staff=True))

        assert warning is not None
        assert "deadline" in warning.lower()

    def test_reserve_keeps_size_mismatch_warning(self):
        shuttle = ShuttleFactory(name="G866", status=Shuttle.Status.OPEN)
        slot = _slot(shuttle)
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.HALF_WIDTH)

        warning = slot.reserve(project, UserFactory(is_staff=True))

        assert warning is not None
        assert "size mismatch" in warning.lower()
