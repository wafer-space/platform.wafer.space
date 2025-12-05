"""Docker utility functions for manufacturability checks."""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

# Matches Docker RFC3339Nano timestamp at start of line
DOCKER_TIMESTAMP_PATTERN = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d+)Z"
)


def parse_docker_timestamp_float(line: str) -> float | None:
    """Extract timestamp from Docker log line as Unix float with nanoseconds.

    Docker log timestamps are RFC3339Nano format:
    2024-12-05T14:30:45.123456789Z

    Args:
        line: A Docker log line, potentially starting with timestamp.

    Returns:
        Unix timestamp as float with nanosecond precision, or None if no match.
    """
    match = DOCKER_TIMESTAMP_PATTERN.match(line)
    if not match:
        return None

    year, month, day, hour, minute, second, nanos = match.groups()

    dt = datetime(
        int(year),
        int(month),
        int(day),
        int(hour),
        int(minute),
        int(second),
        tzinfo=UTC,
    )

    unix_seconds = dt.timestamp()
    nano_fraction = int(nanos) / (10 ** len(nanos))

    return unix_seconds + nano_fraction


def strip_docker_timestamps(logs: str) -> str:
    """Remove Docker timestamps from log lines.

    Args:
        logs: Raw Docker logs with timestamps.

    Returns:
        Logs with timestamps stripped from each line.
    """
    if not logs:
        return logs

    lines = logs.split("\n")
    clean_lines = []

    for line in lines:
        match = DOCKER_TIMESTAMP_PATTERN.match(line)
        if match:
            # Remove timestamp and the 'Z ' after it
            clean_lines.append(line[match.end() :].lstrip())
        else:
            clean_lines.append(line)

    return "\n".join(clean_lines)


@contextmanager
def track_task(check_id: int) -> Generator[None]:
    """Delete task tracking row when work completes.

    Used by work tasks (do_*) to clean up their ManufacturabilityCheckTask
    row regardless of success or failure.

    Args:
        check_id: ID of the ManufacturabilityCheck.

    Yields:
        None - work is done in the context block.
    """
    # Import here to avoid circular dependency
    from wafer_space.projects.models import ManufacturabilityCheckTask  # noqa: PLC0415

    try:
        yield
    finally:
        ManufacturabilityCheckTask.objects.filter(
            manufacturability_check_id=check_id
        ).delete()
