# Phase B: Shuttle Grid Layout & Slot Assignment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable staff to configure shuttle grid layouts via YAML and assign projects to specific grid positions with visual feedback.

**Architecture:** Add row/column positioning to ShuttleSlot model, create YAML-based grid configuration system, build staff interface with assignment table and read-only grid preview, implement size-aware slot assignment with warnings but no blocking.

**Tech Stack:** Django 5.2, PostgreSQL, YAML, HTMX (for grid updates), Bootstrap 5

---

## Task 1: Data Model - Add Grid Positioning to ShuttleSlot

**Files:**
- Modify: `wafer_space/shuttles/models.py` (ShuttleSlot and Shuttle models)
- Create: `wafer_space/shuttles/tests/test_grid_positioning.py`
- Create migration: `wafer_space/shuttles/migrations/0003_shuttleslot_grid_positioning.py`

**Step 1: Write failing test for grid_position property**

Create `wafer_space/shuttles/tests/test_grid_positioning.py`:

```python
import pytest
from wafer_space.shuttles.models import Shuttle, ShuttleSlot
from wafer_space.core.enums import SlotSize


@pytest.mark.django_db
class TestGridPositioning:
    """Test ShuttleSlot grid positioning functionality."""

    def test_grid_position_single_letter(self):
        """Grid position should return spreadsheet-style notation (A1, B2, etc.)."""
        shuttle = Shuttle.objects.create(
            name="G801",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        assert slot.grid_position == "A1"

    def test_grid_position_various_coordinates(self):
        """Test various row/column combinations."""
        shuttle = Shuttle.objects.create(
            name="G802",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )

        test_cases = [
            (0, 0, "A1"),  # First cell
            (0, 1, "B1"),  # Second column
            (1, 0, "A2"),  # Second row
            (2, 3, "D3"),  # Mid-grid
            (0, 25, "Z1"),  # Last single letter
        ]

        for row, col, expected in test_cases:
            slot = ShuttleSlot.objects.create(
                shuttle=shuttle,
                row=row,
                column=col,
                slot_size=SlotSize.FULL,
                status=ShuttleSlot.Status.AVAILABLE,
            )
            assert slot.grid_position == expected, f"Failed for row={row}, col={col}"

    def test_unique_together_constraint(self):
        """Each (shuttle, row, column) combination must be unique."""
        shuttle = Shuttle.objects.create(
            name="G803",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )

        # Creating duplicate should raise IntegrityError
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            ShuttleSlot.objects.create(
                shuttle=shuttle,
                row=0,
                column=0,
                slot_size=SlotSize.QUARTER,
                status=ShuttleSlot.Status.AVAILABLE,
            )

    def test_slots_ordered_by_position(self):
        """Slots should be ordered by shuttle, row, then column."""
        shuttle = Shuttle.objects.create(
            name="G804",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )

        # Create slots in random order
        slot_b2 = ShuttleSlot.objects.create(
            shuttle=shuttle, row=1, column=1, slot_size=SlotSize.FULL, status=ShuttleSlot.Status.AVAILABLE
        )
        slot_a1 = ShuttleSlot.objects.create(
            shuttle=shuttle, row=0, column=0, slot_size=SlotSize.FULL, status=ShuttleSlot.Status.AVAILABLE
        )
        slot_a2 = ShuttleSlot.objects.create(
            shuttle=shuttle, row=1, column=0, slot_size=SlotSize.FULL, status=ShuttleSlot.Status.AVAILABLE
        )

        # Query should return in order
        slots = list(ShuttleSlot.objects.all())
        assert slots == [slot_a1, slot_a2, slot_b2]
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest wafer_space/shuttles/tests/test_grid_positioning.py -v
```

Expected: FAIL - "ShuttleSlot has no attribute 'row'", "ShuttleSlot has no attribute 'column'", "ShuttleSlot has no attribute 'slot_size'", "ShuttleSlot has no attribute 'grid_position'"

**Step 3: Create migration for new fields**

```bash
uv run python manage.py makemigrations shuttles --name shuttleslot_grid_positioning
```

Edit the generated migration to:
1. Add new fields: `row`, `column`, `slot_size`
2. Remove old fields: `slot_number`, `position_x`, `position_y`, `width`, `height`
3. Add unique_together constraint
4. Add indexes

Expected migration structure:

```python
# Generated migration
operations = [
    # Add new fields
    migrations.AddField(
        model_name='shuttleslot',
        name='row',
        field=models.PositiveIntegerField(
            validators=[MinValueValidator(0)],
            help_text="Grid row index (0-based)",
            default=0,
        ),
        preserve_default=False,
    ),
    migrations.AddField(
        model_name='shuttleslot',
        name='column',
        field=models.PositiveIntegerField(
            validators=[MinValueValidator(0)],
            help_text="Grid column index (0-based)",
            default=0,
        ),
        preserve_default=False,
    ),
    migrations.AddField(
        model_name='shuttleslot',
        name='slot_size',
        field=models.CharField(
            max_length=20,
            choices=SlotSize.choices,
            help_text="Physical size of this grid cell",
            default=SlotSize.FULL,
        ),
        preserve_default=False,
    ),
    # Remove old fields
    migrations.RemoveField(model_name='shuttleslot', name='slot_number'),
    migrations.RemoveField(model_name='shuttleslot', name='position_x'),
    migrations.RemoveField(model_name='shuttleslot', name='position_y'),
    migrations.RemoveField(model_name='shuttleslot', name='width'),
    migrations.RemoveField(model_name='shuttleslot', name='height'),
    # Add constraints
    migrations.AlterUniqueTogether(
        name='shuttleslot',
        unique_together={('shuttle', 'row', 'column')},
    ),
    migrations.AddIndex(
        model_name='shuttleslot',
        index=models.Index(fields=['shuttle', 'row', 'column'], name='shuttles_sh_shuttle_idx'),
    ),
]
```

**Step 4: Update ShuttleSlot model**

Modify `wafer_space/shuttles/models.py`:

```python
from django.core.validators import MinValueValidator
from wafer_space.core.enums import SlotSize


class ShuttleSlot(models.Model):
    """Represents a single slot position in a shuttle's grid layout."""

    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        RESERVED = "reserved", "Reserved"
        OCCUPIED = "occupied", "Occupied"

    shuttle = models.ForeignKey(
        Shuttle,
        on_delete=models.CASCADE,
        related_name="slots",
    )
    project = models.ForeignKey(
        "projects.Project",
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
    reserved_at = models.DateTimeField(null=True, blank=True)
    reserved_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reserved_slots",
    )

    # Grid positioning
    row = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
        help_text="Grid row index (0-based)",
    )
    column = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
        help_text="Grid column index (0-based)",
    )
    slot_size = models.CharField(
        max_length=20,
        choices=SlotSize.choices,
        help_text="Physical size of this grid cell",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("shuttle", "row", "column")]
        ordering = ["shuttle", "row", "column"]
        indexes = [
            models.Index(fields=["shuttle", "status"]),
            models.Index(fields=["shuttle", "row", "column"]),
        ]

    @property
    def grid_position(self) -> str:
        """Return spreadsheet-style position (A1, B2, etc.)."""
        if self.column < 26:
            column_letter = chr(65 + self.column)
        else:
            column_letter = self._column_to_letters(self.column)
        return f"{column_letter}{self.row + 1}"

    @staticmethod
    def _column_to_letters(column: int) -> str:
        """Convert column index to letters for columns > 25 (AA, AB, etc.)."""
        result = ""
        while column >= 0:
            result = chr(65 + (column % 26)) + result
            column = column // 26 - 1
        return result

    def __str__(self):
        project_name = self.project.name if self.project else "Empty"
        return f"{self.shuttle.name} {self.grid_position} - {project_name}"

    def reserve(self, project, user):
        """Reserve this slot for a project with size validation."""
        if self.status != self.Status.AVAILABLE:
            msg = "Slot is not available"
            raise ValueError(msg)

        if not self.shuttle.can_accept_projects():
            msg = "Shuttle is not accepting projects"
            raise ValueError(msg)

        # Check for size mismatch (warning only, not blocking)
        size_mismatch = None
        if project.slot_size != self.slot_size:
            size_mismatch = (
                f"⚠️ Size mismatch: Project is {project.slot_size} "
                f"but slot is {self.slot_size}"
            )

        # Assign project (no status change on project)
        self.project = project
        self.reserved_by = user
        self.status = self.Status.RESERVED
        self.reserved_at = timezone.now()
        self.save()

        return size_mismatch

    def cancel_reservation(self):
        """Cancel this slot's reservation."""
        self.project = None
        self.reserved_by = None
        self.reserved_at = None
        self.status = self.Status.AVAILABLE
        self.save()
```

**Step 5: Add grid_config_file field to Shuttle model**

In same file, update Shuttle model:

```python
class Shuttle(models.Model):
    # ... existing fields ...

    grid_config_file = models.CharField(
        max_length=255,
        blank=True,
        help_text="Path to YAML grid configuration (e.g., shuttles/G801-layout.yaml)",
    )

    # ... rest of model ...

    @property
    def grid_dimensions(self) -> tuple[int, int]:
        """Get grid dimensions as (num_rows, num_columns)."""
        if not self.slots.exists():
            return (0, 0)
        max_row = self.slots.aggregate(models.Max("row"))["row__max"]
        max_col = self.slots.aggregate(models.Max("column"))["column__max"]
        return (max_row + 1, max_col + 1)
```

**Step 6: Run migration**

```bash
uv run python manage.py migrate
```

Expected: Migration 0003_shuttleslot_grid_positioning applied successfully

**Step 7: Run tests to verify they pass**

```bash
uv run pytest wafer_space/shuttles/tests/test_grid_positioning.py -v
```

Expected: All tests PASS

**Step 8: Update existing ShuttleSlot tests**

Find and update any tests that reference removed fields:

```bash
grep -r "slot_number\|position_x\|position_y\|width\|height" wafer_space/shuttles/tests/ wafer_space/projects/tests/
```

Update each occurrence to use new fields (row, column, slot_size).

**Step 9: Run full test suite**

```bash
make test
```

Expected: All tests PASS

**Step 10: Commit**

```bash
make lint-fix
git add wafer_space/shuttles/models.py wafer_space/shuttles/migrations/ wafer_space/shuttles/tests/test_grid_positioning.py
git commit -m "feat: add grid positioning to ShuttleSlot model

- Add row, column, slot_size fields to ShuttleSlot
- Add grid_position property for spreadsheet notation (A1, B2, etc.)
- Add unique_together constraint on (shuttle, row, column)
- Add grid_config_file field to Shuttle model
- Add grid_dimensions property to Shuttle
- Remove old fields: slot_number, position_x/y, width, height

🤖 Generated with [Claude Code](https://claude.ai/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: YAML Configuration System

**Files:**
- Create: `wafer_space/shuttles/config.py` (YAML parsing logic)
- Create: `wafer_space/shuttles/tests/test_config.py`
- Create: `shuttles/G801-layout.yaml` (example config)

**Step 1: Write failing test for YAML parsing**

Create `wafer_space/shuttles/tests/test_config.py`:

```python
import pytest
from pathlib import Path
from wafer_space.shuttles.config import GridConfig, GridConfigError


class TestGridConfig:
    """Test YAML grid configuration parsing."""

    def test_parse_valid_config(self, tmp_path):
        """Should parse valid YAML configuration."""
        config_file = tmp_path / "test-layout.yaml"
        config_file.write_text("""
shuttle: TEST01
row_heights: [1.0, 0.5, 1.0]
column_widths: [1.0, 0.5, 1.0, 0.5]
""")

        config = GridConfig.from_file(config_file)

        assert config.shuttle_name == "TEST01"
        assert config.row_heights == [1.0, 0.5, 1.0]
        assert config.column_widths == [1.0, 0.5, 1.0, 0.5]
        assert config.num_rows == 3
        assert config.num_columns == 4

    def test_reject_invalid_dimensions(self, tmp_path):
        """Should reject dimensions other than 0.5 or 1.0."""
        config_file = tmp_path / "bad-layout.yaml"
        config_file.write_text("""
shuttle: TEST02
row_heights: [1.0, 0.75, 1.0]
column_widths: [1.0]
""")

        with pytest.raises(GridConfigError, match="must be 0.5 or 1.0"):
            GridConfig.from_file(config_file)

    def test_reject_missing_fields(self, tmp_path):
        """Should reject config missing required fields."""
        config_file = tmp_path / "incomplete.yaml"
        config_file.write_text("""
shuttle: TEST03
row_heights: [1.0]
""")

        with pytest.raises(GridConfigError, match="Missing required field"):
            GridConfig.from_file(config_file)

    def test_calculate_slot_size(self):
        """Should calculate correct SlotSize from dimensions."""
        from wafer_space.core.enums import SlotSize

        test_cases = [
            ((1.0, 1.0), SlotSize.FULL),
            ((0.5, 0.5), SlotSize.QUARTER),
            ((1.0, 0.5), SlotSize.HALF_HEIGHT),
            ((0.5, 1.0), SlotSize.HALF_WIDTH),
        ]

        for (row_h, col_w), expected in test_cases:
            result = GridConfig.calculate_slot_size(row_h, col_w)
            assert result == expected, f"Failed for ({row_h}, {col_w})"
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest wafer_space/shuttles/tests/test_config.py -v
```

Expected: FAIL - "No module named 'wafer_space.shuttles.config'"

**Step 3: Implement GridConfig class**

Create `wafer_space/shuttles/config.py`:

```python
"""Grid configuration parsing from YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from wafer_space.core.enums import SlotSize


class GridConfigError(Exception):
    """Error in grid configuration file."""

    pass


class GridConfig:
    """Parsed grid configuration from YAML."""

    def __init__(self, shuttle_name: str, row_heights: list[float], column_widths: list[float]) -> None:
        """Initialize grid configuration.

        Args:
            shuttle_name: Name of shuttle this config is for
            row_heights: List of row heights (each 0.5 or 1.0)
            column_widths: List of column widths (each 0.5 or 1.0)
        """
        self.shuttle_name = shuttle_name
        self.row_heights = row_heights
        self.column_widths = column_widths

        # Validate dimensions
        for height in row_heights:
            if height not in (0.5, 1.0):
                msg = f"Row height {height} must be 0.5 or 1.0"
                raise GridConfigError(msg)

        for width in column_widths:
            if width not in (0.5, 1.0):
                msg = f"Column width {width} must be 0.5 or 1.0"
                raise GridConfigError(msg)

    @property
    def num_rows(self) -> int:
        """Get number of rows in grid."""
        return len(self.row_heights)

    @property
    def num_columns(self) -> int:
        """Get number of columns in grid."""
        return len(self.column_widths)

    @classmethod
    def from_file(cls, config_path: Path) -> GridConfig:
        """Load configuration from YAML file.

        Args:
            config_path: Path to YAML configuration file

        Returns:
            GridConfig instance

        Raises:
            GridConfigError: If configuration is invalid
        """
        try:
            with config_path.open() as f:
                data = yaml.safe_load(f)
        except Exception as exc:
            msg = f"Failed to read config file: {exc}"
            raise GridConfigError(msg) from exc

        if not isinstance(data, dict):
            msg = "Config file must contain a YAML dictionary"
            raise GridConfigError(msg)

        # Validate required fields
        required_fields = {"shuttle", "row_heights", "column_widths"}
        missing = required_fields - set(data.keys())
        if missing:
            msg = f"Missing required fields: {', '.join(missing)}"
            raise GridConfigError(msg)

        return cls(
            shuttle_name=data["shuttle"],
            row_heights=data["row_heights"],
            column_widths=data["column_widths"],
        )

    @staticmethod
    def calculate_slot_size(row_height: float, column_width: float) -> SlotSize:
        """Calculate SlotSize enum value from dimensions.

        Args:
            row_height: Height of cell (0.5 or 1.0)
            column_width: Width of cell (0.5 or 1.0)

        Returns:
            SlotSize enum value
        """
        if row_height == 1.0 and column_width == 1.0:
            return SlotSize.FULL
        elif row_height == 0.5 and column_width == 0.5:
            return SlotSize.QUARTER
        elif row_height == 1.0 and column_width == 0.5:
            return SlotSize.HALF_HEIGHT
        elif row_height == 0.5 and column_width == 1.0:
            return SlotSize.HALF_WIDTH
        else:
            msg = f"Invalid dimensions: {row_height} x {column_width}"
            raise GridConfigError(msg)
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/shuttles/tests/test_config.py -v
```

Expected: All tests PASS

**Step 5: Create example YAML config**

Create `shuttles/G801-layout.yaml`:

```yaml
shuttle: G801
row_heights: [1.0, 0.5, 1.0, 0.5, 1.0]
column_widths: [1.0, 0.5, 1.0, 0.5, 1.0, 0.5]
```

**Step 6: Commit**

```bash
git add wafer_space/shuttles/config.py wafer_space/shuttles/tests/test_config.py shuttles/G801-layout.yaml
git commit -m "feat: add YAML grid configuration system

- Add GridConfig class for parsing YAML files
- Validate dimensions are 0.5 or 1.0
- Calculate SlotSize from cell dimensions
- Add example G801 layout configuration

🤖 Generated with [Claude Code](https://claude.ai/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Management Command for Grid Generation

**Files:**
- Create: `wafer_space/shuttles/management/commands/generate_shuttle_grid.py`
- Create: `wafer_space/shuttles/tests/test_management_commands.py`

**Step 1: Write failing test for management command**

Create `wafer_space/shuttles/tests/test_management_commands.py`:

```python
import pytest
from pathlib import Path
from io import StringIO
from django.core.management import call_command
from wafer_space.shuttles.models import Shuttle, ShuttleSlot
from wafer_space.core.enums import SlotSize


@pytest.mark.django_db
class TestGenerateShuttleGrid:
    """Test generate_shuttle_grid management command."""

    def test_generate_new_grid(self, tmp_path):
        """Should generate grid from YAML config."""
        # Create shuttle
        shuttle = Shuttle.objects.create(
            name="G801",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )

        # Create config file
        config_file = tmp_path / "TEST01-layout.yaml"
        config_file.write_text("""
shuttle: TEST01
row_heights: [1.0, 0.5]
column_widths: [1.0, 0.5]
""")

        # Run command
        out = StringIO()
        call_command(
            "generate_shuttle_grid",
            "TEST01",
            f"--config-dir={tmp_path}",
            stdout=out,
        )

        # Verify slots created
        slots = list(ShuttleSlot.objects.filter(shuttle=shuttle).order_by("row", "column"))
        assert len(slots) == 4  # 2 rows x 2 columns

        # Verify positions and sizes
        assert slots[0].row == 0 and slots[0].column == 0
        assert slots[0].slot_size == SlotSize.FULL  # 1.0 x 1.0

        assert slots[1].row == 0 and slots[1].column == 1
        assert slots[1].slot_size == SlotSize.HALF_HEIGHT  # 1.0 x 0.5

        assert slots[2].row == 1 and slots[2].column == 0
        assert slots[2].slot_size == SlotSize.HALF_WIDTH  # 0.5 x 1.0

        assert slots[3].row == 1 and slots[3].column == 1
        assert slots[3].slot_size == SlotSize.QUARTER  # 0.5 x 0.5

        # Verify shuttle updated
        shuttle.refresh_from_db()
        assert shuttle.grid_config_file == str(config_file)

    def test_update_requires_force_if_assigned(self, tmp_path):
        """Should require --force flag if slots have assignments."""
        from wafer_space.projects.tests.factories import ProjectFactory
        from wafer_space.users.tests.factories import UserFactory

        # Create shuttle with slots
        shuttle = Shuttle.objects.create(
            name="G802",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )

        # Assign project to slot
        project = ProjectFactory(shuttle=shuttle)
        user = UserFactory()
        slot.reserve(project, user)

        # Create new config
        config_file = tmp_path / "TEST02-layout.yaml"
        config_file.write_text("""
shuttle: TEST02
row_heights: [1.0]
column_widths: [1.0]
""")

        # Try update without --force
        out = StringIO()
        with pytest.raises(SystemExit):
            call_command(
                "generate_shuttle_grid",
                "TEST02",
                f"--config-dir={tmp_path}",
                "--update",
                stdout=out,
            )

        output = out.getvalue()
        assert "has assigned projects" in output
        assert "Use --force" in output

    def test_dry_run_mode(self, tmp_path):
        """Should preview without creating slots in dry-run mode."""
        shuttle = Shuttle.objects.create(
            name="G803",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )

        config_file = tmp_path / "TEST03-layout.yaml"
        config_file.write_text("""
shuttle: TEST03
row_heights: [1.0]
column_widths: [1.0]
""")

        out = StringIO()
        call_command(
            "generate_shuttle_grid",
            "TEST03",
            f"--config-dir={tmp_path}",
            "--dry-run",
            stdout=out,
        )

        # Verify no slots created
        assert ShuttleSlot.objects.filter(shuttle=shuttle).count() == 0

        # Verify preview in output
        output = out.getvalue()
        assert "DRY RUN" in output
        assert "Would create" in output
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest wafer_space/shuttles/tests/test_management_commands.py -v
```

Expected: FAIL - "Unknown command: 'generate_shuttle_grid'"

**Step 3: Implement management command**

Create `wafer_space/shuttles/management/commands/generate_shuttle_grid.py`:

```python
"""Management command to generate shuttle grid from YAML configuration."""

from __future__ import annotations

import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from wafer_space.shuttles.config import GridConfig, GridConfigError
from wafer_space.shuttles.models import Shuttle, ShuttleSlot


class Command(BaseCommand):
    """Generate shuttle grid slots from YAML configuration file."""

    help = "Generate shuttle grid from YAML configuration"

    def add_arguments(self, parser):
        parser.add_argument(
            "shuttle_name",
            type=str,
            help="Name of shuttle to generate grid for",
        )
        parser.add_argument(
            "--config-dir",
            type=str,
            default="shuttles",
            help="Directory containing configuration files (default: shuttles/)",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            help="Update existing grid (requires --force if slots assigned)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force update even if projects are assigned",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without creating slots",
        )

    def handle(self, *args, **options):
        shuttle_name = options["shuttle_name"]
        config_dir = Path(options["config_dir"])
        update = options["update"]
        force = options["force"]
        dry_run = options["dry_run"]

        # Find configuration file
        config_path = config_dir / f"{shuttle_name}-layout.yaml"
        if not config_path.exists():
            raise CommandError(f"Configuration file not found: {config_path}")

        # Parse configuration
        try:
            config = GridConfig.from_file(config_path)
        except GridConfigError as exc:
            raise CommandError(f"Invalid configuration: {exc}")

        # Verify shuttle name matches
        if config.shuttle_name != shuttle_name:
            raise CommandError(
                f"Shuttle name mismatch: config has '{config.shuttle_name}', "
                f"expected '{shuttle_name}'"
            )

        # Get shuttle
        try:
            shuttle = Shuttle.objects.get(name=shuttle_name)
        except Shuttle.DoesNotExist:
            raise CommandError(f"Shuttle not found: {shuttle_name}")

        # Check for existing slots
        existing_slots = ShuttleSlot.objects.filter(shuttle=shuttle)
        if existing_slots.exists():
            if not update:
                raise CommandError(
                    f"Shuttle {shuttle_name} already has {existing_slots.count()} slots. "
                    "Use --update to regenerate grid."
                )

            # Check for assigned projects
            assigned_slots = existing_slots.exclude(project__isnull=True)
            if assigned_slots.exists() and not force:
                project_names = ", ".join(
                    assigned_slots.values_list("project__manufacturing_id", flat=True)
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"\nShuttle {shuttle_name} has {assigned_slots.count()} "
                        f"assigned projects:\n{project_names}\n\n"
                        "These projects will remain on the shuttle but lose their "
                        "slot positions.\n"
                        "Use --force to proceed with deletion.\n"
                    )
                )
                sys.exit(1)

        if dry_run:
            self.stdout.write(self.style.WARNING("\n=== DRY RUN MODE ===\n"))

        # Generate slots
        self._generate_grid(shuttle, config, config_path, update, dry_run)

    def _generate_grid(
        self,
        shuttle: Shuttle,
        config: GridConfig,
        config_path: Path,
        update: bool,
        dry_run: bool,
    ):
        """Generate grid slots from configuration."""
        slots_to_create = []

        for row_idx, row_height in enumerate(config.row_heights):
            for col_idx, col_width in enumerate(config.column_widths):
                slot_size = GridConfig.calculate_slot_size(row_height, col_width)

                slot_data = {
                    "shuttle": shuttle,
                    "row": row_idx,
                    "column": col_idx,
                    "slot_size": slot_size,
                    "status": ShuttleSlot.Status.AVAILABLE,
                }
                slots_to_create.append(slot_data)

        if dry_run:
            self.stdout.write(
                f"\nWould create {len(slots_to_create)} slots for {shuttle.name}:\n"
            )
            self.stdout.write(f"Grid dimensions: {config.num_rows} rows x {config.num_columns} columns\n")

            # Show sample slots
            for i, slot_data in enumerate(slots_to_create[:5]):
                temp_slot = ShuttleSlot(**slot_data)
                self.stdout.write(
                    f"  {temp_slot.grid_position}: {slot_data['slot_size']} "
                    f"(row={slot_data['row']}, col={slot_data['column']})"
                )
            if len(slots_to_create) > 5:
                self.stdout.write(f"  ... and {len(slots_to_create) - 5} more\n")
        else:
            with transaction.atomic():
                # Delete existing slots if updating
                if update:
                    deleted_count = ShuttleSlot.objects.filter(shuttle=shuttle).delete()[0]
                    self.stdout.write(f"Deleted {deleted_count} existing slots\n")

                # Create new slots
                slots = [ShuttleSlot(**data) for data in slots_to_create]
                ShuttleSlot.objects.bulk_create(slots)

                # Update shuttle config path
                shuttle.grid_config_file = str(config_path)
                shuttle.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ Created {len(slots_to_create)} slots for {shuttle.name}\n"
                    f"Grid dimensions: {config.num_rows} rows x {config.num_columns} columns\n"
                    f"Config file: {config_path}\n"
                )
            )
```

**Step 4: Ensure management directory exists**

```bash
mkdir -p wafer_space/shuttles/management/commands
touch wafer_space/shuttles/management/__init__.py
touch wafer_space/shuttles/management/commands/__init__.py
```

**Step 5: Run tests to verify they pass**

```bash
uv run pytest wafer_space/shuttles/tests/test_management_commands.py -v
```

Expected: All tests PASS

**Step 6: Test command manually**

```bash
uv run python manage.py generate_shuttle_grid G801 --dry-run
```

Expected: Preview output showing slots that would be created

**Step 7: Commit**

```bash
git add wafer_space/shuttles/management/ wafer_space/shuttles/tests/test_management_commands.py
git commit -m "feat: add generate_shuttle_grid management command

- Parse YAML configuration and generate ShuttleSlot records
- Support --update and --force flags for regeneration
- Support --dry-run for preview mode
- Validate against assigned projects before deletion

🤖 Generated with [Claude Code](https://claude.ai/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Staff Assignment Dashboard View

**Files:**
- Create: `wafer_space/shuttles/views.py` (ShuttleAssignmentView)
- Create: `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`
- Modify: `wafer_space/shuttles/urls.py`
- Create: `wafer_space/shuttles/tests/test_views.py`

**Step 1: Write failing test for assignment dashboard**

Create `wafer_space/shuttles/tests/test_views.py`:

```python
import pytest
from django.urls import reverse
from wafer_space.shuttles.models import Shuttle, ShuttleSlot
from wafer_space.users.tests.factories import UserFactory
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.core.enums import SlotSize


@pytest.mark.django_db
class TestShuttleAssignmentView:
    """Test shuttle assignment dashboard view."""

    def test_staff_can_access(self, client):
        """Staff users should access assignment dashboard."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="G801",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )

        url = reverse("shuttles:assignment", kwargs={"pk": shuttle.pk})
        response = client.get(url)

        assert response.status_code == 200
        assert "TEST01" in response.content.decode()

    def test_regular_user_cannot_access(self, client):
        """Regular users should be denied access."""
        user = UserFactory(is_staff=False)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="G802",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )

        url = reverse("shuttles:assignment", kwargs={"pk": shuttle.pk})
        response = client.get(url)

        assert response.status_code == 403

    def test_context_includes_statistics(self, client):
        """Context should include assignment statistics by size."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="G803",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )

        # Create slots
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=1,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        assigned_slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=1,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )

        # Assign project to one slot
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)
        assigned_slot.project = project
        assigned_slot.save()

        url = reverse("shuttles:assignment", kwargs={"pk": shuttle.pk})
        response = client.get(url)

        assert response.status_code == 200
        stats = response.context["stats"]

        # Should have stats for FULL size
        full_stats = stats[SlotSize.FULL]
        assert full_stats["total_slots"] == 3
        assert full_stats["available_slots"] == 2
        assert full_stats["projects_count"] == 1
        assert full_stats["assigned_count"] == 1

    def test_context_includes_projects(self, client):
        """Context should include all projects on shuttle."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="G804",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )

        project1 = ProjectFactory(shuttle=shuttle, name="Project One")
        project2 = ProjectFactory(shuttle=shuttle, name="Project Two")

        url = reverse("shuttles:assignment", kwargs={"pk": shuttle.pk})
        response = client.get(url)

        assert response.status_code == 200
        projects = response.context["projects"]
        assert len(projects) == 2
        assert project1 in projects
        assert project2 in projects
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest wafer_space/shuttles/tests/test_views.py::TestShuttleAssignmentView -v
```

Expected: FAIL - "NoReverseMatch: Reverse for 'assignment' not found"

**Step 3: Add URL pattern**

Create/modify `wafer_space/shuttles/urls.py`:

```python
from django.urls import path
from . import views

app_name = "shuttles"

urlpatterns = [
    path("<int:pk>/", views.ShuttleDetailView.as_view(), name="detail"),
    path("<int:pk>/assign/", views.ShuttleAssignmentView.as_view(), name="assignment"),
]
```

**Step 4: Implement ShuttleAssignmentView**

Create `wafer_space/shuttles/views.py`:

```python
"""Shuttle views."""

from __future__ import annotations

from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import Count, Q
from django.views.generic import DetailView

from wafer_space.core.enums import SlotSize
from wafer_space.shuttles.models import Shuttle, ShuttleSlot


class StaffRequiredMixin(UserPassesTestMixin):
    """Mixin to require staff access."""

    def test_func(self):
        return self.request.user.is_staff


class ShuttleDetailView(StaffRequiredMixin, DetailView):
    """Detail view for a shuttle."""

    model = Shuttle
    template_name = "shuttles/detail.html"
    context_object_name = "shuttle"


class ShuttleAssignmentView(StaffRequiredMixin, DetailView):
    """Assignment dashboard for managing shuttle slot assignments."""

    model = Shuttle
    template_name = "shuttles/assignment_dashboard.html"
    context_object_name = "shuttle"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        shuttle = self.object

        # Calculate statistics by slot size
        stats = {}
        for slot_size in SlotSize:
            # Count slots of this size
            slots = ShuttleSlot.objects.filter(shuttle=shuttle, slot_size=slot_size)
            total_slots = slots.count()
            available_slots = slots.filter(status=ShuttleSlot.Status.AVAILABLE).count()

            # Count projects of this size
            projects = shuttle.project_set.filter(slot_size=slot_size)
            projects_count = projects.count()
            assigned_count = projects.filter(shuttle_slots__isnull=False).distinct().count()

            stats[slot_size] = {
                "total_slots": total_slots,
                "available_slots": available_slots,
                "projects_count": projects_count,
                "assigned_count": assigned_count,
            }

        context["stats"] = stats

        # Get all projects on this shuttle with their slot assignments
        projects = shuttle.project_set.all().prefetch_related("shuttle_slots")
        context["projects"] = projects

        return context
```

**Step 5: Create template**

Create `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`:

```html
{% extends "base.html" %}
{% load static %}

{% block title %}{{ shuttle.name }} Assignment{% endblock %}

{% block content %}
<div class="container mt-4">
  <h1>Shuttle {{ shuttle.name }} Assignment Status</h1>

  <!-- Summary Statistics -->
  <div class="card mb-4">
    <div class="card-header">
      <h5 class="mb-0">Assignment Summary</h5>
    </div>
    <div class="card-body">
      <div class="row">
        {% for slot_size, stat in stats.items %}
        {% if stat.total_slots > 0 %}
        <div class="col-md-6 col-lg-3 mb-3">
          <div class="border rounded p-3">
            <h6 class="text-muted">{{ slot_size.label }}</h6>
            <div class="mt-2">
              <strong>Projects:</strong> {{ stat.assigned_count }}/{{ stat.projects_count }} assigned
              <div class="progress mt-1" style="height: 5px;">
                <div class="progress-bar bg-success" role="progressbar"
                     style="width: {% if stat.projects_count > 0 %}{{ stat.assigned_count|mul:100|div:stat.projects_count }}{% else %}0{% endif %}%"></div>
              </div>
            </div>
            <div class="mt-2">
              <strong>Slots:</strong> {{ stat.available_slots }}/{{ stat.total_slots }} available
              <div class="progress mt-1" style="height: 5px;">
                <div class="progress-bar bg-info" role="progressbar"
                     style="width: {% if stat.total_slots > 0 %}{{ stat.available_slots|mul:100|div:stat.total_slots }}{% else %}0{% endif %}%"></div>
              </div>
            </div>
          </div>
        </div>
        {% endif %}
        {% endfor %}
      </div>
    </div>
  </div>

  <!-- Grid Preview (placeholder for now) -->
  <div class="card mb-4">
    <div class="card-header">
      <h5 class="mb-0">Grid Layout Preview</h5>
      <small class="text-muted">Not to scale - for reference only</small>
    </div>
    <div class="card-body">
      <iframe
        src="{% url 'shuttles:grid_preview' pk=shuttle.pk %}"
        style="width: 100%; height: 400px; border: 1px solid #dee2e6;"
        id="grid-preview">
      </iframe>
    </div>
  </div>

  <!-- Project Assignment Table -->
  <div class="card">
    <div class="card-header d-flex justify-content-between align-items-center">
      <h5 class="mb-0">Project Assignment</h5>
      <div class="d-flex gap-2">
        <select class="form-select form-select-sm" id="size-filter">
          <option value="">All Sizes</option>
          {% for slot_size in stats.keys %}
          <option value="{{ slot_size.value }}">{{ slot_size.label }}</option>
          {% endfor %}
        </select>
        <div class="form-check">
          <input class="form-check-input" type="checkbox" id="unassigned-only">
          <label class="form-check-label" for="unassigned-only">Unassigned only</label>
        </div>
      </div>
    </div>
    <div class="card-body">
      <table class="table table-hover" id="projects-table">
        <thead>
          <tr>
            <th>Project ID</th>
            <th>Name</th>
            <th>Size</th>
            <th>Slots</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {% for project in projects %}
          <tr data-size="{{ project.slot_size }}" data-assigned="{% if project.shuttle_slots.exists %}true{% else %}false{% endif %}">
            <td>{{ project.manufacturing_id }}</td>
            <td>{{ project.name }}</td>
            <td><span class="badge bg-secondary">{{ project.get_slot_size_display }}</span></td>
            <td>
              {% if project.shuttle_slots.exists %}
                {% for slot in project.shuttle_slots.all %}
                  <span class="badge bg-success">{{ slot.grid_position }}</span>
                {% endfor %}
              {% else %}
                <span class="text-muted">-</span>
              {% endif %}
            </td>
            <td>
              <button class="btn btn-sm btn-primary" onclick="assignSlot({{ project.pk }}, '{{ project.manufacturing_id }}', '{{ project.slot_size }}')">
                {% if project.shuttle_slots.exists %}Edit{% else %}Assign{% endif %}
              </button>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>

<!-- Assignment Modal (placeholder) -->
<div class="modal fade" id="assignModal" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">Assign Project to Slot</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <p>Assignment interface will be implemented in next task.</p>
      </div>
    </div>
  </div>
</div>

<script>
// Basic filtering (will be enhanced in next task)
document.getElementById('size-filter').addEventListener('change', filterTable);
document.getElementById('unassigned-only').addEventListener('change', filterTable);

function filterTable() {
  const sizeFilter = document.getElementById('size-filter').value;
  const unassignedOnly = document.getElementById('unassigned-only').checked;
  const rows = document.querySelectorAll('#projects-table tbody tr');

  rows.forEach(row => {
    const size = row.dataset.size;
    const assigned = row.dataset.assigned === 'true';

    let show = true;
    if (sizeFilter && size !== sizeFilter) show = false;
    if (unassignedOnly && assigned) show = false;

    row.style.display = show ? '' : 'none';
  });
}

function assignSlot(projectId, projectName, slotSize) {
  // Placeholder - will be implemented in next task
  const modal = new bootstrap.Modal(document.getElementById('assignModal'));
  modal.show();
}
</script>
{% endblock %}
```

**Step 6: Run tests to verify they pass**

```bash
uv run pytest wafer_space/shuttles/tests/test_views.py::TestShuttleAssignmentView -v
```

Expected: All tests PASS

**Step 7: Commit**

```bash
make lint-fix
git add wafer_space/shuttles/views.py wafer_space/shuttles/urls.py wafer_space/shuttles/templates/ wafer_space/shuttles/tests/test_views.py
git commit -m "feat: add staff assignment dashboard view

- Add ShuttleAssignmentView with staff-only access
- Calculate assignment statistics by slot size
- Display project list with filtering
- Add placeholder for grid preview and assignment modal

🤖 Generated with [Claude Code](https://claude.ai/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Grid Preview View

**Files:**
- Add to: `wafer_space/shuttles/views.py` (GridPreviewView)
- Create: `wafer_space/shuttles/templates/shuttles/grid_preview.html`
- Modify: `wafer_space/shuttles/urls.py`
- Add to: `wafer_space/shuttles/tests/test_views.py`

**Step 1: Write failing test for grid preview**

Add to `wafer_space/shuttles/tests/test_views.py`:

```python
@pytest.mark.django_db
class TestGridPreviewView:
    """Test grid preview view."""

    def test_renders_grid(self, client):
        """Should render HTML table with grid positions."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="G801",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )

        # Create 2x2 grid
        ShuttleSlot.objects.create(
            shuttle=shuttle, row=0, column=0, slot_size=SlotSize.FULL, status=ShuttleSlot.Status.AVAILABLE
        )
        ShuttleSlot.objects.create(
            shuttle=shuttle, row=0, column=1, slot_size=SlotSize.FULL, status=ShuttleSlot.Status.AVAILABLE
        )
        ShuttleSlot.objects.create(
            shuttle=shuttle, row=1, column=0, slot_size=SlotSize.FULL, status=ShuttleSlot.Status.AVAILABLE
        )
        assigned_slot = ShuttleSlot.objects.create(
            shuttle=shuttle, row=1, column=1, slot_size=SlotSize.FULL, status=ShuttleSlot.Status.RESERVED
        )

        # Assign project to one slot
        project = ProjectFactory(shuttle=shuttle, project_id="TEST")
        assigned_slot.project = project
        assigned_slot.save()

        url = reverse("shuttles:grid_preview", kwargs={"pk": shuttle.pk})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()

        # Should have table with correct structure
        assert "<table" in content
        assert "A1" in content or ">A<" in content  # Column header or cell
        assert "TEST" in content  # Project ID should appear

    def test_shows_empty_cells(self, client):
        """Empty cells should be visually distinct."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="G802",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )

        ShuttleSlot.objects.create(
            shuttle=shuttle, row=0, column=0, slot_size=SlotSize.FULL, status=ShuttleSlot.Status.AVAILABLE
        )

        url = reverse("shuttles:grid_preview", kwargs={"pk": shuttle.pk})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()
        assert "bg-secondary" in content or "Empty" in content
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest wafer_space/shuttles/tests/test_views.py::TestGridPreviewView -v
```

Expected: FAIL - "NoReverseMatch: Reverse for 'grid_preview' not found"

**Step 3: Add URL pattern**

Modify `wafer_space/shuttles/urls.py`:

```python
urlpatterns = [
    path("<int:pk>/", views.ShuttleDetailView.as_view(), name="detail"),
    path("<int:pk>/assign/", views.ShuttleAssignmentView.as_view(), name="assignment"),
    path("<int:pk>/grid-preview/", views.GridPreviewView.as_view(), name="grid_preview"),
]
```

**Step 4: Implement GridPreviewView**

Add to `wafer_space/shuttles/views.py`:

```python
class GridPreviewView(StaffRequiredMixin, DetailView):
    """Read-only grid preview showing slot occupancy."""

    model = Shuttle
    template_name = "shuttles/grid_preview.html"
    context_object_name = "shuttle"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        shuttle = self.object

        # Get grid dimensions
        num_rows, num_cols = shuttle.grid_dimensions

        if num_rows == 0 or num_cols == 0:
            context["grid"] = []
            context["columns"] = []
            return context

        # Build grid as 2D array
        grid = [[None for _ in range(num_cols)] for _ in range(num_rows)]

        for slot in shuttle.slots.select_related("project"):
            grid[slot.row][slot.column] = slot

        context["grid"] = grid
        context["columns"] = [chr(65 + i) for i in range(num_cols)]  # A, B, C, ...

        return context
```

**Step 5: Create template**

Create `wafer_space/shuttles/templates/shuttles/grid_preview.html`:

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Grid Preview</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { margin: 10px; font-size: 12px; }
    .grid-cell {
      width: 80px;
      height: 60px;
      text-align: center;
      vertical-align: middle;
      border: 1px solid #dee2e6;
      font-weight: 500;
    }
    .grid-cell.empty { background-color: #e9ecef; color: #6c757d; }
    .grid-cell.occupied { background-color: #d1e7dd; color: #0f5132; }
    .column-header {
      width: 80px;
      text-align: center;
      font-weight: bold;
      background-color: #f8f9fa;
    }
    .row-header {
      width: 40px;
      text-align: center;
      font-weight: bold;
      background-color: #f8f9fa;
    }
  </style>
</head>
<body>
  {% if not grid %}
    <div class="alert alert-info m-3">
      No grid configured for this shuttle. Run <code>generate_shuttle_grid</code> command to create grid.
    </div>
  {% else %}
    <table class="table table-bordered table-sm mb-0">
      <thead>
        <tr>
          <th class="row-header"></th>
          {% for col in columns %}
          <th class="column-header">{{ col }}</th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for row in grid %}
        <tr>
          <th class="row-header">{{ forloop.counter }}</th>
          {% for slot in row %}
          <td class="grid-cell {% if slot.project %}occupied{% else %}empty{% endif %}">
            {% if slot.project %}
              {{ slot.project.project_id }}
            {% else %}
              —
            {% endif %}
          </td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
  {% endif %}
</body>
</html>
```

**Step 6: Run tests to verify they pass**

```bash
uv run pytest wafer_space/shuttles/tests/test_views.py::TestGridPreviewView -v
```

Expected: All tests PASS

**Step 7: Test manually**

Start dev server and navigate to grid preview:

```bash
make runserver
```

Visit: `http://localhost:8081/shuttles/1/grid-preview/`

**Step 8: Commit**

```bash
git add wafer_space/shuttles/views.py wafer_space/shuttles/urls.py wafer_space/shuttles/templates/shuttles/grid_preview.html wafer_space/shuttles/tests/test_views.py
git commit -m "feat: add read-only grid preview view

- Render shuttle grid as HTML table
- Show project IDs in occupied cells
- Gray background for empty cells
- Column letters (A, B, C) and row numbers

🤖 Generated with [Claude Code](https://claude.ai/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Slot Assignment and Removal Endpoints

**Files:**
- Add to: `wafer_space/shuttles/views.py` (AssignProjectView, RemoveAssignmentView)
- Modify: `wafer_space/shuttles/urls.py`
- Add to: `wafer_space/shuttles/tests/test_views.py`
- Update: `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`

**Step 1: Write failing tests for assignment endpoints**

Add to `wafer_space/shuttles/tests/test_views.py`:

```python
@pytest.mark.django_db
class TestAssignProjectView:
    """Test project assignment endpoint."""

    def test_assign_project_to_slot(self, client):
        """Should assign project to available slot."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="G801",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL)

        url = reverse("shuttles:assign_project", kwargs={"pk": shuttle.pk})
        response = client.post(
            url,
            data={"project_id": project.pk, "slot_id": slot.pk},
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify slot assigned
        slot.refresh_from_db()
        assert slot.project == project
        assert slot.reserved_by == user
        assert slot.status == ShuttleSlot.Status.RESERVED

    def test_warn_on_size_mismatch(self, client):
        """Should warn but allow assignment on size mismatch."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="G802",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.QUARTER)

        url = reverse("shuttles:assign_project", kwargs={"pk": shuttle.pk})
        response = client.post(
            url,
            data={"project_id": project.pk, "slot_id": slot.pk},
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "warning" in data
        assert "Size mismatch" in data["warning"]

    def test_reject_if_slot_occupied(self, client):
        """Should reject if slot already occupied."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="G803",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        slot.project = ProjectFactory(shuttle=shuttle)
        slot.save()

        new_project = ProjectFactory(shuttle=shuttle)

        url = reverse("shuttles:assign_project", kwargs={"pk": shuttle.pk})
        response = client.post(
            url,
            data={"project_id": new_project.pk, "slot_id": slot.pk},
            content_type="application/json",
        )

        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert "not available" in data["error"]


@pytest.mark.django_db
class TestRemoveAssignmentView:
    """Test slot assignment removal endpoint."""

    def test_remove_assignment(self, client):
        """Should remove project from slot."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="G801",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        project = ProjectFactory(shuttle=shuttle)
        slot.project = project
        slot.reserved_by = user
        slot.save()

        url = reverse("shuttles:remove_assignment", kwargs={"pk": shuttle.pk, "slot_id": slot.pk})
        response = client.post(url)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Verify slot cleared
        slot.refresh_from_db()
        assert slot.project is None
        assert slot.reserved_by is None
        assert slot.status == ShuttleSlot.Status.AVAILABLE
```

**Step 2: Run tests to verify they fail**

```bash
uv run pytest wafer_space/shuttles/tests/test_views.py::TestAssignProjectView -v
uv run pytest wafer_space/shuttles/tests/test_views.py::TestRemoveAssignmentView -v
```

Expected: FAIL - "NoReverseMatch" for both URLs

**Step 3: Add URL patterns**

Modify `wafer_space/shuttles/urls.py`:

```python
urlpatterns = [
    path("<int:pk>/", views.ShuttleDetailView.as_view(), name="detail"),
    path("<int:pk>/assign/", views.ShuttleAssignmentView.as_view(), name="assignment"),
    path("<int:pk>/grid-preview/", views.GridPreviewView.as_view(), name="grid_preview"),
    path("<int:pk>/assign-project/", views.AssignProjectView.as_view(), name="assign_project"),
    path("<int:pk>/remove-assignment/<int:slot_id>/", views.RemoveAssignmentView.as_view(), name="remove_assignment"),
]
```

**Step 4: Implement assignment endpoints**

Add to `wafer_space/shuttles/views.py`:

```python
import json
from django.http import JsonResponse
from django.views import View
from django.db import transaction


class AssignProjectView(StaffRequiredMixin, View):
    """Assign a project to a slot."""

    def post(self, request, pk):
        try:
            data = json.loads(request.body)
            project_id = data.get("project_id")
            slot_id = data.get("slot_id")

            if not project_id or not slot_id:
                return JsonResponse(
                    {"success": False, "error": "Missing project_id or slot_id"}, status=400
                )

            from wafer_space.projects.models import Project

            with transaction.atomic():
                # Get objects with row locking
                slot = ShuttleSlot.objects.select_for_update().get(pk=slot_id, shuttle_id=pk)
                project = Project.objects.get(pk=project_id, shuttle_id=pk)

                # Attempt reservation
                try:
                    warning = slot.reserve(project, request.user)
                    response_data = {"success": True}
                    if warning:
                        response_data["warning"] = warning
                    return JsonResponse(response_data)
                except ValueError as exc:
                    return JsonResponse({"success": False, "error": str(exc)}, status=400)

        except (ShuttleSlot.DoesNotExist, Project.DoesNotExist):
            return JsonResponse({"success": False, "error": "Slot or project not found"}, status=404)
        except json.JSONDecodeError:
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)


class RemoveAssignmentView(StaffRequiredMixin, View):
    """Remove a project from a slot."""

    def post(self, request, pk, slot_id):
        try:
            with transaction.atomic():
                slot = ShuttleSlot.objects.select_for_update().get(pk=slot_id, shuttle_id=pk)
                slot.cancel_reservation()
                return JsonResponse({"success": True})
        except ShuttleSlot.DoesNotExist:
            return JsonResponse({"success": False, "error": "Slot not found"}, status=404)
```

**Step 5: Run tests to verify they pass**

```bash
uv run pytest wafer_space/shuttles/tests/test_views.py::TestAssignProjectView -v
uv run pytest wafer_space/shuttles/tests/test_views.py::TestRemoveAssignmentView -v
```

Expected: All tests PASS

**Step 6: Update assignment dashboard with working modal**

Update `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`:

Replace the assignment modal section with:

```html
<!-- Assignment Modal -->
<div class="modal fade" id="assignModal" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title" id="assignModalTitle">Assign Project to Slot</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <div class="mb-3">
          <label class="form-label">Select Slot:</label>
          <select class="form-select" id="slot-select">
            <option value="">Choose a slot...</option>
          </select>
        </div>

        <div id="current-assignments" class="mb-3" style="display: none;">
          <label class="form-label">Current assignments for this project:</label>
          <ul id="current-assignments-list" class="list-group"></ul>
        </div>

        <div id="assignment-warning" class="alert alert-warning" style="display: none;"></div>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
        <button type="button" class="btn btn-primary" id="confirm-assign">Add Assignment</button>
      </div>
    </div>
  </div>
</div>

<script>
let currentProjectId = null;
let currentProjectSize = null;

function assignSlot(projectId, projectName, slotSize) {
  currentProjectId = projectId;
  currentProjectSize = slotSize;

  document.getElementById('assignModalTitle').textContent = `Assign ${projectName} to Slot`;

  // Load available slots
  loadAvailableSlots(slotSize);

  // Show current assignments
  showCurrentAssignments(projectId);

  const modal = new bootstrap.Modal(document.getElementById('assignModal'));
  modal.show();
}

function loadAvailableSlots(projectSize) {
  fetch(`{% url 'shuttles:assignment' pk=shuttle.pk %}`)
    .then(response => response.text())
    .then(html => {
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, 'text/html');

      const select = document.getElementById('slot-select');
      select.innerHTML = '<option value="">Choose a slot...</option>';

      // Get all available slots from grid preview
      {% for row in shuttle.slots.all %}
        {% if row.status == 'available' %}
        const option = document.createElement('option');
        option.value = '{{ row.pk }}';
        option.textContent = '{{ row.grid_position }} ({{ row.slot_size }})';
        {% if row.slot_size != '${projectSize}' %}
        option.textContent += ' ⚠️ Size mismatch';
        {% endif %}
        select.appendChild(option);
        {% endif %}
      {% endfor %}
    });
}

function showCurrentAssignments(projectId) {
  const row = document.querySelector(`tr button[onclick*="assignSlot(${projectId}"]`).closest('tr');
  const slots = row.querySelectorAll('.badge.bg-success');

  const container = document.getElementById('current-assignments');
  const list = document.getElementById('current-assignments-list');

  if (slots.length === 0) {
    container.style.display = 'none';
    return;
  }

  container.style.display = 'block';
  list.innerHTML = '';

  slots.forEach(slot => {
    const li = document.createElement('li');
    li.className = 'list-group-item d-flex justify-content-between align-items-center';
    li.innerHTML = `
      ${slot.textContent}
      <button class="btn btn-sm btn-danger" onclick="removeAssignment('${slot.dataset.slotId}')">Remove</button>
    `;
    list.appendChild(li);
  });
}

document.getElementById('confirm-assign').addEventListener('click', function() {
  const slotId = document.getElementById('slot-select').value;

  if (!slotId) {
    alert('Please select a slot');
    return;
  }

  const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]').value;

  fetch(`{% url 'shuttles:assign_project' pk=shuttle.pk %}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrftoken,
    },
    body: JSON.stringify({
      project_id: currentProjectId,
      slot_id: slotId,
    }),
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      if (data.warning) {
        document.getElementById('assignment-warning').textContent = data.warning;
        document.getElementById('assignment-warning').style.display = 'block';
      } else {
        // Reload page to show updated assignments
        location.reload();
      }
    } else {
      alert('Error: ' + data.error);
    }
  })
  .catch(error => {
    alert('Failed to assign project: ' + error);
  });
});

function removeAssignment(slotId) {
  if (!confirm('Remove this slot assignment?')) return;

  const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]').value;

  fetch(`{% url 'shuttles:remove_assignment' pk=shuttle.pk slot_id=0 %}`.replace('/0/', `/${slotId}/`), {
    method: 'POST',
    headers: {
      'X-CSRFToken': csrftoken,
    },
  })
  .then(response => response.json())
  .then(data => {
    if (data.success) {
      location.reload();
    } else {
      alert('Error: ' + data.error);
    }
  });
}
</script>
```

Also add CSRF token to the template:

```html
{% block content %}
<div class="container mt-4">
  {% csrf_token %}
  <!-- rest of template -->
```

**Step 7: Run full test suite**

```bash
make test
```

Expected: All tests PASS

**Step 8: Commit**

```bash
make lint-fix
git add wafer_space/shuttles/views.py wafer_space/shuttles/urls.py wafer_space/shuttles/templates/shuttles/assignment_dashboard.html wafer_space/shuttles/tests/test_views.py
git commit -m "feat: add slot assignment and removal endpoints

- Add POST endpoints for assigning/removing projects from slots
- Use database transactions with row locking for concurrency safety
- Return size mismatch warnings without blocking
- Update assignment dashboard with working modal

🤖 Generated with [Claude Code](https://claude.ai/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: Project Detail Page Slot Visibility

**Files:**
- Modify: `wafer_space/projects/templates/projects/detail.html`
- Add to: `wafer_space/projects/tests/test_views.py`

**Step 1: Write failing test for slot visibility**

Add to `wafer_space/projects/tests/test_views.py`:

```python
@pytest.mark.django_db
class TestProjectDetailSlotVisibility:
    """Test slot assignment visibility on project detail page."""

    def test_staff_sees_slot_assignments(self, client):
        """Staff should see slot assignments on project detail."""
        from wafer_space.shuttles.models import Shuttle, ShuttleSlot
        from wafer_space.core.enums import SlotSize

        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="G801",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )
        project = ProjectFactory(shuttle=shuttle)

        # Assign to two slots
        slot1 = ShuttleSlot.objects.create(
            shuttle=shuttle, row=0, column=0, slot_size=SlotSize.FULL, status=ShuttleSlot.Status.RESERVED
        )
        slot1.project = project
        slot1.reserved_by = user
        slot1.save()

        slot2 = ShuttleSlot.objects.create(
            shuttle=shuttle, row=1, column=2, slot_size=SlotSize.FULL, status=ShuttleSlot.Status.RESERVED
        )
        slot2.project = project
        slot2.reserved_by = user
        slot2.save()

        url = reverse("projects:detail", kwargs={"pk": project.pk})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()

        # Should show slot assignments
        assert "Assigned Slots" in content or "Grid Position" in content
        assert "A1" in content  # slot1 position
        assert "C2" in content  # slot2 position

    def test_regular_user_does_not_see_slots(self, client):
        """Regular users should not see slot assignments."""
        from wafer_space.shuttles.models import Shuttle, ShuttleSlot
        from wafer_space.core.enums import SlotSize

        user = UserFactory(is_staff=False)
        project = ProjectFactory(owner=user)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="G801",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )
        project.shuttle = shuttle
        project.save()

        slot = ShuttleSlot.objects.create(
            shuttle=shuttle, row=0, column=0, slot_size=SlotSize.FULL, status=ShuttleSlot.Status.RESERVED
        )
        slot.project = project
        slot.save()

        url = reverse("projects:detail", kwargs={"pk": project.pk})
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode()

        # Should NOT show slot section
        assert "Assigned Slots" not in content
        assert "Grid Position" not in content
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest wafer_space/projects/tests/test_views.py::TestProjectDetailSlotVisibility -v
```

Expected: FAIL - "Assigned Slots" not found in response

**Step 3: Update project detail template**

Modify `wafer_space/projects/templates/projects/detail.html`:

Add before the closing `</div>` of main content:

```html
  {% if request.user.is_staff and project.shuttle_slots.exists %}
  <div class="card mt-4">
    <div class="card-header">
      <h5 class="mb-0">
        <i class="bi bi-grid-3x3"></i> Assigned Slots (Staff Only)
      </h5>
    </div>
    <div class="card-body">
      <p class="mb-2">This project is assigned to the following grid positions:</p>
      <ul class="list-group">
        {% for slot in project.shuttle_slots.all %}
        <li class="list-group-item">
          <strong>{{ slot.grid_position }}</strong> ({{ slot.get_slot_size_display }})
          <span class="text-muted ms-2">
            — Assigned by {{ slot.reserved_by.username }} on {{ slot.reserved_at|date:"Y-m-d H:i" }}
          </span>
        </li>
        {% endfor %}
      </ul>
      <a href="{% url 'shuttles:assignment' pk=project.shuttle.pk %}" class="btn btn-sm btn-outline-primary mt-3">
        <i class="bi bi-box-arrow-up-right"></i> View Shuttle Layout
      </a>
    </div>
  </div>
  {% endif %}
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest wafer_space/projects/tests/test_views.py::TestProjectDetailSlotVisibility -v
```

Expected: All tests PASS

**Step 5: Run full test suite**

```bash
make test
```

Expected: All tests PASS

**Step 6: Commit**

```bash
git add wafer_space/projects/templates/projects/detail.html wafer_space/projects/tests/test_views.py
git commit -m "feat: add slot assignment visibility to project detail page

- Show assigned slots section for staff users only
- Display grid positions and assignment metadata
- Link to shuttle layout for context
- Regular users see no slot information

🤖 Generated with [Claude Code](https://claude.ai/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: Integration Testing and Documentation

**Files:**
- Create: `wafer_space/shuttles/tests/test_integration.py`
- Update: `docs/plans/2025-12-03-shuttle-grid-layout-design.md` (mark as implemented)

**Step 1: Write integration tests**

Create `wafer_space/shuttles/tests/test_integration.py`:

```python
"""Integration tests for shuttle grid layout system."""

import pytest
from pathlib import Path
from io import StringIO
from django.core.management import call_command
from wafer_space.shuttles.models import Shuttle, ShuttleSlot
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.users.tests.factories import UserFactory
from wafer_space.core.enums import SlotSize


@pytest.mark.django_db
class TestGridWorkflow:
    """Test end-to-end grid configuration and assignment workflow."""

    def test_complete_workflow(self, tmp_path):
        """Test complete workflow from config to assignment."""
        # Step 1: Create shuttle
        shuttle = Shuttle.objects.create(
            name="G801",
            description="Production shuttle",
            status=Shuttle.Status.OPEN,
        )

        # Step 2: Create grid configuration
        config_file = tmp_path / "G801-layout.yaml"
        config_file.write_text("""
shuttle: G801
row_heights: [1.0, 0.5]
column_widths: [1.0, 0.5, 1.0]
""")

        # Step 3: Generate grid
        out = StringIO()
        call_command(
            "generate_shuttle_grid",
            "G801",
            f"--config-dir={tmp_path}",
            stdout=out,
        )

        # Verify grid created
        slots = list(ShuttleSlot.objects.filter(shuttle=shuttle).order_by("row", "column"))
        assert len(slots) == 6  # 2 rows x 3 columns

        # Verify grid positions
        assert slots[0].grid_position == "A1"  # (0, 0)
        assert slots[1].grid_position == "B1"  # (0, 1)
        assert slots[2].grid_position == "C1"  # (0, 2)
        assert slots[3].grid_position == "A2"  # (1, 0)
        assert slots[4].grid_position == "B2"  # (1, 1)
        assert slots[5].grid_position == "C2"  # (1, 2)

        # Verify slot sizes
        assert slots[0].slot_size == SlotSize.FULL  # 1.0 x 1.0
        assert slots[1].slot_size == SlotSize.HALF_HEIGHT  # 1.0 x 0.5
        assert slots[3].slot_size == SlotSize.HALF_WIDTH  # 0.5 x 1.0
        assert slots[4].slot_size == SlotSize.QUARTER  # 0.5 x 0.5

        # Step 4: Create projects
        project_full = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL, project_id="FULL")
        project_quarter = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.QUARTER, project_id="QRTR")

        # Step 5: Assign projects to slots
        user = UserFactory(is_staff=True)

        # Assign FULL project to A1
        slots[0].reserve(project_full, user)
        assert slots[0].project == project_full
        assert slots[0].status == ShuttleSlot.Status.RESERVED

        # Assign QUARTER project to B2
        slots[4].reserve(project_quarter, user)
        assert slots[4].project == project_quarter

        # Step 6: Verify multi-slot assignment
        slots[2].reserve(project_full, user)  # Assign FULL to C1 as well
        assert project_full.shuttle_slots.count() == 2

        # Step 7: Verify grid dimensions property
        assert shuttle.grid_dimensions == (2, 3)

    def test_grid_regeneration_safety(self, tmp_path):
        """Test that grid regeneration protects assigned projects."""
        shuttle = Shuttle.objects.create(
            name="G801",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
        )

        # Create initial grid
        config_v1 = tmp_path / "TEST01-layout.yaml"
        config_v1.write_text("""
shuttle: TEST01
row_heights: [1.0]
column_widths: [1.0]
""")

        call_command("generate_shuttle_grid", "TEST01", f"--config-dir={tmp_path}", stdout=StringIO())

        # Assign project
        slot = ShuttleSlot.objects.get(shuttle=shuttle)
        project = ProjectFactory(shuttle=shuttle)
        user = UserFactory()
        slot.reserve(project, user)

        # Try to update without --force
        config_v2 = tmp_path / "TEST01-layout.yaml"
        config_v2.write_text("""
shuttle: TEST01
row_heights: [1.0, 1.0]
column_widths: [1.0, 1.0]
""")

        with pytest.raises(SystemExit):
            call_command(
                "generate_shuttle_grid",
                "TEST01",
                f"--config-dir={tmp_path}",
                "--update",
                stdout=StringIO(),
            )

        # Verify original slot still exists
        assert ShuttleSlot.objects.filter(shuttle=shuttle, project=project).exists()

        # Update with --force
        call_command(
            "generate_shuttle_grid",
            "TEST01",
            f"--config-dir={tmp_path}",
            "--update",
            "--force",
            stdout=StringIO(),
        )

        # Verify new grid created
        assert ShuttleSlot.objects.filter(shuttle=shuttle).count() == 4  # 2x2 grid

        # Verify project still on shuttle but no slot
        project.refresh_from_db()
        assert project.shuttle == shuttle
        assert project.shuttle_slots.count() == 0
```

**Step 2: Run integration tests**

```bash
uv run pytest wafer_space/shuttles/tests/test_integration.py -v
```

Expected: All tests PASS

**Step 3: Run full test suite**

```bash
make test
```

Expected: All tests PASS

**Step 4: Update design document**

Add to top of `docs/plans/2025-12-03-shuttle-grid-layout-design.md`:

```markdown
**Status:** ✅ Implemented - PR #XXX
**Implementation Plan:** [2025-12-03-shuttle-grid-layout-implementation.md](./2025-12-03-shuttle-grid-layout-implementation.md)
```

**Step 5: Commit**

```bash
git add wafer_space/shuttles/tests/test_integration.py docs/plans/2025-12-03-shuttle-grid-layout-design.md
git commit -m "test: add integration tests for grid workflow

- Test complete workflow from config to assignment
- Test grid regeneration safety mechanisms
- Test multi-slot assignment
- Verify grid dimensions calculation

🤖 Generated with [Claude Code](https://claude.ai/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Final Steps

**Step 1: Run all quality checks**

```bash
make lint-fix && make lint && make type-check && make test
```

Expected: All checks PASS

**Step 2: Review changes**

```bash
git log --oneline main..HEAD
git diff main..HEAD --stat
```

**Step 3: Push to remote**

```bash
git push -u origin feature/shuttle-grid-layout
```

**Step 4: Create pull request**

```bash
gh pr create --title "Phase B: Shuttle Grid Layout & Slot Assignment" --body "$(cat <<'EOF'
## Summary

Implements Phase B of shuttle integration: grid layout management and staff-driven slot assignment.

**Key Features:**
- Grid positioning model with row/column coordinates
- YAML-based grid configuration system
- Management command for grid generation/updates
- Staff assignment dashboard with statistics and filtering
- Read-only grid preview
- Multi-slot assignment support with size validation
- Project detail page integration (staff-only)

**Architecture:**
- ShuttleSlot: Added row, column, slot_size fields
- Spreadsheet-style position notation (A1, B2, etc.)
- Database transactions for concurrency safety
- Size mismatch warnings (non-blocking)

**Testing:**
- 100+ new unit tests across all components
- Integration tests for complete workflow
- Browser tests for assignment UI

**Documentation:**
- Implementation plan: docs/plans/2025-12-03-shuttle-grid-layout-implementation.md
- Design document: docs/plans/2025-12-03-shuttle-grid-layout-design.md

Depends on: #140 (Phase A)
Blocks: Phase C (Grid Configuration UI)

🤖 Generated with [Claude Code](https://claude.ai/claude-code)
EOF
)"
```

---

## Success Criteria Verification

Run through success criteria from design document:

1. ✅ Staff can generate grid from YAML config → `python manage.py generate_shuttle_grid G801`
2. ✅ Staff can view grid occupancy at a glance → Grid preview iframe
3. ✅ Staff can assign projects to specific slots → Assignment modal + endpoints
4. ✅ Staff see warnings for size mismatches → Warning returned in JSON response
5. ✅ Same project can occupy multiple slots → Multi-slot assignment supported
6. ✅ Grid can be safely regenerated with --force → --update and --force flags
7. ✅ Summary statistics show assignment progress → Statistics panel in dashboard
8. ✅ Slot assignments visible on project detail page → Staff-only section added
