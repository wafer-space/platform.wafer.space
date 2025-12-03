from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from wafer_space.projects.models import Project

# Shuttle ID format constants
SHUTTLE_ID_LENGTH = 4
SHUTTLE_ID_MIN_NUMBER = 0
SHUTTLE_ID_MAX_NUMBER = 99


def validate_shuttle_id(value: str) -> None:
    """Validate shuttle ID format (G8XX where XX are two digits).

    Valid examples: G800, G801, G802, ..., G899
    """
    if len(value) != SHUTTLE_ID_LENGTH:
        msg = "Shuttle ID must be exactly 4 characters"
        raise ValidationError(msg)

    if not value.startswith("G8"):
        msg = "Shuttle ID must start with 'G8'"
        raise ValidationError(msg)

    # Check last two characters are digits
    suffix = value[2:]
    if not suffix.isdigit():
        msg = (
            f"Shuttle ID must end with two digits "
            f"({SHUTTLE_ID_MIN_NUMBER:02d}-{SHUTTLE_ID_MAX_NUMBER:02d})"
        )
        raise ValidationError(msg)

    # Validate range 00-99
    try:
        number = int(suffix)
        if not SHUTTLE_ID_MIN_NUMBER <= number <= SHUTTLE_ID_MAX_NUMBER:
            msg = (
                f"Shuttle ID suffix must be between "
                f"{SHUTTLE_ID_MIN_NUMBER:02d} and {SHUTTLE_ID_MAX_NUMBER:02d}"
            )
            raise ValidationError(msg)
    except ValueError as e:
        msg = "Shuttle ID must end with valid two-digit number"
        raise ValidationError(msg) from e


class Shuttle(models.Model):
    """Manufacturing runs that combine multiple projects."""

    class Status(models.TextChoices):
        PLANNING = "planning", "Planning"
        OPEN = "open", "Open for Submissions"
        FULL = "full", "Full"
        LOCKED = "locked", "Locked"
        IN_PRODUCTION = "production", "In Production"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    name = models.CharField(
        max_length=SHUTTLE_ID_LENGTH,
        unique=True,
        validators=[validate_shuttle_id],
        help_text="Shuttle ID (format: G8XX where XX are two digits, e.g., G801)",
    )
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PLANNING,
    )

    # Capacity and scheduling
    max_slots = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(1000)],
    )
    reserved_slots = models.PositiveIntegerField(default=0)
    available_slots = models.PositiveIntegerField(default=0)

    # Important dates
    created_at = models.DateTimeField(auto_now_add=True)
    submission_deadline = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Deadline for project submissions",
    )
    production_start_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Expected production start date",
    )
    estimated_completion_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Estimated completion date",
    )
    actual_completion_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Actual completion date",
    )

    # Manufacturing details
    technology_node = models.CharField(
        max_length=50,
        blank=True,
        help_text="Manufacturing technology node (e.g., 180nm, 65nm)",
    )
    foundry = models.CharField(
        max_length=100,
        blank=True,
        help_text="Manufacturing foundry",
    )
    wafer_size = models.CharField(
        max_length=20,
        blank=True,
        help_text="Wafer size (e.g., 8 inch, 12 inch)",
    )

    # Cost information
    total_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    cost_per_slot = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Shuttle"
        verbose_name_plural = "Shuttles"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "submission_deadline"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        """Save with validation - ensures shuttle ID format is always enforced."""
        self.full_clean()
        super().save(*args, **kwargs)

    def update_slot_counts(self):
        """Update reserved and available slot counts."""
        self.reserved_slots = self.slots.filter(
            status=ShuttleSlot.Status.RESERVED,
        ).count()
        self.available_slots = self.max_slots - self.reserved_slots

        # Update status based on capacity
        if self.available_slots == 0 and self.status == self.Status.OPEN:
            self.status = self.Status.FULL
        elif self.available_slots > 0 and self.status == self.Status.FULL:
            self.status = self.Status.OPEN

        self.save()

    def can_accept_projects(self):
        """Check if shuttle can accept new projects."""
        return (
            self.status in [self.Status.OPEN]
            and self.available_slots > 0
            and (
                not self.submission_deadline
                or timezone.now() < self.submission_deadline
            )
        )

    def generate_manifest(self) -> dict[str, str | int | list[dict[str, str | None]]]:
        """Generate manifest data for production."""
        slots = self.slots.filter(status=ShuttleSlot.Status.RESERVED).select_related(
            "project",
        )

        manifest_data: dict[str, str | int | list[dict[str, str | None]]] = {
            "shuttle_name": self.name,
            "generated_at": timezone.now().isoformat(),
            "technology_node": self.technology_node,
            "foundry": self.foundry,
            "wafer_size": self.wafer_size,
            "total_slots": self.max_slots,
            "reserved_slots": self.reserved_slots,
            "projects": [],
        }

        projects_list: list[dict[str, str | None]] = []
        for slot in slots:
            # Skip slots without projects (defensive programming)
            if not slot.project:
                continue

            project_data: dict[str, str | None] = {
                "slot_number": str(slot.slot_number),
                "project_id": str(slot.project.id),
                "project_name": slot.project.name,
                "user": slot.project.user.username,
                "reserved_at": slot.reserved_at.isoformat()
                if slot.reserved_at
                else None,
            }
            projects_list.append(project_data)

        manifest_data["projects"] = projects_list
        return manifest_data


class ShuttleSlot(models.Model):
    """Individual slots within a shuttle for projects."""

    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        RESERVED = "reserved", "Reserved"
        OCCUPIED = "occupied", "Occupied"
        CANCELLED = "cancelled", "Cancelled"

    shuttle = models.ForeignKey(
        Shuttle,
        on_delete=models.CASCADE,
        related_name="slots",
    )
    slot_number = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shuttle_slots",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
    )

    # Reservation details
    reserved_at = models.DateTimeField(null=True, blank=True)
    reserved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reserved_slots",
    )

    # Slot positioning (for layout purposes)
    position_x = models.FloatField(null=True, blank=True)
    position_y = models.FloatField(null=True, blank=True)
    width = models.FloatField(null=True, blank=True)
    height = models.FloatField(null=True, blank=True)

    class Meta:
        verbose_name = "Shuttle Slot"
        verbose_name_plural = "Shuttle Slots"
        ordering = ["shuttle", "slot_number"]
        unique_together = ["shuttle", "slot_number"]
        indexes = [
            models.Index(fields=["shuttle", "status"]),
            models.Index(fields=["project", "status"]),
        ]

    def __str__(self):
        project_name = self.project.name if self.project else "Empty"
        return f"{self.shuttle.name} Slot {self.slot_number} - {project_name}"

    def reserve(self, project, user):
        """Reserve this slot for a project."""
        if self.status != self.Status.AVAILABLE:
            msg = "Slot is not available for reservation"
            raise ValueError(msg)

        if not self.shuttle.can_accept_projects():
            msg = "Shuttle is not accepting new projects"
            raise ValueError(msg)

        # NEW: Check compliance certification
        if not hasattr(project, "compliance_certification"):
            msg = "Project must have compliance certification before shuttle assignment"
            raise ValueError(msg)

        cert = project.compliance_certification
        if not (cert.export_control_compliant and cert.not_restricted_entity):
            msg = "Compliance certification is incomplete"
            raise ValueError(msg)

        if not cert.end_use_statement.strip():
            msg = "End-use statement is required"
            raise ValueError(msg)

        self.project = project
        self.reserved_by = user
        self.status = self.Status.RESERVED
        self.reserved_at = timezone.now()
        self.save()

        # Update project status
        project.status = Project.Status.ASSIGNED_TO_SHUTTLE
        project.save()

        # Update shuttle slot counts
        self.shuttle.update_slot_counts()

    def cancel_reservation(self):
        """Cancel the reservation for this slot."""
        if self.status != self.Status.RESERVED:
            msg = "Slot is not currently reserved"
            raise ValueError(msg)

        # Update project status back to manufacturable
        if self.project:
            self.project.status = Project.Status.MANUFACTURABLE
            self.project.save()

        self.project = None
        self.reserved_by = None
        self.status = self.Status.AVAILABLE
        self.reserved_at = None
        self.save()

        # Update shuttle slot counts
        self.shuttle.update_slot_counts()


class ShuttleManifest(models.Model):
    """Generated manifests for shuttles going to production."""

    shuttle = models.ForeignKey(
        Shuttle,
        on_delete=models.CASCADE,
        related_name="manifests",
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    manifest_data = models.JSONField()
    file_path = models.CharField(max_length=500, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "Shuttle Manifest"
        verbose_name_plural = "Shuttle Manifests"
        ordering = ["-generated_at"]
        unique_together = ["shuttle", "version"]

    def __str__(self):
        return f"{self.shuttle.name} Manifest v{self.version}"
