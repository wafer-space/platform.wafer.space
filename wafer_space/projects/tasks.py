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
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request
from urllib.request import urlopen

import docker
import requests
from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone
from django_celery_results.models import TaskResult

from wafer_space.notifications.services import NotificationService

from .models import ManufacturabilityCheck
from .models import Project
from .models import ProjectFile
from .models import ProjectFileChunk
from .precheck_parser import PrecheckLogParser
from .precheck_parser import classify_failure
from .url_handlers import GoogleSourceHandler
from .url_handlers import URLHandlerRegistry
from .verification import is_task_actively_running
from .verification import is_task_queued

# HTTP status codes
HTTP_PARTIAL_CONTENT = 206  # Server supports range requests

# Byte conversion constants
BYTES_PER_KILOBYTE = 1024

# Progress logging interval (seconds)
PROGRESS_LOG_INTERVAL_SECONDS = 30

# Initialize URL handler registry for post-download processing
_url_handler_registry = URLHandlerRegistry()
_url_handler_registry.register(GoogleSourceHandler())


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
    gds_path: str
    task_instance: "shared_task"
    logger: logging.Logger


def _pull_and_record_image(context: _CheckContext):
    """Pull Docker image and record metadata.

    Args:
        context: Check execution context

    Returns:
        Docker image object
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
    context.check.docker_image = image.tags[0] if image.tags else image_name
    context.check.docker_image_digest = image.id
    context.check.save(update_fields=["docker_image", "docker_image_digest"])

    # Log image details
    image_size = image.attrs.get("Size", 0)
    context.logger.info(
        "  ✓ Image ready: %s (digest: %s, size: %s)",
        context.check.docker_image,
        context.check.docker_image_digest[:12],
        _format_bytes(image_size),
    )
    return image


def _run_container_and_stream_logs(context: _CheckContext):
    """Run Docker container and stream logs with progress updates.

    Args:
        context: Check execution context

    Returns:
        tuple: (logs string, exit_code int, container object)
    """
    context.logger.info("Step 4: Creating Docker container...")
    context.logger.info("  Input file: %s", context.gds_path)
    context.logger.info("  Project name: %s", context.project.name)
    context.logger.info("  Project ID: %s", context.project.id)
    context.logger.info("  Memory limit: 8GB")
    context.logger.info("  CPU limit: 1 CPU")

    container_start = timezone.now()

    # Build the precheck command to run inside nix-shell
    # The precheck.py script is in /workspace, and we run it via nix-shell
    # to get access to Python and other Nix-provided dependencies
    precheck_cmd = (
        f"python3 precheck.py --input /input/design.gds "
        f'--top "{context.project.name}" --id "{context.project.id}"'
    )

    # Log the full Docker command for debugging
    docker_command = ["nix-shell", "--run", precheck_cmd]
    context.logger.info("  Docker image: %s", settings.PRECHECK_DOCKER_IMAGE)
    context.logger.info("  Docker command: %s", docker_command)
    context.logger.info("  Volume mount: %s -> /input/design.gds", context.gds_path)
    context.logger.info("  Working dir: /workspace")

    container = context.client.containers.run(
        image=settings.PRECHECK_DOCKER_IMAGE,
        command=docker_command,
        volumes={context.gds_path: {"bind": "/input/design.gds", "mode": "ro"}},
        working_dir="/workspace",
        detach=True,
        mem_limit="8g",
        cpu_quota=100000,  # 1 CPU
    )
    context.logger.info("  ✓ Container started: %s", container.id[:12])

    context.logger.info("Step 5: Running precheck analysis...")
    context.logger.info("  Streaming container logs...")

    # Stream logs and update progress
    logs = ""
    line_count = 0
    last_progress_log = timezone.now()

    for line in container.logs(stream=True):
        line_text = line.decode("utf-8")
        logs += line_text
        line_count += 1

        # Log the actual container output
        for log_line in line_text.strip().split("\n"):
            if log_line:
                context.logger.info("  [container] %s", log_line)

        # Update last activity and logs
        context.check.last_activity = timezone.now()
        context.check.processing_logs = logs
        context.check.save(update_fields=["last_activity", "processing_logs"])

        # Periodic progress update
        now = timezone.now()
        if (now - last_progress_log).total_seconds() >= PROGRESS_LOG_INTERVAL_SECONDS:
            elapsed = (now - container_start).total_seconds()
            context.logger.info(
                "  ... still running (%.0f seconds, %d log lines)",
                elapsed,
                line_count,
            )
            last_progress_log = now

        # Update Celery task state
        context.task_instance.update_state(
            state="PROGRESS",
            meta={
                "message": "Running precheck...",
                "logs": logs[-1000:],  # Last 1000 chars
                "line_count": line_count,
            },
        )

    context.logger.info("Step 6: Waiting for container to complete...")

    # Wait for completion
    result = container.wait(timeout=settings.PRECHECK_TIMEOUT_SECONDS)
    exit_code = result["StatusCode"]

    container_duration = (timezone.now() - container_start).total_seconds()
    context.logger.info(
        "  ✓ Container completed in %.1f seconds (exit code: %d, %d log lines)",
        container_duration,
        exit_code,
        line_count,
    )

    return logs, exit_code, container


def _handle_check_result(check, logs, exit_code, logger):
    """Parse logs and update check status based on results.

    Args:
        check: ManufacturabilityCheck instance
        logs: Container logs string
        exit_code: Container exit code
        logger: Logger instance

    Returns:
        dict: Result data with status and details
    """
    logger.info("Step 7: Parsing check results...")

    # Extract version information
    check.tool_versions = {
        "pdk": "gf180mcuD",  # Will extract from logs
        "magic": "unknown",  # Will extract from logs
        "klayout": "unknown",  # Will extract from logs
    }
    check.save(update_fields=["tool_versions"])

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
    if exit_code == 0:
        # Success
        check.complete(
            is_manufacturable=True,
            errors=[],
            warnings=parsed.get("warnings", []),
            logs=logs,
        )
        logger.info("Check completed successfully - project is manufacturable")
        return "success"

    # Failure - classify
    failure_type = classify_failure(logs, exit_code)
    logger.info("Check failed with type: %s", failure_type)

    if failure_type == "system":
        # System failure - prepare for retry
        error_summary = (
            parsed["errors"][0]["message"]
            if parsed["errors"]
            else "Unknown system error"
        )
        return "system", error_summary

    # Design failure - complete with errors
    check.complete(
        is_manufacturable=False,
        errors=parsed.get("errors", []),
        warnings=parsed.get("warnings", []),
        logs=logs,
    )
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


def _handle_retry(check, error_summary, task_instance, logger):
    """Handle system failure - mark as FAILED for periodic retry.

    System failures (Docker errors, timeouts, etc.) are different from
    manufacturing issues. System failures:
    - Set status to FAILED
    - Store error in error_message field
    - Will be retried by the periodic scan task if retry_count < max_retries

    We don't use Celery's built-in retry here because the periodic scan
    provides better visibility and control over the retry queue.

    Args:
        check: ManufacturabilityCheck instance
        error_summary: Error message string
        task_instance: Celery task instance (unused, kept for API compatibility)
        logger: Logger instance
    """
    logger.error("System failure detected: %s", error_summary)
    check.fail(error_summary)
    logger.info(
        "  Check marked as FAILED (retry %d/%d available)",
        check.retry_count,
        check.max_retries,
    )


def _handle_exception_retry(check_id, exc, task_instance, logger):
    """Handle exception - mark as FAILED for periodic retry.

    System failures (Docker errors, timeouts, etc.) are different from
    manufacturing issues. System failures:
    - Set status to FAILED
    - Store error in error_message field
    - Will be retried by the periodic scan task if retry_count < max_retries

    We don't use Celery's built-in retry here because the periodic scan
    provides better visibility and control over the retry queue.

    Args:
        check_id: ManufacturabilityCheck ID
        exc: Exception instance
        task_instance: Celery task instance (unused, kept for API compatibility)
        logger: Logger instance
    """
    try:
        check = ManufacturabilityCheck.objects.get(id=check_id)
        error_msg = str(exc)
        logger.error("Exception during check: %s", error_msg)
        check.fail(error_msg)
        logger.info(
            "  Check marked as FAILED (retry %d/%d available)",
            check.retry_count,
            check.max_retries,
        )
    except ManufacturabilityCheck.DoesNotExist:
        logger.warning("Check %s not found when handling exception", check_id)


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


def _setup_docker_context(check, project_file, task_instance, logger):
    """Set up Docker client and execution context.

    Returns:
        _CheckContext: Execution context for the check
    """
    logger.info("Step 2: Connecting to Docker daemon...")
    client = docker.from_env()
    docker_info = client.info()
    logger.info("  ✓ Docker connected: %s", docker_info.get("Name", "unknown"))
    logger.info("  ✓ Docker version: %s", docker_info.get("ServerVersion", "unknown"))

    return _CheckContext(
        check=check,
        client=client,
        project=check.project,
        gds_path=project_file.file.path,
        task_instance=task_instance,
        logger=logger,
    )


@shared_task(
    bind=True,
    time_limit=settings.PRECHECK_TIMEOUT_SECONDS,
    soft_time_limit=settings.PRECHECK_TIMEOUT_SECONDS - 300,
)
def check_project_manufacturability(self, check_id):
    """Run manufacturability check in Docker container.

    This task performs manufacturability analysis using the gf180mcu-precheck
    tool running in a Docker container. It replaces the previous mock implementation.

    Args:
        check_id: The ID of the ManufacturabilityCheck instance

    Returns:
        dict: Result data with status and details
    """
    logger = logging.getLogger(__name__)
    container = None
    task_start = timezone.now()

    try:
        _log_task_start(logger, check_id, self.request.id)

        # Step 1: Get check and project
        logger.info("Step 1: Loading check and project data...")
        check = ManufacturabilityCheck.objects.get(id=check_id)
        check.task_id = self.request.id or "test-task"
        check.save(update_fields=["task_id"])
        check.start_processing()

        project_file = _validate_project_file(check)
        logger.info("  ✓ Project: %s (ID: %s)", check.project.name, check.project.id)
        logger.info("  ✓ File: %s", project_file.original_filename)
        logger.info("  ✓ File size: %s", _format_bytes(project_file.file_size or 0))

        # Step 2: Connect to Docker (in helper)
        context = _setup_docker_context(check, project_file, self, logger)

        # Steps 3-6: Pull image and run container (in helpers)
        _pull_and_record_image(context)
        logs, exit_code, container = _run_container_and_stream_logs(context)

        # Step 7: Handle results (in helper)
        result = _handle_check_result(check, logs, exit_code, logger)

        # Handle system failures
        if isinstance(result, tuple) and result[0] == "system":
            _handle_retry(check, result[1], self, logger)

        # Step 8: Cleanup
        logger.info("Step 8: Cleaning up...")
        _cleanup_container(container, logger)

        # Final summary
        _log_task_complete(logger, task_start, check)

        return {
            "status": "completed",
            "is_manufacturable": check.is_manufacturable,
            "errors": check.errors,
            "warnings": check.warnings,
            "project_id": str(check.project.id),
        }

    except ManufacturabilityCheck.DoesNotExist:
        logger.exception("ManufacturabilityCheck with id %s not found", check_id)
        return {
            "status": "error",
            "message": f"ManufacturabilityCheck with id {check_id} not found",
        }

    except docker.errors.ContainerError as exc:
        logger.exception("Container error during precheck execution")
        _handle_exception_retry(check_id, exc, self, logger)
        return {
            "status": "failed",
            "message": f"Container error: {exc!s}",
        }

    except docker.errors.ImageNotFound:
        logger.exception(
            "Docker image not found: %s",
            settings.PRECHECK_DOCKER_IMAGE,
        )

        try:
            check = ManufacturabilityCheck.objects.get(id=check_id)
            error_msg = f"Docker image not found: {settings.PRECHECK_DOCKER_IMAGE}"
            check.fail(error_msg)
        except ManufacturabilityCheck.DoesNotExist:
            pass

        return {
            "status": "failed",
            "message": "Docker image not found",
        }

    except docker.errors.APIError as exc:
        logger.exception("Docker API error")
        _handle_exception_retry(check_id, exc, self, logger)
        return {
            "status": "failed",
            "message": f"Docker API error: {exc!s}",
        }

    except Exception as exc:
        logger.exception("Unexpected error in manufacturability check task")
        _handle_exception_retry(check_id, exc, self, logger)
        return {
            "status": "failed",
            "message": str(exc),
            "retries": self.request.retries,
        }


@shared_task
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


def _download_file_content(project_file) -> bytes:
    """Download file content from URL using secure URL validation."""
    content, headers = _safe_urlopen(project_file.source_url)

    # Set content type if available
    content_type = headers.get("Content-Type", "")
    if content_type:
        project_file.content_type = content_type

    return content


def _save_file_to_django(project_file, file_content: bytes, temp_dir: Path) -> None:
    """Save downloaded content to Django file field."""
    # Create temporary file to store content
    temp_filename = f"{project_file.id}_{project_file.original_filename}"
    temp_path = temp_dir / temp_filename

    # Write content to temp file
    temp_path.write_bytes(file_content)

    # Create Django file from the downloaded content
    with temp_path.open("rb") as temp_file:
        django_file = ContentFile(temp_file.read())
        django_file.name = project_file.original_filename
        project_file.file.save(
            project_file.original_filename,
            django_file,
            save=False,
        )

    # Clean up temp file
    with contextlib.suppress(OSError):
        temp_path.unlink()


def _prepare_download_request(
    url: str,
    temp_path: Path,
) -> tuple[dict[str, str], int]:
    """Prepare download request with resume support.

    Returns:
        tuple: (headers dict, resume byte position)
    """
    logger = logging.getLogger(__name__)
    headers = {"User-Agent": "wafer.space/1.0"}
    resume_byte_pos = 0

    if temp_path.exists():
        resume_byte_pos = temp_path.stat().st_size
        headers["Range"] = f"bytes={resume_byte_pos}-"
        formatted_size = _format_bytes(resume_byte_pos)
        logger.info("  Resume: Found partial download (%s)", formatted_size)

    return headers, resume_byte_pos


def _get_download_response(
    url: str,
    headers: dict[str, str],
    temp_path: Path,
    resume_byte_pos: int,
) -> tuple[requests.Response, int]:
    """Get HTTP response for download, handling resume failures.

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
        response = requests.get(url, headers=headers, stream=True, timeout=30)

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
    """State for chunk-based file download."""

    response: requests.Response
    temp_path: Path
    task: "shared_task"  # Celery task instance (use string to avoid circular import)
    project_file: ProjectFile
    total_size: int
    resume_byte_pos: int
    md5_hasher: "hashlib._Hash"  # hashlib hash object
    sha1_hasher: "hashlib._Hash"  # hashlib hash object
    sha256_hasher: "hashlib._Hash"  # hashlib hash object
    chunk_size: int
    start_time: float  # Unix timestamp when download started


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


def _download_chunks(state: _ChunkDownloadState) -> int:
    """Download file chunks with progress tracking.

    Returns:
        int: Number of chunks downloaded
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

            # Write chunk and update hashes
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
                # Update last activity timestamp
                state.project_file.last_activity = timezone.now()
                state.project_file.save(update_fields=["last_activity"])

                # Record chunk checkpoint for performance analysis
                # Use rounded checkpoint values at exact 5MB boundaries
                ProjectFileChunk.objects.create(
                    project_file=state.project_file,
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
    return chunk_count


def _download_with_progress(
    task,
    project_file,
    temp_path: Path,
    *,
    chunk_size: int = 1024 * 1024,  # 1MB chunks
) -> tuple[str, str, str]:
    """Download file with progress tracking and resume capability.

    Args:
        task: The Celery task instance (for progress updates)
        project_file: The ProjectFile instance
        temp_path: Path to temporary file for download
        chunk_size: Size of download chunks in bytes

    Returns:
        tuple: (md5_hash, sha1_hash, sha256_hash) of downloaded content
    """
    url = project_file.source_url

    # Prepare request with resume support
    headers, resume_byte_pos = _prepare_download_request(url, temp_path)

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


def _initialize_download(project_file: ProjectFile) -> None:
    """Mark file download as started and set initial metadata.

    Args:
        project_file: The file to initialize
    """
    # Transition QUEUED → DOWNLOADING and capture worker info
    project_file.download_status = ProjectFile.DownloadStatus.DOWNLOADING
    project_file.worker_pid = os.getpid()
    project_file.worker_hostname = socket.gethostname()
    project_file.task_started_at = timezone.now()
    project_file.download_started_at = timezone.now()
    project_file.last_activity = timezone.now()
    project_file.save(
        update_fields=[
            "download_status",
            "worker_pid",
            "worker_hostname",
            "task_started_at",
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
    retry_delay = 60 * (2**task_self.request.retries)

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
) -> dict[str, str | int]:
    """Handle final download failure after max retries.

    Args:
        project_id: UUID of the project
        exc: The exception that caused the failure
        temp_path: Path to temp file to clean up

    Returns:
        dict: Failure status information
    """
    try:
        _project, project_file = _get_project_file_for_download(project_id)
        if project_file:
            error_msg = f"Max retries reached: {exc!s}"
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


def _process_and_save_content(
    project_file: ProjectFile,
    downloaded_content: bytes,
    temp_path: Path,
    hashes: HashResults,
) -> tuple[bytes, HashResults]:
    """Process downloaded content and save to Django storage.

    Returns:
        tuple: (processed_content, final_hashes)
    """
    logger = logging.getLogger(__name__)

    # Apply URL handler post-download processing
    logger.info("Step 6: Checking for post-download processing...")
    if project_file.handler_metadata:
        logger.info("  Handler metadata found: %s", project_file.handler_metadata)
    processed_content = _apply_post_download_processing(
        project_file,
        downloaded_content,
    )

    # Recalculate hashes if content was transformed
    final_hashes = hashes

    if processed_content != downloaded_content:
        logger.info("  Content was transformed by handler - recalculating hashes...")
        logger.info("  Original size: %s", _format_bytes(len(downloaded_content)))
        logger.info("  Processed size: %s", _format_bytes(len(processed_content)))
        md5, sha1, sha256 = _calculate_file_hashes(processed_content)
        final_hashes = HashResults(md5=md5, sha1=sha1, sha256=sha256)
        logger.info("  ✓ Recalculated MD5: %s", final_hashes.md5)
        logger.info("  ✓ Recalculated SHA1: %s", final_hashes.sha1)
        logger.info("  ✓ Recalculated SHA256: %s", final_hashes.sha256)
        temp_path.write_bytes(processed_content)
    else:
        logger.info("  ✓ No transformation needed - using original content")

    # Save to Django file field
    logger.info("Step 7: Saving file to Django storage...")
    django_file = ContentFile(processed_content)
    django_file.name = project_file.original_filename
    project_file.file.save(
        project_file.original_filename,
        django_file,
        save=False,
    )
    logger.info("  ✓ File saved to Django storage")

    # Set file size and hashes
    project_file.file_size = len(processed_content)
    project_file.hash_md5 = final_hashes.md5
    project_file.hash_sha1 = final_hashes.sha1
    project_file.hash_sha256 = final_hashes.sha256
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

    return processed_content, final_hashes


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
    project_file.mark_download_complete()
    logger.info("  ✓ Download marked as COMPLETE")

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
        logger.info("  ✓ File ready for manufacturability checking")
        # Note: Manufacturability check is queued by a separate periodic task
        # that scans for verified files without checks
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


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def download_project_file(self, project_id):  # noqa: PLR0915
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
            "  ✓ Download started: file=%s, PID=%s, host=%s, task_id=%s",
            project_file.id,
            project_file.worker_pid,
            project_file.worker_hostname,
            self.request.id,
        )

        # Set up temporary directory
        temp_path = _setup_download_temp_path(project_file)

        # Download with progress tracking
        logger.info("Step 4: Starting chunked download from URL...")
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
        from .services import detect_file_type_from_data  # noqa: PLC0415

        # Use first 1MB for MIME detection (or entire file if smaller)
        detection_data = downloaded_content[: 1024 * 1024]
        try:
            mime_type, detected_extension = detect_file_type_from_data(detection_data)
            logger.info("  ✓ Detected MIME type: %s", mime_type)
            logger.info("  ✓ Detected extension: %s", detected_extension)

            # Update filename based on detected type
            base_name = project_file.original_filename.rsplit(".", 1)[0]
            if base_name == "download" or not base_name:
                base_name = "file"
            new_filename = f"{base_name}{detected_extension}"
            old_name = project_file.original_filename
            logger.info("  ✓ Updated filename: %s → %s", old_name, new_filename)
            project_file.original_filename = new_filename
            project_file.save(update_fields=["original_filename"])
        except ValueError as e:
            logger.exception("  ✗ File type detection failed")
            # Mark download as failed
            project_file.download_status = ProjectFile.DownloadStatus.FAILED
            project_file.download_error = str(e)
            project_file.save(update_fields=["download_status", "download_error"])
            raise

        # Process and save content
        logger.info("Step 7: Processing and saving content...")
        download_hashes = HashResults(
            md5=md5_hash,
            sha1=sha1_hash,
            sha256=sha256_hash,
        )
        _processed_content, final_hashes = _process_and_save_content(
            project_file,
            downloaded_content,
            temp_path,
            download_hashes,
        )

        # Verify hashes and create notifications
        logger.info("Step 8: Verifying hashes and creating notifications...")
        hash_verified, verification_errors = _verify_and_notify(
            project_file,
            final_hashes,
        )

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
            retry_delay = 60 * (2**self.request.retries)
            logger.info(
                "Retry %d/%d - Will retry in %d seconds",
                retry_num,
                self.max_retries,
                retry_delay,
            )
            _handle_download_retry(self, project_id, exc)
        else:
            logger.exception(
                "DOWNLOAD TASK FAILED - Max retries reached for project %s", project_id
            )
            return _handle_download_failure(project_id, exc, temp_path)


@shared_task
def retry_failed_downloads():
    """Periodic task to automatically retry failed downloads.

    This task runs every 5 minutes and:
    1. Finds all failed downloads that are eligible for retry
    2. Checks exponential backoff timing
    3. Re-queues the download task
    4. Updates retry counters

    Returns:
        dict: Statistics about retries attempted
    """
    logger = logging.getLogger(__name__)

    # Find all failed downloads eligible for retry
    failed_files = ProjectFile.objects.filter(
        download_status=ProjectFile.DownloadStatus.FAILED,
        is_active=True,
        auto_retry_enabled=True,
        retry_count__lt=models.F("max_retries"),
    ).filter(
        models.Q(next_retry_at__isnull=True)
        | models.Q(next_retry_at__lte=timezone.now())
    )

    retried_count = 0
    skipped_count = 0

    for project_file in failed_files:
        # Double-check should_auto_retry (belt and suspenders)
        if not project_file.should_auto_retry():
            skipped_count += 1
            continue

        logger.info(
            "Auto-retrying failed download for file %s (retry %d/%d)",
            project_file.id,
            project_file.retry_count + 1,
            project_file.max_retries,
        )

        # Update retry tracking
        project_file.retry_count += 1
        project_file.last_retry_at = timezone.now()
        project_file.download_status = ProjectFile.DownloadStatus.PENDING
        project_file.download_error = ""  # Clear previous error
        project_file.next_retry_at = None  # Clear next retry time

        # Queue the download task and store task ID
        task = download_project_file.delay(str(project_file.project.id))
        project_file.download_task_id = task.id

        project_file.save(
            update_fields=[
                "retry_count",
                "last_retry_at",
                "download_status",
                "download_error",
                "next_retry_at",
                "download_task_id",
            ]
        )

        retried_count += 1

    logger.info(
        "Auto-retry task completed: %d retried, %d skipped",
        retried_count,
        skipped_count,
    )

    return {
        "status": "completed",
        "retried": retried_count,
        "skipped": skipped_count,
    }


@shared_task
def check_download_states():
    """Verify all downloading files are in correct state.

    Runs frequently (every 30s) - no timeout needed.

    Returns:
        dict: Status with counts of created_tasks, orphaned, verified
    """
    logger = logging.getLogger(__name__)

    created_tasks = 0
    orphaned_count = 0
    verified_count = 0

    # PENDING: Create tasks if missing
    pending_files = ProjectFile.objects.filter(
        download_status=ProjectFile.DownloadStatus.PENDING,
        is_active=True,
    )

    for project_file in pending_files:
        if not project_file.download_task_id:
            # Create task and transition to QUEUED
            task = download_project_file.delay(project_file.project.id)
            project_file.download_task_id = task.id
            project_file.download_status = ProjectFile.DownloadStatus.QUEUED
            project_file.save(update_fields=["download_task_id", "download_status"])
            created_tasks += 1
            logger.info("Created task for pending file %s", project_file.id)
        else:
            # Has task - should be QUEUED
            project_file.download_status = ProjectFile.DownloadStatus.QUEUED
            project_file.save(update_fields=["download_status"])

    # QUEUED: Verify task in Celery queue
    queued_files = ProjectFile.objects.filter(
        download_status=ProjectFile.DownloadStatus.QUEUED,
        is_active=True,
    ).exclude(download_task_id="")

    for project_file in queued_files:
        if is_task_queued(project_file):
            verified_count += 1
        else:
            error_msg = "Task not found in Celery queue (worker may be down)"
            logger.warning("Orphaned queued file %s", project_file.id)
            project_file.mark_download_failed(error_msg)
            orphaned_count += 1

    # DOWNLOADING: Verify task executing AND PID exists
    downloading_files = ProjectFile.objects.filter(
        download_status=ProjectFile.DownloadStatus.DOWNLOADING,
        is_active=True,
    ).exclude(download_task_id="")

    for project_file in downloading_files:
        if is_task_actively_running(project_file):
            verified_count += 1
        else:
            error_msg = "Task not running (worker crashed or task failed)"
            logger.warning("Orphaned downloading file %s", project_file.id)
            project_file.mark_download_failed(error_msg)
            orphaned_count += 1

    logger.info(
        "State check: %d created, %d orphaned, %d verified",
        created_tasks,
        orphaned_count,
        verified_count,
    )

    return {
        "status": "completed",
        "created_tasks": created_tasks,
        "orphaned": orphaned_count,
        "verified": verified_count,
    }


@shared_task
def update_project_status(project_id, new_status):
    """
    Update a project's status.

    Args:
        project_id: UUID of the project
        new_status: New status to set

    Returns:
        dict: Result data
    """
    try:
        project = Project.objects.get(id=project_id)
        old_status = project.status
        project.status = new_status
        project.save()

        return {
            "status": "completed",
            "project_id": str(project_id),
            "old_status": old_status,
            "new_status": new_status,
        }

    except Project.DoesNotExist:
        return {
            "status": "error",
            "message": f"Project with id {project_id} not found",
        }


@shared_task
def scan_and_queue_manufacturability_checks():
    """Scan for files ready for manufacturability checking and queue checks.

    This periodic task finds ProjectFiles that are:
    - Download completed (has a COMPLETED download attempt)
    - Hash verified (hash_verified=True)
    - Either no ManufacturabilityCheck exists, OR check status is FAILED and retryable

    Respects global concurrent limit (PRECHECK_CONCURRENT_LIMIT setting).

    Returns:
        dict: Status with counts of queued_checks, skipped (at limit), already_running
    """
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("SCANNING FOR FILES READY FOR MANUFACTURABILITY CHECKING")
    logger.info("=" * 60)

    queued_checks = 0
    skipped_at_limit = 0
    already_running = 0

    # Get concurrent limit from settings
    concurrent_limit = getattr(settings, "PRECHECK_CONCURRENT_LIMIT", 4)

    # Count currently active checks (QUEUED or PROCESSING)
    active_count = ManufacturabilityCheck.objects.filter(
        status__in=[
            ManufacturabilityCheck.Status.QUEUED,
            ManufacturabilityCheck.Status.PROCESSING,
        ]
    ).count()

    logger.info("  Active checks: %d / %d (limit)", active_count, concurrent_limit)

    if active_count >= concurrent_limit:
        logger.info("  At concurrent limit, skipping scan")
        return {
            "status": "at_limit",
            "active_count": active_count,
            "concurrent_limit": concurrent_limit,
            "queued_checks": 0,
        }

    # Find files ready for checking:
    # 1. Download completed (has COMPLETED attempt)
    # 2. Hash verified
    # 3. Is active file
    ready_files = ProjectFile.objects.filter(
        is_active=True,
        hash_verified=True,
        download_attempts__status=DownloadAttempt.Status.COMPLETED,
    ).distinct()

    file_count = ready_files.count()
    logger.info("  Found %d files with completed verified downloads", file_count)

    for project_file in ready_files:
        # Check if we've hit the concurrent limit
        if active_count >= concurrent_limit:
            skipped_at_limit += 1
            continue

        # Check if a check already exists for this file
        try:
            existing_check = project_file.manufacturability_check
            # Check exists - see if it's running or completed
            if existing_check.status in [
                ManufacturabilityCheck.Status.QUEUED,
                ManufacturabilityCheck.Status.PROCESSING,
            ]:
                already_running += 1
                continue
            if existing_check.status == ManufacturabilityCheck.Status.COMPLETED:
                # Already completed (pass or fail on manufacturing issues)
                continue
            if existing_check.status == ManufacturabilityCheck.Status.FAILED:
                # System failure - check if retryable
                if not existing_check.can_retry():
                    logger.info(
                        "  File %s: check failed, max retries exceeded",
                        project_file.id,
                    )
                    continue
                # Retryable - will be re-queued below
                logger.info(
                    "  File %s: retrying failed check (attempt %d/%d)",
                    project_file.id,
                    existing_check.retry_count + 1,
                    existing_check.max_retries,
                )
        except ManufacturabilityCheck.DoesNotExist:
            # No check exists - this file needs one
            pass

        # Queue the check
        try:
            _queue_manufacturability_check(project_file, logger)
            queued_checks += 1
            active_count += 1
        except Exception:
            logger.exception("Failed to queue check for file %s", project_file.id)

    logger.info("=" * 60)
    logger.info("SCAN COMPLETE")
    logger.info("  Queued: %d", queued_checks)
    logger.info("  Already running: %d", already_running)
    logger.info("  Skipped (at limit): %d", skipped_at_limit)
    logger.info("=" * 60)

    return {
        "status": "completed",
        "queued_checks": queued_checks,
        "already_running": already_running,
        "skipped_at_limit": skipped_at_limit,
    }


def _queue_manufacturability_check(project_file: ProjectFile, logger) -> None:
    """Queue a manufacturability check for a file.

    Creates or updates ManufacturabilityCheck and queues the Celery task.

    Args:
        project_file: The file to check
        logger: Logger instance for output
    """
    # Get or create the check
    check, created = ManufacturabilityCheck.objects.get_or_create(
        project=project_file.project,
        project_file=project_file,
        defaults={"status": ManufacturabilityCheck.Status.QUEUED},
    )

    if not created:
        # Existing check - reset for retry
        check.status = ManufacturabilityCheck.Status.QUEUED
        check.retry_count += 1
        check.is_manufacturable = None
        check.errors = []
        check.warnings = []
        check.error_message = ""
        check.started_at = None
        check.completed_at = None

    check.save()

    # Queue the task
    task = check_project_manufacturability.delay(check.id)
    check.task_id = task.id
    check.save(update_fields=["task_id"])

    logger.info(
        "  Queued check %s for file %s (task: %s)",
        check.id,
        project_file.id,
        task.id,
    )
