"""Tests for the shuttle date template filters."""

import datetime

import pytest

from wafer_space.shuttles.templatetags.shuttle_dates import aoe_deadline
from wafer_space.shuttles.templatetags.shuttle_dates import milestone_date

AOE = datetime.timezone(datetime.timedelta(hours=-12), "AoE")


class TestAoeDeadline:
    """Deadlines are shown in Anywhere-on-Earth time, as wafer.space does."""

    def test_shows_published_aoe_date_not_next_utc_day(self):
        # 16 Dec 2026 23:59:59 AoE is 17 Dec 2026 11:59:59 UTC.
        deadline = datetime.datetime(2026, 12, 17, 11, 59, 59, tzinfo=datetime.UTC)

        assert aoe_deadline(deadline) == "16 December 2026 @ 11:59 PM AoE"

    def test_accepts_value_stored_in_aoe(self):
        deadline = datetime.datetime(2025, 12, 3, 23, 59, 59, tzinfo=AOE)

        assert aoe_deadline(deadline) == "3 December 2025 @ 11:59 PM AoE"

    def test_rejects_naive_datetime(self):
        naive = datetime.datetime.fromisoformat("2026-12-16T23:59:59")

        with pytest.raises(ValueError, match="timezone-aware"):
            aoe_deadline(naive)


class TestMilestoneDate:
    """Milestones are stored as midnight UTC and shown as a UTC day."""

    def test_shows_utc_day(self):
        milestone = datetime.datetime(2026, 1, 8, tzinfo=datetime.UTC)

        assert milestone_date(milestone) == "8 January 2026"
