# Data migration applying the published GF180MCU shuttle schedule.
#
# Dates come from the public schedule spreadsheet ("New Date" column):
# https://docs.google.com/spreadsheets/d/1KD2Mn7s7WoZ738tmH0LNp_uvDCJVLOdqiyMbqEh0ApU/
#
# Field mapping (spreadsheet milestone -> Shuttle field):
# - "Final GDS in date"                     -> submission_deadline (23:59:59 AoE)
# - "GDS delivered to GlobalFoundries"      -> production_start_date
# - "Wafers returned from GlobalFoundries"  -> estimated_completion_date
# - "Wafers returned from GlobalFoundries"  -> actual_completion_date (G801 only)

import datetime
import logging
from typing import ClassVar

from django.db import migrations

logger = logging.getLogger(__name__)

# Deadlines are published as "@ 11:59 PM AoE" on https://wafer.space.
# AoE (Anywhere on Earth, UTC-12) means a date only ends once it is
# over everywhere on earth.
AOE = datetime.timezone(datetime.timedelta(hours=-12), "AoE")


def _deadline(year: int, month: int, day: int) -> datetime.datetime:
    """Return 23:59:59 Anywhere-on-Earth for a published deadline date."""
    return datetime.datetime(year, month, day, 23, 59, 59, tzinfo=AOE)


def _utc(year: int, month: int, day: int) -> datetime.datetime:
    """Return midnight UTC for an informational milestone date."""
    return datetime.datetime(year, month, day, tzinfo=datetime.UTC)


def update_shuttle_schedule(apps, _schema_editor):
    """Apply the published Run #1/#2 schedule to G801/G802.

    Update-only: shuttles are never created here. G801 exists in all
    databases (seeded by projects migration 0041); G802 exists in
    production but not in test databases, where creating it would
    collide with ShuttleFactory's G8XX name sequence.
    """
    Shuttle = apps.get_model("shuttles", "Shuttle")

    # GF180MCU Run #1: manufacturing finished, wafers returned 06 Apr 2026
    g801_updated = Shuttle.objects.filter(name="G801").update(
        status="completed",
        submission_deadline=_deadline(2025, 12, 17),
        production_start_date=_utc(2026, 1, 8),
        estimated_completion_date=_utc(2026, 4, 6),
        actual_completion_date=_utc(2026, 4, 6),
    )
    logger.info("Updated %d G801 shuttle(s) with Run #1 schedule", g801_updated)

    # GF180MCU Run #2: campaign open, final GDS due 14 Jul 2026
    g802_updated = Shuttle.objects.filter(name="G802").update(
        submission_deadline=_deadline(2026, 7, 14),
        production_start_date=_utc(2026, 7, 24),
        estimated_completion_date=_utc(2026, 10, 16),
    )
    logger.info("Updated %d G802 shuttle(s) with Run #2 schedule", g802_updated)


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("shuttles", "0008_shuttle_crowd_supply_url"),
    ]

    operations: ClassVar[list[migrations.RunPython]] = [
        migrations.RunPython(update_shuttle_schedule, migrations.RunPython.noop),
    ]
