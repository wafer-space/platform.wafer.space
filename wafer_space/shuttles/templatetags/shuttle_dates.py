"""Template filters for showing shuttle dates as wafer.space publishes them.

Deadlines are stored as 23:59:59 AoE (Anywhere on Earth, UTC-12) and
must be shown in AoE: rendered in the site's UTC time zone they fall on
the next calendar day. Milestones are stored as midnight UTC and are
shown as that UTC day.
"""

from __future__ import annotations

import datetime

from django import template
from django.utils import dateformat
from django.utils import timezone

register = template.Library()

AOE = datetime.timezone(datetime.timedelta(hours=-12), "AoE")


def _require_aware(value: datetime.datetime | None) -> datetime.datetime:
    # Templates guard optional dates with {% if %}; reaching a filter without
    # one is a template bug, so fail loudly rather than print a placeholder.
    if value is None:
        msg = "Shuttle date filter got no date; guard it with {% if %}"
        raise ValueError(msg)
    if value.tzinfo is None or value.utcoffset() is None:
        msg = f"Shuttle date must be timezone-aware, got {value!r}"
        raise ValueError(msg)
    return value


@register.filter
def aoe_deadline(value: datetime.datetime | None) -> str:
    """Format a deadline like wafer.space: '16 December 2026 @ 11:59 PM AoE'."""
    deadline = _require_aware(value)
    return dateformat.format(deadline.astimezone(AOE), r"j F Y \@ h:i A \A\o\E")


@register.filter
def milestone_date(value: datetime.datetime | None) -> str:
    """Format a milestone stored as midnight UTC: '8 January 2026'."""
    milestone = _require_aware(value)
    return dateformat.format(milestone.astimezone(datetime.UTC), "j F Y")


@register.filter
def iso_utc(value: datetime.datetime | None) -> str:
    """The deadline instant in UTC for scripts: '2026-12-17T11:59:59Z'.

    Countdowns and local-time display read only this value, never a
    formatted display string (#349).
    """
    instant = _require_aware(value).astimezone(datetime.UTC)
    return instant.strftime("%Y-%m-%dT%H:%M:%SZ")


# timeanddate.com location id the website's "see in your timezone" links use
# for AoE (wafer-space.github.io _data/runs.yml).
TIMEANDDATE_AOE_LOCATION = 3399


@register.filter
def timeanddate_url(value: datetime.datetime | None) -> str:
    """The website's 'see in your timezone' link for an AoE deadline."""
    deadline = _require_aware(value).astimezone(AOE)
    return (
        "https://www.timeanddate.com/worldclock/fixedtime.html"
        f"?iso={deadline:%Y%m%dT%H%M}&p1={TIMEANDDATE_AOE_LOCATION}"
    )


@register.inclusion_tag("shuttles/_deadline.html")
def shuttle_deadline(
    deadline: datetime.datetime | None,
    label: str = "",
    *,
    compact: bool = False,
) -> dict[str, object]:
    """A deadline as wafer.space shows it: AoE, local time, countdown (#349).

    The server decides whether the deadline has passed, so a page loaded
    after it never counts down; the script refines the countdown from the
    UTC instant only.
    """
    instant = _require_aware(deadline)
    remaining = instant - timezone.now()
    return {
        "compact": compact,
        "label": label,
        "aoe_date": dateformat.format(instant.astimezone(AOE), r"j F Y \@ h:i A"),
        "iso_utc": iso_utc(instant),
        "timeanddate_url": timeanddate_url(instant),
        "passed": remaining <= datetime.timedelta(0),
        "days_left": remaining.days,
    }
