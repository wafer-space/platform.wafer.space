"""Docker utility functions for manufacturability checks."""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from datetime import UTC
from datetime import datetime
from functools import wraps
from typing import TYPE_CHECKING
from typing import Any
from typing import ParamSpec
from typing import TypeVar

import docker
from celery import shared_task
from django.conf import settings

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
    *,
    expected_status: str | None = None,
    **celery_kwargs: Any,
) -> Callable[[Callable[..., T]], Any]:
    """Decorator for manufacturability check work tasks.

    Combines @shared_task with automatic task tracking cleanup and optional
    status verification. The decorated function receives a ManufacturabilityCheck
    object as its first argument (fetched from the check_id passed by Celery).

    Args:
        expected_status: If provided, verify check.status matches this value
            before calling the wrapped function. Returns skip result if mismatch.
            Use the status name, e.g., "DISPATCHING", "STARTING", "RUNNING".
        **celery_kwargs: Arguments passed to @shared_task
            (e.g., queue="docker-ephemeral")

    Returns:
        Decorator that wraps the function with task tracking and Celery integration.

    Example:
        @queued_check_task(expected_status="RUNNING")
        def do_running(check: ManufacturabilityCheck) -> dict[str, Any]:
            # check is already fetched and status verified
            # ... do work
            return {"status": "completed"}
    """
    # Default to docker-ephemeral queue if not specified
    if "queue" not in celery_kwargs:
        celery_kwargs["queue"] = "docker-ephemeral"

    def decorator(func: Callable[..., T]) -> Any:
        @wraps(func)
        def wrapper(check_id: int, *args: Any, **kwargs: Any) -> T | dict[str, str]:
            import logging  # noqa: PLC0415

            # Import here to avoid circular dependency
            from wafer_space.projects.models import (  # noqa: PLC0415
                ManufacturabilityCheck,
            )
            from wafer_space.projects.models import (  # noqa: PLC0415
                ManufacturabilityCheckTask,
            )

            logger = logging.getLogger(__name__)

            logger.info("Starting %s for check %s", func.__name__, check_id)

            try:
                # Fetch the check object
                check = ManufacturabilityCheck.objects.get(id=check_id)

                # Verify expected status if specified
                if expected_status and check.status != expected_status:
                    logger.info(
                        "Skipping %s for check %s - status changed to %s",
                        func.__name__,
                        check_id,
                        check.status,
                    )
                    return {"status": "skipped", "reason": "status_changed"}

                # Call wrapped function with check object
                result = func(check, *args, **kwargs)
                logger.info("Completed %s for check %s", func.__name__, check_id)
                return result
            finally:
                ManufacturabilityCheckTask.objects.filter(
                    manufacturability_check_id=check_id
                ).delete()

        # Apply shared_task decorator with provided kwargs
        # Return type is Any because Celery tasks have special methods
        # like .delay() and .apply_async()
        return shared_task(**celery_kwargs)(wrapper)

    return decorator


def checks_task(**celery_kwargs: Any) -> Callable[[Callable[..., T]], Any]:
    """Decorator for periodic checks_ tasks with automatic logging.

    Wraps function with @shared_task and adds start/stop logging.
    The function name is used in log messages (e.g., "[checks_pending] Starting...").

    Args:
        **celery_kwargs: Arguments passed to @shared_task (e.g., queue="default")

    Returns:
        Decorator that wraps the function with Celery and logging.

    Example:
        @checks_task(queue="default")
        def checks_pending() -> dict[str, int]:
            # ... do work
            return {"dispatched": 5}
    """
    # Default to default queue if not specified
    if "queue" not in celery_kwargs:
        celery_kwargs["queue"] = "default"

    def decorator(func: Callable[..., T]) -> Any:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            logger = logging.getLogger(__name__)

            logger.info("[%s] Starting", func.__name__)

            result = func(*args, **kwargs)

            logger.info("[%s] Complete", func.__name__)

            return result

        return shared_task(**celery_kwargs)(wrapper)

    return decorator


def get_server_config(server_id: str) -> dict | None:
    """Get server config by ID from DOCKER_SERVERS settings.

    Args:
        server_id: The server ID to look up.

    Returns:
        Server config dict if found, None otherwise.
    """
    return next(
        (s for s in settings.DOCKER_SERVERS if s["id"] == server_id),
        None,
    )


def get_docker_client(server: dict) -> docker.DockerClient:
    """Create a Docker client for the given server config.

    Args:
        server: Server config dict with 'url' key.

    Returns:
        Docker client instance.

    Raises:
        docker.errors.DockerException: If connection fails.
    """
    return docker.DockerClient(base_url=str(server["url"]))


def stop_and_remove_container(
    container: docker.models.containers.Container,
    logger: logging.Logger,
) -> None:
    """Stop and remove a Docker container safely.

    Args:
        container: Docker container to remove.
        logger: Logger for error messages.
    """
    try:
        if container.status == "running":
            container.stop(timeout=10)
        container.remove(force=True)
    except docker.errors.DockerException:
        logger.exception("Failed to remove container %s", container.id)
