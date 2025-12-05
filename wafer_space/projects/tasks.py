"""
Background tasks for project processing.
"""

import contextlib
import hashlib
import logging
import os
import socket
import tempfile
import time
import traceback
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request
from urllib.request import urlopen

import docker
import docker.errors
import requests
from celery import shared_task
from celery.utils.log import get_task_logger
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models
from django.db import transaction
from django.utils import timezone
from django_celery_results.models import TaskResult

from wafer_space.notifications.services import NotificationService

from .content_pipeline import ContentPipeline
from .content_pipeline import cleanup_temp_dir
from .content_pipeline import get_temp_dir_for_file
from .content_processors import _processor_registry
from .docker_utils import parse_docker_timestamp_float
from .docker_utils import strip_docker_timestamps
from .docker_utils import track_task
from .exceptions import InvalidStateTransitionError
from .file_type_utils import detect_file_type_from_data
from .format_validators import validate_output_format
from .models import DownloadAttempt
from .models import FileProcessingError
from .models import ManufacturabilityCheck
from .models import ManufacturabilityCheckpoint
from .models import ManufacturabilityCheckTask
from .models import Project
from .models import ProjectFile
from .models import ProjectFileChunk
from .precheck_parser import PrecheckLogParser
from .precheck_parser import classify_failure
from .processors.top_cell_extractor import extract_top_cell
from .url_handlers import GitHubArtifactHandler
from .url_handlers import GoogleSourceHandler
from .url_handlers import URLHandlerRegistry
from .verification import is_check_task_actively_running
from .verification import is_download_task_actively_running
from .verification import is_download_task_queued

# HTTP status codes
HTTP_PARTIAL_CONTENT = 206  # Server supports range requests

# Byte conversion constants
BYTES_PER_KILOBYTE = 1024

# Progress logging interval (seconds)
PROGRESS_LOG_INTERVAL_SECONDS = 30

# Initialize URL handler registry for post-download processing
_url_handler_registry = URLHandlerRegistry()
_url_handler_registry.register(GoogleSourceHandler())
_url_handler_registry.register(GitHubArtifactHandler())


# Helper functions for file download
def _format_bytes(num_bytes: int) -> str:
    """Format bytes in human-readable format (KB, MB, GB, TB).

    Args:
        num_bytes: Number of bytes to format

    Returns:
        str: Formatted string like "1.23 MB" or "456.78 GB"
    """
    bytes_float = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if bytes_float < BYTES_PER_KILOBYTE:
            return f"{bytes_float:.2f} {unit}"
        bytes_float /= BYTES_PER_KILOBYTE
    return f"{bytes_float:.2f} PB"


# Checkpoint interval for manufacturability checks (seconds)
CHECKPOINT_INTERVAL_SECONDS = 10


def _calculate_cpu_percent(stats: dict[str, Any]) -> float | None:
    """Calculate CPU percentage from Docker stats.

    Args:
        stats: Docker container stats dictionary

    Returns:
        CPU percentage or None if stats unavailable
    """
    try:
        cpu_stats = stats.get("cpu_stats", {})
        precpu_stats = stats.get("precpu_stats", {})

        current_cpu = cpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        previous_cpu = precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
        cpu_delta = current_cpu - previous_cpu

        system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get(
            "system_cpu_usage", 0
        )

        online_cpus = cpu_stats.get("online_cpus") or len(
            cpu_stats.get("cpu_usage", {}).get("percpu_usage", []) or [1]
        )

        if system_delta > 0 and cpu_delta > 0:
            return (cpu_delta / system_delta) * online_cpus * 100.0
    except (KeyError, TypeError, ZeroDivisionError):
        pass
    return None


def _record_checkpoint(
    check: "ManufacturabilityCheck",
    container,
    checkpoint_number: int,
    elapsed_seconds: float,
    logger: logging.Logger,
) -> None:
    """Record a checkpoint with Docker container stats.

    Args:
        check: ManufacturabilityCheck instance
        container: Docker container object
        checkpoint_number: Sequential checkpoint number
        elapsed_seconds: Seconds since container start
        logger: Logger instance
    """
    try:
        # Get container stats (non-streaming, single snapshot)
        stats = container.stats(stream=False)

        # Validate stats is a dict (not a mock)
        if not isinstance(stats, dict):
            logger.debug(
                "  Checkpoint %d: stats not available (mock)", checkpoint_number
            )
            return

        # Extract CPU stats
        cpu_stats = stats.get("cpu_stats", {})
        cpu_usage = cpu_stats.get("cpu_usage", {})
        cpu_percent = _calculate_cpu_percent(stats)

        # Extract memory stats
        memory_stats = stats.get("memory_stats", {})
        memory_usage = memory_stats.get("usage")
        memory_limit = memory_stats.get("limit")
        memory_cache = memory_stats.get("stats", {}).get("cache")
        memory_percent = None
        if (
            isinstance(memory_usage, int | float)
            and isinstance(memory_limit, int | float)
            and memory_limit > 0
        ):
            memory_percent = (memory_usage / memory_limit) * 100.0

        # Extract block I/O stats
        blkio_stats = stats.get("blkio_stats", {})
        io_service_bytes = blkio_stats.get("io_service_bytes_recursive") or []
        block_read = sum(
            entry.get("value", 0)
            for entry in io_service_bytes
            if entry.get("op") == "Read"
        )
        block_write = sum(
            entry.get("value", 0)
            for entry in io_service_bytes
            if entry.get("op") == "Write"
        )

        # Extract network stats
        networks = stats.get("networks", {})
        network_rx = sum(net.get("rx_bytes", 0) for net in networks.values())
        network_tx = sum(net.get("tx_bytes", 0) for net in networks.values())

        # Create checkpoint record
        ManufacturabilityCheckpoint.objects.create(
            manufacturability_check=check,
            checkpoint_number=checkpoint_number,
            elapsed_seconds=elapsed_seconds,
            cpu_percent=cpu_percent,
            cpu_total_usage=cpu_usage.get("total_usage"),
            cpu_system_usage=cpu_stats.get("system_cpu_usage"),
            cpu_online_cpus=cpu_stats.get("online_cpus"),
            memory_usage_bytes=memory_usage if isinstance(memory_usage, int) else None,
            memory_limit_bytes=memory_limit if isinstance(memory_limit, int) else None,
            memory_percent=memory_percent,
            memory_cache_bytes=memory_cache if isinstance(memory_cache, int) else None,
            block_read_bytes=block_read if block_read else None,
            block_write_bytes=block_write if block_write else None,
            network_rx_bytes=network_rx if network_rx else None,
            network_tx_bytes=network_tx if network_tx else None,
            container_state=stats.get("State", ""),
        )

        mem_str = (
            _format_bytes(memory_usage or 0) if isinstance(memory_usage, int) else "N/A"
        )
        logger.info(
            "  Checkpoint %d: CPU=%.1f%%, Mem=%.1f%% (%s)",
            checkpoint_number,
            cpu_percent or 0,
            memory_percent or 0,
            mem_str,
        )

    except (AttributeError, TypeError, KeyError) as e:
        # Handle cases where container is a mock or stats are unavailable
        logger.debug(
            "  Could not get stats for checkpoint %d: %s", checkpoint_number, e
        )


def _save_logs_to_file(
    check: "ManufacturabilityCheck",
    logs: str,
    logger: logging.Logger,
) -> None:
    """Save container logs to filesystem next to the GDS file.

    Creates a unique log file for each check run.
    Format: <gds_name>.<top_cell>.precheck.<timestamp>.log

    Args:
        check: ManufacturabilityCheck instance
        logs: Container logs string
        logger: Logger instance
    """
    try:
        timestamp = check.celery_job_started_at or timezone.now()
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")

        # Get GDS filename
        gds_name = "design"
        if check.project_file and check.project_file.processed_filename:
            gds_name = check.project_file.processed_filename

        # Get top cell name (sanitized for filesystem)
        top_cell = "unknown"
        if check.project_file and check.project_file.top_cell:
            top_cell = check.project_file.top_cell.replace("/", "_").replace("\\", "_")

        filename = f"{gds_name}.{top_cell}.precheck.{timestamp_str}.log"

        # Save logs using Django's file handling
        content = ContentFile(logs.encode("utf-8"))
        check.log_file.save(filename, content, save=True)

        logger.info("  ✓ Logs saved to: %s", check.log_file.name)
    except OSError as e:
        logger.warning("  Could not save logs to file: %s", e)


def _extract_runs_archive(
    check: "ManufacturabilityCheck",
    container,
    logger: logging.Logger,
) -> None:
    """Extract the runs/ directory from container and save as tar archive.

    The precheck tool creates detailed step logs in runs/RUN_<timestamp>/
    which contain more information than the main log output.

    Args:
        check: ManufacturabilityCheck instance
        container: Docker container object (must still exist, not yet removed)
        logger: Logger instance
    """
    try:
        # Get tar archive of runs directory from container
        # get_archive returns (tar_stream, stat_info)
        tar_stream, _stat_info = container.get_archive("/workspace/runs")

        # Read the tar data
        tar_data = b"".join(tar_stream)

        if len(tar_data) == 0:
            logger.info("  No runs directory found in container")
            return

        logger.info("  Extracted runs archive: %d bytes", len(tar_data))

        # Generate filename
        timestamp = check.celery_job_started_at or timezone.now()
        timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
        gds_name = "design"
        if check.project_file and check.project_file.processed_filename:
            gds_name = check.project_file.processed_filename
        top_cell = "unknown"
        if check.project_file and check.project_file.top_cell:
            top_cell = check.project_file.top_cell.replace("/", "_").replace("\\", "_")

        filename = f"{gds_name}.{top_cell}.precheck.{timestamp_str}.runs.tar"

        # Save using Django's file handling
        content = ContentFile(tar_data)
        check.runs_archive.save(filename, content, save=True)

        logger.info("  ✓ Runs archive saved to: %s", check.runs_archive.name)

    except docker.errors.NotFound:
        logger.info("  No runs directory found in container (path does not exist)")
    except OSError as e:
        logger.warning("  Could not save runs archive: %s", e)


def _setup_temp_directory() -> Path:
    """Create and return temporary directory for downloads."""
    temp_dir = Path(tempfile.gettempdir()) / "wafer_space_downloads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def _extract_filename_from_url(url: str) -> str:
    """Extract filename from URL or return default."""
    parsed_url = urlparse(url)
    return Path(parsed_url.path).name or "downloaded_file"


def _calculate_file_hashes(content: bytes) -> tuple[str, str, str]:
    """Calculate MD5, SHA1, and SHA256 hashes for file content.

    Note: MD5 and SHA1 are used here for file integrity verification only,
    not for cryptographic security purposes. These match industry standard
    hash algorithms commonly used for file verification in manufacturing.
    SHA256 is also provided as a more modern alternative.
    """
    md5_hash = hashlib.md5(content, usedforsecurity=False).hexdigest()
    sha1_hash = hashlib.sha1(content, usedforsecurity=False).hexdigest()
    sha256_hash = hashlib.sha256(content).hexdigest()
    return md5_hash, sha1_hash, sha256_hash


def _verify_file_hashes(
    project_file,
    hashes: "HashResults",
) -> tuple[bool, list[str]]:
    """Verify file hashes against expected values."""
    verified = True
    errors = []

    if project_file.expected_hash_md5:
        if hashes.md5.lower() != project_file.expected_hash_md5.lower():
            verified = False
            errors.append(
                f"MD5 mismatch: expected {project_file.expected_hash_md5}, "
                f"got {hashes.md5}",
            )

    if project_file.expected_hash_sha1:
        if hashes.sha1.lower() != project_file.expected_hash_sha1.lower():
            verified = False
            errors.append(
                f"SHA1 mismatch: expected {project_file.expected_hash_sha1}, "
                f"got {hashes.sha1}",
            )

    if project_file.expected_hash_sha256:
        if hashes.sha256.lower() != project_file.expected_hash_sha256.lower():
            verified = False
            errors.append(
                f"SHA256 mismatch: expected {project_file.expected_hash_sha256}, "
                f"got {hashes.sha256}",
            )

    return verified, errors


@dataclass
class _CheckContext:
    """Context object for manufacturability check execution."""

    check: "ManufacturabilityCheck"
    client: "docker.DockerClient"
    project: "Project"
    project_file: "ProjectFile"
    gds_path: str
    task_instance: "shared_task"
    logger: logging.Logger
    container: Any = None  # Set by _start_container()


def _pull_and_record_image(context: _CheckContext) -> tuple[str, str]:
    """Pull Docker image and return metadata (does not save to database).

    Args:
        context: Check execution context

    Returns:
        Tuple of (docker_image tag, docker_image_digest)
    """
    image_name = settings.PRECHECK_DOCKER_IMAGE
    context.logger.info("Step 3: Pulling Docker image: %s", image_name)

    # Check if image already exists locally
    try:
        existing = context.client.images.get(image_name)
        context.logger.info("  ✓ Image already exists locally: %s", existing.id[:12])
        context.logger.info("  Checking for updates...")
    except docker.errors.ImageNotFound:
        context.logger.info("  Image not found locally, will download...")

    # Pull with progress logging
    context.logger.info("  Starting pull (this may take several minutes)...")
    pull_start = timezone.now()
    last_status = {}

    # Use low-level API to get progress
    for line in context.client.api.pull(image_name, stream=True, decode=True):
        status = line.get("status", "")
        progress = line.get("progress", "")
        layer_id = line.get("id", "")

        # Log layer progress changes
        if layer_id and status:
            key = f"{layer_id}:{status}"
            if key not in last_status:
                last_status[key] = True
                layer_short = layer_id[:12]
                if progress:
                    context.logger.info("    [%s] %s %s", layer_short, status, progress)
                elif status in ("Pull complete", "Already exists", "Download complete"):
                    context.logger.info("    [%s] %s", layer_short, status)
        elif status and not layer_id:
            # Status without layer ID (e.g., "Digest:", "Status:")
            context.logger.info("  %s", status)

    pull_duration = (timezone.now() - pull_start).total_seconds()
    context.logger.info("  Pull completed in %.1f seconds", pull_duration)

    # Get the pulled image
    image = context.client.images.get(image_name)
    docker_image = image.tags[0] if image.tags else image_name
    docker_image_digest = image.id

    # Log image details
    image_size = image.attrs.get("Size", 0)
    context.logger.info(
        "  ✓ Image ready: %s (digest: %s, size: %s)",
        docker_image,
        docker_image_digest[:12],
        _format_bytes(image_size),
    )
    return docker_image, docker_image_digest


def _stream_logs_with_checkpoints(context: _CheckContext, container, container_start):
    """Stream container logs and record checkpoints periodically.

    Args:
        context: Check execution context
        container: Docker container object
        container_start: Datetime when container started

    Returns:
        tuple: (logs string, line_count int, checkpoint_number int)
    """
    logs = ""
    line_count = 0
    last_progress_log = timezone.now()
    last_checkpoint_time = timezone.now()
    checkpoint_number = 0

    # Record initial checkpoint
    _record_checkpoint(context.check, container, checkpoint_number, 0.0, context.logger)
    checkpoint_number += 1

    for line in container.logs(stream=True):
        line_text = line.decode("utf-8")
        logs += line_text
        line_count += 1

        # Update logs using model method (the only allowed update during RUNNING)
        context.check.update_processing_logs(logs)

        now = timezone.now()

        # Record checkpoint periodically
        if (now - last_checkpoint_time).total_seconds() >= CHECKPOINT_INTERVAL_SECONDS:
            elapsed = (now - container_start).total_seconds()
            _record_checkpoint(
                context.check, container, checkpoint_number, elapsed, context.logger
            )
            checkpoint_number += 1
            last_checkpoint_time = now

        # Periodic progress update
        if (now - last_progress_log).total_seconds() >= PROGRESS_LOG_INTERVAL_SECONDS:
            elapsed = (now - container_start).total_seconds()
            context.logger.info(
                "  ... still running (%.0f seconds, %d log lines)", elapsed, line_count
            )
            last_progress_log = now

        # Update Celery task state
        context.task_instance.update_state(
            state="PROGRESS",
            meta={
                "message": "Running precheck...",
                "logs": logs[-1000:],
                "line_count": line_count,
            },
        )

    return logs, line_count, checkpoint_number


def _start_container(context: _CheckContext) -> tuple[str, str]:
    """Build docker command and start container.

    Args:
        context: Check execution context

    Returns:
        tuple: (docker_command string for reproducibility, container_id string)

    Note: The container object is stored in context.container for later use.
    """
    context.logger.info("Step 4: Creating Docker container...")
    context.logger.info("  Input file: %s", context.gds_path)
    context.logger.info("  Project name: %s", context.project.name)
    context.logger.info("  Project ID: %s", context.project.id)
    context.logger.info("  Slot size: %s", context.project.slot_size)
    context.logger.info("  Memory limit: 24GB")

    # Build the precheck command to run inside nix-shell
    if not context.project_file.top_cell:
        msg = "Cannot run manufacturability check: top_cell not extracted from file"
        raise ValueError(msg)

    if not context.project.full_id:
        msg = (
            "Cannot run manufacturability check: "
            "project must be assigned to shuttle with project ID"
        )
        raise ValueError(msg)

    full_id = context.project.full_id
    top_cell = context.project_file.top_cell
    context.logger.info("  Top cell: %s", top_cell)

    # Build command - the container's dev-shell entrypoint handles nix develop --offline
    slot_size = context.project.slot_size
    docker_command_list = [
        "python3",
        "precheck.py",
        "--input",
        "/input/design.gds",
        "--top",
        top_cell,
        "--slot",
        slot_size,
        "--id",
        full_id,
    ]

    # Log equivalent docker run command for easy reproduction
    precheck_cmd = (
        f"python3 precheck.py --input /input/design.gds "
        f'--top "{top_cell}" --slot {slot_size} --id {full_id}'
    )
    docker_command = (
        f"docker run --rm --network=none "
        f"-e COLUMNS=200 -e TERM=xterm-256color "
        f"-v {context.gds_path}:/input/design.gds:ro "
        f"-w /workspace "
        f"--memory 24g "
        f"{settings.PRECHECK_DOCKER_IMAGE} "
        f"{precheck_cmd}"
    )
    context.logger.info("  Docker run command:")
    context.logger.info("  %s", docker_command)

    # CRITICAL: Container is created with labels atomically BEFORE check status
    # transitions to RUNNING. This ensures orphaned check detection can find
    # containers by label. Labels are set during container creation (atomic).
    container = context.client.containers.run(
        image=settings.PRECHECK_DOCKER_IMAGE,
        command=docker_command_list,
        volumes={context.gds_path: {"bind": "/input/design.gds", "mode": "ro"}},
        working_dir="/workspace",
        detach=True,
        mem_limit="24g",
        network_disabled=True,
        environment={
            "COLUMNS": "200",  # Wide terminal for better log output
            "TERM": "xterm-256color",
        },
        labels={
            "wafer.space.service": "manufacturability-check",
            # Used by orphaned check detection to find container
            "wafer.space.check_id": str(context.check.id),
        },
    )
    context.logger.info("  ✓ Container started: %s", container.id[:12])

    # Store container in context for later use
    context.container = container

    return docker_command, container.id


def _run_container_to_completion(context: _CheckContext):
    """Stream logs and wait for container completion.

    Must be called after mark_running() - requires check to be in RUNNING state.

    Args:
        context: Check execution context (must have context.container set)

    Returns:
        tuple: (logs string, exit_code int)
    """
    container = context.container
    container_start = timezone.now()

    context.logger.info("Step 5: Running precheck analysis...")
    context.logger.info("  Streaming container logs...")

    # Stream logs and record checkpoints
    logs, line_count, checkpoint_number = _stream_logs_with_checkpoints(
        context, container, container_start
    )

    context.logger.info("Step 6: Waiting for container to complete...")

    # Wait for completion
    result = container.wait(timeout=settings.PRECHECK_TIMEOUT_SECONDS)
    exit_code = result["StatusCode"]

    container_duration = (timezone.now() - container_start).total_seconds()

    # Fetch complete logs after container exits to capture any final output
    # (streaming may miss buffered output that's flushed on exit)
    complete_logs = container.logs(stdout=True, stderr=True).decode("utf-8")
    if len(complete_logs) > len(logs):
        context.logger.info(
            "  Captured %d additional bytes of final output",
            len(complete_logs) - len(logs),
        )
        logs = complete_logs
        # Final log update before transitioning out of RUNNING
        context.check.update_processing_logs(logs)

    # Record final checkpoint
    _record_checkpoint(
        context.check, container, checkpoint_number, container_duration, context.logger
    )
    checkpoint_number += 1

    context.logger.info(
        "  ✓ Container completed in %.1f seconds "
        "(exit code: %d, %d log lines, %d checkpoints)",
        container_duration,
        exit_code,
        line_count,
        checkpoint_number,
    )

    return logs, exit_code


def _handle_check_result(check, logs, exit_code, logger):
    """Parse logs and update check status based on results.

    Args:
        check: ManufacturabilityCheck instance
        logs: Container logs string
        exit_code: Container exit code
        logger: Logger instance

    Returns:
        str or tuple: "success", "design", or ("system", error_message)
    """
    logger.info("Step 7: Parsing check results...")

    # Save logs to filesystem (before parsing, so we always have them)
    _save_logs_to_file(check, logs, logger)

    # Collect version information (will be passed to mark_finished)
    tool_versions = {
        "pdk": "gf180mcuD",  # Will extract from logs
        "magic": "unknown",  # Will extract from logs
        "klayout": "unknown",  # Will extract from logs
    }

    # Parse logs
    logger.info("  Parsing %d bytes of logs...", len(logs))
    parsed = PrecheckLogParser.parse_logs(logs, exit_code)
    logger.info(
        "  ✓ Parsing completed: success=%s, errors=%d, warnings=%d",
        parsed["success"],
        len(parsed["errors"]),
        len(parsed["warnings"]),
    )

    # Handle results based on exit code
    if exit_code != 0:
        # Failure - classify
        failure_type = classify_failure(logs, exit_code)
        logger.info("Check failed with type: %s", failure_type)

        if failure_type == "system":
            # System failure - prepare for retry (don't mark finished)
            error_summary = (
                parsed["errors"][0]["message"]
                if parsed["errors"]
                else "Unknown system error"
            )
            return "system", error_summary

    # Mark finished - either success or design failure
    # Pass tool_versions atomically with the state transition
    is_manufacturable = exit_code == 0
    check.mark_finished(
        is_manufacturable=is_manufacturable,
        errors=[] if is_manufacturable else parsed.get("errors", []),
        warnings=parsed.get("warnings", []),
        tool_versions=tool_versions,
    )

    if is_manufacturable:
        logger.info("Check completed successfully - project is manufacturable")
        return "success"
    logger.info("Design errors found - check completed with errors")
    return "design"


def _validate_project_file(check):
    """Validate that check has a valid GDS file.

    Args:
        check: ManufacturabilityCheck instance (must have project_file set)

    Returns:
        ProjectFile instance

    Raises:
        ValueError: If no valid file available
    """
    if not check.project_file:
        msg = "ManufacturabilityCheck must have a project_file"
        raise ValueError(msg)

    if not check.project_file.file:
        msg = "ProjectFile has no uploaded file"
        raise ValueError(msg)

    return check.project_file


def _cleanup_container(container, logger):
    """Remove Docker container safely.

    Args:
        container: Docker container object or None
        logger: Logger instance
    """
    if container:
        try:
            container.remove()
            logger.info("  ✓ Container removed")
        except docker.errors.DockerException as exc:
            logger.warning("  ⚠ Failed to remove container: %s", exc)


def _log_task_start(logger, check_id, task_id):
    """Log task start banner."""
    logger.info("=" * 60)
    logger.info("MANUFACTURABILITY CHECK TASK STARTING")
    logger.info("=" * 60)
    logger.info("Check ID: %s", check_id)
    logger.info("Task ID: %s", task_id)


def _log_task_complete(logger, task_start, check):
    """Log task completion summary."""
    task_duration = (timezone.now() - task_start).total_seconds()
    logger.info("=" * 60)
    logger.info("MANUFACTURABILITY CHECK COMPLETED")
    logger.info("  Duration: %.1f seconds", task_duration)
    logger.info("  Result: %s", "PASS" if check.is_manufacturable else "FAIL")
    logger.info("  Errors: %d", len(check.errors or []))
    logger.info("  Warnings: %d", len(check.warnings or []))
    logger.info("=" * 60)


def _log_project_info(check, project_file, logger):
    """Log project and file information.

    Args:
        check: ManufacturabilityCheck instance
        project_file: ProjectFile instance
        logger: Logger instance
    """
    logger.info("  ✓ Project: %s (ID: %s)", check.project.name, check.project.id)
    logger.info("  ✓ File: %s", project_file.original_filename)
    logger.info("  ✓ File size: %s", _format_bytes(project_file.file_size or 0))


def _setup_docker_context(check, project_file, task_instance, logger):
    """Set up Docker client and execution context.

    Returns:
        _CheckContext: Execution context for the check
    """
    logger.info("Step 2: Connecting to Docker daemon...")
    client = docker.from_env(timeout=settings.DOCKER_CLIENT_TIMEOUT)
    docker_info = client.info()
    logger.info("  ✓ Docker connected: %s", docker_info.get("Name", "unknown"))
    logger.info("  ✓ Docker version: %s", docker_info.get("ServerVersion", "unknown"))

    return _CheckContext(
        check=check,
        client=client,
        project=check.project,
        project_file=project_file,
        gds_path=project_file.file.path,
        task_instance=task_instance,
        logger=logger,
    )


def _mark_check_error_if_exists(
    check: ManufacturabilityCheck | None,
    error_message: str,
) -> None:
    """Mark check as ERROR if it exists.

    Helper to safely mark a check as failed during exception handling,
    when check might not have been loaded yet.
    """
    if check is not None:
        check.mark_error(error_message=error_message)


@shared_task(queue="maintenance")
def cleanup_old_task_results():
    """
    Periodic task to clean up old Celery task results.
    """
    # Delete task results older than 24 hours
    cutoff_date = timezone.now() - timedelta(hours=24)
    deleted_count = TaskResult.objects.filter(date_created__lt=cutoff_date).delete()[0]

    return {
        "status": "completed",
        "deleted_count": deleted_count,
        "cutoff_date": cutoff_date.isoformat(),
    }


def _safe_urlopen(url: str, headers: dict | None = None) -> tuple[bytes, dict]:
    """Safely open URL with security validation.

    Security Note:
    This function implements strict URL scheme validation to prevent security
    vulnerabilities. Only http:// and https:// schemes are allowed. This prevents:
    - file:// scheme attacks that could read local files
    - ftp://, ldap://, and other protocol injections
    - javascript:, data:, and other XSS-related schemes
    - Custom schemes that could be exploited

    The validation occurs before any network operations to ensure no dangerous
    URLs can reach the urllib.request.Request() or urlopen() calls.

    Args:
        url: URL to fetch (must be http or https)
        headers: Optional headers to add to request

    Returns:
        Tuple of (response content as bytes, response headers dict)

    Raises:
        ValueError: If URL scheme is not http or https
    """
    # SECURITY: Validate URL scheme for security - only allow http/https
    parsed_url = urlparse(url)
    if parsed_url.scheme.lower() not in ("http", "https"):
        msg = f"Unsupported URL scheme: {parsed_url.scheme.lower()}"
        raise ValueError(msg)

    request = Request(url)  # noqa: S310 - URL scheme validated above to only allow http/https

    # Add default user agent
    request.add_header("User-Agent", "wafer.space/1.0")

    # Add any additional headers
    if headers:
        for key, value in headers.items():
            request.add_header(key, value)

    with urlopen(request) as response:  # noqa: S310 - URL scheme validated above to only allow http/https
        return response.read(), dict(response.headers)


def _log_github_artifacts(artifacts: list[dict[str, Any]], run_id: str) -> None:
    """Log available GitHub artifacts with formatted size information."""
    logger = logging.getLogger(__name__)
    logger.info("  Available artifacts:")
    for idx, art in enumerate(artifacts, 1):
        art_name = art.get("name", "unknown")
        art_id = art.get("id", "unknown")
        art_size = art.get("size_in_bytes", 0)
        # Format size in human-readable format
        if art_size < BYTES_PER_KILOBYTE:
            size_str = f"{art_size} B"
        elif art_size < BYTES_PER_KILOBYTE * BYTES_PER_KILOBYTE:
            size_str = f"{art_size / BYTES_PER_KILOBYTE:.1f} KB"
        elif art_size < BYTES_PER_KILOBYTE * BYTES_PER_KILOBYTE * BYTES_PER_KILOBYTE:
            size_str = f"{art_size / (BYTES_PER_KILOBYTE * BYTES_PER_KILOBYTE):.1f} MB"
        else:
            gb_divisor = BYTES_PER_KILOBYTE * BYTES_PER_KILOBYTE * BYTES_PER_KILOBYTE
            size_str = f"{art_size / gb_divisor:.2f} GB"
        logger.info("    %d. %s (ID: %s, Size: %s)", idx, art_name, art_id, size_str)


def _select_github_artifact(
    artifacts: list[dict[str, Any]],
    artifact_id: str | None,
    run_id: str,
) -> dict[str, Any]:
    """Select a GitHub artifact by ID or return the first one.

    Args:
        artifacts: List of artifact dicts from GitHub API
        artifact_id: Optional specific artifact ID to find
        run_id: Run ID for error messages

    Returns:
        The selected artifact dict

    Raises:
        ValueError: If artifact_id is provided but not found
    """
    logger = logging.getLogger(__name__)

    if artifact_id:
        # Find the specific artifact by ID
        target_artifact_id = int(artifact_id)
        for art in artifacts:
            if art.get("id") == target_artifact_id:
                logger.info(
                    "  → Using specified artifact: %s (ID: %s)",
                    art.get("name"),
                    art.get("id"),
                )
                return art

        available_ids = [str(art.get("id")) for art in artifacts]
        msg = (
            f"Artifact ID {artifact_id} not found in run {run_id}. "
            f"Available artifact IDs: {', '.join(available_ids)}"
        )
        raise ValueError(msg)

    # Use first artifact
    artifact = artifacts[0]
    logger.info(
        "  → Selecting first artifact: %s (ID: %s)",
        artifact.get("name"),
        artifact.get("id"),
    )
    return artifact


def _build_github_artifact_filename(
    metadata: dict[str, Any],
    extracted_filename: str,
) -> str:
    """Build descriptive filename for GitHub artifact downloads.

    Format: {owner}.{repo}.r{run_id}-a{artifact_id}.{artifact_name}.{extracted_filename}

    Args:
        metadata: Handler metadata with owner, repo, run_id, artifact_id, artifact_name
        extracted_filename: Filename after extraction (e.g., design.gds)

    Returns:
        Descriptive filename like:
        TinyTapeout.tinytapeout-gf-0p2.r19443235082-a4593573393.chipfoundry.design.gds
    """
    owner = metadata.get("owner", "unknown")
    repo = metadata.get("repo", "unknown")
    run_id = metadata.get("run_id", "0")
    artifact_id = metadata.get("artifact_id", "0")
    artifact_name = metadata.get("artifact_name", "artifact")

    prefix = f"{owner}.{repo}.r{run_id}-a{artifact_id}.{artifact_name}"
    return f"{prefix}.{extracted_filename}"


def _download_github_artifact(
    owner: str,
    repo: str,
    run_id: str,
    github_token: str | None,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    """Get authenticated download URL for GitHub Actions artifact.

    GitHub artifact download URLs are authenticated and expire after 60 seconds.
    This function fetches the artifact list, selects the specified artifact
    (or first if not specified), and returns the authenticated download URL.

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        run_id: GitHub Actions run ID
        github_token: GitHub personal access token (requires actions:read scope)
        artifact_id: Optional specific artifact ID to download. If not provided,
                     downloads the first artifact from the run.

    Returns:
        dict with keys:
            - url: Authenticated download URL (valid for 60 seconds)
            - headers: HTTP headers required for download (Authorization, etc.)
            - artifact_name: Name of the selected artifact
            - artifact_id: ID of the selected artifact (string)
            - artifact_size: Size in bytes

    Raises:
        ValueError: If no artifacts found, artifact_id not found, or no token
    """
    logger = logging.getLogger(__name__)

    if not github_token:
        msg = "GitHub token required for artifact download"
        raise ValueError(msg)

    # GitHub API requires specific headers
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # List artifacts for the run
    list_url = (
        f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts"
    )

    logger.info("  Fetching artifact list from: %s", list_url)
    list_response = requests.get(list_url, headers=headers, timeout=30)
    list_response.raise_for_status()

    artifacts_data = list_response.json()
    artifacts = artifacts_data.get("artifacts", [])
    total_count = artifacts_data.get("total_count", 0)

    logger.info("  ✓ Found %d artifact(s) for run %s", total_count, run_id)

    if not artifacts:
        msg = f"No artifacts found for run {run_id}"
        raise ValueError(msg)

    # Log all available artifacts
    _log_github_artifacts(artifacts, run_id)

    # Select artifact: use specific ID if provided, otherwise use first
    artifact = _select_github_artifact(artifacts, artifact_id, run_id)
    artifact_name = artifact["name"]
    selected_artifact_id = str(artifact["id"])
    artifact_size = artifact.get("size_in_bytes", 0)

    # Construct authenticated download URL
    download_url = (
        f"https://api.github.com/repos/{owner}/{repo}/"
        f"actions/artifacts/{artifact['id']}/zip"
    )
    logger.info("  ✓ Generated authenticated download URL (valid for 60 seconds)")

    return {
        "url": download_url,
        "headers": headers,
        "artifact_name": artifact_name,
        "artifact_id": selected_artifact_id,
        "artifact_size": artifact_size,
    }


def _prepare_download_request(
    project_file: ProjectFile,
    temp_path: Path,
) -> tuple[str, dict[str, str], int]:
    """Prepare download request with resume support and GitHub authentication.

    For GitHub artifacts, obtains authenticated download URL (valid 60 seconds).
    For standard URLs, uses URL as-is with User-Agent header.

    Args:
        project_file: ProjectFile with source_url and handler_metadata
        temp_path: Path to temporary download file

    Returns:
        tuple: (download_url, headers dict, resume byte position)
    """
    logger = logging.getLogger(__name__)

    # Check if this is a GitHub artifact requiring authentication
    if project_file.handler_metadata and project_file.handler_metadata.get(
        "requires_github_auth"
    ):
        logger.info("  GitHub artifact detected - obtaining authenticated URL...")

        metadata = project_file.handler_metadata
        auth_data = _download_github_artifact(
            owner=metadata["owner"],
            repo=metadata["repo"],
            run_id=metadata["run_id"],
            github_token=settings.GITHUB_TOKEN,
            artifact_id=metadata.get("artifact_id"),
        )

        url = auth_data["url"]
        headers = auth_data["headers"].copy()  # Copy to avoid mutating original

        # Add User-Agent (GitHub requires it)
        headers["User-Agent"] = "wafer.space/1.0"

        # Store artifact info in metadata for filename generation after extraction
        updated_metadata = metadata.copy()
        updated_metadata["artifact_name"] = auth_data["artifact_name"]
        updated_metadata["artifact_id"] = auth_data["artifact_id"]
        project_file.handler_metadata = updated_metadata

        # Update original_filename to show descriptive name in UI during download
        # Format: {owner}.{repo}.r{run_id}-a{artifact_id}.{artifact_name}.zip
        download_filename = _build_github_artifact_filename(
            updated_metadata,
            "artifact.zip",  # Placeholder - will be updated after extraction
        )
        project_file.original_filename = download_filename

        project_file.save(update_fields=["handler_metadata", "original_filename"])

        logger.info(
            "  ✓ Authenticated URL obtained for artifact: %s (ID: %s)",
            auth_data["artifact_name"],
            auth_data["artifact_id"],
        )

        # GitHub artifact downloads don't support resume (they're dynamic URLs)
        resume_byte_pos = 0

        return url, headers, resume_byte_pos

    # Standard HTTP(S) download
    url = project_file.source_url
    headers = {"User-Agent": "wafer.space/1.0"}
    resume_byte_pos = 0

    if temp_path.exists():
        resume_byte_pos = temp_path.stat().st_size
        headers["Range"] = f"bytes={resume_byte_pos}-"
        formatted_size = _format_bytes(resume_byte_pos)
        logger.info("  Resume: Found partial download (%s)", formatted_size)

    return url, headers, resume_byte_pos


def _get_download_response(
    url: str,
    headers: dict[str, str],
    temp_path: Path,
    resume_byte_pos: int,
) -> tuple[requests.Response, int]:
    """Get HTTP response for download, handling resume failures.

    Args:
        url: Download URL
        headers: HTTP headers (may include Range, Authorization, etc.)
        temp_path: Path to temp file
        resume_byte_pos: Byte position to resume from

    Returns:
        tuple: (response object, adjusted resume byte position)
    """
    logger = logging.getLogger(__name__)
    logger.info("  Sending HTTP GET request...")
    response = requests.get(url, headers=headers, stream=True, timeout=30)
    logger.info("  Response status: %s", response.status_code)

    # Check if server supports resume
    if resume_byte_pos > 0 and response.status_code != HTTP_PARTIAL_CONTENT:
        logger.info("  Server doesn't support resume - restarting from beginning")
        resume_byte_pos = 0
        temp_path.unlink(missing_ok=True)
        # Remove Range header for fresh start
        headers_no_range = {k: v for k, v in headers.items() if k != "Range"}
        response = requests.get(url, headers=headers_no_range, stream=True, timeout=30)

    response.raise_for_status()
    return response, resume_byte_pos


def _log_file_size(
    response: requests.Response,
    project_file,
    resume_byte_pos: int,
) -> int:
    """Log file size and return total size.

    Returns:
        int: Total file size in bytes
    """
    logger = logging.getLogger(__name__)
    total_size = project_file.file_size or 0

    if "Content-Length" in response.headers:
        content_length = int(response.headers["Content-Length"])
        total_size = (
            resume_byte_pos + content_length if resume_byte_pos > 0 else content_length
        )
        logger.info("  Total file size: %s", _format_bytes(total_size))
    else:
        logger.info("  No Content-Length header - size unknown")

    return total_size


def _initialize_hash_calculators(
    temp_path: Path,
    resume_byte_pos: int,
):
    """Initialize hash calculators, updating with existing content if resuming.

    Returns:
        tuple: (md5_hasher, sha1_hasher, sha256_hasher)
    """
    logger = logging.getLogger(__name__)
    logger.info("  Initializing hash calculators (MD5, SHA1, SHA256)...")

    md5_hasher = hashlib.md5(usedforsecurity=False)
    sha1_hasher = hashlib.sha1(usedforsecurity=False)
    sha256_hasher = hashlib.sha256()

    if resume_byte_pos > 0:
        logger.info("  Reading existing partial download for hash calculation...")
        with temp_path.open("rb") as existing_file:
            existing_content = existing_file.read()
            md5_hasher.update(existing_content)
            sha1_hasher.update(existing_content)
            sha256_hasher.update(existing_content)
        logger.info("  ✓ Hashes updated with %s", _format_bytes(resume_byte_pos))

    return md5_hasher, sha1_hasher, sha256_hasher


@dataclass
class _ChunkDownloadState:
    """State for chunk download operation."""

    response: requests.Response
    temp_path: Path
    task: Any  # Celery task instance
    project_file: ProjectFile
    attempt: DownloadAttempt
    total_size: int
    resume_byte_pos: int
    md5_hasher: "hashlib._Hash"  # hashlib hash object
    sha1_hasher: "hashlib._Hash"  # hashlib hash object
    sha256_hasher: "hashlib._Hash"  # hashlib hash object
    chunk_size: int
    start_time: float


@dataclass
class HashResults:
    """Container for file hash calculation results."""

    md5: str
    sha1: str
    sha256: str


def _should_log_progress(
    *,
    total_size: int,
    downloaded: int,
    last_log_progress: int,
    last_log_bytes: int,
) -> tuple[bool, int, int]:
    """Determine if progress should be logged.

    Returns:
        tuple: (should_log, new_last_log_progress, new_last_log_bytes)
    """
    if total_size > 0:
        # Known size: log every 10% change
        progress = int((downloaded / total_size) * 100)
        if progress >= last_log_progress + 10:
            return True, progress, last_log_bytes
    else:
        # Unknown size: log every 10MB downloaded
        mb_downloaded = downloaded / (1024 * 1024)
        mb_last_log = last_log_bytes / (1024 * 1024)
        if mb_downloaded >= mb_last_log + 10:
            return True, last_log_progress, downloaded

    return False, last_log_progress, last_log_bytes


def _log_download_progress(
    *,
    file_path: Path,
    total_size: int,
    downloaded: int,
    chunk_count: int,
    start_time: float,
) -> None:
    """Log download progress information with speed."""
    logger = logging.getLogger(__name__)

    # Calculate download speed
    elapsed_time = time.time() - start_time
    speed_bytes_per_sec = downloaded / elapsed_time if elapsed_time > 0 else 0
    speed_formatted = _format_bytes(int(speed_bytes_per_sec))

    if total_size > 0:
        progress = int((downloaded / total_size) * 100)
        logger.info(
            "  Progress [%s]: %d%% (%s / %s, %d chunks, %s/s)",
            file_path,
            progress,
            _format_bytes(downloaded),
            _format_bytes(total_size),
            chunk_count,
            speed_formatted,
        )
    else:
        logger.info(
            "  Progress [%s]: %s, %d chunks, %s/s",
            file_path,
            _format_bytes(downloaded),
            chunk_count,
            speed_formatted,
        )


def _should_update_database(
    *,
    total_size: int,
    downloaded: int,
    last_db_update_progress: int,
    last_db_update_bytes: int,
) -> tuple[bool, int, int]:
    """Determine if database should be updated.

    Returns:
        tuple: (should_update, new_last_db_update_progress, new_last_db_update_bytes)
    """
    if total_size > 0:
        # Known size: update every 5% progress
        progress = int((downloaded / total_size) * 100)
        if progress >= last_db_update_progress + 5:
            return True, progress, downloaded
    else:
        # Unknown size: update every 5MB
        mb_downloaded = downloaded / (1024 * 1024)
        mb_last_update = last_db_update_bytes / (1024 * 1024)
        if mb_downloaded >= mb_last_update + 5:
            # Round down to nearest 5MB boundary for clean checkpoint values
            checkpoint_mb = int(mb_downloaded / 5) * 5
            checkpoint_bytes = checkpoint_mb * 1024 * 1024
            return True, last_db_update_progress, checkpoint_bytes

    return False, last_db_update_progress, last_db_update_bytes


def _download_chunks(state: _ChunkDownloadState) -> None:
    """Download file in chunks with progress tracking.

    Updates:
    - Writes chunks to temp file
    - Updates database progress every N chunks
    - Logs progress to console

    Does NOT calculate hashes - that happens after extraction.
    """
    logger = logging.getLogger(__name__)

    downloaded = state.resume_byte_pos
    last_db_update_progress = 0
    last_log_progress = 0

    # Align last_log_bytes to 10MB boundaries for consistent logging
    # E.g., if resumed at 42.31 MB, set to 40 MB so next log is at 50 MB
    mb_downloaded = state.resume_byte_pos / (1024 * 1024)
    last_log_mb = int(mb_downloaded / 10) * 10  # Round down to nearest 10MB
    last_log_bytes = last_log_mb * 1024 * 1024

    # Align last_db_update_bytes to 5MB boundaries for consistent database checkpoints
    # E.g., if resumed at 42.31 MB, set to 40 MB so next checkpoint is at 45 MB
    last_db_update_mb = int(mb_downloaded / 5) * 5  # Round down to nearest 5MB
    last_db_update_bytes = last_db_update_mb * 1024 * 1024

    mode = "ab" if state.resume_byte_pos > 0 else "wb"

    formatted_chunk_size = _format_bytes(state.chunk_size)
    logger.info("  Starting chunked download (chunk size: %s)...", formatted_chunk_size)
    chunk_count = 0

    with state.temp_path.open(mode) as temp_file:
        for chunk in state.response.iter_content(chunk_size=state.chunk_size):
            if not chunk:  # filter out keep-alive chunks
                continue

            # Write chunk
            temp_file.write(chunk)
            state.md5_hasher.update(chunk)
            state.sha1_hasher.update(chunk)
            state.sha256_hasher.update(chunk)
            downloaded += len(chunk)
            chunk_count += 1

            # Log first chunk to confirm download is working
            if chunk_count == 1:
                logger.info("  ✓ Received first chunk (%s)", _format_bytes(len(chunk)))

            # Calculate download speed for task state
            elapsed_time = time.time() - state.start_time
            speed_bytes_per_sec = downloaded / elapsed_time if elapsed_time > 0 else 0

            # Update Celery task state with progress
            progress = (
                int((downloaded / state.total_size) * 100)
                if state.total_size > 0
                else 0
            )
            if state.total_size > 0:
                progress_msg = (
                    f"Downloaded {_format_bytes(downloaded)} of "
                    f"{_format_bytes(state.total_size)} "
                    f"({_format_bytes(int(speed_bytes_per_sec))}/s)"
                )
            else:
                progress_msg = (
                    f"Downloaded {_format_bytes(downloaded)} "
                    f"({_format_bytes(int(speed_bytes_per_sec))}/s)"
                )

            state.task.update_state(
                state="PROGRESS",
                meta={
                    "current": downloaded,
                    "total": state.total_size,
                    "progress": progress,
                    "message": progress_msg,
                    "speed": speed_bytes_per_sec,
                },
            )

            # Check if we should log progress
            should_log, last_log_progress, last_log_bytes = _should_log_progress(
                total_size=state.total_size,
                downloaded=downloaded,
                last_log_progress=last_log_progress,
                last_log_bytes=last_log_bytes,
            )
            if should_log:
                _log_download_progress(
                    file_path=state.temp_path,
                    total_size=state.total_size,
                    downloaded=downloaded,
                    chunk_count=chunk_count,
                    start_time=state.start_time,
                )

            # Check if we should update database
            (
                should_update_db,
                last_db_update_progress,
                last_db_update_bytes,
            ) = _should_update_database(
                total_size=state.total_size,
                downloaded=downloaded,
                last_db_update_progress=last_db_update_progress,
                last_db_update_bytes=last_db_update_bytes,
            )
            if should_update_db:
                # Update attempt with current progress
                state.attempt.last_activity = timezone.now()
                state.attempt.bytes_downloaded = last_db_update_bytes
                state.attempt.save(update_fields=["last_activity", "bytes_downloaded"])

                # Record chunk checkpoint for performance analysis
                # Use rounded checkpoint values at exact 5MB boundaries
                ProjectFileChunk.objects.create(
                    download_attempt=state.attempt,
                    bytes_downloaded=last_db_update_bytes,
                    chunk_number=chunk_count,
                )

    # Calculate final download speed
    elapsed_time = time.time() - state.start_time
    speed_bytes_per_sec = downloaded / elapsed_time if elapsed_time > 0 else 0

    logger.info(
        "  ✓ Download complete! Total: %s, %d chunks, Average speed: %s/s",
        _format_bytes(downloaded),
        chunk_count,
        _format_bytes(int(speed_bytes_per_sec)),
    )


def _download_with_progress(
    task,
    project_file: ProjectFile,
    attempt: DownloadAttempt,
    temp_path: Path,
    *,
    chunk_size: int = 1024 * 1024,  # 1MB chunks
) -> tuple[str, str, str]:
    """Download file with progress tracking and resume capability.

    Downloads file in chunks, tracking progress to database.
    Hash calculation is performed separately after extraction pipeline.

    Args:
        task: The Celery task instance (for progress updates)
        project_file: The ProjectFile instance
        attempt: The DownloadAttempt instance for tracking
        temp_path: Path to temporary file for download
        chunk_size: Size of download chunks in bytes

    Returns:
        tuple: (md5_hash, sha1_hash, sha256_hash) of downloaded content
    """
    # Prepare request (gets authenticated URL for GitHub artifacts)
    url, headers, resume_byte_pos = _prepare_download_request(project_file, temp_path)

    # Get HTTP response
    response, resume_byte_pos = _get_download_response(
        url, headers, temp_path, resume_byte_pos
    )

    # Log file size information
    total_size = _log_file_size(response, project_file, resume_byte_pos)

    # Initialize hash calculators
    md5_hasher, sha1_hasher, sha256_hasher = _initialize_hash_calculators(
        temp_path, resume_byte_pos
    )

    # Download chunks with progress tracking
    download_state = _ChunkDownloadState(
        response=response,
        temp_path=temp_path,
        task=task,
        project_file=project_file,
        attempt=attempt,
        total_size=total_size,
        resume_byte_pos=resume_byte_pos,
        md5_hasher=md5_hasher,
        sha1_hasher=sha1_hasher,
        sha256_hasher=sha256_hasher,
        chunk_size=chunk_size,
        start_time=time.time(),
    )
    _download_chunks(download_state)

    return md5_hasher.hexdigest(), sha1_hasher.hexdigest(), sha256_hasher.hexdigest()


def _create_download_attempt_atomic(
    project_file_id: int,
    status: str,
    **extra_fields: Any,
) -> DownloadAttempt:
    """Create a DownloadAttempt with atomic attempt_number assignment.

    Uses select_for_update() to prevent race conditions when multiple tasks
    try to create attempts for the same file concurrently.

    Args:
        project_file_id: ID of the ProjectFile
        status: Status for the new attempt
        **extra_fields: Additional fields to set on the attempt (e.g.,
            download_started_at, worker_pid, worker_hostname, task_started_at)

    Returns:
        Newly created DownloadAttempt with correct attempt_number
    """
    with transaction.atomic():
        # Lock the project file row to serialize attempt creation
        project_file = ProjectFile.objects.select_for_update().get(id=project_file_id)
        attempt_number = project_file.download_attempts.count() + 1

        return DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=attempt_number,
            status=status,
            **extra_fields,
        )


def _get_project_file_for_download(
    project_id: str,
) -> tuple[Project, ProjectFile | None]:
    """Get project and its active file for download.

    Args:
        project_id: UUID of the project

    Returns:
        tuple: (Project, ProjectFile or None)

    Raises:
        Project.DoesNotExist: If project not found
    """
    project = Project.objects.get(id=project_id)
    project_file = project.files.filter(is_active=True).first()
    return project, project_file


def _get_or_create_download_attempt(project_file: ProjectFile) -> DownloadAttempt:
    """Get existing PENDING attempt or create new DOWNLOADING attempt.

    When a retry is scheduled, a PENDING attempt is created immediately.
    When the retry starts, we reuse that attempt instead of creating a new one.
    This ensures the UI shows "Pending" during retry delay instead of "Failed".

    Args:
        project_file: The file to create/update attempt for

    Returns:
        DownloadAttempt in DOWNLOADING status
    """
    logger = logging.getLogger(__name__)

    # Check for existing PENDING attempt (created when retry was scheduled)
    pending_attempt = project_file.download_attempts.filter(
        status=DownloadAttempt.Status.PENDING
    ).first()

    if pending_attempt:
        # Reuse existing PENDING attempt
        pending_attempt.status = DownloadAttempt.Status.DOWNLOADING
        pending_attempt.download_started_at = timezone.now()
        pending_attempt.worker_pid = os.getpid()
        pending_attempt.worker_hostname = socket.gethostname()
        pending_attempt.task_started_at = timezone.now()
        pending_attempt.save()
        logger.info(
            "Updated pending attempt #%d to DOWNLOADING (PID=%s, host=%s)",
            pending_attempt.attempt_number,
            pending_attempt.worker_pid,
            pending_attempt.worker_hostname,
        )
        return pending_attempt

    # Create new attempt atomically (first download or no pending attempt)
    attempt = _create_download_attempt_atomic(
        project_file.id,
        DownloadAttempt.Status.DOWNLOADING,
        download_started_at=timezone.now(),
        worker_pid=os.getpid(),
        worker_hostname=socket.gethostname(),
        task_started_at=timezone.now(),
    )
    logger.info(
        "Created attempt #%d (PID=%s, host=%s)",
        attempt.attempt_number,
        attempt.worker_pid,
        attempt.worker_hostname,
    )
    return attempt


def _initialize_download(project_file: ProjectFile) -> None:
    """Initialize file download metadata.

    Args:
        project_file: The file to initialize

    Note:
        download_status is now derived from DownloadAttempt.
        Worker tracking moved to DownloadAttempt creation.
    """
    # Update timestamps and activity
    project_file.download_started_at = timezone.now()
    project_file.last_activity = timezone.now()
    project_file.save(
        update_fields=[
            "download_started_at",
            "last_activity",
        ],
    )

    if not project_file.original_filename:
        filename = _extract_filename_from_url(project_file.source_url)
        project_file.original_filename = filename
        project_file.save(update_fields=["original_filename"])


def _handle_download_retry(
    task_self,
    project_id: str,
    exc: Exception,
) -> None:
    """Handle download retry with exponential backoff.

    Args:
        task_self: The Celery task instance
        project_id: UUID of the project
        exc: The exception that caused the retry

    Raises:
        Retry: To retry the task
    """
    retry_delay = settings.DOWNLOAD_TASK_RETRY_BASE_DELAY_SECONDS * (
        settings.DOWNLOAD_TASK_RETRY_BACKOFF_MULTIPLIER**task_self.request.retries
    )

    try:
        _project, project_file = _get_project_file_for_download(project_id)
        if project_file:
            error_msg = (
                f"Retry {task_self.request.retries + 1}/"
                f"{task_self.max_retries}: {exc!s}"
            )
            project_file.download_error = error_msg
            project_file.last_activity = timezone.now()
            project_file.save(
                update_fields=["download_error", "last_activity"],
            )
    except Project.DoesNotExist:
        pass

    raise task_self.retry(exc=exc, countdown=retry_delay) from exc


def _handle_download_failure(
    project_id: str,
    exc: Exception,
    temp_path: Path | None,
    attempt: DownloadAttempt | None = None,
) -> dict[str, str | int]:
    """Handle final download failure after max retries.

    Args:
        project_id: UUID of the project
        exc: The exception that caused the failure
        temp_path: Path to temp file to clean up
        attempt: The download attempt that failed (if available)

    Returns:
        dict: Failure status information
    """
    try:
        _project, project_file = _get_project_file_for_download(project_id)
        if project_file:
            # Get or create attempt if not provided
            if not attempt:
                # Try to get the most recent attempt
                attempt = project_file.download_attempts.first()
                if not attempt:
                    # Create a new attempt atomically if none exists
                    attempt = _create_download_attempt_atomic(
                        project_file.id,
                        DownloadAttempt.Status.FAILED,
                    )

            # Create structured error log
            FileProcessingError.objects.create(
                download_attempt=attempt,
                error_type=FileProcessingError.ErrorType.DOWNLOAD,
                error_message=f"Download failed: {exc}",
                error_detail={
                    "original_url": project_file.original_url,
                    "source_url": project_file.source_url,
                    "error_type": exc.__class__.__name__,
                    "traceback": traceback.format_exc(),
                },
            )

            # Mark attempt as failed with actual error message
            attempt.status = DownloadAttempt.Status.FAILED
            attempt.download_error = str(exc)  # Store actual error message
            attempt.completed_at = timezone.now()
            if attempt.download_started_at:
                attempt.download_duration_seconds = (
                    attempt.completed_at - attempt.download_started_at
                ).total_seconds()
            attempt.save()

            error_msg = str(exc)  # Use actual error message, not "Max retries reached"
            project_file.mark_download_failed(error_msg)

            # Create failure notification
            NotificationService.create_download_failed_notification(
                user=project_file.project.user,
                project_file=project_file,
                error_message=str(exc),
            )
    except Project.DoesNotExist:
        pass

    if temp_path and temp_path.exists():
        with contextlib.suppress(OSError):
            temp_path.unlink()

    return {
        "status": "failed",
        "message": str(exc),
    }


def _apply_post_download_processing(
    project_file: ProjectFile,
    content: bytes,
) -> bytes:
    """Apply URL handler post-download processing if applicable.

    Args:
        project_file: The project file with handler_metadata
        content: The raw downloaded content

    Returns:
        bytes: Processed content (or original if no handler)
    """
    # Check if handler metadata exists
    if not project_file.handler_metadata:
        return content

    handler_name = project_file.handler_metadata.get("handler")
    if not handler_name:
        return content

    # Get the appropriate handler from registry
    # We use the handler name to recreate the handler instance
    handler = None
    if handler_name == "GoogleSourceHandler":
        handler = GoogleSourceHandler()

    if handler:
        return handler.post_download(content, project_file.handler_metadata)

    return content


def _apply_content_pipeline(
    project_file: ProjectFile,
    content: bytes,
    temp_path: Path,
) -> tuple[bytes, str, str, str]:
    """Apply content extraction pipeline to process compressed/archived files.

    Args:
        project_file: The project file being processed
        content: The content to process
        temp_path: Temporary file path for intermediate processing

    Returns:
        tuple: (processed_content, md5_hash, sha1_hash, sha256_hash)

    Raises:
        ValueError: If pipeline processing fails or format validation fails
    """
    logger = logging.getLogger(__name__)

    # Write content to temp file for pipeline
    temp_path.write_bytes(content)

    # Get temp directory for this file
    pipeline_temp_dir = get_temp_dir_for_file(project_file.id)

    try:
        # Run pipeline
        pipeline = ContentPipeline(_processor_registry)
        result = pipeline.process_file(
            input_path=temp_path,
            filename=project_file.original_filename,
            temp_dir=pipeline_temp_dir,
            max_size=settings.MAX_EXTRACTED_SIZE,
        )

        # Validate format
        format_name = validate_output_format(result.output_path)
        logger.info("  ✓ Format validated: %s", format_name)

        # Read processed content
        processed_content = result.output_path.read_bytes()

        # Recalculate hashes after pipeline processing
        logger.info("  Recalculating hashes after pipeline processing...")
        final_md5, final_sha1, final_sha256 = _calculate_file_hashes(processed_content)
        logger.info("  ✓ MD5: %s", final_md5)
        logger.info("  ✓ SHA1: %s", final_sha1)
        logger.info("  ✓ SHA256: %s", final_sha256)

        # Build final filename
        # For GitHub artifacts, include metadata prefix for better identification
        final_filename = result.filename
        if (
            project_file.handler_metadata
            and project_file.handler_metadata.get("handler") == "GitHubArtifactHandler"
        ):
            final_filename = _build_github_artifact_filename(
                project_file.handler_metadata,
                result.filename,
            )
            logger.info(
                "  ✓ Built GitHub artifact filename: %s",
                final_filename,
            )

        # Always set processed_filename (even if unchanged from original)
        # This indicates processing completed successfully
        project_file.processed_filename = final_filename

        if final_filename != project_file.original_filename:
            logger.info(
                "  ✓ Pipeline transformed: %s → %s",
                project_file.original_filename,
                final_filename,
            )
        else:
            logger.info(
                "  ✓ No transformation needed: %s",
                final_filename,
            )

        logger.info("  ✓ Pipeline processing complete")
        logger.info("  ✓ Output size: %s", _format_bytes(result.size_bytes))

        return processed_content, final_md5, final_sha1, final_sha256

    finally:
        # Always cleanup temp directory
        cleanup_temp_dir(pipeline_temp_dir)


def _process_and_save_content(
    project_file: ProjectFile,
    attempt: DownloadAttempt,
    downloaded_content: bytes,
    temp_path: Path,
) -> tuple[bytes, str, str, str]:
    """Process downloaded content and save to Django storage.

    Args:
        project_file: The ProjectFile being processed
        attempt: The DownloadAttempt for error tracking
        downloaded_content: The raw downloaded content
        temp_path: Path to temporary file

    Returns:
        tuple: (processed_content, final_md5_hash, final_sha1_hash, final_sha256_hash)
              Hashes are for the FINAL extracted GDS/OASIS file
    """
    logger = logging.getLogger(__name__)

    # Apply URL handler post-download processing (e.g., base64 decode)
    logger.info("Step 6: Checking for post-download processing...")
    if project_file.handler_metadata:
        logger.info("  Handler metadata found: %s", project_file.handler_metadata)
    processed_content = _apply_post_download_processing(
        project_file,
        downloaded_content,
    )

    if processed_content != downloaded_content:
        logger.info("  Content was transformed by handler")
        logger.info("  Original size: %s", _format_bytes(len(downloaded_content)))
        logger.info("  Processed size: %s", _format_bytes(len(processed_content)))
        temp_path.write_bytes(processed_content)
    else:
        logger.info("  ✓ No transformation needed - using original content")

    # Apply content extraction pipeline
    # This extracts GDS/OASIS from archives and calculates hashes on final file
    logger.info("Step 6.5: Running content extraction pipeline...")
    try:
        result = _apply_content_pipeline(project_file, processed_content, temp_path)
        processed_content, final_md5, final_sha1, final_sha256 = result
    except ValueError as e:
        logger.exception("Pipeline processing failed")

        # Create structured error log
        FileProcessingError.objects.create(
            download_attempt=attempt,
            error_type=FileProcessingError.ErrorType.PIPELINE,
            error_message=str(e),
            error_detail={
                "stage": "content_extraction",
                "traceback": traceback.format_exc(),
                "original_filename": project_file.original_filename,
                "file_size": (
                    processed_content.stat().st_size
                    if isinstance(processed_content, Path)
                    and processed_content.exists()
                    else None
                ),
            },
        )

        # Mark attempt as failed
        attempt.status = DownloadAttempt.Status.FAILED
        attempt.completed_at = timezone.now()
        if attempt.download_started_at:
            attempt.download_duration_seconds = (
                attempt.completed_at - attempt.download_started_at
            ).total_seconds()
        attempt.save()

        # Note: download_status is now derived from attempt status
        project_file.download_error = f"Pipeline error: {e}"
        project_file.save(update_fields=["download_error"])
        raise

    # Save to Django file field using processed filename
    logger.info("Step 7: Saving file to Django storage...")
    # Use processed_filename (set by pipeline) for the final file
    # This is the extracted/decompressed filename, not the original download name
    final_filename = (
        project_file.processed_filename
        if project_file.processed_filename
        else project_file.original_filename
    )
    django_file = ContentFile(processed_content)
    django_file.name = final_filename
    project_file.file.save(
        final_filename,
        django_file,
        save=False,
    )
    logger.info("  ✓ File saved to Django storage")

    # Set file size and hashes (for FINAL extracted file)
    project_file.file_size = len(processed_content)
    project_file.hash_md5 = final_md5
    project_file.hash_sha1 = final_sha1
    project_file.hash_sha256 = final_sha256
    project_file.save(
        update_fields=[
            "file",
            "file_size",
            "hash_md5",
            "hash_sha1",
            "hash_sha256",
            "processed_filename",
        ]
    )
    logger.info("  ✓ File size: %s", _format_bytes(project_file.file_size))
    logger.info("  ✓ MD5 hash: %s", final_md5)
    logger.info("  ✓ SHA1 hash: %s", final_sha1)
    logger.info("  ✓ SHA256 hash: %s", final_sha256)

    return processed_content, final_md5, final_sha1, final_sha256


def _verify_and_notify(
    project_file: ProjectFile,
    hashes: HashResults,
) -> tuple[bool, list[str]]:
    """Verify file hashes and create notifications.

    Returns:
        tuple: (hash_verified, verification_errors)
    """
    logger = logging.getLogger(__name__)

    # Verify hashes
    logger.info("Step 8: Verifying file integrity...")
    if project_file.expected_hash_md5:
        logger.info("  Expected MD5: %s", project_file.expected_hash_md5)
        logger.info("  Actual MD5:   %s", hashes.md5)
    if project_file.expected_hash_sha1:
        logger.info("  Expected SHA1: %s", project_file.expected_hash_sha1)
        logger.info("  Actual SHA1:   %s", hashes.sha1)
    if project_file.expected_hash_sha256:
        logger.info("  Expected SHA256: %s", project_file.expected_hash_sha256)
        logger.info("  Actual SHA256:   %s", hashes.sha256)

    hash_verified, verification_errors = _verify_file_hashes(
        project_file,
        hashes,
    )

    if hash_verified:
        logger.info("  ✓ Hash verification PASSED!")
    else:
        logger.warning("  ⚠ Hash verification FAILED!")
        for error in verification_errors:
            logger.warning("    - %s", error)

    project_file.hash_verified = hash_verified
    project_file.save(update_fields=["hash_verified"])
    project_file.mark_download_complete()
    logger.info("  ✓ Download marked as COMPLETE")

    # Extract top cell from GDS/OASIS file (required for manufacturability check)
    logger.info("Step 8.5: Extracting top cell from layout file...")
    if not project_file.file:
        msg = "No file available for top cell extraction"
        raise ValueError(msg)

    file_path = Path(project_file.file.path)
    top_cell = extract_top_cell(file_path)
    if not top_cell:
        msg = f"Could not extract top cell from {project_file.processed_filename}"
        raise ValueError(msg)

    project_file.top_cell = top_cell
    project_file.save(update_fields=["top_cell"])
    logger.info("  ✓ Top cell identified: %s", top_cell)

    # Create notifications
    logger.info("Step 9: Creating notifications...")
    NotificationService.create_download_complete_notification(
        user=project_file.project.user,
        project_file=project_file,
    )
    logger.info("  ✓ Download completion notification created")

    if hash_verified:
        NotificationService.create_checksum_verified_notification(
            user=project_file.project.user,
            project_file=project_file,
        )
        logger.info("  ✓ Checksum verified notification created")
        # Note: ManufacturabilityCheck creation is handled by the periodic
        # checks_create() task, not here. This avoids race conditions and
        # ensures idempotent check creation.
    elif verification_errors:
        NotificationService.create_checksum_mismatch_notification(
            user=project_file.project.user,
            project_file=project_file,
            errors=verification_errors,
        )
        logger.warning("  ⚠ Checksum mismatch notification created")

    return hash_verified, verification_errors


def _log_download_start(project_id: str, project_file: ProjectFile) -> None:
    """Log download task start information."""
    logger = logging.getLogger(__name__)

    # Calculate temp path for display
    temp_dir = Path(tempfile.gettempdir()) / "wafer_space_downloads"
    temp_filename = f"{project_file.id}_{project_file.original_filename}"
    temp_path = temp_dir / temp_filename

    logger.info("=" * 80)
    logger.info("DOWNLOAD TASK STARTED - Project ID: %s", project_id)
    logger.info("  User: %s", project_file.project.user.username)
    logger.info("  File: %s", temp_path)
    logger.info("=" * 80)

    logger.info("Step 1: Looking up project and active file...")
    logger.info("  ✓ Found active file: %s", project_file.id)
    logger.info("  ✓ Original filename: %s", project_file.original_filename)
    logger.info("  ✓ Source URL: %s", project_file.source_url)


def _setup_download_temp_path(project_file: ProjectFile) -> Path:
    """Set up temporary directory and return temp file path.

    Returns:
        Path: Path to temporary file for download
    """
    logger = logging.getLogger(__name__)
    logger.info("Step 3: Setting up temporary download directory...")
    temp_dir = _setup_temp_directory()
    temp_filename = f"{project_file.id}_{project_file.original_filename}"
    temp_path = temp_dir / temp_filename
    logger.info("  ✓ Temp file path: %s", temp_path)
    return temp_path


def _log_download_completion(
    project_id: str,
    project_file: ProjectFile,
    *,
    hash_verified: bool,
) -> None:
    """Log download task completion information."""
    logger = logging.getLogger(__name__)
    logger.info("Step 10: Cleaning up temporary files...")

    logger.info("=" * 80)
    logger.info("DOWNLOAD TASK COMPLETED SUCCESSFULLY")
    logger.info("  Project ID: %s", project_id)
    logger.info("  File ID: %s", project_file.id)
    logger.info("  Filename: %s", project_file.original_filename)
    logger.info(
        "  Size: %s",
        _format_bytes(project_file.file_size) if project_file.file_size else "Unknown",
    )
    logger.info("  Hash Verified: %s", hash_verified)
    logger.info("=" * 80)


@shared_task(
    bind=True,
    queue="downloads",
    max_retries=settings.DOWNLOAD_TASK_MAX_RETRIES,
    default_retry_delay=settings.DOWNLOAD_TASK_RETRY_BASE_DELAY_SECONDS,
)
def download_project_file(self, project_id):  # noqa: PLR0915, C901
    """Background task to download a project file from a URL.

    Supports:
    - Chunked downloading for large files (up to 100GB)
    - Resume capability with HTTP Range requests
    - Progress tracking via Celery task state
    - Hash verification (MD5, SHA1, SHA256)
    - Exponential backoff retry on failures

    Args:
        project_id: The UUID of the Project (not ProjectFile ID)

    Returns:
        dict: Result data with status and details
    """
    logger = logging.getLogger(__name__)
    temp_path = None
    attempt = None  # Track attempt for error handling

    try:
        # Get and validate project file
        _project, project_file = _get_project_file_for_download(project_id)

        if not project_file:
            logger.error("ERROR: No active file found for project %s", project_id)
            return {
                "status": "error",
                "message": f"No active file found for project {project_id}",
            }

        if not project_file.source_url:
            logger.error("ERROR: No source URL provided for file download")
            return {
                "status": "error",
                "message": "No source URL provided for file download",
            }

        # Log start
        _log_download_start(project_id, project_file)

        # Initialize download
        logger.info("Step 2: Initializing download (marking as DOWNLOADING)...")
        _initialize_download(project_file)
        logger.info(
            "  ✓ Download started: file=%s, task_id=%s",
            project_file.id,
            self.request.id,
        )

        # Create or reuse download attempt
        # If a PENDING attempt exists (created when retry was scheduled), reuse it
        # Otherwise create a new one
        logger.info("Step 2.5: Creating/updating download attempt record...")
        attempt = _get_or_create_download_attempt(project_file)

        # Set up temporary directory
        temp_path = _setup_download_temp_path(project_file)

        # Download with progress tracking
        logger.info("Step 4: Starting download from URL...")
        max_url_len = 100
        url_display = (
            project_file.source_url[:max_url_len] + "..."
            if len(project_file.source_url) > max_url_len
            else project_file.source_url
        )
        logger.info("  URL: %s", url_display)
        expected_size = (
            _format_bytes(project_file.file_size)
            if project_file.file_size
            else "unknown"
        )
        logger.info("  Expected file size: %s", expected_size)
        md5_hash, sha1_hash, sha256_hash = _download_with_progress(
            self,
            project_file,
            attempt,
            temp_path,
        )
        logger.info("  ✓ Download completed successfully!")
        logger.info("  ✓ MD5: %s", md5_hash)
        logger.info("  ✓ SHA1: %s", sha1_hash)
        logger.info("  ✓ SHA256: %s", sha256_hash)

        # Read downloaded content
        logger.info("Step 5: Reading downloaded content...")
        with temp_path.open("rb") as temp_file:
            downloaded_content = temp_file.read()
        formatted_size = _format_bytes(len(downloaded_content))
        logger.info("  ✓ Read %s from temp file", formatted_size)

        # Detect file type from actual content
        logger.info("Step 6: Detecting file type from content...")

        # Use first 1MB for MIME detection (or entire file if smaller)
        detection_data = downloaded_content[: 1024 * 1024]
        try:
            mime_type, detected_extension = detect_file_type_from_data(detection_data)
            logger.info("  ✓ Detected MIME type: %s", mime_type)
            logger.info("  ✓ Detected extension: %s", detected_extension)

            # Log detected file type
            # Note: original_filename stays unchanged - it's what was downloaded
            logger.info(
                "  ✓ Detected file type: %s (extension: %s)",
                project_file.original_filename,
                detected_extension,
            )
        except ValueError as e:
            logger.exception("  ✗ File type detection failed")

            # Create structured error log
            FileProcessingError.objects.create(
                download_attempt=attempt,
                error_type=FileProcessingError.ErrorType.VALIDATION,
                error_message=str(e),
                error_detail={
                    "stage": "file_type_detection",
                    "traceback": traceback.format_exc(),
                    "original_filename": project_file.original_filename,
                },
            )

            # Mark attempt as failed
            attempt.status = DownloadAttempt.Status.FAILED
            attempt.completed_at = timezone.now()
            if attempt.download_started_at:
                attempt.download_duration_seconds = (
                    attempt.completed_at - attempt.download_started_at
                ).total_seconds()
            attempt.save()

            # Mark download as failed
            # Note: download_status is now derived from attempt status
            project_file.download_error = f"Validation error: {e}"
            project_file.save(update_fields=["download_error"])
            raise

        # Process and save content (extracts GDS/OASIS and calculates hashes)
        logger.info("Step 7: Processing and saving content...")
        result = _process_and_save_content(
            project_file, attempt, downloaded_content, temp_path
        )
        _processed_content, final_md5, final_sha1, final_sha256 = result

        # Create HashResults for verification
        # All hashes are for the FINAL extracted file
        final_hashes = HashResults(
            md5=final_md5,
            sha1=final_sha1,
            sha256=final_sha256,
        )

        # Verify hashes and create notifications
        logger.info("Step 8: Verifying hashes and creating notifications...")
        hash_verified, verification_errors = _verify_and_notify(
            project_file,
            final_hashes,
        )

        # Mark attempt as completed
        logger.info("Step 8.5: Marking download attempt as completed...")
        attempt.status = DownloadAttempt.Status.COMPLETED
        attempt.completed_at = timezone.now()
        attempt.download_completed_at = timezone.now()
        if attempt.download_started_at:
            attempt.download_duration_seconds = (
                attempt.completed_at - attempt.download_started_at
            ).total_seconds()
        # Update bytes_downloaded from final file size
        if project_file.file_size:
            attempt.bytes_downloaded = project_file.file_size
        attempt.save()
        logger.info("  ✓ Attempt #%d marked as COMPLETED", attempt.attempt_number)

        # Clean up temp file
        logger.info("Step 9: Cleaning up temporary files...")
        with contextlib.suppress(OSError):
            temp_path.unlink()
        logger.info("  ✓ Temp file removed")

        # Log completion
        _log_download_completion(project_id, project_file, hash_verified=hash_verified)

        return {
            "status": "completed",
            "project_id": str(project_id),
            "file_id": str(project_file.id),
            "original_filename": project_file.original_filename,
            "file_size": project_file.file_size,
            "hash_verified": hash_verified,
            "verification_errors": verification_errors,
            "md5": project_file.hash_md5,
            "sha1": project_file.hash_sha1,
            "sha256": project_file.hash_sha256,
        }

    except Project.DoesNotExist:
        logger.exception("DOWNLOAD TASK FAILED - Project not found: %s", project_id)
        return {
            "status": "error",
            "message": f"Project with id {project_id} not found",
        }

    except (OSError, ValueError, requests.RequestException) as exc:
        logger.exception("DOWNLOAD TASK ERROR")
        if self.request.retries < self.max_retries:
            retry_num = self.request.retries + 1
            retry_delay = settings.DOWNLOAD_TASK_RETRY_BASE_DELAY_SECONDS * (
                settings.DOWNLOAD_TASK_RETRY_BACKOFF_MULTIPLIER**self.request.retries
            )
            logger.info(
                "Retry %d/%d - Will retry in %d seconds",
                retry_num,
                self.max_retries,
                retry_delay,
            )
            # Mark attempt as failed with error message if it exists
            if attempt:
                attempt.status = DownloadAttempt.Status.FAILED
                attempt.download_error = str(exc)  # Store actual error message
                attempt.completed_at = timezone.now()
                if attempt.download_started_at:
                    attempt.download_duration_seconds = (
                        attempt.completed_at - attempt.download_started_at
                    ).total_seconds()
                attempt.save()

                # Create structured error log for this failed attempt
                error_msg = f"Download failed (retry {retry_num} scheduled): {exc}"
                FileProcessingError.objects.create(
                    download_attempt=attempt,
                    error_type=FileProcessingError.ErrorType.DOWNLOAD,
                    error_message=error_msg,
                    error_detail={
                        "original_url": attempt.project_file.original_url,
                        "source_url": attempt.project_file.source_url,
                        "error_type": exc.__class__.__name__,
                        "traceback": traceback.format_exc(),
                        "retry_number": retry_num,
                        "retry_delay": retry_delay,
                    },
                )

                # Create a PENDING attempt atomically for the upcoming retry
                # This ensures UI shows "Pending" instead of "Failed" during retry delay
                _create_download_attempt_atomic(
                    attempt.project_file.id,
                    DownloadAttempt.Status.PENDING,
                )
            _handle_download_retry(self, project_id, exc)
        else:
            logger.exception(
                "DOWNLOAD TASK FAILED - Max retries reached for project %s", project_id
            )
            return _handle_download_failure(project_id, exc, temp_path, attempt)


# AUTO-RETRY SYSTEM REMOVED
# Retries are now handled by Celery's built-in retry mechanism.
# See download_project_file task decorator for max_retries setting.
# This eliminates duplicate retry logic (18 attempts → 3 attempts).


@shared_task(queue="maintenance")
def ensure_download_tasks_queued():
    """Ensure all active files have download tasks queued (fallback recovery).

    This is NOT a retry system - it's a fallback to recover from queue loss.
    Retries are handled by Celery's built-in retry mechanism.

    Runs periodically (every 60s) to detect and recover from:
    - Tasks lost from Celery queue (worker crash, broker restart)
    - Tasks stuck in invalid states (orphaned downloads)

    Returns:
        dict: Status with counts of created_tasks, orphaned, verified
    """
    logger = logging.getLogger(__name__)

    created_tasks = 0
    orphaned_count = 0
    verified_count = 0

    # Find PENDING files: no task_id AND is_active
    # (download_status property returns PENDING when no task_id and no attempts)
    pending_files = ProjectFile.objects.filter(
        is_active=True,
    ).filter(
        models.Q(download_task_id="") | models.Q(download_task_id__isnull=True),
    )

    for project_file in pending_files:
        # Create task for active file with no task queued
        task = download_project_file.delay(project_file.project.id)
        project_file.download_task_id = task.id
        project_file.save(update_fields=["download_task_id"])
        created_tasks += 1
        logger.info("Created task for pending file %s", project_file.id)

    # Find QUEUED files: has task_id but latest_attempt is None or PENDING
    # Need to check if task still exists in Celery queue
    queued_files = (
        ProjectFile.objects.filter(
            is_active=True,
        )
        .exclude(
            models.Q(download_task_id="") | models.Q(download_task_id__isnull=True),
        )
        .exclude(
            download_attempts__status__in=[
                DownloadAttempt.Status.DOWNLOADING,
                DownloadAttempt.Status.COMPLETED,
                DownloadAttempt.Status.FAILED,
            ],
        )
    )

    for project_file in queued_files:
        if is_download_task_queued(project_file):
            verified_count += 1
        else:
            error_msg = "Task not found in Celery queue (worker may be down)"
            logger.warning("Orphaned queued file %s", project_file.id)

            # Create FAILED attempt (no attempt exists for QUEUED files)
            DownloadAttempt.objects.create(
                project_file=project_file,
                attempt_number=1,
                status=DownloadAttempt.Status.FAILED,
                download_error=error_msg,
                completed_at=timezone.now(),
            )
            project_file.mark_download_failed(error_msg)
            orphaned_count += 1

    # Find DOWNLOADING files: latest_attempt.status == DOWNLOADING
    # Need to verify task is actually running with valid PID
    downloading_files = ProjectFile.objects.filter(
        is_active=True,
        download_attempts__status=DownloadAttempt.Status.DOWNLOADING,
    ).exclude(
        models.Q(download_task_id="") | models.Q(download_task_id__isnull=True),
    )

    # Track tasks requeued after orphan detection
    requeued_count = 0

    for project_file in downloading_files:
        # Only check if this is the latest attempt
        latest = project_file.latest_attempt
        if latest and latest.status == DownloadAttempt.Status.DOWNLOADING:
            if is_download_task_actively_running(project_file):
                verified_count += 1
            else:
                logger.warning("Orphaned downloading file %s", project_file.id)

                # Preserve existing error message if present
                if latest.download_error:
                    error_msg = latest.download_error
                else:
                    error_msg = "Task not running (worker crashed or task failed)"

                # Update attempt to FAILED
                latest.status = DownloadAttempt.Status.FAILED
                latest.download_error = error_msg
                latest.completed_at = timezone.now()
                latest.save(update_fields=["status", "download_error", "completed_at"])

                project_file.mark_download_failed(error_msg)
                orphaned_count += 1

                # Queue a new download task if under retry limit
                # max_retries=2 means 3 total attempts (initial + 2 retries)
                max_attempts = settings.DOWNLOAD_TASK_MAX_RETRIES + 1
                attempt_count = project_file.download_attempts.count()

                if attempt_count < max_attempts:
                    logger.info(
                        "  Requeuing download for file %s (attempt %d/%d)",
                        project_file.id,
                        attempt_count + 1,
                        max_attempts,
                    )
                    # Queue new download task
                    task = download_project_file.delay(project_file.project.id)
                    project_file.download_task_id = task.id
                    project_file.save(update_fields=["download_task_id"])
                    requeued_count += 1
                else:
                    logger.warning(
                        "  File %s exceeded max attempts (%d/%d), not requeuing",
                        project_file.id,
                        attempt_count,
                        max_attempts,
                    )

    logger.info(
        "Fallback check: %d created, %d orphaned, %d requeued, %d verified",
        created_tasks,
        orphaned_count,
        requeued_count,
        verified_count,
    )

    return {
        "status": "completed",
        "created_tasks": created_tasks,
        "orphaned": orphaned_count,
        "requeued": requeued_count,
        "verified": verified_count,
    }


def _stop_and_remove_container(container, logger) -> None:
    """Stop and remove a Docker container safely."""
    try:
        if container.status == "running":
            container.stop(timeout=10)
        container.remove(force=True)
    except docker.errors.DockerException:
        logger.exception("Failed to remove container %s", container.id)


@shared_task(queue="docker-ephemeral")
def checks_cleanup_orphaned_docker() -> dict:
    """Remove Docker containers not linked to active checks (fallback cleanup).

    Starts from Docker (source of truth) and validates against database.
    Removes containers where the associated ManufacturabilityCheck is:
    - Missing (deleted)
    - FINISHED
    - ERROR
    - CANCELLED

    CANCELLING containers are handled by checks_cancelling task, not here.

    Returns:
        dict with 'containers_scanned' and 'removed' counts
    """
    logger = get_task_logger(__name__)
    logger.info("=" * 60)
    logger.info("CLEANING UP ORPHANED DOCKER CONTAINERS")
    logger.info("=" * 60)

    try:
        client = docker.from_env(timeout=settings.DOCKER_CLIENT_TIMEOUT)
    except docker.errors.DockerException as exc:
        logger.exception("Failed to connect to Docker")
        return {
            "status": "error",
            "error": str(exc),
        }

    # Get all containers with our label
    containers = client.containers.list(
        all=True,
        filters={"label": "wafer.space.service=manufacturability-check"},
    )

    logger.info("  Found %d containers with service label", len(containers))

    removed = 0
    for container in containers:
        check_id = container.labels.get("wafer.space.check_id")

        # No check_id label = definitely orphaned
        if not check_id:
            logger.info(
                "  Container %s: no check_id label, removing",
                container.short_id,
            )
            _stop_and_remove_container(container, logger)
            removed += 1
            continue

        # Look up the check
        try:
            check = ManufacturabilityCheck.objects.get(id=check_id)
        except ManufacturabilityCheck.DoesNotExist:
            logger.info(
                "  Container %s: check %s not found, removing",
                container.short_id,
                check_id,
            )
            _stop_and_remove_container(container, logger)
            removed += 1
            continue

        # Check exists - is it in an active state?
        # CANCELLING containers are handled by checks_cancelling, not here
        active_states = [
            ManufacturabilityCheck.Status.DISPATCHED,
            ManufacturabilityCheck.Status.RUNNING,
            ManufacturabilityCheck.Status.CANCELLING,
        ]
        if check.status not in active_states:
            logger.info(
                "  Container %s: check %s in %s state, removing",
                container.short_id,
                check_id,
                check.status,
            )
            _stop_and_remove_container(container, logger)
            removed += 1
        else:
            logger.debug(
                "  Container %s: check %s in %s state, keeping",
                container.short_id,
                check_id,
                check.status,
            )

    logger.info("=" * 60)
    logger.info("CLEANUP COMPLETE")
    logger.info("  Scanned: %d", len(containers))
    logger.info("  Removed: %d", removed)
    logger.info("=" * 60)

    return {"containers_scanned": len(containers), "removed": removed}


@shared_task(queue="default")
def checks_pending() -> dict[str, int]:
    """Transition PENDING checks to DISPATCHING with server assignment.

    Respects per-server concurrent limits. Assigns to servers in priority order.

    Returns:
        Dict with count of dispatched checks.
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_pending] Starting pending check assignment")

    dispatched = 0

    # Sort servers by priority (lowest first)
    servers = sorted(settings.DOCKER_SERVERS, key=lambda s: s["priority"])

    for server in servers:
        server_id = str(server["id"])
        max_concurrent = int(server["max_concurrent"])

        # Count active checks on this server
        active_count = ManufacturabilityCheck.objects.filter(
            docker_server_id=server_id,
            status__in=ManufacturabilityCheck.Status.active(),
        ).count()

        available_slots = max_concurrent - active_count

        if available_slots > 0:
            logger.info(
                "[checks_pending] Server %s: %d/%d active, %d slots available",
                server_id,
                active_count,
                max_concurrent,
                available_slots,
            )

            pending_checks = ManufacturabilityCheck.objects.filter(
                status=ManufacturabilityCheck.Status.PENDING,
            ).order_by("created_at")[:available_slots]

            for check in pending_checks:
                check.mark_dispatching(server_id=server_id)
                logger.info(
                    "[checks_pending] Assigned check %s to server %s",
                    check.id,
                    server_id,
                )
                dispatched += 1

    logger.info("[checks_pending] Complete: dispatched=%d", dispatched)
    return {"dispatched": dispatched}


@shared_task(queue="default")
def checks_dispatching() -> dict[str, int]:
    """Queue do_dispatching work tasks for DISPATCHING checks.

    Only queues if check doesn't already have a pending task.

    Returns:
        Dict with count of queued tasks.
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_dispatching] Starting dispatching cycle")

    queued = 0

    dispatching_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.DISPATCHING,
    ).exclude(pending_task__isnull=False)

    logger.info(
        "[checks_dispatching] Found %d DISPATCHING checks without pending task",
        dispatching_checks.count(),
    )

    for check in dispatching_checks:
        result = do_dispatching.delay(check.id)
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id=result.id,
            task_name="do_dispatching",
        )
        logger.info(
            "[checks_dispatching] Queued do_dispatching for check %s (task: %s)",
            check.id,
            result.id,
        )
        queued += 1

    logger.info("[checks_dispatching] Complete: queued=%d", queued)
    return {"queued": queued}


@shared_task(queue="default")
def checks_starting() -> dict[str, int]:
    """Queue do_starting work tasks for STARTING checks.

    Only queues if check doesn't already have a pending task.

    Returns:
        Dict with count of queued tasks.
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_starting] Starting starting cycle")

    queued = 0

    starting_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.STARTING,
    ).exclude(pending_task__isnull=False)

    logger.info(
        "[checks_starting] Found %d STARTING checks without pending task",
        starting_checks.count(),
    )

    for check in starting_checks:
        result = do_starting.delay(check.id)
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id=result.id,
            task_name="do_starting",
        )
        logger.info(
            "[checks_starting] Queued do_starting for check %s (task: %s)",
            check.id,
            result.id,
        )
        queued += 1

    logger.info("[checks_starting] Complete: queued=%d", queued)
    return {"queued": queued}


@shared_task(queue="default")
def checks_running() -> dict[str, int]:
    """Queue do_running work tasks for RUNNING checks.

    Only queues if check doesn't already have a pending task.

    Returns:
        Dict with count of queued tasks.
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_running] Starting running cycle")

    queued = 0

    running_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.RUNNING,
    ).exclude(pending_task__isnull=False)

    logger.info(
        "[checks_running] Found %d RUNNING checks without pending task",
        running_checks.count(),
    )

    for check in running_checks:
        result = do_running.delay(check.id)
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id=result.id,
            task_name="do_running",
        )
        logger.info(
            "[checks_running] Queued do_running for check %s (task: %s)",
            check.id,
            result.id,
        )
        queued += 1

    logger.info("[checks_running] Complete: queued=%d", queued)
    return {"queued": queued}


@shared_task(queue="default")
def checks_analyzing() -> dict[str, int]:
    """Queue do_analyzing work tasks for ANALYZING checks.

    Only queues if check doesn't already have a pending task.

    Returns:
        Dict with count of queued tasks.
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_analyzing] Starting analyzing cycle")

    queued = 0

    analyzing_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.ANALYZING,
    ).exclude(pending_task__isnull=False)

    logger.info(
        "[checks_analyzing] Found %d ANALYZING checks without pending task",
        analyzing_checks.count(),
    )

    for check in analyzing_checks:
        result = do_analyzing.delay(check.id)
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id=result.id,
            task_name="do_analyzing",
        )
        logger.info(
            "[checks_analyzing] Queued do_analyzing for check %s (task: %s)",
            check.id,
            result.id,
        )
        queued += 1

    logger.info("[checks_analyzing] Complete: queued=%d", queued)
    return {"queued": queued}


@shared_task(queue="default")
def checks_retry() -> dict:
    """Move retryable ERROR checks back to PENDING state.

    Returns:
        dict with 'retried' and 'exhausted' counts
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_retry] Starting retry cycle")

    retried = 0
    exhausted = 0

    error_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.ERROR,
    )
    error_count = error_checks.count()
    logger.info("[checks_retry] Found %d checks in ERROR state", error_count)

    for check in error_checks:
        if check.can_retry():
            logger.info(
                "[checks_retry] Retrying check %s (project: %s, attempt %d/%d)",
                check.id,
                check.project.name,
                check.retry_count + 1,
                check.max_retries,
            )
            check.reset_for_retry(reason="Automatic retry after error")
            retried += 1
        else:
            logger.info(
                "[checks_retry] Check %s exhausted retries (%d/%d)",
                check.id,
                check.retry_count,
                check.max_retries,
            )
            exhausted += 1

    logger.info(
        "[checks_retry] Complete: retried=%d, exhausted=%d",
        retried,
        exhausted,
    )
    return {"retried": retried, "exhausted": exhausted}


@shared_task(queue="default")
def checks_create() -> dict:
    """Create ManufacturabilityChecks for verified downloads that need them.

    Returns:
        dict with 'created' count
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_create] Starting check creation cycle")

    created = 0

    # Find active, verified files without a check
    files_needing_checks = ProjectFile.objects.filter(
        is_active=True,
        hash_verified=True,
    ).exclude(
        manufacturability_check__isnull=False,
    )

    files_count = files_needing_checks.count()
    logger.info("[checks_create] Found %d verified files needing checks", files_count)

    for project_file in files_needing_checks:
        check = ManufacturabilityCheck.objects.create(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        logger.info(
            "[checks_create] Created check %s for project %s, file %s",
            check.id,
            project_file.project.name,
            project_file.original_filename,
        )
        created += 1

    logger.info("[checks_create] Complete: created=%d", created)
    return {"created": created}


@shared_task(queue="default")
def checks_cleanup_orphaned_processing() -> dict:
    """Find and mark RUNNING checks with dead workers as ERROR.

    Orphaned checks are those in RUNNING state whose worker process
    has died or is no longer actively executing the task.

    mark_error() preserves all tracking fields for debugging purposes.
    Fields are cleared by reset_for_retry() if/when the check is retried.

    Returns:
        dict with 'orphaned' and 'verified' counts
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_cleanup_orphaned_processing] Starting orphan check")

    orphaned = 0
    verified = 0

    running_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.RUNNING,
    )
    running_count = running_checks.count()
    logger.info(
        "[checks_cleanup_orphaned_processing] Found %d RUNNING checks",
        running_count,
    )

    for check in running_checks:
        if is_check_task_actively_running(check):
            logger.debug(
                "[checks_cleanup_orphaned_processing] Check %s verified "
                "(PID %s on %s is active)",
                check.id,
                check.celery_worker_pid,
                check.celery_worker_hostname,
            )
            verified += 1
        else:
            error_msg = (
                f"Orphaned RUNNING check: Worker PID {check.celery_worker_pid} "
                f"on {check.celery_worker_hostname} is dead or task not active"
            )
            logger.warning(
                "[checks_cleanup_orphaned_processing] Orphaned check %s "
                "(project: %s): %s",
                check.id,
                check.project.name,
                error_msg,
            )
            check.mark_error(error_message=error_msg)
            orphaned += 1

    logger.info(
        "[checks_cleanup_orphaned_processing] Complete: verified=%d, orphaned=%d",
        verified,
        orphaned,
    )
    return {"orphaned": orphaned, "verified": verified}


@shared_task(queue="default")
def checks_cancelling() -> dict[str, int]:
    """Queue do_cancelling work tasks for CANCELLING checks.

    Only queues if check doesn't already have a pending task.

    Returns:
        Dict with count of queued tasks.
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_cancelling] Starting cancelling cycle")

    queued = 0

    cancelling_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.CANCELLING,
    ).exclude(pending_task__isnull=False)

    logger.info(
        "[checks_cancelling] Found %d CANCELLING checks without pending task",
        cancelling_checks.count(),
    )

    for check in cancelling_checks:
        result = do_cancelling.delay(check.id)
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id=result.id,
            task_name="do_cancelling",
        )
        logger.info(
            "[checks_cancelling] Queued do_cancelling for check %s (task: %s)",
            check.id,
            result.id,
        )
        queued += 1

    logger.info("[checks_cancelling] Complete: queued=%d", queued)
    return {"queued": queued}


# Work tasks (do_*) - Placeholder stubs for polling architecture
# These will be implemented in later phases


@shared_task(queue="docker-ephemeral")
def do_dispatching(check_id: int) -> dict[str, str]:
    """Pull Docker image for a DISPATCHING check.

    Transitions to STARTING on success.

    Args:
        check_id: ManufacturabilityCheck ID.

    Returns:
        Dict with result status.
    """
    with track_task(check_id):
        check = ManufacturabilityCheck.objects.get(id=check_id)

        if check.status != ManufacturabilityCheck.Status.DISPATCHING:
            return {"status": "skipped", "reason": "status_changed"}

        # Get server config
        server = next(
            (s for s in settings.DOCKER_SERVERS if s["id"] == check.docker_server_id),
            None,
        )
        if not server:
            error_msg = f"Unknown server: {check.docker_server_id}"
            check.mark_error(error_message=error_msg)
            return {"status": "error", "reason": "unknown_server"}

        # Connect to Docker
        client = docker.DockerClient(base_url=str(server["url"]))

        try:
            image_name = settings.PRECHECK_DOCKER_IMAGE
            image = client.images.pull(image_name)

            # Extract digest from pulled image
            digests = image.attrs.get("RepoDigests", [])
            digest = digests[0].split("@")[1] if digests else "unknown"

            check.mark_starting(
                docker_image=image_name,
                docker_image_digest=digest,
            )
        except docker.errors.DockerException as e:
            error_msg = f"Docker pull failed: {e}"
            check.mark_error(error_message=error_msg)
            return {"status": "error", "reason": str(e)}
        else:
            return {"status": "success", "image": image_name, "digest": digest}


@shared_task(queue="docker-ephemeral")
def do_starting(check_id: int) -> dict[str, Any]:  # noqa: C901, PLR0911, PLR0915
    """Create and start Docker container for a STARTING check.

    Creates a Docker container with appropriate labels and volume mounts,
    starts it, and waits briefly for it to reach running state.

    Args:
        check_id: ManufacturabilityCheck ID.

    Returns:
        Dict with status and container info.
    """
    logger = logging.getLogger(__name__)

    with track_task(check_id):
        check = ManufacturabilityCheck.objects.get(id=check_id)

        if check.status != ManufacturabilityCheck.Status.STARTING:
            logger.info(
                "Skipping do_starting for check %s - status changed to %s",
                check_id,
                check.status,
            )
            return {"status": "skipped", "reason": "status_changed"}

        # Get server config
        server = next(
            (s for s in settings.DOCKER_SERVERS if s["id"] == check.docker_server_id),
            None,
        )
        if not server:
            error_msg = f"Unknown server: {check.docker_server_id}"
            logger.error(error_msg)
            check.mark_error(error_message=error_msg)
            return {"status": "error", "reason": "unknown_server"}

        # Connect to Docker
        try:
            client = docker.DockerClient(base_url=str(server["url"]))
        except docker.errors.DockerException as e:
            error_msg = f"Failed to connect to Docker server: {e}"
            logger.exception(error_msg)
            check.mark_error(error_message=error_msg)
            return {"status": "error", "reason": str(e)}

        try:
            # Get the project file path
            project_file = check.project_file
            if not project_file.file:
                error_msg = "Project file not downloaded yet"
                logger.error(error_msg)
                check.mark_error(error_message=error_msg)
                return {"status": "error", "reason": "file_not_ready"}

            gds_path = Path(project_file.file.path)
            if not gds_path.exists():
                error_msg = f"File not found at {gds_path}"
                logger.error(error_msg)
                check.mark_error(error_message=error_msg)
                return {"status": "error", "reason": "file_not_found"}

            # Create container with labels and volume mount
            command = "precheck"
            container = client.containers.create(
                check.docker_image,
                command=command,
                labels={
                    "wafer.space.service": "manufacturability-check",
                    "wafer.space.check_id": str(check.id),
                    "wafer.space.project_id": str(check.project.id),
                },
                volumes={
                    str(gds_path): {
                        "bind": "/input/design.gds",
                        "mode": "ro",
                    },
                },
                # Limit resources to prevent runaway containers
                mem_limit="4g",
                cpu_count=2,
            )

            logger.info(
                "Created container %s for check %s on server %s",
                container.id[:12],
                check_id,
                check.docker_server_id,
            )

            # Start the container
            container.start()
            logger.info("Started container %s", container.id[:12])

            # Wait briefly for container to be running
            # Give it a few seconds to start
            max_wait = 10
            for _ in range(max_wait):
                container.reload()
                if container.status == "running":
                    break
                if container.status == "exited":
                    # Container exited immediately - this is an error
                    error_msg = "Container exited immediately after start"
                    logger.error(error_msg)
                    check.mark_error(error_message=error_msg)
                    return {"status": "error", "reason": "container_exited_immediately"}
                time.sleep(1)

            # Final status check
            container.reload()
            if container.status != "running":
                error_msg = f"Container failed to start: status={container.status}"
                logger.error(error_msg)
                check.mark_error(error_message=error_msg)
                return {"status": "error", "reason": "failed_to_start"}

            # Transition to RUNNING
            check.mark_running(
                docker_container_id=container.id,
                docker_command=command,
            )

            logger.info(
                "Check %s transitioned to RUNNING with container %s",
                check_id,
                container.id[:12],
            )

            return {  # noqa: TRY300
                "status": "success",
                "container_id": container.id,
                "command": command,
            }

        except docker.errors.DockerException as e:
            error_msg = f"Docker container creation failed: {e}"
            logger.exception(error_msg)
            check.mark_error(error_message=error_msg)
            return {"status": "error", "reason": str(e)}


@shared_task(queue="docker-ephemeral")
def do_running(check_id: int) -> dict[str, Any]:  # noqa: C901, PLR0911, PLR0912, PLR0915
    """Monitor running container and download logs incrementally.

    Checks container status, downloads new logs since last fetch,
    and transitions to ANALYZING if container has exited.

    Args:
        check_id: ManufacturabilityCheck ID.

    Returns:
        Dict with status and log info.
    """
    logger = logging.getLogger(__name__)

    with track_task(check_id):
        check = ManufacturabilityCheck.objects.get(id=check_id)

        if check.status != ManufacturabilityCheck.Status.RUNNING:
            logger.info(
                "Skipping do_running for check %s - status changed to %s",
                check_id,
                check.status,
            )
            return {"status": "skipped", "reason": "status_changed"}

        # Get server config
        server = next(
            (s for s in settings.DOCKER_SERVERS if s["id"] == check.docker_server_id),
            None,
        )
        if not server:
            error_msg = f"Unknown server: {check.docker_server_id}"
            logger.error(error_msg)
            check.mark_error(error_message=error_msg)
            return {"status": "error", "reason": "unknown_server"}

        # Connect to Docker
        try:
            client = docker.DockerClient(base_url=str(server["url"]))
        except docker.errors.DockerException as e:
            error_msg = f"Failed to connect to Docker server: {e}"
            logger.exception(error_msg)
            check.mark_error(error_message=error_msg)
            return {"status": "error", "reason": str(e)}

        try:
            # Get the container
            container = client.containers.get(check.docker_container_id)
        except docker.errors.NotFound:
            error_msg = f"Container {check.docker_container_id} not found"
            logger.exception(error_msg)
            check.mark_error(error_message=error_msg)
            return {"status": "error", "reason": "container_not_found"}
        except docker.errors.DockerException as e:
            error_msg = f"Failed to get container: {e}"
            logger.exception(error_msg)
            check.mark_error(error_message=error_msg)
            return {"status": "error", "reason": str(e)}

        try:
            # Download logs incrementally
            logs_kwargs: dict[str, Any] = {"timestamps": True}
            if check.logs_downloaded_until:
                # Only get logs since last download
                logs_kwargs["since"] = check.logs_downloaded_until

            raw_logs = container.logs(**logs_kwargs).decode("utf-8", errors="replace")

            # Find the latest timestamp in the logs for next incremental fetch
            latest_timestamp = None
            if raw_logs:
                for line in raw_logs.split("\n"):
                    timestamp = parse_docker_timestamp_float(line)
                    if timestamp:
                        latest_timestamp = timestamp

                # Strip timestamps and append to processing logs
                clean_logs = strip_docker_timestamps(raw_logs)
                if clean_logs.strip():
                    check.append_to_processing_logs(clean_logs)
                    logger.info(
                        "Downloaded %d bytes of logs for check %s",
                        len(clean_logs),
                        check_id,
                    )

            # Check container status
            container.reload()
            container_status = container.status

            if container_status == "exited":
                # Container has finished - get exit code and transition
                exit_code = container.attrs.get("State", {}).get("ExitCode", -1)
                logger.info(
                    "Container %s exited with code %d",
                    container.id[:12],
                    exit_code,
                )

                check.mark_analyzing(docker_exit_code=exit_code)
                return {
                    "status": "container_exited",
                    "exit_code": exit_code,
                }

            # Container still running - update logs timestamp
            if latest_timestamp:
                check.logs_downloaded_until = latest_timestamp
                check.save(update_fields=["logs_downloaded_until"])

            logger.info(
                "Container %s still running for check %s",
                container.id[:12],
                check_id,
            )

            return {
                "status": "still_running",
                "container_status": container_status,
                "logs_bytes": len(raw_logs) if raw_logs else 0,
            }

        except docker.errors.DockerException as e:
            error_msg = f"Docker error while monitoring container: {e}"
            logger.exception(error_msg)
            check.mark_error(error_message=error_msg)
            return {"status": "error", "reason": str(e)}


@shared_task(queue="docker-ephemeral")
def do_analyzing(check_id: int) -> dict[str, Any]:
    """Analyze container logs and extract results.

    Parses the container logs to determine if the design is manufacturable,
    extracts errors and warnings, and transitions to FINISHED.

    Args:
        check_id: ManufacturabilityCheck ID.

    Returns:
        Dict with analysis results.
    """
    logger = logging.getLogger(__name__)

    from wafer_space.projects.precheck_parser import PrecheckLogParser  # noqa: PLC0415

    with track_task(check_id):
        check = ManufacturabilityCheck.objects.get(id=check_id)

        if check.status != ManufacturabilityCheck.Status.ANALYZING:
            logger.info(
                "Skipping do_analyzing for check %s - status changed to %s",
                check_id,
                check.status,
            )
            return {"status": "skipped", "reason": "status_changed"}

        try:
            # Parse the logs
            logs = check.processing_logs or ""
            exit_code = check.docker_exit_code or 0

            logger.info(
                "Parsing logs for check %s (exit_code=%d, log_length=%d)",
                check_id,
                exit_code,
                len(logs),
            )

            parse_result = PrecheckLogParser.parse_logs(logs, exit_code)

            # Extract errors and warnings
            error_messages = [e["message"] for e in parse_result["errors"]]
            warning_messages = [
                w.get("message", str(w)) for w in parse_result["warnings"]
            ]

            # Determine manufacturability
            is_manufacturable = parse_result["success"]

            # Extract tool versions from logs if available
            # For now, use a simple approach - look for version strings
            tool_versions: dict[str, str] = {}
            # Placeholder - real version extraction would be more sophisticated
            if "precheck" in logs.lower():
                tool_versions["precheck"] = "unknown"

            logger.info(
                "Analysis complete for check %s: "
                "manufacturable=%s, errors=%d, warnings=%d",
                check_id,
                is_manufacturable,
                len(error_messages),
                len(warning_messages),
            )

            # Transition to FINISHED
            check.mark_finished(
                is_manufacturable=is_manufacturable,
                errors=error_messages,
                warnings=warning_messages,
                tool_versions=tool_versions,
            )

            return {
                "status": "success",
                "is_manufacturable": is_manufacturable,
                "error_count": len(error_messages),
                "warning_count": len(warning_messages),
            }

        except Exception as e:
            # Catch any parsing errors and mark as system error
            error_msg = f"Failed to analyze logs: {e}"
            logger.exception(error_msg)
            check.mark_error(error_message=error_msg)
            return {"status": "error", "reason": str(e)}


@shared_task(queue="docker-ephemeral")
def do_cancelling(check_id: int) -> dict[str, Any]:
    """Stop and remove container for a CANCELLING check.

    Attempts to stop and remove the Docker container if it exists,
    then transitions the check to CANCELLED status.

    Args:
        check_id: ManufacturabilityCheck ID.

    Returns:
        Dict with cancellation status.
    """
    logger = logging.getLogger(__name__)

    with track_task(check_id):
        check = ManufacturabilityCheck.objects.get(id=check_id)

        if check.status != ManufacturabilityCheck.Status.CANCELLING:
            logger.info(
                "Skipping do_cancelling for check %s - status changed to %s",
                check_id,
                check.status,
            )
            return {"status": "skipped", "reason": "status_changed"}

        container_id = check.docker_container_id
        container_stopped = False
        container_removed = False

        # Only attempt Docker operations if we have a container ID and server
        if container_id and check.docker_server_id:
            # Get server config
            server = next(
                (
                    s
                    for s in settings.DOCKER_SERVERS
                    if s["id"] == check.docker_server_id
                ),
                None,
            )

            if server:
                try:
                    client = docker.DockerClient(base_url=str(server["url"]))

                    try:
                        container = client.containers.get(container_id)

                        # Stop the container if it's running
                        container.reload()
                        if container.status in ("running", "paused"):
                            logger.info(
                                "Stopping container %s for check %s",
                                container_id[:12],
                                check_id,
                            )
                            container.stop(timeout=10)
                            container_stopped = True

                        # Remove the container
                        logger.info(
                            "Removing container %s for check %s",
                            container_id[:12],
                            check_id,
                        )
                        container.remove()
                        container_removed = True

                    except docker.errors.NotFound:
                        # Container already gone - that's fine
                        logger.info(
                            "Container %s not found (already removed)",
                            container_id[:12],
                        )
                        container_removed = True

                except docker.errors.DockerException as e:
                    # Log the error but don't fail - we still want to mark as cancelled
                    logger.warning(
                        "Docker error during cancellation of check %s: %s",
                        check_id,
                        e,
                    )
            else:
                logger.warning(
                    "Unknown server %s for check %s - cannot clean up container",
                    check.docker_server_id,
                    check_id,
                )

        # Transition to CANCELLED
        check.mark_cancelled()

        logger.info(
            "Check %s cancelled (container_stopped=%s, container_removed=%s)",
            check_id,
            container_stopped,
            container_removed,
        )

        return {
            "status": "success",
            "container_stopped": container_stopped,
            "container_removed": container_removed,
        }


@shared_task(queue="default")
def checks_cleanup_stale_files() -> dict:
    """Cancel checks on project files that are no longer active.

    When a user uploads a new file to a project, the old file's is_active
    flag is set to False. Any in-progress checks on inactive files should
    be cancelled since they're no longer relevant.

    This task finds such checks and marks them as CANCELLING, which will
    then be processed by the checks_cancelling task.

    Returns:
        dict with 'cancelled' count of checks marked for cancellation
    """
    logger = logging.getLogger(__name__)
    cancelled = 0

    # Find checks in progress on inactive project files
    stale_checks = ManufacturabilityCheck.objects.filter(
        status__in=ManufacturabilityCheck.IN_PROGRESS_STATUSES,
        project_file__is_active=False,
    )

    for check in stale_checks:
        try:
            logger.info(
                "Cancelling stale check %s on inactive file %s (project %s)",
                check.id,
                check.project_file.original_filename,
                check.project.name,
            )
            check.mark_cancelling(reason="Project file replaced with newer version")
            cancelled += 1
        except InvalidStateTransitionError:
            logger.exception(
                "Failed to mark check %s as cancelling",
                check.id,
            )

    return {"cancelled": cancelled}
