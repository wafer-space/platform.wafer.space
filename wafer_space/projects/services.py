"""Business logic services for project file management.

This service layer prevents circular imports by providing a clean separation:
- Views call services
- Services coordinate models and tasks
- Models remain focused on data representation
- Tasks handle background processing
"""

from django.db import transaction
from django.utils import timezone

from .models import Project
from .models import ProjectFile
from .security import SecurityValidationError
from .security import URLValidator
from .url_rewriters import URLRewriter


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
    ) -> tuple[ProjectFile, dict[str, bool | str]]:
        """Submit a file URL for download with validation and rewriting.

        This is the main entry point for URL-based file submission. It:
        1. Rewrites URLs for common hosting platforms
        2. Validates URL security (SSRF prevention)
        3. Checks file size and accessibility
        4. Replaces existing active file if needed
        5. Creates ProjectFile record
        6. Starts background download task

        Args:
            project: The project to associate the file with
            url: The URL submitted by the user
            expected_hash_md5: Optional MD5 hash for verification
            expected_hash_sha1: Optional SHA1 hash for verification

        Returns:
            tuple: (ProjectFile instance, metadata dict)
                metadata contains:
                - url_rewritten: bool - Whether URL was rewritten
                - rewrite_reason: str - Explanation of URL rewriting
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

        # Step 2: Validate URL security and get metadata
        try:
            validation_result = URLValidator.validate_url(rewritten_url)
        except SecurityValidationError as e:
            # Re-raise with better context
            msg = f"URL validation failed: {e}"
            raise SecurityValidationError(msg) from e

        # Step 3: Handle file replacement if needed
        cls._handle_file_replacement(project)

        # Step 4: Create ProjectFile record
        project_file = cls._create_project_file(
            project=project,
            original_url=url,
            source_url=rewritten_url,
            expected_hash_md5=expected_hash_md5,
            expected_hash_sha1=expected_hash_sha1,
            file_size=validation_result["file_size"],
            content_type=validation_result.get("content_type", ""),
        )

        # Step 5: Start download task
        cls._start_download_task(project_file)

        # Return file and metadata
        metadata = {
            "url_rewritten": was_rewritten,
            "rewrite_reason": rewrite_reason,
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
        original_url: str,
        source_url: str,
        expected_hash_md5: str,
        expected_hash_sha1: str,
        file_size: int,
        content_type: str,
    ) -> ProjectFile:
        """Create a ProjectFile record.

        Args:
            project: The project to associate the file with
            original_url: The URL submitted by the user
            source_url: The URL after rewriting
            expected_hash_md5: Optional MD5 hash for verification
            expected_hash_sha1: Optional SHA1 hash for verification
            file_size: File size in bytes
            content_type: Content type from server

        Returns:
            ProjectFile: The created file record
        """
        # Extract filename from URL
        from urllib.parse import unquote
        from urllib.parse import urlparse

        parsed = urlparse(source_url)
        filename = parsed.path.split("/")[-1] or "download"
        filename = unquote(filename)

        # Create the file record
        project_file = ProjectFile.objects.create(
            project=project,
            original_url=original_url,
            source_url=source_url,
            expected_hash_md5=expected_hash_md5.strip().lower(),
            expected_hash_sha1=expected_hash_sha1.strip().lower(),
            file_size=file_size,
            content_type=content_type,
            original_filename=filename,
            download_status=ProjectFile.DownloadStatus.PENDING,
            is_active=True,  # New file is active
            file_type=ProjectFile.FileType.DESIGN,
        )

        return project_file

    @classmethod
    def _start_download_task(cls, project_file: ProjectFile) -> str:
        """Start background download task.

        Args:
            project_file: The file to download

        Returns:
            str: The Celery task ID
        """
        from .tasks import download_project_file

        # Start the download task
        task = download_project_file.delay(str(project_file.project.id))

        # Store task ID
        project_file.download_task_id = task.id
        project_file.download_status = ProjectFile.DownloadStatus.PENDING
        project_file.save(update_fields=["download_task_id", "download_status"])

        return task.id

    @classmethod
    def get_download_progress(cls, project_file: ProjectFile) -> dict[str, str | int | float]:
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

        # Import here to avoid circular dependency
        from celery.result import AsyncResult

        task = AsyncResult(project_file.download_task_id)

        if task.state == "PENDING":
            return {
                "status": "pending",
                "progress": 0,
                "current": 0,
                "total": project_file.file_size or 0,
                "message": "Download pending",
            }
        if task.state == "STARTED":
            return {
                "status": "downloading",
                "progress": 0,
                "current": 0,
                "total": project_file.file_size or 0,
                "message": "Download starting",
            }
        if task.state == "PROGRESS":
            # Get progress from task meta
            meta = task.info or {}
            return {
                "status": "downloading",
                "progress": meta.get("progress", 0),
                "current": meta.get("current", 0),
                "total": meta.get("total", project_file.file_size or 0),
                "message": meta.get("message", "Downloading"),
            }
        if task.state == "SUCCESS":
            return {
                "status": "completed",
                "progress": 100,
                "current": project_file.file_size or 0,
                "total": project_file.file_size or 0,
                "message": "Download completed",
            }
        if task.state == "FAILURE":
            return {
                "status": "failed",
                "progress": 0,
                "current": 0,
                "total": project_file.file_size or 0,
                "message": str(task.info) if task.info else "Download failed",
            }

        # Unknown state
        return {
            "status": "unknown",
            "progress": 0,
            "current": 0,
            "total": project_file.file_size or 0,
            "message": f"Unknown state: {task.state}",
        }
