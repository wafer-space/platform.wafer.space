"""Tests for shuttle models."""

import importlib

import pytest
from django.apps import apps

from wafer_space.shuttles.models import Shuttle

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
