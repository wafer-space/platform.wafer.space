from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from wafer_space.core.enums import SlotSize
from wafer_space.projects.models import Project

if TYPE_CHECKING:
    from wafer_space.users.models import User

# Shuttle ID format constants
SHUTTLE_ID_LENGTH = 4
SHUTTLE_ID_MIN_NUMBER = 0
SHUTTLE_ID_MAX_NUMBER = 99

# Grid positioning constants
ALPHABET_SIZE = 26  # Number of letters in alphabet (A-Z)


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
    description = models.TextField(
        help_text="Human-readable description (e.g., 'GF180MCU Shuttle Run 1')",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PLANNING,
    )

    # Grid configuration
    grid_config_file = models.CharField(
        max_length=255,
        blank=True,
        help_text="Path to YAML grid configuration (e.g., shuttles/G801-layout.yaml)",
    )

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
        return f"{self.name} - {self.description}"

    def save(self, *args, **kwargs):
        """Save with validation - ensures shuttle ID format is always enforced."""
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def max_slots(self) -> int:
        """Total number of slots derived from ShuttleSlot records."""
        return self.slots.count()

    @property
    def reserved_slots(self) -> int:
        """Number of reserved slots."""
        return self.slots.filter(status=ShuttleSlot.Status.RESERVED).count()

    @property
    def available_slots(self) -> int:
        """Number of available slots."""
        return self.slots.filter(status=ShuttleSlot.Status.AVAILABLE).count()

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

    def get_available_slot_sizes(self) -> list[str]:
        """Get list of slot sizes that have available slots.

        Returns:
            List of SlotSize values (e.g., ['1x1', '0p5x1']) that have at least
            one available slot on this shuttle.
        """
        available_sizes = (
            self.slots.filter(status=ShuttleSlot.Status.AVAILABLE)
            .values_list("slot_size", flat=True)
            .distinct()
        )
        return list(available_sizes)

    @property
    def grid_dimensions(self) -> tuple[int, int]:
        """Get grid dimensions as (num_rows, num_columns)."""
        aggregates = self.slots.aggregate(
            max_row=models.Max("row"),
            max_col=models.Max("column"),
        )
        max_row = aggregates["max_row"]
        max_col = aggregates["max_col"]
        if max_row is None or max_col is None:
            return (0, 0)
        return (max_row + 1, max_col + 1)

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

            user_name = (
                slot.project.user.username if hasattr(slot.project, "user") else None
            )
            project_data: dict[str, str | None] = {
                "grid_position": slot.grid_position,
                "project_id": str(slot.project.id),
                "project_name": slot.project.name,
                "user": user_name,
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

    # Grid positioning
    row = models.PositiveIntegerField(
        help_text="Grid row index (0-based)",
        default=0,
    )
    column = models.PositiveIntegerField(
        help_text="Grid column index (0-based)",
        default=0,
    )
    slot_size = models.CharField(
        max_length=20,
        choices=SlotSize.choices,
        help_text="Physical size of this grid cell",
        default=SlotSize.FULL,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Shuttle Slot"
        verbose_name_plural = "Shuttle Slots"
        ordering = ["shuttle", "row", "column"]
        unique_together = [("shuttle", "row", "column")]
        indexes = [
            models.Index(fields=["shuttle", "status"]),
            models.Index(fields=["shuttle", "row", "column"]),
        ]

    def __str__(self):
        project_name = self.project.name if self.project else "Empty"
        return f"{self.shuttle.name} {self.grid_position} - {project_name}"

    @property
    def grid_position(self) -> str:
        """Return spreadsheet-style position (A1, B2, etc.)."""
        if self.column < ALPHABET_SIZE:
            column_letter = chr(65 + self.column)
        else:
            column_letter = self.column_to_letters(self.column)
        return f"{column_letter}{self.row + 1}"

    @staticmethod
    def column_to_letters(column: int) -> str:
        """Convert column index to letters for columns > 25 (AA, AB, etc.)."""
        result = ""
        while column >= 0:
            result = chr(65 + (column % 26)) + result
            column = column // 26 - 1
        return result

    @property
    def short_size_display(self) -> str:
        """Return short human-readable size (e.g., '1×1', '0.5×1')."""
        return self.get_slot_size_display()

    def reserve(self, project: Project, user: User) -> str | None:
        """Reserve this slot for a project with size validation.

        Allows reassignment: if the slot is already reserved, the existing
        assignment will be replaced with the new project.
        """
        warnings = []
        is_reassignment = False

        # Handle reassignment case
        if self.status == self.Status.RESERVED:
            if self.project == project:
                # Already assigned to this project - no-op
                return None
            # Reassigning to a different project (no warning needed)
            is_reassignment = True
        elif self.status != self.Status.AVAILABLE:
            # Other statuses (OCCUPIED, CANCELLED) are not reassignable
            msg = "Slot is not available"
            raise ValueError(msg)

        # For new reservations, check can_accept_projects (includes available_slots > 0)
        # For reassignment, only check shuttle status and deadline (not available slots)
        shuttle = self.shuttle
        if is_reassignment:
            # Check shuttle is still open
            if shuttle.status != Shuttle.Status.OPEN:
                msg = "Shuttle is not open for assignments"
                raise ValueError(msg)
            # Check deadline hasn't passed
            deadline = shuttle.submission_deadline
            if deadline and timezone.now() >= deadline:
                msg = "Shuttle submission deadline has passed"
                raise ValueError(msg)
        elif not shuttle.can_accept_projects():
            msg = "Shuttle is not accepting projects"
            raise ValueError(msg)

        # Check for size mismatch (warning only, not blocking)
        if hasattr(project, "slot_size") and project.slot_size != self.slot_size:
            warnings.append(
                f"Size mismatch: Project is {project.slot_size} "
                f"but slot is {self.slot_size}"
            )

        # Assign project (no status change on project)
        self.project = project
        self.reserved_by = user
        self.status = self.Status.RESERVED
        self.reserved_at = timezone.now()
        self.save()

        return " | ".join(warnings) if warnings else None

    def cancel_reservation(self) -> None:
        """Cancel this slot's reservation."""
        self.project = None
        self.reserved_by = None
        self.reserved_at = None
        self.status = self.Status.AVAILABLE
        self.save()


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
