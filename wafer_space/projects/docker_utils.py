"""Docker utility functions for manufacturability checks."""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import UTC
from datetime import datetime
from functools import wraps
from typing import TYPE_CHECKING
from typing import Any
from typing import ParamSpec
from typing import TypeVar

from celery import shared_task

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Generator

P = ParamSpec("P")
T = TypeVar("T")

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

    Note:
        Prefer using @queued_check_task decorator instead of this context manager.
    """
    # Import here to avoid circular dependency
    from wafer_space.projects.models import ManufacturabilityCheckTask  # noqa: PLC0415

    try:
        yield
    finally:
        ManufacturabilityCheckTask.objects.filter(
            manufacturability_check_id=check_id
        ).delete()


def queued_check_task(
    **celery_kwargs: Any,
) -> Callable[[Callable[..., T]], Any]:
    """Decorator for manufacturability check work tasks.

    Combines @shared_task with automatic task tracking cleanup.
    The decorated function's first argument must be check_id.

    Args:
        **celery_kwargs: Arguments passed to @shared_task
            (e.g., queue="docker-ephemeral")

    Returns:
        Decorator that wraps the function with task tracking and Celery integration.

    Example:
        @queued_check_task(queue="docker-ephemeral")
        def do_running(check_id: int) -> dict[str, Any]:
            check = ManufacturabilityCheck.objects.get(id=check_id)
            # ... do work
            return {"status": "completed"}
    """
    # Default to docker-ephemeral queue if not specified
    if "queue" not in celery_kwargs:
        celery_kwargs["queue"] = "docker-ephemeral"

    def decorator(func: Callable[..., T]) -> Any:
        @wraps(func)
        def wrapper(check_id: int, *args: Any, **kwargs: Any) -> T:
            # Import here to avoid circular dependency
            from wafer_space.projects.models import (  # noqa: PLC0415
                ManufacturabilityCheckTask,
            )

            try:
                return func(check_id, *args, **kwargs)
            finally:
                ManufacturabilityCheckTask.objects.filter(
                    manufacturability_check_id=check_id
                ).delete()

        # Apply shared_task decorator with provided kwargs
        # Return type is Any because Celery tasks have special methods
        # like .delay() and .apply_async()
        return shared_task(**celery_kwargs)(wrapper)

    return decorator
