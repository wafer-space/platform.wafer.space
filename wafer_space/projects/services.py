"""Business logic services for project file management.

This service layer prevents circular imports by providing a clean separation:
- Views call services
- Services coordinate models and tasks
- Models remain focused on data representation
- Tasks handle background processing
"""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote
from urllib.parse import urlparse

import magic
from celery.result import AsyncResult
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import ManufacturabilityCheck
from .models import Project
from .models import ProjectFile
from .security import SecurityValidationError
from .security import URLValidator
from .tasks import check_project_manufacturability
from .tasks import download_project_file
from .url_handlers import GitHubArtifactHandler
from .url_handlers import GoogleSourceHandler
from .url_handlers import URLHandlerRegistry
from .url_rewriters import URLRewriter

# Valid GDS/OASIS file formats
VALID_GDS_FORMATS = {".gds", ".gdsii", ".gds2"}
VALID_OASIS_FORMATS = {".oas", ".oasis"}
VALID_COMPRESSION_FORMATS = {".gz", ".zip", ".bz2", ".xz"}
VALID_BASE_FORMATS = VALID_GDS_FORMATS | VALID_OASIS_FORMATS
VALID_ALL_FORMATS = VALID_BASE_FORMATS | VALID_COMPRESSION_FORMATS

# Initialize URL handler registry with known handlers
_url_handler_registry = URLHandlerRegistry()
_url_handler_registry.register(GoogleSourceHandler())
_url_handler_registry.register(GitHubArtifactHandler())


def _extract_filename_from_content_disposition(content_disposition: str) -> str | None:
    """Extract filename from Content-Disposition header.

    Args:
        content_disposition: Content-Disposition header value

    Returns:
        Extracted filename or None if not found
    """
    if not content_disposition:
        return None

    # Try filename*=UTF-8'' format first (RFC 5987)
    utf8_match = re.search(r"filename\*=UTF-8''(.+?)(?:;|$)", content_disposition)
    if utf8_match:
        return unquote(utf8_match.group(1))

    # Try regular filename= format
    filename_match = re.search(r'filename="?([^";\r\n]+)"?', content_disposition)
    if filename_match:
        return filename_match.group(1).strip('"')

    return None


def _extract_filename_from_url(
    url: str,
    *,
    content_disposition: str | None = None,
) -> str:
    """Extract filename from URL, Content-Disposition header, or query parameters.

    Args:
        url: The URL to extract filename from
        content_disposition: Optional Content-Disposition header value

    Returns:
        Extracted filename (may be a default like "download.zip")
    """
    # Try Content-Disposition header first
    if content_disposition:
        filename = _extract_filename_from_content_disposition(content_disposition)
        if filename:
            return filename

    # Parse URL
    parsed = urlparse(url)

    # Try to extract from URL path
    path_parts = parsed.path.rstrip("/").split("/")
    if path_parts:
        filename = path_parts[-1]
        # Only use path filename if it has a file extension
        if filename and filename != "download" and "." in filename:
            return unquote(filename)

    # No filename found - return generic default
    # This will fail validation, which is appropriate
    return "download"


def detect_file_type_from_data(data: bytes) -> tuple[str, str]:
    """Detect file type from actual file data using MIME type detection.

    Args:
        data: File data bytes (at least first 1MB recommended)

    Returns:
        tuple: (mime_type, file_extension)
            - mime_type: Detected MIME type (e.g., "application/gzip")
            - file_extension: Appropriate file extension (e.g., ".gds.gz")

    Raises:
        ValueError: If file type is not a valid GDS/OASIS file
    """
    # Detect MIME type from data
    mime = magic.Magic(mime=True)
    mime_type = mime.from_buffer(data)

    # Map MIME types to file extensions
    # GDS/OASIS files are binary formats, often detected as generic binary
    mime_to_extension = {
        # Compressed formats
        "application/gzip": ".gds.gz",  # Assume GDS compressed with gzip
        "application/x-gzip": ".gds.gz",
        "application/zip": ".gds.zip",
        "application/x-zip-compressed": ".gds.zip",
        "application/x-bzip2": ".gds.bz2",
        "application/x-xz": ".gds.xz",
        # Uncompressed - these are tricky as GDS/OASIS have no standard MIME type
        "application/octet-stream": ".gds",  # Generic binary, assume GDS
        "application/x-gds": ".gds",  # Non-standard but sometimes used
        "application/x-oasis": ".oas",
    }

    if mime_type not in mime_to_extension:
        msg = (
            f"Unsupported file type: {mime_type}. "
            f"Only GDS/OASIS files are accepted. "
            f"Supported MIME types: {', '.join(sorted(mime_to_extension.keys()))}"
        )
        raise ValueError(msg)

    extension = mime_to_extension[mime_type]
    return mime_type, extension


def _validate_filename_format(filename: str) -> None:
    """Validate that filename has a GDS or OASIS format.

    Valid formats:
    - GDS: .gds, .gdsii, .gds2
    - OASIS: .oas, .oasis
    - Compressed: .gds.gz, .gds.zip, .oas.bz2, etc.

    Args:
        filename: The filename to validate

    Raises:
        ValueError: If filename doesn't have a valid GDS/OASIS format
    """
    path = Path(filename.lower())

    # Get all suffixes (e.g., ['.gds', '.gz'] for 'file.gds.gz')
    suffixes = path.suffixes

    if not suffixes:
        compression_str = ", ".join(sorted(VALID_COMPRESSION_FORMATS))
        msg = (
            f"Invalid file format: '{filename}'. "
            f"Only GDS/OASIS files are accepted. "
            f"Valid formats: {', '.join(sorted(VALID_BASE_FORMATS))} "
            f"(optionally compressed with {compression_str})"
        )
        raise ValueError(msg)

    # Check if last suffix is compression
    min_suffixes_for_compressed_file = 2  # e.g., .gds.gz needs both suffixes
    last_suffix = suffixes[-1]
    if last_suffix in VALID_COMPRESSION_FORMATS:
        # Compressed file - check if there's a base format before compression
        if len(suffixes) < min_suffixes_for_compressed_file:
            msg = (
                f"Invalid file format: '{filename}'. "
                f"Compressed files must have a GDS/OASIS extension before compression. "
                f"Valid formats: file.gds.gz, file.oas.zip, etc."
            )
            raise ValueError(msg)

        # Check the extension before compression
        base_suffix = suffixes[-2]
        if base_suffix not in VALID_BASE_FORMATS:
            compression_str = ", ".join(sorted(VALID_COMPRESSION_FORMATS))
            msg = (
                f"Invalid file format: '{filename}'. "
                f"File must be GDS/OASIS format. "
                f"Valid formats: {', '.join(sorted(VALID_BASE_FORMATS))} "
                f"(optionally compressed with {compression_str})"
            )
            raise ValueError(msg)
    elif last_suffix in VALID_BASE_FORMATS:
        # Uncompressed GDS/OASIS file - valid
        pass
    else:
        # Invalid format
        compression_str = ", ".join(sorted(VALID_COMPRESSION_FORMATS))
        msg = (
            f"Invalid file format: '{filename}'. "
            f"Only GDS/OASIS files are accepted. "
            f"Valid formats: {', '.join(sorted(VALID_BASE_FORMATS))} "
            f"(optionally compressed with {compression_str})"
        )
        raise ValueError(msg)


@dataclass
class FileCreationData:
    """Data required to create a ProjectFile record."""

    original_url: str
    source_url: str
    expected_hash_md5: str
    expected_hash_sha1: str
    expected_hash_sha256: str
    file_size: int
    content_type: str


class ProjectFileService:
    """Service for handling project file operations."""

    @classmethod
    def submit_file_from_url(
        cls,
        project: Project,
        url: str,
        *,
        expected_hash_md5: str = "",
        expected_hash_sha1: str = "",
        expected_hash_sha256: str = "",
    ) -> tuple[ProjectFile, dict[str, bool | str | int | None]]:
        """Submit a file URL for download with validation and rewriting.

        This is the main entry point for URL-based file submission. It:
        1. Rewrites URLs for common hosting platforms
        2. Applies URL handlers for special processing (e.g., Google Source)
        3. Validates URL security (SSRF prevention)
        4. Checks file size and accessibility
        5. Replaces existing active file if needed
        6. Creates ProjectFile record with handler metadata
        7. Starts background download task

        Args:
            project: The project to associate the file with
            url: The URL submitted by the user
            expected_hash_md5: Optional MD5 hash for verification
            expected_hash_sha1: Optional SHA1 hash for verification
            expected_hash_sha256: Optional SHA256 hash for verification

        Returns:
            tuple: (ProjectFile instance, metadata dict)
                metadata contains:
                - url_rewritten: bool - Whether URL was rewritten
                - rewrite_reason: str - Explanation of URL rewriting
                - handler_used: str | None - Name of URL handler used
                - file_size: int - File size in bytes
                - content_type: str - Content type from server
                - supports_range: bool - Whether resume is supported

        Raises:
            SecurityValidationError: If URL validation fails
            ValueError: If URL is invalid or missing
        """
        if not url or not url.strip():
            msg = "URL is required"
            raise ValueError(msg)

        url = url.strip()

        # Step 1: Rewrite URL for common hosting platforms
        rewritten_url, was_rewritten, rewrite_reason = URLRewriter.rewrite_url(url)

        # Step 2: Check for URL handler (e.g., Google Source)
        handler = _url_handler_registry.get_handler(rewritten_url)
        handler_metadata = {}
        handler_name = None

        if handler:
            # Apply handler pre-processing
            handler_result = handler.process_url(rewritten_url)
            rewritten_url = handler_result["url"]
            handler_metadata = handler_result["metadata"]
            handler_name = handler_metadata.get("handler")

        # Step 3: Validate URL security and get metadata
        # Skip validation for URLs requiring authentication (e.g., GitHub artifacts)
        # These will be validated during actual download with credentials
        if handler_metadata.get("requires_github_auth"):
            # GitHub artifacts require authentication - cannot validate without token
            # Validation will happen during download task with proper credentials
            validation_result: dict[str, int | str | bool | None] = {
                "file_size": 0,  # Unknown until download
                "content_type": None,
                "content_disposition": None,
                "etag": None,
                "supports_range": False,
            }
        else:
            # For URLs with handlers (like Google Source), allow missing Content-Length
            # because the handler transforms the content (e.g., base64 decode)
            allow_missing_length = handler is not None
            try:
                validation_result = URLValidator.validate_url(
                    rewritten_url,
                    allow_missing_content_length=allow_missing_length,
                )
            except SecurityValidationError as e:
                # Re-raise with better context
                msg = f"URL validation failed: {e}"
                raise SecurityValidationError(msg) from e

        # Step 4: Extract filename (validated from file content later)
        content_disposition = validation_result.get("content_disposition")
        # Ensure content_disposition is str | None (not int)
        if isinstance(content_disposition, int):
            content_disposition = None
        filename = _extract_filename_from_url(
            rewritten_url,
            content_disposition=content_disposition,
        )

        # Step 5: Handle file replacement if needed
        cls._handle_file_replacement(project)

        # Step 6: Create ProjectFile record with handler metadata
        file_size = validation_result["file_size"]
        content_type = validation_result.get("content_type", "")

        # Ensure types are correct for FileCreationData
        if not isinstance(file_size, int):
            file_size = 0
        if not isinstance(content_type, str):
            content_type = ""

        file_data = FileCreationData(
            original_url=url,
            source_url=rewritten_url,
            expected_hash_md5=expected_hash_md5,
            expected_hash_sha1=expected_hash_sha1,
            expected_hash_sha256=expected_hash_sha256,
            file_size=file_size,
            content_type=content_type,
        )
        project_file = cls._create_project_file(
            project=project,
            file_data=file_data,
            filename=filename,
            handler_metadata=handler_metadata,
        )

        # Step 7: Start download task
        cls._start_download_task(project_file)

        # Return file and metadata
        metadata = {
            "url_rewritten": was_rewritten,
            "rewrite_reason": rewrite_reason,
            "handler_used": handler_name,
            "file_size": validation_result["file_size"],
            "content_type": validation_result.get("content_type"),
            "supports_range": validation_result.get("supports_range", False),
        }

        return project_file, metadata

    @classmethod
    @transaction.atomic
    def _handle_file_replacement(cls, project: Project) -> None:
        """Mark existing active file as inactive before creating new one.

        Args:
            project: The project to check for active files
        """
        # Get the currently active file (if any)
        active_file = ProjectFile.objects.filter(
            project=project,
            is_active=True,
        ).first()

        if active_file:
            # Mark as inactive (the new file will be marked active)
            active_file.is_active = False
            active_file.save(update_fields=["is_active"])

    @classmethod
    @transaction.atomic
    def _create_project_file(
        cls,
        *,
        project: Project,
        file_data: FileCreationData,
        filename: str,
        handler_metadata: dict | None = None,
    ) -> ProjectFile:
        """Create a ProjectFile record.

        Args:
            project: The project to associate the file with
            file_data: File creation data (URLs, hashes, size, content type)
            filename: The extracted and validated filename
            handler_metadata: Optional metadata from URL handler

        Returns:
            ProjectFile: The created file record
        """
        # Create the file record
        # Note: download_status will be PENDING (no task_id, no attempts)
        return ProjectFile.objects.create(
            project=project,
            original_url=file_data.original_url,
            source_url=file_data.source_url,
            expected_hash_md5=file_data.expected_hash_md5.strip().lower(),
            expected_hash_sha1=file_data.expected_hash_sha1.strip().lower(),
            expected_hash_sha256=file_data.expected_hash_sha256.strip().lower(),
            file_size=file_data.file_size,
            content_type=file_data.content_type,
            original_filename=filename,
            handler_metadata=handler_metadata or {},
            is_active=True,  # New file is active
            file_type=ProjectFile.FileType.DESIGN,
        )

    @classmethod
    def _start_download_task(cls, project_file: ProjectFile) -> str:
        """Start background download task.

        Args:
            project_file: The file to download

        Returns:
            str: The Celery task ID
        """
        # Start the download task
        task = download_project_file.delay(str(project_file.project.id))

        # Store task ID (status will become QUEUED automatically)
        project_file.download_task_id = task.id
        project_file.save(update_fields=["download_task_id"])

        return task.id

    @classmethod
    def _handle_pending_started_state(
        cls,
        task: AsyncResult,
        project_file: ProjectFile,
    ) -> dict[str, str | int | float]:
        """Handle PENDING or STARTED task state."""
        status = "pending" if task.state == "PENDING" else "downloading"
        message = "Download pending" if task.state == "PENDING" else "Download starting"
        return {
            "status": status,
            "progress": 0,
            "current": 0,
            "total": project_file.file_size or 0,
            "message": message,
        }

    @classmethod
    def _handle_progress_state(
        cls,
        task: AsyncResult,
        project_file: ProjectFile,
    ) -> dict[str, str | int | float]:
        """Handle PROGRESS task state."""
        meta = task.info or {}
        return {
            "status": "downloading",
            "progress": meta.get("progress", 0),
            "current": meta.get("current", 0),
            "total": meta.get("total", project_file.file_size or 0),
            "message": meta.get("message", "Downloading"),
        }

    @classmethod
    def _handle_success_state(
        cls,
        task: AsyncResult,
        project_file: ProjectFile,
    ) -> dict[str, str | int | float]:
        """Handle SUCCESS task state."""
        return {
            "status": "completed",
            "progress": 100,
            "current": project_file.file_size or 0,
            "total": project_file.file_size or 0,
            "message": "Download completed",
        }

    @classmethod
    def _handle_failure_state(
        cls,
        task: AsyncResult,
        project_file: ProjectFile,
    ) -> dict[str, str | int | float]:
        """Handle FAILURE task state."""
        return {
            "status": "failed",
            "progress": 0,
            "current": 0,
            "total": project_file.file_size or 0,
            "message": str(task.info) if task.info else "Download failed",
        }

    @classmethod
    def _handle_retry_state(
        cls,
        task: AsyncResult,
        project_file: ProjectFile,
    ) -> dict[str, str | int | float]:
        """Handle RETRY task state."""
        return {
            "status": "retrying",
            "progress": 0,
            "current": 0,
            "total": project_file.file_size or 0,
            "message": "Download retrying after error...",
        }

    @classmethod
    def _handle_unknown_state(
        cls,
        task: AsyncResult,
        project_file: ProjectFile,
    ) -> dict[str, str | int | float]:
        """Handle unknown task state."""
        return {
            "status": "unknown",
            "progress": 0,
            "current": 0,
            "total": project_file.file_size or 0,
            "message": f"Unknown state: {task.state}",
        }

    @classmethod
    def get_download_progress(
        cls,
        project_file: ProjectFile,
    ) -> dict[str, str | int | float]:
        """Get current download progress from Celery task state.

        Args:
            project_file: The file being downloaded

        Returns:
            dict: Progress information containing:
                - status: Download status (pending, downloading, completed, failed)
                - progress: Progress percentage (0-100)
                - current: Bytes downloaded
                - total: Total file size in bytes
                - message: Status message
        """
        if not project_file.download_task_id:
            return {
                "status": project_file.download_status,
                "progress": 0,
                "current": 0,
                "total": project_file.file_size or 0,
                "message": "Download not started",
            }

        task = AsyncResult(project_file.download_task_id)

        # Dispatch to appropriate handler based on task state
        state_handlers = {
            "PENDING": cls._handle_pending_started_state,
            "STARTED": cls._handle_pending_started_state,
            "PROGRESS": cls._handle_progress_state,
            "SUCCESS": cls._handle_success_state,
            "FAILURE": cls._handle_failure_state,
            "RETRY": cls._handle_retry_state,
        }

        handler = state_handlers.get(task.state, cls._handle_unknown_state)
        return handler(task, project_file)


class ManufacturabilityService:
    """Service for handling manufacturability check operations."""

    @classmethod
    def queue_check(
        cls, project: Project, project_file: "ProjectFile"
    ) -> ManufacturabilityCheck:
        """Queue a manufacturability check for a specific project file.

        Creates or gets an existing check for the file, sets status to QUEUED,
        and triggers the Celery task for processing.

        Thread-safe: Uses database transaction to ensure per-user
        concurrency limits are enforced atomically.

        Args:
            project: The project to check
            project_file: The specific file to check (required)

        Returns:
            ManufacturabilityCheck instance

        Raises:
            ValidationError: If user already has a check running
        """
        with transaction.atomic():
            # Get or create the check FIRST (within transaction)
            # Each check is tied to a specific project_file
            check, created = ManufacturabilityCheck.objects.get_or_create(
                project=project,
                project_file=project_file,
                defaults={"status": ManufacturabilityCheck.Status.QUEUED},
            )

            # If already queued/processing, return immediately (idempotent)
            if not created and check.status in [
                ManufacturabilityCheck.Status.QUEUED,
                ManufacturabilityCheck.Status.PROCESSING,
            ]:
                return check

            # NOW check per-user limit (excluding THIS project's check)
            # Lock the user's OTHER active checks to prevent race conditions
            active_checks_qs = ManufacturabilityCheck.objects.select_for_update()
            active_user_checks = (
                active_checks_qs.filter(
                    project__user=project.user,
                    status__in=[
                        ManufacturabilityCheck.Status.QUEUED,
                        ManufacturabilityCheck.Status.PROCESSING,
                    ],
                )
                .exclude(id=check.id)
                .count()
            )  # Exclude THIS check

            per_user_limit = getattr(settings, "PRECHECK_PER_USER_LIMIT", 1)
            if active_user_checks >= per_user_limit:
                # If we just created this check, delete it before raising
                if created:
                    check.delete()
                msg = (
                    f"You already have {active_user_checks} check(s) running. "
                    "Please wait for them to complete before starting a new check."
                )
                raise ValidationError(msg)

            # Reset for new run (including ALL fields)
            check.status = ManufacturabilityCheck.Status.QUEUED
            check.is_manufacturable = None  # Reset manufacturability
            check.errors = []
            check.warnings = []
            check.processing_logs = ""
            check.retry_count = 0  # Reset retry count
            check.save()

            # Queue task
            task = check_project_manufacturability.delay(check.id)
            check.task_id = task.id
            check.save(update_fields=["task_id"])

            return check

    @classmethod
    def get_check_status_for_file(cls, project_file: "ProjectFile") -> dict | None:
        """Get check status information for a specific file.

        Args:
            project_file: The project file to get check status for

        Returns:
            dict with check status information, or None if no check exists.
        """
        try:
            check = project_file.manufacturability_check
        except ManufacturabilityCheck.DoesNotExist:
            return None
        else:
            return {
                "status": check.status,
                "is_manufacturable": check.is_manufacturable,
                "errors": check.errors,
                "warnings": check.warnings,
                "started_at": check.started_at,
                "completed_at": check.completed_at,
            }

    @classmethod
    def get_check_status(cls, project: Project) -> dict | None:
        """Get check status for the project's active file.

        Args:
            project: The project to get check status for

        Returns:
            dict with check status information, or None if no active file
            or no check exists for the active file.
        """
        active_file = project.files.filter(is_active=True).first()
        if not active_file:
            return None

        return cls.get_check_status_for_file(active_file)
