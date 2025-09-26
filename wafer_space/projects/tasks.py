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

from celery import shared_task
from django.core.files.base import ContentFile
from django.utils import timezone
from django_celery_results.models import TaskResult

from .models import ManufacturabilityCheck
from .models import Project
from .models import ProjectFile


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
    project_file, md5_hash: str, sha1_hash: str,
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
            project_file.original_filename, django_file, save=False,
        )

    # Clean up temp file
    with contextlib.suppress(OSError):
        temp_path.unlink()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def download_project_file(self, file_id):
    """
    Background task to download a project file from a URL.

    Args:
        file_id: The ID of the ProjectFile instance

    Returns:
        dict: Result data with status and details
    """
    try:
        # Get the project file instance
        project_file = ProjectFile.objects.get(id=file_id)

        if not project_file.source_url:
            return {
                "status": "error",
                "message": "No source URL provided for file download",
            }

        # Set up filename if not already provided
        if not project_file.original_filename:
            filename = _extract_filename_from_url(project_file.source_url)
            project_file.original_filename = filename
            project_file.save()

        # Set up temporary directory
        temp_dir = _setup_temp_directory()

        # Download file content
        file_content = _download_file_content(project_file)

        # Save to Django file field
        _save_file_to_django(project_file, file_content, temp_dir)

        # Set file size
        project_file.file_size = len(file_content)

        # Calculate and verify file hashes
        md5_hash, sha1_hash = _calculate_file_hashes(file_content)
        project_file.hash_md5 = md5_hash
        project_file.hash_sha1 = sha1_hash

        hash_verified, verification_errors = _verify_file_hashes(
            project_file, md5_hash, sha1_hash,
        )
        project_file.hash_verified = hash_verified
        project_file.mark_download_complete()

        return {
            "status": "completed",
            "file_id": str(file_id),
            "original_filename": project_file.original_filename,
            "file_size": project_file.file_size,
            "hash_verified": hash_verified,
            "verification_errors": verification_errors,
            "md5": project_file.hash_md5,
            "sha1": project_file.hash_sha1,
        }

    except ProjectFile.DoesNotExist:
        return {
            "status": "error",
            "message": f"ProjectFile with id {file_id} not found",
        }

    except (OSError, ValueError) as exc:
        # Handle task retry logic
        if self.request.retries < self.max_retries:
            # Update file with retry info
            try:
                project_file = ProjectFile.objects.get(id=file_id)
                project_file.download_error = (
                    f"Retry {self.request.retries + 1}: {exc!s}"
                )
                project_file.save()
            except ProjectFile.DoesNotExist:
                pass

            # Retry the task
            raise self.retry(exc=exc) from exc
        # Max retries reached, mark as failed
        try:
            project_file = ProjectFile.objects.get(id=file_id)
            project_file.mark_download_failed(f"Max retries reached: {exc!s}")
        except ProjectFile.DoesNotExist:
            pass

        return {
            "status": "failed",
            "message": str(exc),
            "retries": self.request.retries,
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
