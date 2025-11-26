import hashlib
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone


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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="projects",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
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

        # Check project status
        if self.status != self.Status.DRAFT:
            return False, "Project has already been submitted (status must be DRAFT)"

        # Check manufacturability (combined None and False check to reduce returns)
        if self.is_manufacturable is None:
            return False, "Manufacturability check has not been completed"
        return (
            (True, "")
            if self.is_manufacturable
            else (False, "File did not pass manufacturability checks")
        )

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

    # File verification (calculated) - keep original field names from migration
    hash_md5 = models.CharField(max_length=32, blank=True)
    hash_sha1 = models.CharField(max_length=40, blank=True)
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
        """Calculate MD5 and SHA1 hashes for the downloaded file."""
        if not self.file:
            return False

        try:
            self.file.seek(0)
            content = self.file.read()

            self.hash_md5 = hashlib.md5(content, usedforsecurity=False).hexdigest()
            self.hash_sha1 = hashlib.sha1(content, usedforsecurity=False).hexdigest()
            self.file_size = len(content)

            self.file.seek(0)  # Reset file pointer
            self.save()
        except OSError:
            return False
        else:
            return True

    def verify_hash(self):
        """Verify downloaded file hash against user-provided expected values."""
        if not self.hash_md5 or not self.hash_sha1:
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
    def current_status(self) -> str:
        """Get current download status from latest attempt.

        DEPRECATED: Use download_status property instead.
        Returns 'pending' if no attempts exist.
        """
        attempt = self.latest_attempt
        if not attempt:
            return "pending"
        return attempt.status

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

        return False

    @property
    def has_expected_hash(self) -> bool:
        """Check if user provided any expected hash for verification."""
        return bool(self.expected_hash_md5 or self.expected_hash_sha1)


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


class ManufacturabilityCheck(models.Model):
    """Track manufacturability checking process for projects."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="manufacturability_checks",
    )
    project_file = models.OneToOneField(
        "ProjectFile",
        on_delete=models.CASCADE,
        related_name="manufacturability_check",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
    )

    # Processing details
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    task_id = models.CharField(max_length=100, blank=True, default="")  # Celery task ID

    # Results
    is_manufacturable = models.BooleanField(null=True, blank=True)
    errors = models.JSONField(default=list, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    processing_logs = models.TextField(blank=True)

    # Retry handling
    retry_count = models.PositiveIntegerField(default=0)
    max_retries = models.PositiveIntegerField(default=3)

    class Meta:
        verbose_name = "Manufacturability Check"
        verbose_name_plural = "Manufacturability Checks"
        ordering = ["-started_at"]

    def __str__(self):
        return f"Check for {self.project.name} - {self.get_status_display()}"

    def start_processing(self):
        """Mark check as started."""
        self.status = self.Status.PROCESSING
        self.started_at = timezone.now()
        self.save()

    def complete(self, is_manufacturable, errors=None, warnings=None, logs=""):
        """Mark check as completed with results."""
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        self.is_manufacturable = is_manufacturable
        self.errors = errors or []
        self.warnings = warnings or []
        self.processing_logs = logs
        self.save()

        # Update project status
        if is_manufacturable:
            self.project.status = Project.Status.MANUFACTURABLE
        else:
            self.project.status = Project.Status.NOT_MANUFACTURABLE
        self.project.is_manufacturable = is_manufacturable
        self.project.manufacturability_errors = self.errors
        self.project.check_completed_at = self.completed_at
        self.project.save()

    def fail(self, error_message):
        """Mark check as failed."""
        self.status = self.Status.FAILED
        self.completed_at = timezone.now()
        self.processing_logs += f"\nFAILED: {error_message}"
        self.save()

    def can_retry(self):
        """Check if this check can be retried."""
        return self.retry_count < self.max_retries
