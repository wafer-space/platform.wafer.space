from django.db import models
from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.utils import timezone
import hashlib
import uuid


class Project(models.Model):
    """User-submitted design projects for manufacturing."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SUBMITTED = 'submitted', 'Submitted'
        CHECKING = 'checking', 'Checking Manufacturability'
        MANUFACTURABLE = 'manufacturable', 'Manufacturable'
        NOT_MANUFACTURABLE = 'not_manufacturable', 'Not Manufacturable'
        ASSIGNED_TO_SHUTTLE = 'assigned', 'Assigned to Shuttle'
        IN_PRODUCTION = 'production', 'In Production'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='projects'
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT
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
        blank=True
    )

    class Meta:
        verbose_name = "Project"
        verbose_name_plural = "Projects"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"{self.name} ({self.user.username})"

    def submit(self):
        """Mark project as submitted."""
        self.status = self.Status.SUBMITTED
        self.submitted_at = timezone.now()
        self.save()


def project_file_upload_path(instance, filename):
    """Generate upload path for project files."""
    return f"projects/{instance.project.id}/{filename}"


class ProjectFile(models.Model):
    """Files associated with a project (design files, documentation, etc.)."""

    class FileType(models.TextChoices):
        DESIGN = 'design', 'Design File'
        DOCUMENTATION = 'docs', 'Documentation'
        SCHEMATIC = 'schematic', 'Schematic'
        LAYOUT = 'layout', 'Layout'
        GERBER = 'gerber', 'Gerber Files'
        OTHER = 'other', 'Other'

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='files'
    )
    file = models.FileField(
        upload_to=project_file_upload_path,
        validators=[
            FileExtensionValidator(
                allowed_extensions=['zip', 'rar', '7z', 'tar', 'gz', 'gds', 'gdsii', 'cif', 'pdf', 'png', 'jpg', 'svg']
            )
        ]
    )
    file_type = models.CharField(
        max_length=20,
        choices=FileType.choices,
        default=FileType.DESIGN
    )
    url_source = models.URLField(
        blank=True,
        help_text="Original URL if file was fetched from remote source"
    )

    # File verification
    hash_md5 = models.CharField(max_length=32, blank=True)
    hash_sha1 = models.CharField(max_length=40, blank=True)
    hash_verified = models.BooleanField(default=False)

    # Metadata
    file_size = models.BigIntegerField(null=True, blank=True)
    original_filename = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Project File"
        verbose_name_plural = "Project Files"
        ordering = ['uploaded_at']

    def __str__(self):
        return f"{self.project.name} - {self.original_filename}"

    def calculate_hashes(self):
        """Calculate MD5 and SHA1 hashes for the file."""
        if self.file:
            self.file.seek(0)
            content = self.file.read()

            self.hash_md5 = hashlib.md5(content).hexdigest()
            self.hash_sha1 = hashlib.sha1(content).hexdigest()
            self.file_size = len(content)

            self.file.seek(0)  # Reset file pointer
            self.save()

    def verify_hash(self, provided_md5=None, provided_sha1=None):
        """Verify file hash against provided values."""
        if not self.hash_md5 or not self.hash_sha1:
            self.calculate_hashes()

        verified = True
        if provided_md5 and self.hash_md5.lower() != provided_md5.lower():
            verified = False
        if provided_sha1 and self.hash_sha1.lower() != provided_sha1.lower():
            verified = False

        self.hash_verified = verified
        self.save()
        return verified


class ManufacturabilityCheck(models.Model):
    """Track manufacturability checking process for projects."""

    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name='manufacturability_check'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED
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
        ordering = ['-started_at']

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
