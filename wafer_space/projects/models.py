import hashlib
import json
import logging
import urllib.parse
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from typing import ClassVar

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
from django.utils.formats import date_format
from simple_history.models import HistoricalRecords

from wafer_space.core.enums import SlotSize
from wafer_space.projects.exceptions import InvalidStateTransitionError
from wafer_space.projects.storage import ProjectFileStorage

logger = logging.getLogger(__name__)

PRECHECK_GITHUB_REPO = "wafer-space/gf180mcu-precheck"


@dataclass
class CheckExecutionContext:
    """Context data for transitioning a check to RUNNING state.

    Groups worker and docker info to avoid too many function parameters.
    """

    docker_container_id: str
    docker_image: str
    docker_image_digest: str
    docker_command: str


# Byte conversion constant
_BYTES_PER_KB = 1024.0

# Project ID validation constant
PROJECT_ID_LENGTH = 4


def validate_project_id(value: str) -> None:
    """Validate project ID is 4 alphanumeric uppercase characters."""
    if len(value) != PROJECT_ID_LENGTH:
        msg = "Project ID must be exactly 4 characters"
        raise ValidationError(msg)
    if not value.isalnum():
        msg = "Project ID must be alphanumeric (A-Z, 0-9)"
        raise ValidationError(msg)
    # Check that any letters present are uppercase (digits are okay)
    if value != value.upper():
        msg = "Project ID must be uppercase"
        raise ValidationError(msg)


class LicenseType(models.TextChoices):
    """License types for projects.

    Uses SPDX identifiers where applicable for standard open source licenses.
    """

    PROPRIETARY = "proprietary", "Proprietary (All Rights Reserved)"
    APACHE_2_0 = "Apache-2.0", "Apache License 2.0"
    MIT = "MIT", "MIT License"
    BSD_3_CLAUSE = "BSD-3-Clause", "BSD 3-Clause License"
    ISC = "ISC", "ISC License"
    CERN_OHL_P = "CERN-OHL-P-2.0", "CERN Open Hardware License (Permissive)"
    SOLDERPAD_2_0 = "SHL-2.0", "Solderpad Hardware License 2.0"
    SOLDERPAD_2_1 = "SHL-2.1", "Solderpad Hardware License 2.1"
    CC0 = "CC0-1.0", "CC0 1.0 (Public Domain)"
    CC_BY = "CC-BY-4.0", "Creative Commons Attribution 4.0"
    OTHER = "other", "Other Open Source License"


class Project(models.Model):
    """User-submitted design projects for manufacturing.

    Project Identifiers
    -------------------
    This model uses three different identifiers, each serving a distinct purpose:

    1. **id** (UUIDField) - Primary Key
       - Auto-generated UUID (e.g., "550e8400-e29b-41d4-a716-446655440000")
       - Used internally for database references, API requests, and foreign keys
       - Globally unique across all projects in the system
       - Never exposed to end users in the UI
       - Immutable once created

    2. **project_id** (CharField) - User-Chosen Identifier
       - 4-character alphanumeric code (e.g., "ABCD", "X123")
       - Uppercase letters (A-Z) and digits (0-9) only
       - Chosen by the user when assigning project to a shuttle
       - Unique within a shuttle, but NOT globally unique
       - Example: Shuttle G801 and G802 can both have project "ABCD"
       - Used for human-readable identification on wafers/dies

    3. **full_id** (property) - Manufacturing Identifier
       - 8-character code: shuttle name (4 chars) + project_id (4 chars)
       - Example: "G801ABCD" (shuttle "G801" + project "ABCD")
       - Globally unique across all manufactured projects
       - Used for physical identification on manufactured wafers
       - Only available when project is assigned to a shuttle with a project_id

    Usage in Code
    -------------
    - Database queries: Use `id` (pk) - e.g., Project.objects.get(pk=uuid)
    - API requests: Use `id` (pk) as the identifier
    - User-facing displays: Use `project_id` or `full_id`
    - Manufacturing labels: Use `full_id`

    Field Immutability
    ------------------
    Fields are organized into three groups:

    - **System fields**: Managed by the system, not shown in forms
    - **Core fields**: Set at creation, immutable after (except by staff)
    - **User fields**: Always editable by project owner

    Core field immutability is enforced in clean() following Django's
    recommended pattern of using from_db() to track original values.
    See: https://docs.djangoproject.com/en/5.2/ref/models/instances/
    """

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

    # Field groups for form handling and immutability validation.
    # See class docstring "Field Immutability" section for details.
    SYSTEM_FIELDS = frozenset(
        {
            "id",
            "user",
            "status",
            "created_at",
            "updated_at",
            "submitted_at",
            "submitted_file",
            "proprietary_terms_cached",
            "proprietary_terms_cached_at",
        }
    )
    CORE_FIELDS = frozenset({"shuttle", "project_id", "slot_size"})
    USER_FIELDS = frozenset(
        {
            "name",
            "description",
            "is_public",
            "chip_on_board",
            "repository_url",
            "license_type",
            "other_license_spdx_id",
            "proprietary_terms_url",
        }
    )

    # Instance attributes for immutability validation (set by from_db and form.save)
    _loaded_values: dict[str, Any]
    _current_user: Any  # User instance passed from form for validation

    # See class docstring for explanation of different project identifiers
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Internal UUID primary key. Use for DB queries and API requests.",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="projects",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    slot_size = models.CharField(
        max_length=20,
        choices=SlotSize.choices,
        default=SlotSize.FULL,
        help_text="Die slot size for manufacturing",
    )

    # Shuttle assignment fields
    shuttle = models.ForeignKey(
        "shuttles.Shuttle",
        on_delete=models.PROTECT,
        related_name="projects",
        null=True,
        blank=True,
        help_text="Shuttle run this project is assigned to",
    )
    project_id = models.CharField(
        max_length=PROJECT_ID_LENGTH,
        blank=True,
        default="",
        validators=[validate_project_id],
        help_text=(
            "User-chosen 4-character code (A-Z, 0-9). "
            "Unique per shuttle, not globally. See class docstring."
        ),
        db_index=True,
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

    # NOTE: is_manufacturable, manufacturability_errors, and check_completed_at
    # are now derived properties (see @property methods below) that read from
    # the latest ManufacturabilityCheck on the submitted_file. This enables
    # multiple checks per file (retries, DRC updates, etc.) without losing history.

    # Visibility settings
    is_public = models.BooleanField(
        default=False,
        help_text="Whether this design should be publicly visible on the platform",
    )

    # Chip-on-Board packaging (Issue #259)
    chip_on_board = models.BooleanField(
        default=False,
        verbose_name="Request Chip-on-Board (CoB) packaging",
        help_text=(
            "Run extra Chip-on-Board (CoB) compatibility checks during the "
            "manufacturability precheck."
        ),
    )

    # Repository URL (Issue #137)
    repository_url = models.URLField(
        blank=True,
        max_length=500,
        help_text="URL to the project's source repository",
    )

    # License tracking (Issue #193)
    license_type = models.CharField(
        max_length=50,
        choices=LicenseType,
        default=LicenseType.PROPRIETARY,
        help_text="License under which this project is released",
    )
    other_license_spdx_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="SPDX identifier when license_type is 'Other'",
    )
    proprietary_terms_url = models.URLField(
        blank=True,
        max_length=500,
        help_text="URL to proprietary license terms",
    )
    proprietary_terms_cached = models.TextField(
        blank=True,
        help_text="Cached content from proprietary_terms_url",
    )
    proprietary_terms_cached_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When proprietary terms were last cached",
    )

    # Change history tracking
    history = HistoricalRecords()

    class Meta:
        verbose_name = "Project"
        verbose_name_plural = "Projects"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["shuttle", "project_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["shuttle", "project_id"],
                name="unique_project_id_per_shuttle",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.user.username})"

    def save(self, *args, **kwargs):
        """Save model, ensuring validation runs first."""
        self.full_clean()
        super().save(*args, **kwargs)
        # Capture current values for subsequent validation.
        # from_db() only runs when loading from database, but we also need
        # _loaded_values after create (for factories) and manual save().
        self._loaded_values = {
            "shuttle_id": self.shuttle_id,
            "project_id": self.project_id,
            "slot_size": self.slot_size,
            "proprietary_terms_url": self.proprietary_terms_url,
        }

    def clean(self):
        """Validate model, including core field immutability.

        Core fields (shuttle, project_id, slot_size) cannot be modified
        after creation except by staff users.
        """
        super().clean()
        if not self._state.adding:
            self._validate_core_fields_immutable()

    @classmethod
    def from_db(cls, db, field_names, values):
        """Capture original field values when loading from database.

        This follows Django's recommended pattern for tracking field changes
        to enforce immutability of CORE_FIELDS after creation.
        See: https://docs.djangoproject.com/en/5.2/ref/models/instances/
        """
        instance = super().from_db(db, field_names, values)
        instance._loaded_values = dict(  # noqa: SLF001 (Django pattern)
            zip(field_names, values, strict=False)
        )
        return instance

    def _validate_core_fields_immutable(self):
        """Raise ValidationError if non-staff user modifies core fields.

        Called by clean() for existing instances. Compares current values
        against _loaded_values captured by from_db().

        Uses fail-closed approach: if we can't determine the user is staff,
        modifications to core fields are blocked.
        """
        # Staff can modify anything
        current_user = getattr(self, "_current_user", None)
        if current_user and current_user.is_staff:
            logger.debug(
                "Skipping core field validation for staff user %s on project %s",
                current_user,
                self.pk,
            )
            return

        # Fail-closed: no user means no modifications allowed
        if current_user is None:
            logger.debug(
                "Core field validation for project %s: no _current_user set "
                "(treating as non-staff, modifications blocked)",
                self.pk,
            )

        loaded = getattr(self, "_loaded_values", {})
        if not loaded:
            # This shouldn't happen for existing instances loaded via QuerySet.
            # If it does, it's a programming error - the instance was modified
            # without being properly loaded from the database first.
            msg = (
                f"Cannot validate core field immutability for project {self.pk}: "
                "instance was not loaded via QuerySet (missing _loaded_values). "
                "Load the instance with Project.objects.get() before modifying."
            )
            raise RuntimeError(msg)

        changed = []
        for field in self.CORE_FIELDS:
            # Handle ForeignKey fields by comparing IDs
            # (loaded values use field_id for FK fields)
            if field == "shuttle":
                loaded_key = "shuttle_id"
                old_value = loaded.get(loaded_key)
                new_value = self.shuttle_id
            else:
                loaded_key = field
                old_value = loaded.get(loaded_key)
                new_value = getattr(self, field)

            if loaded_key not in loaded:
                continue
            if old_value != new_value:
                changed.append(field)

        if changed:
            msg = (
                f"Cannot modify {', '.join(changed)} after project creation. "
                "Contact staff for assistance."
            )
            raise ValidationError(msg)

    # Derived manufacturability properties (from latest check on submitted_file)
    @property
    def latest_manufacturability_check(self) -> "ManufacturabilityCheck | None":
        """Get the latest manufacturability check for this project's submitted file.

        Returns the most recent check on the submitted_file, or None if no
        submitted file or no checks exist.
        """
        if not self.submitted_file:
            return None
        return self.submitted_file.latest_manufacturability_check

    @property
    def is_manufacturable(self) -> bool | None:
        """Derived from latest completed check on submitted file."""
        check = self.latest_manufacturability_check
        if not check or check.status != ManufacturabilityCheck.Status.FINISHED:
            return None
        return check.is_manufacturable

    @property
    def manufacturability_errors(self) -> list[str]:
        """Derived from latest completed check."""
        check = self.latest_manufacturability_check
        if not check or check.status != ManufacturabilityCheck.Status.FINISHED:
            return []
        return check.errors

    @property
    def check_completed_at(self) -> datetime | None:
        """Derived from latest completed check."""
        check = self.latest_manufacturability_check
        if not check or check.status != ManufacturabilityCheck.Status.FINISHED:
            return None
        return check.analysis_completed_at

    @property
    def output_file(self) -> "ProjectFile":
        """Return file for manufacturing output (submitted or latest).

        Returns a dummy ProjectFile if no files exist.
        """
        if self.submitted_file:
            return self.submitted_file
        latest = self.files.order_by("-uploaded_at").first()
        if latest:
            return latest
        # Return unsaved dummy for consistent interface
        return ProjectFile(project=self, top_cell="")

    @property
    def full_id(self) -> str:
        """Return full 8-character manufacturing ID (shuttle code + project ID).

        Example: "G801ABCD"
        """
        if self.shuttle and self.project_id:
            return f"{self.shuttle.name}{self.project_id}"
        return ""

    @property
    def shuttle_positions(self) -> models.QuerySet:
        """Return all shuttle slots assigned to this project."""
        return self.shuttle_slots.all()

    @property
    def shuttle_run_display(self) -> str:
        """Return descriptive shuttle name.

        Example: "GF180MCU Shuttle 1: G801"
        """
        if self.shuttle:
            return f"{self.shuttle.description}: {self.shuttle.name}"
        return ""

    @property
    def slot_size_full_label(self) -> str:
        """Return full slot size label with dimensions.

        Use this for detailed displays like project creation/detail pages.
        For compact displays, use get_slot_size_display() instead.

        Example: "1×1 - Full Slot (3.88mm × 5.07mm = 19.67mm²)"
        """
        return SlotSize(self.slot_size).full_label

    @property
    def is_proprietary_license(self) -> bool:
        """Check if project uses proprietary license."""
        return self.license_type == LicenseType.PROPRIETARY

    @property
    def is_other_license(self) -> bool:
        """Check if project uses 'other' (custom SPDX) license."""
        return self.license_type == LicenseType.OTHER

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
        storage=ProjectFileStorage(),
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

    @property
    def latest_manufacturability_check(self) -> "ManufacturabilityCheck | None":
        """Get the most recent manufacturability check.

        Returns None if no checks exist yet.
        Ordered by -created_at (newest first).
        """
        return self.manufacturability_checks.order_by("-created_at").first()

    @property
    def output_check(self) -> "ManufacturabilityCheck":
        """Return latest finished check, or dummy if none exists.

        Always returns a ManufacturabilityCheck for consistent interface.
        Check if pk is set to determine if it's a real check.
        """
        if self.pk:  # Real file, not dummy
            check = (
                self.manufacturability_checks.filter(
                    status=ManufacturabilityCheck.Status.FINISHED
                )
                .order_by("-created_at")
                .first()
            )
            if check:
                return check
        # Return unsaved dummy for consistent interface
        return ManufacturabilityCheck(project=self.project, project_file=self)


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
    timestamp = instance.container_started_at or instance.created_at or timezone.now()
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


def manufacturability_check_output_gds_path(instance, filename):
    """Generate upload path for output GDS file.

    Output GDS contains the modified design with QR code and other additions.
    Format: projects/<project_id>/<gds_name>.<top_cell>.precheck.<timestamp>.output.gds

    Example: projects/abc123/design.gds.TOP_CELL.precheck.20251126_231820.output.gds
    """
    gds_name, top_cell, timestamp_str = _get_check_file_prefix(instance)
    filename = f"{gds_name}.{top_cell}.precheck.{timestamp_str}.output.gds"
    return f"projects/{instance.project.id}/{filename}"


def manufacturability_check_docker_layer_path(instance, filename):
    """Generate upload path for docker layer export.

    Docker layer export contains only the filesystem changes made during the run.
    Format: projects/<project_id>/<gds_name>.<top_cell>.precheck.<ts>.layer.tar.gz

    Example: projects/abc123/design.gds.TOP_CELL.precheck.20251126.layer.tar.gz
    """
    gds_name, top_cell, timestamp_str = _get_check_file_prefix(instance)
    filename = f"{gds_name}.{top_cell}.precheck.{timestamp_str}.layer.tar.gz"
    return f"projects/{instance.project.id}/{filename}"


class ManufacturabilityCheck(models.Model):
    """Track manufacturability checking process for projects."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"  # Waiting for capacity
        # Running states
        DISPATCHING = "dispatching", "Dispatching"  # Image being pulled
        STARTING = "starting", "Starting"  # Container being created
        RUNNING = "running", "Running"  # Celery worker executing
        ANALYZING = "analyzing", "Analyzing"  # Logs being analyzed
        CANCELLING = "cancelling", "Cancelling"  # Cleanup in progress
        # Terminal states
        CANCELLED = "cancelled", "Cancelled"  # User cancelled
        ERROR = "error", "Error"  # System/processing failure
        FINISHED = "finished", "Finished"  # Analysis complete

        @classmethod
        def display_order(cls) -> tuple[str, ...]:
            """Order to display states in."""
            return (
                cls.PENDING,
                cls.DISPATCHING,
                cls.STARTING,
                cls.RUNNING,
                cls.ANALYZING,
                cls.CANCELLING,
                cls.CANCELLED,
                cls.FINISHED,
                cls.ERROR,
            )

        @classmethod
        def all(cls) -> list[str]:
            """List of all the statuses."""
            return [choice[0] for choice in cls.choices]

        @classmethod
        def active(cls) -> list[str]:
            """Statuses where check is actively being processed.

            These statuses indicate work is happening - either on Docker or analysis.
            Used for concurrent limits and determining if a check is still running.
            """
            return [
                cls.DISPATCHING,
                cls.STARTING,
                cls.RUNNING,
                cls.ANALYZING,
                cls.CANCELLING,
            ]

        @classmethod
        def terminal(cls) -> list[str]:
            """Statuses that represent completion (success or failure)."""
            return [cls.FINISHED, cls.CANCELLED, cls.ERROR]

        @classmethod
        def in_progress(cls) -> list[str]:
            """Statuses where check is in progress (not yet completed)."""
            return [cls.PENDING, *cls.active()]

        @classmethod
        def non_terminal(cls) -> list[str]:
            """Statuses that are not terminal (check still in progress or pending).

            Used for admin status page to show all checks that haven't completed.
            Returns statuses in display_order, excluding terminal ones.
            """
            terminal_set = set(cls.terminal())
            return [s for s in cls.display_order() if s not in terminal_set]

    class TriggerReason(models.TextChoices):
        INITIAL = "initial", "Initial Check"
        DRC_UPDATE = "drc_update", "DRC Rules Updated"
        ADMIN_RERUN = "admin_rerun", "Admin Requested Re-run"
        RETRY = "retry", "Retry After Error"

    class FinishedStatus(models.TextChoices):
        """Sub-status for FINISHED checks indicating manufacturability result."""

        MANUFACTURABLE = "manufacturable", "Manufacturable"
        MANUFACTURABLE_WITH_WARNINGS = (
            "manufacturable_with_warnings",
            "Manufacturable (Warnings)",
        )
        NOT_MANUFACTURABLE = "not_manufacturable", "Not Manufacturable"

    # Status presentation metadata for consistent rendering across templates
    # Maps status values to their display properties
    _STATUS_METADATA: ClassVar[dict[str, dict[str, str | bool]]] = {
        Status.PENDING: {
            "color": "warning",
            "icon": "bi-clock",
            "label": "Pending",
            "show_spinner": False,
        },
        Status.DISPATCHING: {
            "color": "info",
            "icon": "bi-send",
            "label": "Dispatching",
            "show_spinner": True,
        },
        Status.STARTING: {
            "color": "info",
            "icon": "bi-box-arrow-up",
            "label": "Starting",
            "show_spinner": True,
        },
        Status.RUNNING: {
            "color": "primary",
            "icon": "bi-play-circle",
            "label": "Running",
            "show_spinner": True,
        },
        Status.ANALYZING: {
            "color": "primary",
            "icon": "bi-search",
            "label": "Analyzing",
            "show_spinner": True,
        },
        Status.FINISHED: {
            "color": "success",
            "icon": "bi-check-circle",
            "label": "Finished",
            "show_spinner": False,
        },
        Status.ERROR: {
            "color": "danger",
            "icon": "bi-exclamation-triangle",
            "label": "Error",
            "show_spinner": False,
        },
        Status.CANCELLING: {
            "color": "warning",
            "icon": "bi-x-circle",
            "label": "Cancelling",
            "show_spinner": True,
        },
        Status.CANCELLED: {
            "color": "secondary",
            "icon": "bi-x-circle",
            "label": "Cancelled",
            "show_spinner": False,
        },
    }

    # State machine: defines valid transitions
    # PENDING: waiting for capacity to dispatch
    # DISPATCHING: image being pulled
    # STARTING: container being created
    # RUNNING: container executing analysis
    # ANALYZING: logs being analyzed
    # FINISHED: analysis complete (terminal)
    # ERROR: system failure, can retry
    # CANCELLED: user cancelled (terminal)
    ALLOWED_TRANSITIONS: ClassVar[dict[Status, set[Status]]] = {
        Status.PENDING: {
            Status.DISPATCHING,
            Status.ERROR,
            Status.CANCELLING,
        },
        Status.DISPATCHING: {Status.STARTING, Status.ERROR, Status.CANCELLING},
        Status.STARTING: {Status.RUNNING, Status.ERROR, Status.CANCELLING},
        Status.RUNNING: {
            Status.ANALYZING,
            Status.ERROR,
            Status.CANCELLING,
        },
        Status.ANALYZING: {Status.FINISHED, Status.ERROR, Status.CANCELLING},
        Status.FINISHED: set(),  # Terminal - no transitions
        Status.ERROR: {Status.PENDING},  # Can retry
        Status.CANCELLING: {Status.CANCELLED},
        Status.CANCELLED: set(),  # Terminal - no transitions
    }

    # Maximum characters of processing logs to include in GitHub issue body
    GITHUB_ISSUE_LOG_CHARS: ClassVar[int] = 5000

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="manufacturability_checks",
    )
    project_file = models.ForeignKey(
        "ProjectFile",
        on_delete=models.CASCADE,
        related_name="manufacturability_checks",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    trigger_reason = models.CharField(
        max_length=20,
        choices=TriggerReason.choices,
        default=TriggerReason.INITIAL,
        help_text="Why this check was triggered",
    )
    parent_check = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="retry_checks",
        help_text="Original check this is a retry of (null if not a retry)",
    )

    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this check record was created",
    )

    # Docker container tracking
    docker_server_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=(
            "ID of Docker server running this check (from DOCKER_SERVERS setting)"
        ),
    )
    docker_container_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="ID of Docker container running the analysis",
    )

    # Granular timestamps for each phase
    dispatching_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When check entered DISPATCHING (image pull started)",
    )
    starting_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When check entered STARTING (container creation started)",
    )
    container_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When container was confirmed running",
    )
    container_finished_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When container exited",
    )
    analysis_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When log analysis completed",
    )

    # Docker exit code and log tracking
    docker_exit_code = models.IntegerField(
        null=True,
        blank=True,
        help_text="Exit code from Docker container",
    )
    logs_downloaded_until = models.FloatField(
        null=True,
        blank=True,
        help_text="Unix timestamp (with nanoseconds) for incremental log fetch",
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
        storage=ProjectFileStorage(),
        help_text="Log file stored on filesystem (next to GDS file)",
    )
    runs_archive = models.FileField(
        upload_to=manufacturability_check_runs_path,
        max_length=512,
        blank=True,
        storage=ProjectFileStorage(),
        help_text="Tar archive of detailed step logs from precheck runs/ directory",
    )
    output_gds = models.FileField(
        upload_to=manufacturability_check_output_gds_path,
        max_length=512,
        blank=True,
        storage=ProjectFileStorage(),
        help_text="Output GDS file from precheck (modified design with QR code, etc.)",
    )
    docker_layer_export = models.FileField(
        upload_to=manufacturability_check_docker_layer_path,
        max_length=512,
        blank=True,
        storage=ProjectFileStorage(),
        help_text="Compressed tarball of container filesystem changes for debugging",
    )

    # Checksums for output files (SHA256)
    log_file_sha256 = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="SHA256 checksum of log file",
    )
    runs_archive_sha256 = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="SHA256 checksum of runs archive",
    )
    output_gds_sha256 = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="SHA256 checksum of output GDS file",
    )
    docker_layer_sha256 = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="SHA256 checksum of docker layer export",
    )

    # System error tracking (distinct from manufacturing errors)
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="System error message if check failed to run (Docker, timeout, etc.)",
    )

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
        ordering = ["-created_at"]

    def __str__(self):
        return f"Check for {self.project.name} - {self.get_status_display()}"

    @classmethod
    def get_status_metadata(cls, status: str) -> dict[str, str | bool]:
        """Return presentation metadata for a status value.

        Args:
            status: A status value (e.g., 'pending', 'running')

        Returns:
            Dict with keys: color, icon, label, show_spinner

        Raises:
            KeyError: If status is not a valid ManufacturabilityCheck.Status value
        """
        if status not in cls._STATUS_METADATA:
            valid = list(cls._STATUS_METADATA.keys())
            msg = f"Unknown status '{status}'. Valid statuses: {valid}"
            raise KeyError(msg)
        return cls._STATUS_METADATA[status]

    @property
    def status_color(self) -> str:
        """Return Bootstrap color for current status (e.g., 'primary', 'warning')."""
        meta = self.get_status_metadata(self.status)
        return str(meta["color"])

    @property
    def status_icon(self) -> str:
        """Return Bootstrap icon class for current status (e.g., 'bi-clock')."""
        meta = self.get_status_metadata(self.status)
        return str(meta["icon"])

    @property
    def status_label(self) -> str:
        """Return human-readable label for current status."""
        meta = self.get_status_metadata(self.status)
        return str(meta["label"])

    @property
    def status_show_spinner(self) -> bool:
        """Return True if current status should display a spinner."""
        meta = self.get_status_metadata(self.status)
        return bool(meta["show_spinner"])

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

    def mark_dispatching(self, *, server_id: str) -> None:
        """Transition PENDING -> DISPATCHING with server assignment.

        Args:
            server_id: ID of the Docker server to run this check on.

        Raises:
            InvalidStateTransitionError: If not in PENDING status.
        """
        if not self.can_transition_to(self.Status.DISPATCHING):
            raise InvalidStateTransitionError(
                from_status=self.status,
                to_status=self.Status.DISPATCHING,
            )

        self.status = self.Status.DISPATCHING
        self.docker_server_id = server_id
        self.dispatching_started_at = timezone.now()
        self.save(
            update_fields=["status", "docker_server_id", "dispatching_started_at"]
        )

    def mark_starting(self, *, docker_image: str, docker_image_digest: str) -> None:
        """Transition DISPATCHING -> STARTING with image info.

        Args:
            docker_image: Full Docker image name with tag.
            docker_image_digest: Image digest (sha256:...).

        Raises:
            InvalidStateTransitionError: If not in DISPATCHING status.
        """
        if not self.can_transition_to(self.Status.STARTING):
            raise InvalidStateTransitionError(
                from_status=self.status,
                to_status=self.Status.STARTING,
            )

        self.status = self.Status.STARTING
        self.docker_image = docker_image
        self.docker_image_digest = docker_image_digest
        self.starting_started_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "docker_image",
                "docker_image_digest",
                "starting_started_at",
            ]
        )

    def mark_running(
        self,
        *,
        docker_container_id: str,
        docker_command: str,
    ) -> None:
        """Transition STARTING -> RUNNING with container info.

        Args:
            docker_container_id: Docker container ID.
            docker_command: Command executed in container (as string).

        Raises:
            InvalidStateTransitionError: If not in STARTING status.
        """
        if not self.can_transition_to(self.Status.RUNNING):
            raise InvalidStateTransitionError(
                from_status=self.status,
                to_status=self.Status.RUNNING,
            )

        self.status = self.Status.RUNNING
        self.docker_container_id = docker_container_id
        self.docker_command = docker_command
        self.container_started_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "docker_container_id",
                "docker_command",
                "container_started_at",
            ]
        )

    def mark_analyzing(self, *, docker_exit_code: int) -> None:
        """Transition RUNNING -> ANALYZING with exit code.

        Args:
            docker_exit_code: Container exit code.

        Raises:
            InvalidStateTransitionError: If not in RUNNING status.
        """
        if not self.can_transition_to(self.Status.ANALYZING):
            raise InvalidStateTransitionError(
                from_status=self.status,
                to_status=self.Status.ANALYZING,
            )

        self.status = self.Status.ANALYZING
        self.docker_exit_code = docker_exit_code
        self.container_finished_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "docker_exit_code",
                "container_finished_at",
            ]
        )

    def mark_finished(
        self,
        *,
        is_manufacturable: bool,
        errors: list[str],
        warnings: list[str],
        tool_versions: dict[str, str],
    ) -> None:
        """Transition ANALYZING -> FINISHED with analysis results.

        Args:
            is_manufacturable: Whether design is manufacturable.
            errors: List of error messages.
            warnings: List of warning messages.
            tool_versions: Tool versions used in analysis.

        Raises:
            InvalidStateTransitionError: If not in ANALYZING status.
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
        self.tool_versions = tool_versions
        self.analysis_completed_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "is_manufacturable",
                "errors",
                "warnings",
                "tool_versions",
                "analysis_completed_at",
            ]
        )

        # Update project status
        # Note: is_manufacturable, manufacturability_errors, and check_completed_at
        # are now derived properties on Project, so we only update the status.
        if is_manufacturable:
            self.project.status = Project.Status.MANUFACTURABLE
        else:
            self.project.status = Project.Status.NOT_MANUFACTURABLE
        self.project.save(update_fields=["status"])

    def mark_error(
        self,
        *,
        error_message: str,
        processing_logs: str = "",
    ) -> None:
        """Mark check as errored due to system failure.

        Pathways: PENDING/DISPATCHING/STARTING/RUNNING → ERROR

        Preserves tracking fields (docker_container_id) for debugging.

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

        # Set initial logs if provided
        if processing_logs:
            self.processing_logs = processing_logs

        self.save(
            update_fields=[
                "status",
                "error_message",
                "processing_logs",
            ]
        )

        # Append error marker using helper (after save to ensure fresh data)
        self.append_to_processing_logs("=== SYSTEM ERROR - See error_message field ===")

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
        self.save(update_fields=["status"])

        # Append cancellation reason using helper
        self.append_to_processing_logs(f"CANCELLATION REQUESTED: {reason}")

    def mark_cancelled(self) -> None:
        """Complete cancellation - only called by cleanup task after cleanup is done.

        This method should only be called from CANCELLING state, after the
        cleanup task has stopped any Docker container. It clears container
        tracking fields.

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        if not self.can_transition_to(self.Status.CANCELLED):
            raise InvalidStateTransitionError(
                from_status=self.status,
                to_status=self.Status.CANCELLED,
            )

        self.status = self.Status.CANCELLED
        # Clear container tracking fields (cleanup already done)
        self.docker_container_id = ""
        self.save(
            update_fields=[
                "status",
                "docker_container_id",
            ]
        )

    def append_to_processing_logs(self, text: str) -> None:
        """Append text to processing logs (thread-safe, never overwrites).

        This helper ensures logs are only ever appended to, never replaced.
        Safely handles empty logs and adds appropriate separators.

        Args:
            text: Text to append to logs
        """
        if not text:
            return

        # Refresh from DB to get current logs (prevent overwrite race conditions)
        self.refresh_from_db(fields=["processing_logs"])

        if self.processing_logs:
            self.processing_logs += f"\n\n{text}"
        else:
            self.processing_logs = text

        self.last_activity = timezone.now()
        self.save(update_fields=["processing_logs", "last_activity"])

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
    def title(self) -> str:
        """Human-readable title for this check.

        Format: "Check #<pk> (<created_at date>)"
        Example: "Check #10 (2025-12-02 18:22)"
        """
        date_str = date_format(self.created_at, "Y-m-d H:i") if self.created_at else ""
        return f"Check #{self.pk} ({date_str})"

    @property
    def root_check(self) -> "ManufacturabilityCheck":
        """Get the original check in a retry chain.

        For initial checks, returns self.
        For retries, walks up parent_check chain to find the root.
        """
        check = self
        while check.parent_check is not None:
            check = check.parent_check
        return check

    def create_check_drc_update(self) -> "ManufacturabilityCheck":
        """Create a new pending check to re-run with latest precheck version.

        If this check is still in progress, it will be automatically cancelled
        by the existing superseded check cleanup logic.

        Returns:
            The newly created ManufacturabilityCheck.

        Raises:
            ValueError: If this check is not eligible for DRC update.
        """
        # Must be the latest check for this project file
        latest = self.project_file.latest_manufacturability_check
        if latest != self:
            msg = "Can only create DRC update from the latest check for a file"
            raise ValueError(msg)

        # Must have a known version
        if not self.docker_image_digest:
            msg = "Check does not have a version yet"
            raise ValueError(msg)

        # Must have outdated digest
        if self.is_using_latest_precheck is not False:
            msg = "Check is already using latest precheck version"
            raise ValueError(msg)

        return ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            trigger_reason=self.TriggerReason.DRC_UPDATE,
            parent_check=self,
        )

    @property
    def queue_wait_seconds(self) -> float | None:
        """Time spent waiting in queue before running (in seconds).

        Calculated as: container_started_at - created_at
        For checks still waiting: now - created_at
        Returns None if created_at is not set.
        """
        if not self.created_at:
            return None

        if self.container_started_at:
            delta = self.container_started_at - self.created_at
            return delta.total_seconds()

        # Still waiting - show time since creation
        waiting_statuses = [
            self.Status.PENDING,
            self.Status.DISPATCHING,
            self.Status.STARTING,
        ]
        if self.status in waiting_statuses:
            delta = timezone.now() - self.created_at
            return delta.total_seconds()

        return None

    @property
    def state_entered_at(self) -> datetime | None:
        """Timestamp when the check entered its current state.

        Returns the appropriate timestamp based on current status:
        - pending: created_at
        - dispatching: dispatching_started_at
        - starting: starting_started_at
        - running: container_started_at
        - analyzing: container_finished_at
        - finished: analysis_completed_at
        - error/cancelling/cancelled: created_at (fallback)
        """
        status_to_timestamp: dict[str, datetime | None] = {
            self.Status.PENDING: self.created_at,
            self.Status.DISPATCHING: self.dispatching_started_at,
            self.Status.STARTING: self.starting_started_at,
            self.Status.RUNNING: self.container_started_at,
            self.Status.ANALYZING: self.container_finished_at,
            self.Status.FINISHED: self.analysis_completed_at,
        }
        return status_to_timestamp.get(self.status) or self.created_at

    @property
    def run_duration_seconds(self) -> float | None:
        """Time the container spent running (in seconds).

        Calculated as: container_finished_at - container_started_at
        For checks still running: now - container_started_at
        Returns None if container hasn't started.
        """
        if not self.container_started_at:
            return None

        if self.container_finished_at:
            delta = self.container_finished_at - self.container_started_at
            return delta.total_seconds()

        # Still running - show time since container started
        if self.status == self.Status.RUNNING:
            delta = timezone.now() - self.container_started_at
            return delta.total_seconds()

        return None

    @property
    def retry_delay_seconds(self) -> float | None:
        """Time between parent check completion and this check's creation.

        Only applicable for retry checks (has parent_check).
        Returns None if not a retry or if timestamps unavailable.
        """
        if not self.parent_check or not self.created_at:
            return None

        # Use parent's container_finished_at or analysis_completed_at
        parent_end = (
            self.parent_check.analysis_completed_at
            or self.parent_check.container_finished_at
        )
        if not parent_end:
            return None

        delta = self.created_at - parent_end
        return delta.total_seconds()

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
    def finished_status(self) -> FinishedStatus | None:
        """Return FinishedStatus enum value for completed checks.

        Returns None if check is not in FINISHED state.
        """
        if self.status != self.Status.FINISHED or self.is_manufacturable is None:
            return None

        if self.is_manufacturable:
            if self.warnings:
                return self.FinishedStatus.MANUFACTURABLE_WITH_WARNINGS
            return self.FinishedStatus.MANUFACTURABLE
        return self.FinishedStatus.NOT_MANUFACTURABLE

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
        """Get number of checks currently active (DISPATCHING/STARTING/RUNNING)."""
        return ManufacturabilityCheck.objects.filter(
            status__in=self.Status.active(),
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
    --id {self.project.full_id}
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

    @classmethod
    def get_latest_precheck_digest(cls) -> str | None:
        """Get the digest of the most recently used precheck image.

        Returns the docker_image_digest from the check with the most recent
        container_started_at timestamp. Excludes checks that never started
        (NULL container_started_at). Cached for 60 seconds.
        """
        cache_key = "precheck_latest_digest"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached or None

        digest = (
            cls.objects.exclude(docker_image_digest="")
            .exclude(container_started_at__isnull=True)
            .order_by("-container_started_at")
            .values_list("docker_image_digest", flat=True)
            .first()
        )

        cache.set(cache_key, digest or "", 60)  # 1 minute TTL
        return digest

    @property
    def is_using_latest_precheck(self) -> bool | None:
        """Whether this check used the latest precheck image version.

        Returns:
            True - used latest version
            False - used outdated version
            None - cannot determine (no digest or no latest known)
        """
        if not self.docker_image_digest:
            return None
        latest = self.get_latest_precheck_digest()
        if latest is None:
            return None
        return self.docker_image_digest == latest

    @property
    def precheck_revision(self) -> "PrecheckImageRevision | None":
        """Get the PrecheckImageRevision for this check, if cataloged."""
        if not self.docker_image_digest:
            return None
        return PrecheckImageRevision.objects.filter(
            digest=self.docker_image_digest
        ).first()


class ManufacturabilityCheckTask(models.Model):
    """Tracks pending/running Celery tasks for manufacturability checks.

    Ephemeral - rows are deleted when tasks complete. Used to prevent
    duplicate task queuing.
    """

    manufacturability_check = models.OneToOneField(
        ManufacturabilityCheck,
        on_delete=models.CASCADE,
        related_name="pending_task",
    )
    task_id = models.CharField(
        max_length=255,
        help_text="Celery task ID",
    )
    task_name = models.CharField(
        max_length=255,
        help_text="Name of the Celery task (e.g., do_running)",
    )
    queued_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the task was queued",
    )

    class Meta:
        verbose_name = "Manufacturability Check Task"
        verbose_name_plural = "Manufacturability Check Tasks"

    def __str__(self) -> str:
        return f"{self.task_name} for check {self.manufacturability_check_id}"


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

    # Raw Docker stats response for debugging
    raw_stats_json = models.JSONField(
        null=True,
        blank=True,
        help_text="Raw Docker stats API response for debugging",
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


class PrecheckImageRevision(models.Model):
    """
    Catalog of known precheck Docker image versions.

    Populated asynchronously when new digests are discovered from completed
    ManufacturabilityChecks. Linked by digest string match, NOT foreign key.
    """

    # Primary identifier - the immutable digest
    digest = models.CharField(
        max_length=100,
        unique=True,
        help_text="SHA256 digest (e.g., sha256:abc123...)",
    )

    # When we first saw this digest used in a check
    first_seen_at = models.DateTimeField(auto_now_add=True)

    # Metadata fetched from GHCR/GitHub
    image_created_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the image was pushed to GHCR",
    )
    git_commit_sha = models.CharField(
        max_length=40,
        blank=True,
        help_text="Git commit from image labels",
    )

    # Version information
    precheck_version = models.CharField(
        max_length=50,
        blank=True,
        help_text="Precheck tool version (e.g., 1.5.2)",
    )
    pdk_version = models.CharField(
        max_length=50,
        blank=True,
        help_text="PDK version (if available)",
    )
    tool_versions = models.JSONField(
        default=dict,
        blank=True,
        help_text="Tool versions dict (e.g., {magic: '8.3.x', klayout: '0.28.x'})",
    )

    # Git commit info
    commit_message = models.CharField(
        max_length=255,
        blank=True,
        help_text="First line of git commit message",
    )
    commit_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the git commit was made",
    )

    # Tracking
    metadata_fetched_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When GHCR metadata was last fetched",
    )

    class Meta:
        ordering = ["-first_seen_at"]
        indexes = [
            models.Index(fields=["digest"]),
            models.Index(fields=["-first_seen_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.short_digest} (seen {self.first_seen_at.date()})"

    # --- URL helpers ---

    @property
    def github_commit_url(self) -> str | None:
        """URL to the specific commit, or None if unknown."""
        if not self.git_commit_sha:
            return None
        return f"https://github.com/{PRECHECK_GITHUB_REPO}/commit/{self.git_commit_sha}"

    @property
    def ghcr_package_url(self) -> str:
        """URL to the package on GitHub Container Registry."""
        return f"https://github.com/{PRECHECK_GITHUB_REPO}/pkgs/container/gf180mcu-precheck"

    @property
    def short_digest(self) -> str:
        """Truncated digest for display."""
        assert self.digest
        assert self.digest.startswith("sha256:")
        return f"sha256:{self.digest[7:19]}..."

    @property
    def version_display(self) -> str:
        """Human-readable version string for display."""
        if self.precheck_version:
            return self.precheck_version
        if self.git_commit_sha:
            return self.git_commit_sha[:7]
        return self.short_digest

    @classmethod
    def format_version_display(
        cls, check_or_digest: "ManufacturabilityCheck | str | None"
    ) -> tuple[str, bool | None]:
        """Format version display string and is_latest flag for a check or digest.

        Args:
            check_or_digest: A ManufacturabilityCheck, digest string, or None.

        Returns:
            Tuple of (display_string, is_latest_flag).
            display_string is always a valid string for display.
            is_latest_flag is True/False/None (None if cannot determine).
        """
        if check_or_digest is None:
            return ("-", None)

        if isinstance(check_or_digest, str):
            digest = check_or_digest
            latest = ManufacturabilityCheck.get_latest_precheck_digest()
            is_latest = (digest == latest) if digest and latest else None
        else:
            digest = check_or_digest.docker_image_digest
            is_latest = check_or_digest.is_using_latest_precheck

        if not digest:
            return ("-", None)

        cache_key = f"precheck_display:{digest}"
        cached = cache.get(cache_key)
        if cached:
            return (cached, is_latest)

        revision = cls.objects.filter(digest=digest).first()
        display = revision.version_display if revision else f"sha256:{digest[7:19]}..."

        cache.set(cache_key, display, 60)
        return (display, is_latest)

    # --- Statistics helpers ---

    def _get_checks_queryset(self) -> models.QuerySet["ManufacturabilityCheck"]:
        """Get all ManufacturabilityChecks that used this revision."""
        return ManufacturabilityCheck.objects.filter(docker_image_digest=self.digest)

    @property
    def checks_count(self) -> int:
        """Total number of checks that used this revision."""
        return self._get_checks_queryset().count()

    @property
    def checks_passed_count(self) -> int:
        """Number of checks that passed with this revision."""
        return self._get_checks_queryset().filter(is_manufacturable=True).count()

    @property
    def checks_failed_count(self) -> int:
        """Number of checks that failed with this revision."""
        return self._get_checks_queryset().filter(is_manufacturable=False).count()

    def get_run_duration_stats(self) -> dict[str, float | None]:
        """Get average and max run duration for checks using this revision.

        Returns:
            {"average": float|None, "max": float|None} in seconds
        """
        completed = self._get_checks_queryset().filter(
            status=ManufacturabilityCheck.Status.FINISHED,
            container_started_at__isnull=False,
            container_finished_at__isnull=False,
        )

        stats = completed.aggregate(
            avg_duration=models.Avg(
                models.F("container_finished_at") - models.F("container_started_at")
            ),
            max_duration=models.Max(
                models.F("container_finished_at") - models.F("container_started_at")
            ),
        )

        return {
            "average": (
                stats["avg_duration"].total_seconds() if stats["avg_duration"] else None
            ),
            "max": (
                stats["max_duration"].total_seconds() if stats["max_duration"] else None
            ),
        }
