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

        # Check if download is completed
        if active_file.download_status != ProjectFile.DownloadStatus.COMPLETED:
            status_display = active_file.get_download_status_display()
            return False, f"File download is not completed (status: {status_display})"

        # Check if hash is verified
        if not active_file.hash_verified:
            return False, "File hash has not been verified"

        # Check if project is in DRAFT status
        if self.status != self.Status.DRAFT:
            return False, "Project has already been submitted (status must be DRAFT)"

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

        # Update project status
        self.status = self.Status.SUBMITTED
        self.submitted_at = timezone.now()
        self.save()

        # Queue manufacturability check using service layer
        # Import here to avoid circular import
        from .services import ManufacturabilityService  # noqa: PLC0415

        ManufacturabilityService.queue_check(self)


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
    download_status = models.CharField(
        max_length=20,
        choices=DownloadStatus.choices,
        default=DownloadStatus.PENDING,
    )
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
    original_filename = models.CharField(max_length=255)
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
        """Mark download as completed successfully."""
        self.download_status = self.DownloadStatus.COMPLETED
        self.download_completed_at = timezone.now()
        self.save()

    def mark_download_failed(self, error_message):
        """Mark download as failed with error message."""
        self.download_status = self.DownloadStatus.FAILED
        self.download_error = error_message
        self.download_completed_at = timezone.now()
        self.save()

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
        if self.download_status == self.DownloadStatus.COMPLETED:
            return "Download completed successfully"

        if self.download_status == self.DownloadStatus.FAILED:
            if self.download_error:
                return f"Download failed: {self.download_error}"
            return "Download failed"

        if self.download_status == self.DownloadStatus.DOWNLOADING:
            return "Downloading file..."

        if self.download_status == self.DownloadStatus.PENDING:
            return "Download pending - waiting to start"

        return f"Unknown status: {self.download_status}"


class ManufacturabilityCheck(models.Model):
    """Track manufacturability checking process for projects."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="manufacturability_check",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
    )

    # Processing details
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    task_id = models.CharField(max_length=100, blank=True)  # Celery task ID

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
