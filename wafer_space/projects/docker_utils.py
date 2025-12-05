"""Docker utility functions for manufacturability checks."""

from __future__ import annotations

import re
from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING

import docker
from django.conf import settings

if TYPE_CHECKING:
    import logging

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
