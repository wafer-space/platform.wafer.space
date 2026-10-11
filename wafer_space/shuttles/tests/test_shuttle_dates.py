"""Tests for the shuttle date template filters."""

import datetime

import pytest

from wafer_space.shuttles.templatetags.shuttle_dates import aoe_deadline
from wafer_space.shuttles.templatetags.shuttle_dates import iso_utc
from wafer_space.shuttles.templatetags.shuttle_dates import milestone_date
from wafer_space.shuttles.templatetags.shuttle_dates import timeanddate_url

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


G803_DEADLINE = datetime.datetime(2026, 12, 17, 11, 59, 59, tzinfo=datetime.UTC)


class TestIsoUtc:
    """The countdown reads the deadline instant, never a display string."""

    def test_gives_utc_instant(self):
        assert iso_utc(G803_DEADLINE) == "2026-12-17T11:59:59Z"

    def test_converts_aoe_value_to_utc(self):
        deadline = datetime.datetime(2026, 12, 16, 23, 59, 59, tzinfo=AOE)

        assert iso_utc(deadline) == "2026-12-17T11:59:59Z"

    def test_rejects_naive_datetime(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            iso_utc(datetime.datetime.fromisoformat("2026-12-17T11:59:59"))

    def test_rejects_none(self):
        with pytest.raises(ValueError, match="no date"):
            iso_utc(None)


class TestTimeanddateUrl:
    """The no-JavaScript fallback link, built as the website builds it."""

    def test_matches_website_link_for_g803(self):
        assert timeanddate_url(G803_DEADLINE) == (
            "https://www.timeanddate.com/worldclock/fixedtime.html"
            "?iso=20261216T2359&p1=3399"
        )

    def test_rejects_none(self):
        with pytest.raises(ValueError, match="no date"):
            timeanddate_url(None)
