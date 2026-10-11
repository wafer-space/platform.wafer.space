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
