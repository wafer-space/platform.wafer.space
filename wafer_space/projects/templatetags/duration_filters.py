"""Template filters for formatting durations."""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta

from django import template

register = template.Library()


@register.filter
def duration(value: timedelta | float | None) -> str:
    """Format a duration as human-readable string like '1h 42m 12s'.

    Accepts:
        - timedelta objects
        - float/int seconds
        - None (returns '-')

    Examples:
        {{ check.elapsed_seconds|duration }} -> "12m 30s"
        {{ timedelta_obj|duration }} -> "1h 42m 12s"
    """
    if value is None:
        return "-"

    if isinstance(value, timedelta):
        total_seconds = int(value.total_seconds())
    else:
        total_seconds = int(value)

    if total_seconds < 0:
        return "-"

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")

    return " ".join(parts)


@register.filter
def duration_between(end_time: datetime | None, start_time: datetime | None) -> str:
    """Calculate and format duration between two datetimes.

    Usage:
        {{ check.analysis_completed_at|duration_between:check.created_at }}

    Returns '-' if either time is None.
    """
    if end_time is None or start_time is None:
        return "-"

    delta = end_time - start_time
    return duration(delta)
