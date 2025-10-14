"""
Background tasks for project processing.
"""

import contextlib
import hashlib
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request
from urllib.request import urlopen

import requests
from celery import shared_task
from django.core.files.base import ContentFile
from django.core.files.base import File
from django.utils import timezone
from django_celery_results.models import TaskResult

from .models import ManufacturabilityCheck
from .models import Project
from .models import ProjectFile

# HTTP status codes
HTTP_PARTIAL_CONTENT = 206  # Server supports range requests


# Helper functions for file download
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
def check_project_manufacturability(self, check_id):
    """
    Background task to check project manufacturability.

    Args:
        check_id: The ID of the ManufacturabilityCheck instance

    Returns:
        dict: Result data with status and details
    """
    try:
        # Get the manufacturability check instance
        check = ManufacturabilityCheck.objects.get(id=check_id)
        check.task_id = self.request.id
        check.start_processing()

        # Simulate manufacturability checking process
        # In a real implementation, this would:
        # 1. Parse design files
        # 2. Run DRC (Design Rule Check)
        # 3. Validate against manufacturing constraints
        # 4. Generate reports

        project = check.project
        errors = []
        warnings = []
        logs = f"Starting manufacturability check for project: {project.name}\n"

        # Simulate processing time
        time.sleep(2)

        # Basic validation checks (placeholder logic)
        logs += "Checking design files...\n"

        if not project.files.exists():
            errors.append("No design files uploaded")
            logs += "ERROR: No design files found\n"
        else:
            file_count = project.files.count()
            logs += f"Found {file_count} design file(s)\n"

            # Check file verification
            unverified_files = project.files.filter(hash_verified=False)
            if unverified_files.exists():
                warnings.append(
                    f"{unverified_files.count()} files have unverified hashes",
                )
                count = unverified_files.count()
                logs += f"WARNING: {count} files with unverified hashes\n"

        # Simulate additional checks
        logs += "Running design rule checks...\n"
        time.sleep(1)

        logs += "Validating manufacturing constraints...\n"
        time.sleep(1)

        # Determine if manufacturable (simplified logic)
        is_manufacturable = len(errors) == 0

        if is_manufacturable:
            logs += "SUCCESS: Project passed all manufacturability checks\n"
        else:
            logs += f"FAILED: Project failed with {len(errors)} errors\n"

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
        return {
            "status": "error",
            "message": f"ManufacturabilityCheck with id {check_id} not found",
        }

    except Exception as exc:
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


def _download_with_progress(
    task,
    project_file,
    temp_path: Path,
    *,
    chunk_size: int = 1024 * 1024,  # 1MB chunks
) -> tuple[str, str]:
    """Download file with progress tracking and resume capability.

    Args:
        task: The Celery task instance (for progress updates)
        project_file: The ProjectFile instance
        temp_path: Path to temporary file for download
        chunk_size: Size of download chunks in bytes

    Returns:
        tuple: (md5_hash, sha1_hash) of downloaded content
    """
    url = project_file.source_url
    headers = {"User-Agent": "wafer.space/1.0"}

    # Check if we're resuming a partial download
    resume_byte_pos = 0
    if temp_path.exists():
        resume_byte_pos = temp_path.stat().st_size
        headers["Range"] = f"bytes={resume_byte_pos}-"

    # Start download
    response = requests.get(url, headers=headers, stream=True, timeout=30)

    # Check if server supports resume
    if resume_byte_pos > 0 and response.status_code != HTTP_PARTIAL_CONTENT:
        # Server doesn't support resume, start from beginning
        resume_byte_pos = 0
        temp_path.unlink(missing_ok=True)
        response = requests.get(url, headers=headers, stream=True, timeout=30)

    response.raise_for_status()

    # Get total file size
    total_size = project_file.file_size or 0
    if "Content-Length" in response.headers:
        content_length = int(response.headers["Content-Length"])
        if resume_byte_pos > 0:
            total_size = resume_byte_pos + content_length
        else:
            total_size = content_length

    # Initialize hash calculators
    md5_hasher = hashlib.md5(usedforsecurity=False)
    sha1_hasher = hashlib.sha1(usedforsecurity=False)

    # If resuming, read existing content for hash calculation
    if resume_byte_pos > 0:
        with temp_path.open("rb") as existing_file:
            existing_content = existing_file.read()
            md5_hasher.update(existing_content)
            sha1_hasher.update(existing_content)

    # Download with progress updates
    downloaded = resume_byte_pos
    last_db_update_progress = 0
    mode = "ab" if resume_byte_pos > 0 else "wb"

    with temp_path.open(mode) as temp_file:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:  # filter out keep-alive chunks
                temp_file.write(chunk)
                md5_hasher.update(chunk)
                sha1_hasher.update(chunk)
                downloaded += len(chunk)

                # Update progress in Celery task state (every chunk)
                progress = int((downloaded / total_size) * 100) if total_size > 0 else 0
                task.update_state(
                    state="PROGRESS",
                    meta={
                        "current": downloaded,
                        "total": total_size,
                        "progress": progress,
                        "message": f"Downloaded {downloaded:,} of {total_size:,} bytes",
                    },
                )

                # Update database every 5% progress
                if progress >= last_db_update_progress + 5:
                    project_file.last_activity = timezone.now()
                    project_file.save(update_fields=["last_activity"])
                    last_db_update_progress = progress

    return md5_hasher.hexdigest(), sha1_hasher.hexdigest()


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
    project_file.download_status = ProjectFile.DownloadStatus.DOWNLOADING
    project_file.download_started_at = timezone.now()
    project_file.last_activity = timezone.now()
    project_file.save(
        update_fields=[
            "download_status",
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
            project_file.mark_download_failed(f"Max retries reached: {exc!s}")
    except Project.DoesNotExist:
        pass

    if temp_path and temp_path.exists():
        with contextlib.suppress(OSError):
            temp_path.unlink()

    return {
        "status": "failed",
        "message": str(exc),
    }


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def download_project_file(self, project_id):
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
    temp_path = None

    try:
        # Get and validate project file
        _project, project_file = _get_project_file_for_download(project_id)

        if not project_file:
            return {
                "status": "error",
                "message": f"No active file found for project {project_id}",
            }

        if not project_file.source_url:
            return {
                "status": "error",
                "message": "No source URL provided for file download",
            }

        # Initialize download
        _initialize_download(project_file)

        # Set up temporary directory and file path
        temp_dir = _setup_temp_directory()
        temp_filename = f"{project_file.id}_{project_file.original_filename}"
        temp_path = temp_dir / temp_filename

        # Download with progress tracking
        md5_hash, sha1_hash = _download_with_progress(
            self,
            project_file,
            temp_path,
        )

        # Save to Django file field
        with temp_path.open("rb") as temp_file:
            django_file = File(
                temp_file,
                name=project_file.original_filename,
            )
            project_file.file.save(
                project_file.original_filename,
                django_file,
                save=False,
            )

        # Set file size and hashes
        project_file.file_size = temp_path.stat().st_size
        project_file.hash_md5 = md5_hash
        project_file.hash_sha1 = sha1_hash

        # Verify hashes
        hash_verified, verification_errors = _verify_file_hashes(
            project_file,
            md5_hash,
            sha1_hash,
        )
        project_file.hash_verified = hash_verified
        project_file.mark_download_complete()

        # Clean up temp file
        with contextlib.suppress(OSError):
            temp_path.unlink()

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
        return {
            "status": "error",
            "message": f"Project with id {project_id} not found",
        }

    except (OSError, ValueError, requests.RequestException) as exc:
        if self.request.retries < self.max_retries:
            _handle_download_retry(self, project_id, exc)
        else:
            return _handle_download_failure(project_id, exc, temp_path)


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
