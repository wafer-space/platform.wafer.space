import hashlib
import json
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

from wafer_space.projects.exceptions import ConcurrentLimitError
from wafer_space.projects.exceptions import InvalidStateTransitionError
from wafer_space.projects.exceptions import MaxRetriesExceededError


@dataclass
class CheckExecutionContext:
    """Context data for transitioning a check to RUNNING state.

    Groups worker and docker info to avoid too many function parameters.
    """

    celery_worker_pid: int
    celery_worker_hostname: str
    docker_container_id: str
    docker_image: str
    docker_image_digest: str
    docker_command: str


# Byte conversion constant
_BYTES_PER_KB = 1024.0


class Project(models.Model):
    """User-submitted design projects for manufacturing."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        CHECKING = "checking", "Checking Manufacturability"
        MANUFACTURABLE = "manufacturable", "Manufacturable"
        NOT_MANUFACTURABLE = "not_manufacturable", "Not Manufacturable"
        ASSIGNED_TO_SHUTTLE = "assigned", "Assigned to Shuttle"
        IN_PRODUCTION = "production", "In Production"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class SlotSize(models.TextChoices):
        """Available slot sizes for manufacturing.

        Each slot represents a portion of the die area:
        - 1x1: Full slot (3.88mm x 5.07mm = 19.67mm²)
        - 0p5x1: Half width (1.94mm x 5.07mm = 9.84mm²)
        - 1x0p5: Half height (3.88mm x 2.535mm = 9.84mm²)
        - 0p5x0p5: Quarter slot (1.94mm x 2.535mm = 4.92mm²)
        """

        FULL = "1x1", "1×1 - Full Slot (3.88mm × 5.07mm = 19.67mm²)"
        HALF_WIDTH = "0p5x1", "0.5×1 - Half Width (1.94mm × 5.07mm = 9.84mm²)"
        HALF_HEIGHT = "1x0p5", "1×0.5 - Half Height (3.88mm × 2.535mm = 9.84mm²)"
        QUARTER = "0p5x0p5", "0.5×0.5 - Quarter Slot (1.94mm × 2.535mm = 4.92mm²)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="projects",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    slot_size = models.CharField(
        max_length=10,
        choices=SlotSize.choices,
        default=SlotSize.FULL,
        help_text="Die slot size for manufacturing",
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    # Track which file was submitted for manufacturing
    submitted_file = models.ForeignKey(
        "ProjectFile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_for_project",
        help_text="The file that was submitted for manufacturing",
    )

    # Manufacturability check results
    is_manufacturable = models.BooleanField(null=True, blank=True)
    manufacturability_errors = models.JSONField(default=list, blank=True)
    check_completed_at = models.DateTimeField(null=True, blank=True)

    # Manufacturing details
    estimated_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Project"
        verbose_name_plural = "Projects"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.user.username})"

    def can_submit(self) -> tuple[bool, str]:
        """Check if project can be submitted.

        Returns:
            tuple[bool, str]: (can_submit, reason_if_not)
                - can_submit: True if project can be submitted
                - reason_if_not: Empty string if can submit, error message otherwise
        """
        # Check if project has active file
        try:
            active_file = self.files.get(is_active=True)
        except ProjectFile.DoesNotExist:
            return False, "Project has no active file"

        # Check file download and verification status
        if active_file.download_status != ProjectFile.DownloadStatus.COMPLETED:
            status_display = active_file.get_download_status_display()
            return False, f"File download is not completed (status: {status_display})"

        if not active_file.hash_verified:
            return False, "File hash has not been verified"

        # Check project status - only MANUFACTURABLE can be submitted
        # (MANUFACTURABLE status guarantees is_manufacturable=True via mark_finished)
        if self.status != self.Status.MANUFACTURABLE:
            msg = (
                "Manufacturability check must complete before submission"
                if self.status == self.Status.DRAFT
                else "Project has already been submitted"
            )
            return False, msg

        return True, ""

    def submit(self):
        """Mark project as submitted and queue manufacturability check.

        Raises:
            ValidationError: If project cannot be submitted
        """
        # Validate submission
        can_submit, reason = self.can_submit()
        if not can_submit:
            raise ValidationError(reason)

        # Get the active file that's being submitted
        active_file = self.files.get(is_active=True)

        # Update project status
        self.status = self.Status.SUBMITTED
        self.submitted_at = timezone.now()
        self.submitted_file = active_file
        self.save()

        # Note: Manufacturability check has already been completed
        # (it was triggered automatically when file hash was verified)


class ProjectAccessLog(models.Model):
    """Audit log for when admins access other users' projects.

    This model provides audit logging for staff access to projects they
    don't own. Logs are read-only in Django admin but programmatic
    changes are still technically possible.

    Security Features:
    - Admin UI read-only: No update/delete operations allowed in admin
    - User protection: Cannot delete admin users with logs (PROTECT)
    - Comprehensive: Captures IP, user agent, timestamp, action

    Note: For stronger immutability guarantees, consider overriding
    save()/delete() or using database-level protections.
    """

    class Action(models.TextChoices):
        """Types of actions admins can perform on projects."""

        VIEW = "view", "Viewed"
        EDIT = "edit", "Edited"
        DELETE = "delete", "Deleted"
        ACCESS_DENIED = "access_denied", "Access Denied"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="access_logs",
        help_text="Project that was accessed",
    )

    admin_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # SECURITY: Prevent deletion of users with logs
        related_name="admin_access_logs",
        help_text="Admin user who accessed the project",
    )

    accessed_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the access occurred",
    )

    action = models.CharField(
        max_length=20,
        choices=Action.choices,
        help_text="Type of action performed",
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the admin user",
    )

    user_agent = models.TextField(
        blank=True,
        help_text="User agent string from the request",
    )

    view_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Name of the view that was accessed",
    )

    class Meta:
        ordering = ["-accessed_at"]
        verbose_name = "Project Access Log"
        verbose_name_plural = "Project Access Logs"
        indexes = [
            models.Index(fields=["-accessed_at"]),
            models.Index(fields=["admin_user", "-accessed_at"]),
            models.Index(fields=["project", "-accessed_at"]),
        ]

    def __str__(self):
        """String representation of access log."""
        action_text = self.get_action_display().lower()
        return (
            f"{self.admin_user.username} {action_text} "
            f"{self.project.user.username}'s {self.project.name} "
            f"at {self.accessed_at}"
        )


def project_file_upload_path(instance, filename):
    """Generate upload path for project files."""
    return f"projects/{instance.project.id}/{filename}"


class ProjectFile(models.Model):
    """Files associated with a project (design files, documentation, etc.)."""

    class FileType(models.TextChoices):
        DESIGN = "design", "Design File"
        DOCUMENTATION = "docs", "Documentation"
        SCHEMATIC = "schematic", "Schematic"
        LAYOUT = "layout", "Layout"
        GERBER = "gerber", "Gerber Files"
        OTHER = "other", "Other"

    class DownloadStatus(models.TextChoices):
        PENDING = "pending", "Download Pending"
        QUEUED = "queued", "Queued"
        DOWNLOADING = "downloading", "Downloading"
        COMPLETED = "completed", "Download Completed"
        FAILED = "failed", "Download Failed"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="files",
    )

    # File storage (optional - only after download completes)
    file = models.FileField(
        upload_to=project_file_upload_path,
        max_length=512,
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    # GDS formats
                    "gds",
                    "gdsii",
                    "gds2",
                    # OASIS formats
                    "oas",
                    "oasis",
                    # Compression formats
                    "gz",
                    "zip",
                    "bz2",
                    "xz",
                ],
            ),
        ],
    )

    file_type = models.CharField(
        max_length=20,
        choices=FileType.choices,
        default=FileType.DESIGN,
    )

    # URL-based file handling
    original_url = models.URLField(
        blank=True,
        help_text="Original URL submitted by user (before any rewriting)",
    )
    source_url = models.URLField(
        blank=True,
        help_text="Actual URL to download from (after URL rewriting if applicable)",
    )
    # Download status is derived from latest DownloadAttempt (see @property below)
    download_started_at = models.DateTimeField(null=True, blank=True)
    download_completed_at = models.DateTimeField(null=True, blank=True)
    download_error = models.TextField(blank=True)
    download_task_id = models.CharField(max_length=100, blank=True)
    last_activity = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last activity timestamp for download progress tracking",
    )

    # File verification (provided by user)
    expected_hash_md5 = models.CharField(
        max_length=32,
        blank=True,
        help_text="MD5 hash provided by user for verification",
    )
    expected_hash_sha1 = models.CharField(
        max_length=40,
        blank=True,
        help_text="SHA1 hash provided by user for verification",
    )
    expected_hash_sha256 = models.CharField(
        max_length=64,
        blank=True,
        help_text="SHA256 hash provided by user for verification",
    )

    # File verification (calculated) - keep original field names from migration
    hash_md5 = models.CharField(max_length=32, blank=True)
    hash_sha1 = models.CharField(max_length=40, blank=True)
    hash_sha256 = models.CharField(max_length=64, blank=True)
    hash_verified = models.BooleanField(default=False)

    # URL handler metadata
    handler_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Metadata from URL handler "
            "(e.g., which handler was used, handler-specific data)"
        ),
    )

    # Metadata
    file_size = models.BigIntegerField(null=True, blank=True)
    original_filename = models.CharField(
        max_length=255,
        help_text="Original filename when downloaded (immutable)",
    )
    processed_filename = models.CharField(
        max_length=255,
        blank=True,
        help_text="Final filename after extraction/decompression pipeline",
    )
    top_cell = models.CharField(
        max_length=255,
        blank=True,
        help_text="Top-level cell name extracted from GDS/OASIS file",
    )
    content_type = models.CharField(max_length=100, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # File replacement tracking
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this is the currently active file for the project",
    )
    replaced_by = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replaces",
        help_text="The file that replaced this one",
    )

    class Meta:
        verbose_name = "Project File"
        verbose_name_plural = "Project Files"
        ordering = ["uploaded_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["project"],
                condition=models.Q(is_active=True),
                name="one_active_file_per_project",
            ),
        ]

    def __str__(self):
        if self.source_url:
            return f"{self.project.name} - {self.original_filename} (from URL)"
        return f"{self.project.name} - {self.original_filename}"

    def calculate_hashes(self):
        """Calculate MD5, SHA1, and SHA256 hashes for the downloaded file."""
        if not self.file:
            return False

        try:
            self.file.seek(0)
            content = self.file.read()

            self.hash_md5 = hashlib.md5(content, usedforsecurity=False).hexdigest()
            self.hash_sha1 = hashlib.sha1(content, usedforsecurity=False).hexdigest()
            self.hash_sha256 = hashlib.sha256(content).hexdigest()
            self.file_size = len(content)

            self.file.seek(0)  # Reset file pointer
            self.save()
        except OSError:
            return False
        else:
            return True

    def verify_hash(self):
        """Verify downloaded file hash against user-provided expected values."""
        # Calculate missing hashes if needed for verification
        needs_calculation = (
            (self.expected_hash_md5 and not self.hash_md5)
            or (self.expected_hash_sha1 and not self.hash_sha1)
            or (self.expected_hash_sha256 and not self.hash_sha256)
        )

        if needs_calculation:
            if not self.calculate_hashes():
                return False, "Could not calculate file hashes"

        verified = True
        errors = []

        if self.expected_hash_md5:
            if self.hash_md5.lower() != self.expected_hash_md5.lower():
                verified = False
                errors.append(
                    f"MD5 mismatch: expected {self.expected_hash_md5}, "
                    f"got {self.hash_md5}",
                )

        if self.expected_hash_sha1:
            if self.hash_sha1.lower() != self.expected_hash_sha1.lower():
                verified = False
                errors.append(
                    f"SHA1 mismatch: expected {self.expected_hash_sha1}, "
                    f"got {self.hash_sha1}",
                )

        if self.expected_hash_sha256:
            if self.hash_sha256.lower() != self.expected_hash_sha256.lower():
                verified = False
                errors.append(
                    f"SHA256 mismatch: expected {self.expected_hash_sha256}, "
                    f"got {self.hash_sha256}",
                )

        self.hash_verified = verified
        self.save()

        if verified:
            return True, "Hash verification successful"
        return False, "; ".join(errors)

    def mark_download_complete(self):
        """Mark download as completed successfully.

        NOTE: Actual status is derived from DownloadAttempt.
        This method only updates completion timestamp.
        """
        self.download_completed_at = timezone.now()
        self.save(update_fields=["download_completed_at"])

    def mark_download_failed(self, error_message):
        """Mark download as failed - records error on ProjectFile only.

        Note:
            This method only updates ProjectFile fields. The caller is responsible
            for updating the DownloadAttempt status to FAILED. This separation
            avoids circular dependencies between ProjectFile and DownloadAttempt.

            Typical usage from tasks.py:
                # Update attempt status first
                attempt.status = DownloadAttempt.Status.FAILED
                attempt.error_message = error_msg
                attempt.save()
                # Then record on ProjectFile
                project_file.mark_download_failed(error_msg)

        Args:
            error_message: Error description to record
        """
        self.download_error = error_message
        self.download_completed_at = timezone.now()
        self.save(update_fields=["download_error", "download_completed_at"])

    def get_progress_percentage(self) -> int:
        """Calculate download progress percentage.

        Returns:
            int: Progress percentage (0-100)
        """
        if self.download_status == self.DownloadStatus.COMPLETED:
            return 100

        if self.download_status == self.DownloadStatus.FAILED:
            return 0

        # If no file size info, can't calculate percentage
        if not self.file_size:
            return 0

        # Note: Actual progress during download comes from Celery task state
        # This method is for when we only have model data
        if self.download_status == self.DownloadStatus.DOWNLOADING:
            # Return indeterminate progress if no detailed info
            return 0

        return 0

    def get_progress_message(self) -> str:
        """Get user-friendly progress message.

        Returns:
            str: Human-readable status message
        """
        status_messages: dict[str, str] = {
            self.DownloadStatus.COMPLETED.value: "Download completed successfully",
            self.DownloadStatus.DOWNLOADING.value: "Downloading file...",
            self.DownloadStatus.PENDING.value: "Download pending - waiting to start",
            self.DownloadStatus.QUEUED.value: "Download queued - waiting for worker",
        }

        # Handle FAILED specially to include error message if present
        if self.download_status == self.DownloadStatus.FAILED:
            if self.download_error:
                return f"Download failed: {self.download_error}"
            return "Download failed"

        return status_messages.get(
            self.download_status, f"Unknown status: {self.download_status}"
        )

    @property
    def download_duration_seconds(self) -> float | None:
        """Calculate download duration in seconds.

        Returns:
            float: Duration in seconds, or None if not completed successfully
        """
        # Only calculate duration for successfully completed downloads
        if self.download_status != self.DownloadStatus.COMPLETED:
            return None

        if not self.download_started_at or not self.download_completed_at:
            return None

        duration = self.download_completed_at - self.download_started_at
        return duration.total_seconds()

    @property
    def download_speed_bytes_per_second(self) -> float | None:
        """Calculate download speed in bytes per second.

        Returns:
            float: Download speed in bytes/sec, or None if not calculable
        """
        duration = self.download_duration_seconds
        if not duration or not self.file_size or duration <= 0:
            return None

        return self.file_size / duration

    @property
    def download_speed_formatted(self) -> str | None:
        """Get formatted download speed in human-readable format.

        Returns:
            str: Formatted speed like "2.50 MB/s", or None if not calculable
        """
        speed = self.download_speed_bytes_per_second
        if speed is None:
            return None

        # Convert bytes/sec to human-readable format
        bytes_per_kb = 1024
        for unit in ("B/s", "KB/s", "MB/s", "GB/s", "TB/s"):
            if speed < bytes_per_kb:
                return f"{speed:.2f} {unit}"
            speed /= bytes_per_kb
        return f"{speed:.2f} PB/s"

    @property
    def latest_attempt(self) -> "DownloadAttempt | None":
        """Get the most recent download attempt.

        Returns None if no attempts exist yet.
        """
        return self.download_attempts.first()  # Already ordered by -attempt_number

    @property
    def download_status(self) -> str:
        """Derive download status from latest DownloadAttempt.

        State mapping:
        - No attempts + no task_id → PENDING
        - No attempts + task_id exists → QUEUED
        - Latest attempt PENDING + task_id → QUEUED
        - Latest attempt DOWNLOADING/COMPLETED/FAILED → same

        Returns:
            str: One of DownloadStatus enum values
        """
        latest = self.latest_attempt
        if not latest:
            # No attempts yet - check if task queued
            if self.download_task_id:
                return self.DownloadStatus.QUEUED
            return self.DownloadStatus.PENDING

        # Map DownloadAttempt.PENDING + task exists → ProjectFile.QUEUED
        # Both enums share the same "pending" value
        if latest.status == self.DownloadStatus.PENDING and self.download_task_id:
            return self.DownloadStatus.QUEUED

        # Direct mapping for other states
        return latest.status

    def get_download_status_display(self) -> str:
        """Get human-readable display name for download_status.

        Since download_status is a property, Django doesn't auto-generate this.
        We implement it manually to maintain compatibility with code that
        expects get_FIELD_display() methods.

        Returns:
            str: Human-readable status like "Pending", "Completed", etc.
        """
        status_value = self.download_status
        return dict(self.DownloadStatus.choices).get(status_value, status_value)

    @property
    def attempt_count(self) -> int:
        """Get number of download attempts.

        Includes all attempts (successful and failed).
        """
        return self.download_attempts.count()

    @property
    def download_progress(self) -> int:
        """Get download progress percentage from latest attempt.

        Returns 0 if no attempts exist or file size unknown.
        """
        attempt = self.latest_attempt
        if not attempt:
            return 0
        return attempt.download_progress

    @property
    def has_hash_mismatch(self) -> bool:
        """Check if there's a hash mismatch between expected and actual hashes.

        Returns True if any expected hash was provided AND doesn't match actual.
        Returns False if no expected hashes provided (nothing to compare).
        Returns False if expected hashes match actual hashes.
        """
        # Check MD5 mismatch
        if self.expected_hash_md5 and self.hash_md5:
            if self.expected_hash_md5.lower() != self.hash_md5.lower():
                return True

        # Check SHA1 mismatch
        if self.expected_hash_sha1 and self.hash_sha1:
            if self.expected_hash_sha1.lower() != self.hash_sha1.lower():
                return True

        # Check SHA256 mismatch
        if self.expected_hash_sha256 and self.hash_sha256:
            if self.expected_hash_sha256.lower() != self.hash_sha256.lower():
                return True

        return False

    @property
    def has_expected_hash(self) -> bool:
        """Check if user provided any expected hash for verification."""
        return bool(
            self.expected_hash_md5
            or self.expected_hash_sha1
            or self.expected_hash_sha256
        )


class FileProcessingError(models.Model):
    """Log of errors that occurred during file processing.

    Each error belongs to a specific DownloadAttempt, not directly to ProjectFile.
    This allows tracking which errors occurred in which retry attempt.
    """

    class ErrorType(models.TextChoices):
        DOWNLOAD = "download", "Download Error"
        EXTRACTION = "extraction", "Extraction Error"
        VALIDATION = "validation", "Validation Error"
        PIPELINE = "pipeline", "Pipeline Error"

    download_attempt = models.ForeignKey(
        "DownloadAttempt",  # Use string to avoid ordering issues
        on_delete=models.CASCADE,
        related_name="errors",
        help_text="The download attempt this error belongs to",
    )
    error_type = models.CharField(max_length=20, choices=ErrorType.choices)
    error_message = models.TextField(help_text="User-friendly error message")
    error_detail = models.JSONField(
        default=dict,
        blank=True,
        help_text="Technical details: stack trace, context, etc. (superuser only)",
    )
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["download_attempt", "-occurred_at"]),
            models.Index(fields=["error_type", "-occurred_at"]),
        ]

    def __str__(self):
        attempt_num = self.download_attempt.attempt_number
        error_type = self.get_error_type_display()
        message_preview = self.error_message[:50]
        return f"Attempt #{attempt_num} - {error_type}: {message_preview}"


class DownloadAttempt(models.Model):
    """Track a single download attempt for a ProjectFile.

    Created at the start of each download task execution. Tracks the full
    lifecycle of that execution including progress, checkpoints, and errors.

    Each ProjectFile can have multiple attempts (retries). Each attempt has
    its own set of checkpoints and errors, preventing duplicates.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DOWNLOADING = "downloading", "Downloading"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    # Foreign Keys
    project_file = models.ForeignKey(
        ProjectFile,
        on_delete=models.CASCADE,
        related_name="download_attempts",
        help_text="The file this download attempt belongs to",
    )

    # Attempt tracking
    attempt_number = models.IntegerField(
        help_text="Sequential attempt number (1, 2, 3...)",
    )
    started_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this attempt was created",
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this attempt finished (success or failure)",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Current status of this download attempt",
    )

    # Download details (moved from ProjectFile)
    download_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When download actually started (after task setup)",
    )
    download_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When download finished (success or failure)",
    )
    download_error = models.TextField(
        blank=True,
        help_text="Error message if download failed",
    )
    download_duration_seconds = models.FloatField(
        null=True,
        blank=True,
        help_text="Total download duration in seconds",
    )
    bytes_downloaded = models.BigIntegerField(
        default=0,
        help_text="Total bytes downloaded in this attempt",
    )

    # Worker tracking (moved from ProjectFile)
    worker_pid = models.IntegerField(
        null=True,
        blank=True,
        help_text="Process ID of worker executing this attempt",
    )
    worker_hostname = models.CharField(
        max_length=255,
        blank=True,
        help_text="Hostname of worker executing this attempt",
    )
    task_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When Celery task started executing",
    )

    # Metadata
    last_activity = models.DateTimeField(
        auto_now=True,
        help_text="Last update to this attempt (for staleness detection)",
    )

    class Meta:
        ordering = ["-attempt_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["project_file", "attempt_number"],
                name="unique_attempt_per_file",
            ),
        ]
        indexes = [
            models.Index(fields=["project_file", "-attempt_number"]),
            models.Index(fields=["status"]),
            models.Index(fields=["last_activity"]),
        ]

    def __str__(self):
        status = self.get_status_display()
        filename = self.project_file.original_filename
        return f"{filename} - Attempt #{self.attempt_number} ({status})"

    @property
    def download_progress(self) -> int:
        """Calculate download progress percentage.

        Returns:
            int: Progress percentage (0-100)
        """
        if not self.project_file.file_size or self.project_file.file_size == 0:
            return 0
        progress = (self.bytes_downloaded / self.project_file.file_size) * 100
        return min(int(progress), 100)

    @property
    def download_speed_formatted(self) -> str:
        """Get formatted download speed.

        Returns:
            str: Speed like "1.2 MB/s" or empty string
        """
        if not self.download_duration_seconds or self.download_duration_seconds <= 0:
            return ""

        speed_bytes_per_sec = self.bytes_downloaded / self.download_duration_seconds

        # Format speed
        bytes_per_unit = 1024
        for unit in ["B/s", "KB/s", "MB/s", "GB/s"]:
            if speed_bytes_per_sec < bytes_per_unit:
                return f"{speed_bytes_per_sec:.1f} {unit}"
            speed_bytes_per_sec /= bytes_per_unit
        return f"{speed_bytes_per_sec:.1f} TB/s"


class ProjectFileChunk(models.Model):
    """Track individual chunk downloads for performance analysis and resume capability.

    Records are created periodically during download (e.g., every 5MB) rather than
    for every single chunk, to balance granularity with database overhead.

    Each chunk belongs to a specific DownloadAttempt, not directly to ProjectFile.
    This prevents duplicate checkpoints when downloads are retried.
    """

    download_attempt = models.ForeignKey(
        "DownloadAttempt",  # Use string to avoid ordering issues
        on_delete=models.CASCADE,
        related_name="chunks",
        help_text="The download attempt this checkpoint belongs to",
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        help_text="When this checkpoint was recorded",
    )
    bytes_downloaded = models.BigIntegerField(
        help_text="Cumulative bytes downloaded at this checkpoint",
    )
    chunk_number = models.IntegerField(
        help_text="Sequential chunk number for ordering",
    )

    class Meta:
        ordering = ["chunk_number"]
        indexes = [
            models.Index(fields=["download_attempt", "chunk_number"]),
            models.Index(fields=["download_attempt", "timestamp"]),
        ]

    def __str__(self):
        return (
            f"{self.download_attempt.project_file.original_filename} - "
            f"Attempt #{self.download_attempt.attempt_number} - "
            f"Chunk {self.chunk_number} ({self.bytes_downloaded:,} bytes)"
        )

    @property
    def speed_since_previous(self) -> float | None:
        """Calculate download speed since the previous chunk.

        Returns:
            float: Speed in bytes/sec, or None if this is the first chunk
        """
        # Get previous chunk FOR THIS ATTEMPT
        previous = (
            ProjectFileChunk.objects.filter(
                download_attempt=self.download_attempt,
                chunk_number__lt=self.chunk_number,
            )
            .order_by("-chunk_number")
            .first()
        )

        if not previous:
            # This is the first chunk, calculate from download start
            if not self.download_attempt.download_started_at:
                return None

            time_diff = self.timestamp - self.download_attempt.download_started_at
            duration = time_diff.total_seconds()
            if duration <= 0:
                return None

            return self.bytes_downloaded / duration

        # Calculate speed since previous chunk
        time_diff = self.timestamp - previous.timestamp
        duration = time_diff.total_seconds()
        if duration <= 0:
            return None

        bytes_diff = self.bytes_downloaded - previous.bytes_downloaded
        return bytes_diff / duration


def _get_check_file_prefix(instance) -> tuple[str, str, str]:
    """Get common file naming components for manufacturability check files.

    Returns:
        tuple: (gds_name, top_cell, timestamp_str)
    """
    timestamp = instance.celery_job_started_at or timezone.now()
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")

    # Get GDS filename (without path)
    gds_name = "design"
    if instance.project_file and instance.project_file.processed_filename:
        gds_name = instance.project_file.processed_filename

    # Get top cell name
    top_cell = "unknown"
    if instance.project_file and instance.project_file.top_cell:
        # Sanitize top cell name for filesystem (replace unsafe chars)
        top_cell = instance.project_file.top_cell.replace("/", "_").replace("\\", "_")

    return gds_name, top_cell, timestamp_str


def manufacturability_check_log_path(instance, filename):
    """Generate upload path for manufacturability check logs.

    Logs are stored next to the GDS file with a unique name per check run.
    Format: projects/<project_id>/<gds_name>.<top_cell>.precheck.<timestamp>.log

    Example: projects/abc123/design.gds.TOP_CELL.precheck.20251126_231820.log
    """
    gds_name, top_cell, timestamp_str = _get_check_file_prefix(instance)
    filename = f"{gds_name}.{top_cell}.precheck.{timestamp_str}.log"
    return f"projects/{instance.project.id}/{filename}"


def manufacturability_check_runs_path(instance, filename):
    """Generate upload path for manufacturability check runs archive.

    Runs archive contains detailed step-by-step logs from the precheck tool.
    Format: projects/<project_id>/<gds_name>.<top_cell>.precheck.<timestamp>.runs.tar

    Example: projects/abc123/design.gds.TOP_CELL.precheck.20251126_231820.runs.tar
    """
    gds_name, top_cell, timestamp_str = _get_check_file_prefix(instance)
    filename = f"{gds_name}.{top_cell}.precheck.{timestamp_str}.runs.tar"
    return f"projects/{instance.project.id}/{filename}"


class ManufacturabilityCheck(models.Model):
    """Track manufacturability checking process for projects."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"  # Waiting for capacity
        DISPATCHED = "dispatched", "Dispatched"  # Job sent to Celery
        RUNNING = "running", "Running"  # Celery worker executing
        FINISHED = "finished", "Finished"  # Analysis complete
        ERROR = "error", "Error"  # System/processing failure
        CANCELLING = "cancelling", "Cancelling"  # Cleanup in progress
        CANCELLED = "cancelled", "Cancelled"  # User cancelled

    # State machine: defines valid transitions
    # PENDING: waiting for capacity to dispatch to Celery
    # DISPATCHED: job sent to Celery, waiting for worker
    # RUNNING: Celery worker executing analysis
    # FINISHED: analysis complete (terminal)
    # ERROR: system failure, can retry
    # CANCELLED: user cancelled (terminal)
    ALLOWED_TRANSITIONS: ClassVar[dict[Status, set[Status]]] = {
        Status.PENDING: {Status.DISPATCHED, Status.ERROR, Status.CANCELLING},
        Status.DISPATCHED: {Status.RUNNING, Status.ERROR, Status.CANCELLING},
        Status.RUNNING: {Status.FINISHED, Status.ERROR, Status.CANCELLING},
        Status.FINISHED: set(),  # Terminal - no transitions
        Status.ERROR: {Status.PENDING},  # Can retry
        Status.CANCELLING: {Status.CANCELLED},  # Only cleanup task can complete
        Status.CANCELLED: set(),  # Terminal - no transitions
    }

    # Maximum characters of processing logs to include in GitHub issue body
    GITHUB_ISSUE_LOG_CHARS: ClassVar[int] = 5000

    # Maximum concurrent checks allowed (DISPATCHED + RUNNING)
    MAX_CONCURRENT_CHECKS: ClassVar[int] = 4

    # Statuses representing checks that are in progress and should be
    # cancelled when the project file is replaced
    IN_PROGRESS_STATUSES: ClassVar[list[Status]] = [
        Status.PENDING,
        Status.DISPATCHED,
        Status.RUNNING,
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="manufacturability_checks",
    )
    project_file = models.OneToOneField(
        "ProjectFile",
        on_delete=models.CASCADE,
        related_name="manufacturability_check",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this check record was created",
    )

    # Processing details
    celery_job_started_at = models.DateTimeField(null=True, blank=True)
    celery_job_finished_at = models.DateTimeField(null=True, blank=True)
    celery_job_id = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="ID of the Celery job processing this check",
    )
    celery_job_dispatched_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When job was dispatched to Celery queue",
    )

    # Worker tracking (matching DownloadAttempt pattern)
    celery_worker_pid = models.IntegerField(
        null=True,
        blank=True,
        help_text="Process ID of Celery worker executing this check",
    )
    celery_worker_hostname = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Hostname of Celery worker executing this check",
    )

    # Docker container tracking
    docker_container_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="ID of Docker container running the analysis",
    )
    docker_container_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When Docker container started",
    )

    # Results
    is_manufacturable = models.BooleanField(null=True, blank=True)
    errors = models.JSONField(default=list, blank=True)  # Manufacturing errors
    warnings = models.JSONField(default=list, blank=True)  # Manufacturing warnings
    processing_logs = models.TextField(blank=True)
    log_file = models.FileField(
        upload_to=manufacturability_check_log_path,
        max_length=512,
        blank=True,
        help_text="Log file stored on filesystem (next to GDS file)",
    )
    runs_archive = models.FileField(
        upload_to=manufacturability_check_runs_path,
        max_length=512,
        blank=True,
        help_text="Tar archive of detailed step logs from precheck runs/ directory",
    )

    # System error tracking (distinct from manufacturing errors)
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="System error message if check failed to run (Docker, timeout, etc.)",
    )

    # Retry handling
    retry_count = models.PositiveIntegerField(default=0)
    max_retries = models.PositiveIntegerField(default=3)

    # Version tracking
    docker_image = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text=(
            "Docker image used (e.g., ghcr.io/wafer-space/gf180mcu-precheck:latest)"
        ),
    )
    docker_image_digest = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="SHA256 digest of Docker image for reproducibility",
    )
    docker_command = models.TextField(
        blank=True,
        default="",
        help_text="Full docker run command for reproducibility",
    )
    tool_versions = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Tool versions: "
            "{magic: '8.3.x', klayout: '0.28.x', pdk: 'gf180mcuD-v1.2.3'}"
        ),
    )
    precheck_version = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="gf180mcu-precheck version/commit hash",
    )

    # Activity tracking
    last_activity = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last activity timestamp for progress tracking",
    )

    # Admin controls
    rerun_requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_precheck_reruns",
        help_text="Admin who requested re-run",
    )
    rerun_reason = models.TextField(
        blank=True,
        default="",
        help_text="Why this check was re-run (e.g., 'Updated DRC rules')",
    )

    class Meta:
        verbose_name = "Manufacturability Check"
        verbose_name_plural = "Manufacturability Checks"
        ordering = ["-celery_job_started_at"]

    def __str__(self):
        return f"Check for {self.project.name} - {self.get_status_display()}"

    def can_retry(self) -> bool:
        """Check if this check can be retried."""
        return self.retry_count < self.max_retries

    def can_transition_to(self, new_status: Status) -> bool:
        """Check if transition from current status to new_status is valid.

        Args:
            new_status: The status to transition to

        Returns:
            True if transition is allowed, False otherwise

        """
        # Cast string status to Status enum for lookup
        current_status = self.Status(self.status)
        allowed = self.ALLOWED_TRANSITIONS.get(current_status, set())
        return new_status in allowed

    def mark_dispatched(self, *, celery_job_id: str) -> None:
        """Mark check as dispatched to Celery queue.

        Pathway 2: PENDING → DISPATCHED

        Args:
            celery_job_id: The ID returned by celery_task.delay()

        Raises:
            InvalidStateTransitionError: If transition is not allowed
            ConcurrentLimitError: If the concurrent DISPATCHED/RUNNING limit
                would be exceeded
        """
        if not self.can_transition_to(self.Status.DISPATCHED):
            raise InvalidStateTransitionError(
                from_status=self.status,
                to_status=self.Status.DISPATCHED,
            )

        # Check concurrent limit (DISPATCHED + RUNNING)
        active_count = (
            ManufacturabilityCheck.objects.filter(
                status__in=[self.Status.DISPATCHED, self.Status.RUNNING],
            )
            .exclude(pk=self.pk)
            .count()
        )

        if active_count >= self.MAX_CONCURRENT_CHECKS:
            raise ConcurrentLimitError(
                active_count=active_count,
                max_concurrent=self.MAX_CONCURRENT_CHECKS,
            )

        self.status = self.Status.DISPATCHED
        self.celery_job_id = celery_job_id
        self.celery_job_dispatched_at = timezone.now()
        self.save(update_fields=["status", "celery_job_id", "celery_job_dispatched_at"])

    def mark_running(self, *, context: CheckExecutionContext) -> None:
        """Mark check as running in Celery worker.

        Pathway 3: DISPATCHED → RUNNING

        Args:
            context: CheckExecutionContext with worker and docker info

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        if not self.can_transition_to(self.Status.RUNNING):
            raise InvalidStateTransitionError(
                from_status=self.status,
                to_status=self.Status.RUNNING,
            )

        self.status = self.Status.RUNNING
        self.celery_worker_pid = context.celery_worker_pid
        self.celery_worker_hostname = context.celery_worker_hostname
        self.docker_container_id = context.docker_container_id
        self.docker_container_started_at = timezone.now()
        self.celery_job_started_at = timezone.now()
        self.docker_image = context.docker_image
        self.docker_image_digest = context.docker_image_digest
        self.docker_command = context.docker_command
        self.save(
            update_fields=[
                "status",
                "celery_worker_pid",
                "celery_worker_hostname",
                "docker_container_id",
                "docker_container_started_at",
                "celery_job_started_at",
                "docker_image",
                "docker_image_digest",
                "docker_command",
            ]
        )

    def mark_finished(
        self,
        *,
        is_manufacturable: bool,
        errors: list[dict],
        warnings: list[dict],
        processing_logs: str,
        tool_versions: dict | None = None,
    ) -> None:
        """Mark check as finished with results.

        Pathway 4: RUNNING → FINISHED

        Args:
            is_manufacturable: Whether the design is manufacturable
            errors: List of error dicts (manufacturing issues)
            warnings: List of warning dicts (manufacturing warnings)
            processing_logs: Full log output from processing
            tool_versions: Dict of tool versions used (pdk, magic, klayout, etc.)

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        if not self.can_transition_to(self.Status.FINISHED):
            raise InvalidStateTransitionError(
                from_status=self.status,
                to_status=self.Status.FINISHED,
            )

        self.status = self.Status.FINISHED
        self.is_manufacturable = is_manufacturable
        self.errors = errors
        self.warnings = warnings
        self.processing_logs = processing_logs
        self.celery_job_finished_at = timezone.now()
        if tool_versions is not None:
            self.tool_versions = tool_versions

        update_fields = [
            "status",
            "is_manufacturable",
            "errors",
            "warnings",
            "processing_logs",
            "celery_job_finished_at",
        ]
        if tool_versions is not None:
            update_fields.append("tool_versions")
        self.save(update_fields=update_fields)

        # Update project status
        if is_manufacturable:
            self.project.status = Project.Status.MANUFACTURABLE
        else:
            self.project.status = Project.Status.NOT_MANUFACTURABLE
        self.project.is_manufacturable = is_manufacturable
        self.project.manufacturability_errors = self.errors
        self.project.check_completed_at = self.celery_job_finished_at
        self.project.save()

    def mark_error(
        self,
        *,
        error_message: str,
        processing_logs: str = "",
    ) -> None:
        """Mark check as errored due to system failure.

        Pathways 5/6: PENDING/DISPATCHED/RUNNING → ERROR

        Preserves tracking fields (celery_job_id, docker_container_id, worker info)
        for debugging. These are only cleared by reset_for_retry() when retrying.

        Args:
            error_message: System error message describing the failure
            processing_logs: Full log output from processing (optional, defaults
                to empty string)

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        if not self.can_transition_to(self.Status.ERROR):
            raise InvalidStateTransitionError(
                from_status=self.status,
                to_status=self.Status.ERROR,
            )

        self.status = self.Status.ERROR
        self.error_message = error_message
        # Append error marker to logs so it's clear the job failed
        error_suffix = "\n\n=== SYSTEM ERROR - See error_message field ==="
        self.processing_logs = (processing_logs or "") + error_suffix
        self.celery_job_finished_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "error_message",
                "processing_logs",
                "celery_job_finished_at",
            ]
        )

    def mark_cancelling(self, *, reason: str) -> None:
        """Request cancellation - transitions to CANCELLING state.

        Cleanup task will complete the transition to CANCELLED after
        revoking Celery task and stopping Docker container.

        Args:
            reason: Description of why the check is being cancelled

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        if not self.can_transition_to(self.Status.CANCELLING):
            raise InvalidStateTransitionError(
                from_status=self.status,
                to_status=self.Status.CANCELLING,
            )

        self.status = self.Status.CANCELLING

        # Append reason to processing_logs
        cancellation_msg = f"CANCELLATION REQUESTED: {reason}"
        if self.processing_logs:
            self.processing_logs += f"\n\n{cancellation_msg}"
        else:
            self.processing_logs = cancellation_msg

        self.save()

    def mark_cancelled(self) -> None:
        """Complete cancellation - only called by cleanup task after cleanup is done.

        This method should only be called from CANCELLING state, after the
        checks_cancelling task has revoked the Celery task and stopped any
        Docker container. It clears all task/container tracking fields.

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        if not self.can_transition_to(self.Status.CANCELLED):
            raise InvalidStateTransitionError(
                from_status=self.status,
                to_status=self.Status.CANCELLED,
            )

        self.status = self.Status.CANCELLED
        self.celery_job_finished_at = timezone.now()
        # Clear task and container tracking fields (cleanup already done)
        self.celery_job_id = ""
        self.docker_container_id = ""
        self.celery_worker_pid = None
        self.celery_worker_hostname = ""
        self.save(
            update_fields=[
                "status",
                "celery_job_finished_at",
                "celery_job_id",
                "docker_container_id",
                "celery_worker_pid",
                "celery_worker_hostname",
            ]
        )

    def reset_for_retry(self, *, reason: str = "") -> None:
        """Reset check to PENDING state for retry after error.

        Pathway 7: ERROR → PENDING (retry)

        Args:
            reason: Optional description of why the check is being retried

        Raises:
            InvalidStateTransitionError: If transition is not allowed
            MaxRetriesExceededError: If retry_count has reached max_retries
        """
        # Check state transition is valid FIRST
        if not self.can_transition_to(self.Status.PENDING):
            raise InvalidStateTransitionError(
                from_status=self.status,
                to_status=self.Status.PENDING,
            )

        # Then check retry limit using can_retry() and self.max_retries
        if not self.can_retry():
            raise MaxRetriesExceededError(
                retry_count=self.retry_count,
                max_retries=self.max_retries,
            )

        # Reset to PENDING state
        self.status = self.Status.PENDING
        self.retry_count += 1

        # Clear all job-related fields
        self.celery_job_id = ""
        self.celery_job_dispatched_at = None
        self.celery_job_started_at = None
        self.celery_job_finished_at = None
        self.celery_worker_pid = None
        self.celery_worker_hostname = ""
        self.docker_container_id = ""
        self.docker_container_started_at = None
        self.error_message = ""

        # Append reason to processing_logs if provided
        if reason:
            if self.processing_logs:
                self.processing_logs += f"\n\nRETRY #{self.retry_count}: {reason}"
            else:
                self.processing_logs = f"RETRY #{self.retry_count}: {reason}"

        self.save()

    def update_processing_logs(self, logs: str) -> None:
        """Update processing logs during RUNNING state.

        This is the ONLY field update allowed outside of mark_* state transitions.
        It enables real-time progress visibility during long-running checks.

        Args:
            logs: Current processing log output

        Raises:
            ValueError: If check is not in RUNNING state
        """
        if self.status != self.Status.RUNNING:
            msg = (
                f"Cannot update processing_logs: check must be in RUNNING state, "
                f"not {self.status}"
            )
            raise ValueError(msg)

        self.processing_logs = logs
        self.last_activity = timezone.now()
        self.save(update_fields=["processing_logs", "last_activity"])

    @property
    def is_cancellable(self) -> bool:
        """Check if this check can be cancelled.

        Returns True if check can transition to CANCELLING state.
        """
        return self.can_transition_to(self.Status.CANCELLING)

    @property
    def result_display(self) -> str:
        """Get human-readable result classification.

        Returns one of:
        - "Manufacturable - Clean" (no warnings)
        - "Manufacturable with Warnings" (warnings present)
        - "Not Manufacturable" (failed checks)
        - "" (not yet completed)
        """
        if self.status != self.Status.FINISHED or self.is_manufacturable is None:
            return ""

        if self.is_manufacturable:
            if self.warnings:
                return "Manufacturable with Warnings"
            return "Manufacturable - Clean"
        return "Not Manufacturable"

    @property
    def queue_position(self) -> int | None:
        """Get position in the pending queue (1-indexed).

        Returns None if not in PENDING state.
        Queue order is determined by pk (creation order).
        """
        if self.status != self.Status.PENDING:
            return None

        # Count PENDING checks created before this one (lower pk = ahead)
        ahead = ManufacturabilityCheck.objects.filter(
            status=self.Status.PENDING,
            pk__lt=self.pk,
        ).count()

        return ahead + 1  # 1-indexed position

    @property
    def checks_ahead(self) -> int:
        """Get number of checks ahead in the pending queue.

        Returns 0 if not in PENDING state.
        """
        position = self.queue_position
        if position is None:
            return 0
        return position - 1  # position is 1-indexed, so subtract 1

    @property
    def checks_behind(self) -> int:
        """Get number of checks behind in the pending queue (admin info).

        Returns 0 if not in PENDING state.
        """
        if self.status != self.Status.PENDING:
            return 0

        return ManufacturabilityCheck.objects.filter(
            status=self.Status.PENDING,
            pk__gt=self.pk,
        ).count()

    @property
    def checks_running(self) -> int:
        """Get number of checks currently active (DISPATCHED or RUNNING)."""
        return ManufacturabilityCheck.objects.filter(
            status__in=[self.Status.DISPATCHED, self.Status.RUNNING],
        ).count()

    def get_reproduction_instructions(self) -> str:
        """Generate markdown instructions for reproducing check locally."""
        project_file = self.project_file

        return f"""# Reproducing Manufacturability Check Locally

## Prerequisites
- Docker installed and running
- Access to your GDS file

## Steps

### 1. Pull the exact Docker image used
```bash
docker pull {self.docker_image}
# Verify digest matches: {self.docker_image_digest}
docker images --digests | grep gf180mcu-precheck
```

### 2. Run the precheck
```bash
docker run --rm \\
  -v "$(pwd)/{project_file.original_filename}":/input/design.gds:ro \\
  {self.docker_image} \\
  python3 /precheck/precheck.py \\
    --input /input/design.gds \\
    --top "{self.project.name}" \\
    --id {self.project.id}
```

### 3. Verify file hash
Your GDS file should have:
- MD5: {project_file.hash_md5}
- SHA1: {project_file.hash_sha1}

## Environment
- Precheck Version: {self.precheck_version}
- Tool Versions: {json.dumps(self.tool_versions, indent=2)}

## Need Help?
[Report issue on GitHub]({self.generate_github_issue_url()})
"""

    def generate_github_issue_url(self) -> str:
        """Generate pre-filled GitHub issue URL."""
        title = f"Issue with precheck for project {self.project.name}"

        body = f"""### Environment
- Docker Image: `{self.docker_image}`
- Image Digest: `{self.docker_image_digest}`
- Precheck Version: `{self.precheck_version}`
- Tool Versions: {json.dumps(self.tool_versions, indent=2)}

### Issue Description
<!-- Describe the issue here -->

### Logs
<details>
<summary>Click to expand logs</summary>

```
{self.processing_logs[-self.GITHUB_ISSUE_LOG_CHARS :]}
```
</details>

### Error Messages
```json
{json.dumps(self.errors, indent=2)}
```
"""

        params = urllib.parse.urlencode(
            {"title": title, "body": body, "labels": "bug,from-platform"}
        )

        return f"https://github.com/wafer-space/gf180mcu-precheck/issues/new?{params}"


class ManufacturabilityCheckpoint(models.Model):
    """Track resource usage during manufacturability check execution.

    Similar to ProjectFileChunk for downloads, this records periodic snapshots
    of Docker container stats during the precheck run for performance analysis.
    """

    manufacturability_check = models.ForeignKey(
        ManufacturabilityCheck,
        on_delete=models.CASCADE,
        related_name="checkpoints",
        help_text="The manufacturability check this checkpoint belongs to",
    )

    # Timing
    timestamp = models.DateTimeField(
        auto_now_add=True,
        help_text="When this checkpoint was recorded",
    )
    checkpoint_number = models.IntegerField(
        help_text="Sequential checkpoint number for ordering",
    )
    elapsed_seconds = models.FloatField(
        help_text="Seconds since check started",
    )

    # CPU stats
    cpu_percent = models.FloatField(
        null=True,
        blank=True,
        help_text="CPU usage percentage at this checkpoint",
    )
    cpu_total_usage = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Total CPU usage in nanoseconds",
    )
    cpu_system_usage = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="System CPU usage in nanoseconds",
    )
    cpu_online_cpus = models.IntegerField(
        null=True,
        blank=True,
        help_text="Number of online CPUs",
    )

    # Memory stats
    memory_usage_bytes = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Memory usage in bytes",
    )
    memory_limit_bytes = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Memory limit in bytes",
    )
    memory_percent = models.FloatField(
        null=True,
        blank=True,
        help_text="Memory usage as percentage of limit",
    )
    memory_cache_bytes = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Memory cache in bytes",
    )

    # I/O stats
    block_read_bytes = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Block device read bytes",
    )
    block_write_bytes = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Block device write bytes",
    )

    # Network stats
    network_rx_bytes = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Network bytes received",
    )
    network_tx_bytes = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Network bytes transmitted",
    )

    # Container state
    container_state = models.CharField(
        max_length=20,
        blank=True,
        help_text="Container state (running, exited, etc.)",
    )

    class Meta:
        ordering = ["checkpoint_number"]
        indexes = [
            models.Index(fields=["manufacturability_check", "checkpoint_number"]),
            models.Index(fields=["manufacturability_check", "timestamp"]),
        ]

    def __str__(self) -> str:
        return (
            f"Check {self.manufacturability_check_id} - "
            f"Checkpoint {self.checkpoint_number} ({self.elapsed_seconds:.1f}s)"
        )

    @property
    def memory_usage_formatted(self) -> str:
        """Format memory usage for display."""
        if not self.memory_usage_bytes:
            return ""
        return _format_bytes_static(self.memory_usage_bytes)

    @property
    def cpu_percent_formatted(self) -> str:
        """Format CPU percentage for display."""
        if self.cpu_percent is None:
            return ""
        return f"{self.cpu_percent:.1f}%"


def _format_bytes_static(num_bytes: int) -> str:
    """Format bytes as human-readable string."""
    bytes_float = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(bytes_float) < _BYTES_PER_KB:
            return f"{bytes_float:.1f} {unit}"
        bytes_float /= _BYTES_PER_KB
    return f"{bytes_float:.1f} PB"


class ProjectComplianceCertification(models.Model):
    """Export compliance attestation for a specific project."""

    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="compliance_certification",
    )

    # Attestations
    export_control_compliant = models.BooleanField(
        default=False,
        help_text="User confirms compliance with EAR/ITAR export control regulations",
    )
    end_use_statement = models.TextField(
        help_text=(
            "Description of intended end-use (commercial, research, educational, etc.)"
        ),
    )
    not_restricted_entity = models.BooleanField(
        default=False,
        help_text=(
            "User confirms they are not from a restricted country or sanctioned entity"
        ),
    )

    # Tracking
    certified_at = models.DateTimeField(auto_now_add=True)
    certified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="compliance_certifications",
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address from which certification was submitted",
    )
    user_agent = models.TextField(
        blank=True,
        help_text="Browser user agent string",
    )

    # Admin review (optional - can be added later)
    admin_reviewed = models.BooleanField(default=False)
    admin_reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_certifications",
    )
    admin_notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Compliance Certification"
        verbose_name_plural = "Compliance Certifications"
        indexes = [
            models.Index(fields=["certified_at"]),
            models.Index(fields=["admin_reviewed"]),
        ]

    def __str__(self):
        return f"Compliance Certification for {self.project.name}"
