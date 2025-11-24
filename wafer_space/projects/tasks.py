"""
Background tasks for project processing.
"""

import contextlib
import hashlib
import logging
import os
import random
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

import requests
from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone
from django_celery_results.models import TaskResult

from wafer_space.notifications.services import NotificationService

from .models import DownloadAttempt
from .models import FileProcessingError
from .models import ManufacturabilityCheck
from .models import Project
from .models import ProjectFile
from .models import ProjectFileChunk
from .url_handlers import GitHubArtifactHandler
from .url_handlers import GoogleSourceHandler
from .url_handlers import URLHandlerRegistry
from .verification import is_task_actively_running
from .verification import is_task_queued

# Mock manufacturability check constants
MOCK_PROCESSING_TIME_MIN = 2.0
MOCK_PROCESSING_TIME_MAX = 5.0
MOCK_SUCCESS_RATE = 0.8  # 80% success rate for testing

# HTTP status codes
HTTP_PARTIAL_CONTENT = 206  # Server supports range requests

# Byte conversion constants
BYTES_PER_KILOBYTE = 1024

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


def _setup_temp_directory() -> Path:
    """Create and return temporary directory for downloads."""
    temp_dir = Path(tempfile.gettempdir()) / "wafer_space_downloads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def _extract_filename_from_url(url: str) -> str:
    """Extract filename from URL or return default."""
    parsed_url = urlparse(url)
    return Path(parsed_url.path).name or "downloaded_file"


def _calculate_file_hashes(content: bytes) -> tuple[str, str]:
    """Calculate MD5 and SHA1 hashes for file content.

    Note: MD5 and SHA1 are used here for file integrity verification only,
    not for cryptographic security purposes. These match industry standard
    hash algorithms commonly used for file verification in manufacturing.
    """
    md5_hash = hashlib.md5(content, usedforsecurity=False).hexdigest()
    sha1_hash = hashlib.sha1(content, usedforsecurity=False).hexdigest()
    return md5_hash, sha1_hash


def _verify_file_hashes(
    project_file,
    md5_hash: str,
    sha1_hash: str,
) -> tuple[bool, list[str]]:
    """Verify file hashes against expected values."""
    verified = True
    errors = []

    if project_file.expected_hash_md5:
        if md5_hash.lower() != project_file.expected_hash_md5.lower():
            verified = False
            errors.append(
                f"MD5 mismatch: expected {project_file.expected_hash_md5}, "
                f"got {md5_hash}",
            )

    if project_file.expected_hash_sha1:
        if sha1_hash.lower() != project_file.expected_hash_sha1.lower():
            verified = False
            errors.append(
                f"SHA1 mismatch: expected {project_file.expected_hash_sha1}, "
                f"got {sha1_hash}",
            )

    return verified, errors


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_project_manufacturability(self, check_id):  # noqa: PLR0915
    """Background task to check project manufacturability.

    This task performs manufacturability analysis on a project's design files.
    Currently uses mock implementation - will be replaced with real GDS/OASIS
    analysis tools in the future.

    Args:
        check_id: The ID of the ManufacturabilityCheck instance

    Returns:
        dict: Result data with status and details
    """
    logger = logging.getLogger(__name__)

    try:
        # Get the manufacturability check instance
        check = ManufacturabilityCheck.objects.get(id=check_id)
        check.task_id = self.request.id or "test-task"  # Handle test environment
        check.save(update_fields=["task_id"])  # Save task_id first
        check.start_processing()

        project = check.project
        errors = []
        warnings = []
        logs = f"Starting manufacturability check for project: {project.name}\n"

        logger.info("Starting manufacturability check for project %s", project.id)

        # TODO: Replace with real GDS/OASIS analysis
        # Simulate processing time (2-5 seconds)
        processing_time = random.uniform(  # noqa: S311
            MOCK_PROCESSING_TIME_MIN,
            MOCK_PROCESSING_TIME_MAX,
        )
        logs += f"Processing design files (simulated {processing_time:.1f}s)...\n"
        time.sleep(processing_time)

        # Mock implementation: 80% success rate for testing
        is_manufacturable = random.random() < MOCK_SUCCESS_RATE  # noqa: S311

        if is_manufacturable:
            # Success case - add sample warning
            warnings.append("Sample warning: Design uses non-standard layer")
            logs += "Design rule checks: PASSED\n"
            logs += "Manufacturing constraints: PASSED\n"
            logs += "Layer validation: PASSED (with warnings)\n"
            logs += "SUCCESS: Project is manufacturable\n"

            logger.info(
                "Manufacturability check completed: %s - MANUFACTURABLE",
                project.id,
            )
        else:
            # Failure case - add sample errors
            error_msg = (
                "Sample error: Minimum feature size violated "
                "(found 45nm, minimum is 50nm)"
            )
            errors.append(error_msg)
            errors.append("Sample error: Metal layer spacing below minimum threshold")
            warnings.append("Sample warning: High density area may affect yield")
            logs += "Design rule checks: FAILED\n"
            logs += "  - Minimum feature size violation detected\n"
            logs += "  - Metal layer spacing violation detected\n"
            logs += f"FAILED: Project is not manufacturable ({len(errors)} errors)\n"

            logger.warning(
                "Manufacturability check completed: %s - NOT MANUFACTURABLE",
                project.id,
            )

        # Complete the check
        check.complete(
            is_manufacturable=is_manufacturable,
            errors=errors,
            warnings=warnings,
            logs=logs,
        )

        return {
            "status": "completed",
            "is_manufacturable": is_manufacturable,
            "errors": errors,
            "warnings": warnings,
            "project_id": str(project.id),
        }

    except ManufacturabilityCheck.DoesNotExist:
        logger.exception("ManufacturabilityCheck with id %s not found", check_id)
        return {
            "status": "error",
            "message": f"ManufacturabilityCheck with id {check_id} not found",
        }

    except Exception as exc:
        logger.exception("Error in manufacturability check task")

        # Handle task retry logic
        if self.request.retries < self.max_retries:
            # Update check with retry info
            try:
                check = ManufacturabilityCheck.objects.get(id=check_id)
                check.retry_count += 1
                check.processing_logs += f"\nRetry {check.retry_count}: {exc!s}\n"
                check.save()
            except ManufacturabilityCheck.DoesNotExist:
                pass

            # Retry the task
            raise self.retry(exc=exc) from exc

        # Max retries reached, mark as failed
        try:
            check = ManufacturabilityCheck.objects.get(id=check_id)
            check.fail(f"Max retries reached: {exc!s}")
        except ManufacturabilityCheck.DoesNotExist:
            pass

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

        from django.conf import settings  # noqa: PLC0415

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
        project_file.save(update_fields=["handler_metadata"])

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
    chunk_size: int
    start_time: float


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
) -> None:
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
        None - file downloaded to temp_path
    """
    # Prepare request (gets authenticated URL for GitHub artifacts)
    url, headers, resume_byte_pos = _prepare_download_request(project_file, temp_path)

    # Get HTTP response
    response, resume_byte_pos = _get_download_response(
        url, headers, temp_path, resume_byte_pos
    )

    # Log file size information
    total_size = _log_file_size(response, project_file, resume_byte_pos)

    # Download chunks with progress tracking
    download_state = _ChunkDownloadState(
        response=response,
        temp_path=temp_path,
        task=task,
        project_file=project_file,
        attempt=attempt,
        total_size=total_size,
        resume_byte_pos=resume_byte_pos,
        chunk_size=chunk_size,
        start_time=time.time(),
    )
    _download_chunks(download_state)


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

    # Create new attempt (first download or no pending attempt)
    attempt = DownloadAttempt.objects.create(
        project_file=project_file,
        attempt_number=project_file.download_attempts.count() + 1,
        status=DownloadAttempt.Status.DOWNLOADING,
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
                    # Create a new attempt if none exists
                    attempt = DownloadAttempt.objects.create(
                        project_file=project_file,
                        attempt_number=project_file.download_attempts.count() + 1,
                        status=DownloadAttempt.Status.FAILED,
                    )

            # Create structured error log
            FileProcessingError.objects.create(
                download_attempt=attempt,
                error_type=FileProcessingError.ErrorType.DOWNLOAD,
                error_message=f"Download failed: {exc}",
                error_detail={
                    "url": project_file.original_url,
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
) -> tuple[bytes, str, str]:
    """Apply content extraction pipeline to process compressed/archived files.

    Args:
        project_file: The project file being processed
        content: The content to process
        temp_path: Temporary file path for intermediate processing

    Returns:
        tuple: (processed_content, md5_hash, sha1_hash)

    Raises:
        ValueError: If pipeline processing fails or format validation fails
    """
    logger = logging.getLogger(__name__)
    from django.conf import settings  # noqa: PLC0415

    from .content_pipeline import ContentPipeline  # noqa: PLC0415
    from .content_pipeline import cleanup_temp_dir  # noqa: PLC0415
    from .content_pipeline import get_temp_dir_for_file  # noqa: PLC0415
    from .content_processors import _processor_registry  # noqa: PLC0415
    from .format_validators import validate_output_format  # noqa: PLC0415

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
        final_md5, final_sha1 = _calculate_file_hashes(processed_content)
        logger.info("  ✓ MD5: %s", final_md5)
        logger.info("  ✓ SHA1: %s", final_sha1)

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

        return processed_content, final_md5, final_sha1

    finally:
        # Always cleanup temp directory
        cleanup_temp_dir(pipeline_temp_dir)


def _process_and_save_content(
    project_file: ProjectFile,
    attempt: DownloadAttempt,
    downloaded_content: bytes,
    temp_path: Path,
) -> tuple[bytes, str, str]:
    """Process downloaded content and save to Django storage.

    Args:
        project_file: The ProjectFile being processed
        attempt: The DownloadAttempt for error tracking
        downloaded_content: The raw downloaded content
        temp_path: Path to temporary file

    Returns:
        tuple: (processed_content, final_md5_hash, final_sha1_hash)
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
        processed_content, final_md5, final_sha1 = _apply_content_pipeline(
            project_file,
            processed_content,
            temp_path,
        )
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
    project_file.save(update_fields=["file_size", "hash_md5", "hash_sha1"])
    logger.info("  ✓ File size: %s", _format_bytes(project_file.file_size))
    logger.info("  ✓ MD5 hash: %s", final_md5)
    logger.info("  ✓ SHA1 hash: %s", final_sha1)

    return processed_content, final_md5, final_sha1


def _verify_and_notify(
    project_file: ProjectFile,
    md5_hash: str,
    sha1_hash: str,
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
        logger.info("  Actual MD5:   %s", md5_hash)
    if project_file.expected_hash_sha1:
        logger.info("  Expected SHA1: %s", project_file.expected_hash_sha1)
        logger.info("  Actual SHA1:   %s", sha1_hash)

    hash_verified, verification_errors = _verify_file_hashes(
        project_file,
        md5_hash,
        sha1_hash,
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

        # Queue manufacturability check now that hash is verified
        from .services import ManufacturabilityService  # noqa: PLC0415

        logger.info("Step 10: Queueing manufacturability check...")
        ManufacturabilityService.queue_check(project_file.project)
        logger.info("  ✓ Manufacturability check queued")
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
    max_retries=settings.DOWNLOAD_TASK_MAX_RETRIES,
    default_retry_delay=settings.DOWNLOAD_TASK_RETRY_BASE_DELAY_SECONDS,
)
def download_project_file(self, project_id):  # noqa: PLR0915, C901
    """Background task to download a project file from a URL.

    Supports:
    - Chunked downloading for large files (up to 100GB)
    - Resume capability with HTTP Range requests
    - Progress tracking via Celery task state
    - Hash verification (MD5, SHA1)
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

        # Download file (all downloads now use progress tracking)
        logger.info("  Starting chunked download with progress tracking...")
        _download_with_progress(
            self,
            project_file,
            attempt,
            temp_path,
        )
        logger.info("  ✓ Download completed successfully!")

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
        _processed_content, final_md5, final_sha1 = _process_and_save_content(
            project_file,
            attempt,
            downloaded_content,
            temp_path,
        )

        # Verify hashes and create notifications
        logger.info("Step 8: Verifying hashes and creating notifications...")
        hash_verified, verification_errors = _verify_and_notify(
            project_file,
            final_md5,
            final_sha1,
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
                        "url": attempt.project_file.original_url,
                        "error_type": exc.__class__.__name__,
                        "traceback": traceback.format_exc(),
                        "retry_number": retry_num,
                        "retry_delay": retry_delay,
                    },
                )

                # Create a PENDING attempt for the upcoming retry
                # This ensures UI shows "Pending" instead of "Failed" during retry delay
                DownloadAttempt.objects.create(
                    project_file=attempt.project_file,
                    attempt_number=attempt.project_file.download_attempts.count() + 1,
                    status=DownloadAttempt.Status.PENDING,
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


@shared_task
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
        if is_task_queued(project_file):
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
            if is_task_actively_running(project_file):
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
