"""Docker utility functions for manufacturability checks."""

from __future__ import annotations

import gzip
import io
import pathlib
import re
import tarfile
import tempfile
from contextlib import contextmanager
from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator
    from typing import IO

import docker
from django.conf import settings

from .hashing import MultiHasher

if TYPE_CHECKING:
    import logging
    from pathlib import Path

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
    return docker.DockerClient(
        base_url=str(server["url"]),
        timeout=settings.DOCKER_CLIENT_TIMEOUT,
    )


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


@contextmanager
def create_tar_archive(
    file_path: Path | str,
    arcname: str = "design.gds",
) -> Generator[IO[bytes]]:
    """Create a tar archive from a file using streaming (no memory buffering).

    This is used with Docker's put_archive() API to upload files
    to a container without using bind mounts, enabling support
    for remote Docker servers.

    Uses a temporary file to avoid buffering large GDS files in memory.
    The temp file is automatically cleaned up when the context manager exits.

    Args:
        file_path: Path to the file to archive.
        arcname: Name of the file inside the archive.

    Yields:
        File handle for the tar archive, seeked to position 0.

    Example:
        with create_tar_archive(gds_path, arcname="input/design.gds") as tar_stream:
            tar_size = tar_stream.seek(0, 2)  # Get size
            tar_stream.seek(0)
            container.put_archive("/", tar_stream)
    """
    path = pathlib.Path(file_path) if isinstance(file_path, str) else file_path
    # Write tar to temp file (context manager ensures proper cleanup)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".tar") as temp_file:
        with tarfile.open(fileobj=temp_file, mode="w") as tar:
            tar.add(str(path), arcname=arcname)
        temp_path = pathlib.Path(temp_file.name)
    # Re-open for reading and yield to caller
    try:
        with temp_path.open("rb") as read_handle:
            yield read_handle
    finally:
        temp_path.unlink(missing_ok=True)


def create_directory_tar(dirname: str) -> io.BytesIO:
    """Create an in-memory tar archive containing an empty directory.

    This is used with Docker's put_archive() API to create directories
    in a container.

    Args:
        dirname: Name of the directory to create (e.g., "output").

    Returns:
        BytesIO stream containing the tar archive, seeked to position 0.
    """
    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as tar:
        # Create a TarInfo for the directory
        dir_info = tarfile.TarInfo(name=dirname)
        dir_info.type = tarfile.DIRTYPE
        dir_info.mode = 0o755
        tar.addfile(dir_info)
    tar_stream.seek(0)
    return tar_stream


def stream_archive_to_file(
    container: docker.models.containers.Container,
    container_path: str,
    output_path: Path,
    logger: logging.Logger,
    *,
    compress: bool = False,
) -> tuple[int, dict[str, str]] | None:
    """Stream archive from container to file, calculating checksums.

    Args:
        container: Docker container.
        container_path: Path inside container to extract.
        output_path: Local path to write to.
        logger: Logger instance.
        compress: Whether to gzip compress the output.

    Returns:
        Tuple of (bytes_written, checksums_dict) or None if path doesn't exist.
    """
    try:
        bits, _stat = container.get_archive(container_path)
    except docker.errors.NotFound:
        logger.info("Path %s not found in container", container_path)
        return None
    except docker.errors.DockerException as e:
        logger.warning("Failed to extract %s: %s", container_path, e)
        return None

    hasher = MultiHasher(algorithms=["sha256"])
    bytes_written = 0

    # Use temp file in same directory to ensure atomic move
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    try:
        if compress:
            with gzip.open(temp_path, "wb", compresslevel=9) as f:
                for chunk in bits:
                    hasher.update(chunk)
                    f.write(chunk)
                    bytes_written += len(chunk)
        else:
            with temp_path.open("wb") as f:
                for chunk in bits:
                    hasher.update(chunk)
                    f.write(chunk)
                    bytes_written += len(chunk)

        # Atomic rename
        temp_path.rename(output_path)

        logger.info(
            "Extracted %s to %s (%d bytes, sha256=%s...)",
            container_path,
            output_path,
            bytes_written,
            hasher.hexdigest("sha256")[:16],
        )

        return bytes_written, hasher.hexdigests()

    except Exception:
        # Clean up temp file on failure
        if temp_path.exists():
            temp_path.unlink()
        raise


def stream_container_diff_to_file(
    container: docker.models.containers.Container,
    output_path: Path,
    logger: logging.Logger,
) -> tuple[int, dict[str, str]] | None:
    """Stream container filesystem changes to compressed tarball.

    Uses docker export to get the full container filesystem.
    The exported archive includes all changes since container start.

    Args:
        container: Docker container (can be running or stopped).
        output_path: Local path to write .tar.gz to.
        logger: Logger instance.

    Returns:
        Tuple of (bytes_written, checksums_dict) or None if export fails.
    """
    try:
        # Use export() which returns a generator of raw tar chunks
        export_stream = container.export()
    except docker.errors.DockerException as e:
        logger.warning("Failed to export container: %s", e)
        return None

    hasher = MultiHasher(algorithms=["sha256"])
    bytes_written = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    try:
        with gzip.open(temp_path, "wb", compresslevel=9) as gz_file:
            for chunk in export_stream:
                gz_file.write(chunk)

        # Read the compressed file to calculate hash
        with temp_path.open("rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
                bytes_written += len(chunk)

        # Atomic rename
        temp_path.rename(output_path)

        logger.info(
            "Exported container to %s (%d bytes compressed)",
            output_path,
            bytes_written,
        )

        return bytes_written, hasher.hexdigests()

    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
