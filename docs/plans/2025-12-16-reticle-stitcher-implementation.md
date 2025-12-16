# Reticle Stitcher Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the `generate_reticle_package` management command that creates a directory package for the external reticle stitcher tool.

**Architecture:** A service-based approach with the management command delegating to a `ReticlePackageService` class. The service collects project data, builds the tilemap grid, generates CSV files, creates the README with ASCII layout, writes per-project info.json files, and hardlinks GDS files.

**Tech Stack:** Django management command, Python dataclasses, csv module, pathlib, os.link() for hardlinks

**Design Doc:** `docs/plans/2025-12-16-reticle-stitcher-design.md`

---

## Task 1: Create ProjectData Dataclass

**Files:**
- Create: `wafer_space/shuttles/services/reticle_package.py`
- Test: `wafer_space/shuttles/tests/test_reticle_package_service.py`

**Step 1: Create test file with imports**

```python
# wafer_space/shuttles/tests/test_reticle_package_service.py
"""Tests for reticle package generation service."""

from __future__ import annotations

import pytest

from wafer_space.shuttles.services.reticle_package import ProjectData


class TestProjectData:
    """Tests for ProjectData dataclass."""

    def test_project_data_creation(self):
        """ProjectData can be created with required fields."""
        data = ProjectData(
            code="MOLE",
            project_name="Mole Detector",
            project_uuid="12345678-1234-1234-1234-123456789abc",
            project_url="https://example.com/projects/123/",
            slot_size="1x1",
            slot_positions=["A1", "A2", "B1", "B2"],
            top_cell="MOLE_TOP",
            gds_path="/path/to/output.gds",
            gds_sha256="abc123",
            is_submitted=True,
            check_status="manufacturable",
            check_warnings=2,
            check_errors=0,
        )
        assert data.code == "MOLE"
        assert data.layout_path == "MOLE/MOLE_TOP.gds"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestProjectData::test_project_data_creation -v`

Expected: FAIL with "ModuleNotFoundError" or "ImportError"

**Step 3: Create services directory and module**

```bash
mkdir -p wafer_space/shuttles/services
touch wafer_space/shuttles/services/__init__.py
```

**Step 4: Create ProjectData dataclass**

```python
# wafer_space/shuttles/services/reticle_package.py
"""Service for generating reticle stitcher packages."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field


@dataclass
class ProjectData:
    """Data collected for a single project in the reticle package."""

    code: str  # 4-char project_id
    project_name: str
    project_uuid: str
    project_url: str
    slot_size: str  # "1x1", "0p5x1", "1x0p5", "0p5x0p5"
    slot_positions: list[str]  # Grid positions like ["A1", "B1"]
    top_cell: str
    gds_path: str  # Path to source GDS file
    gds_sha256: str
    is_submitted: bool
    check_status: str  # "manufacturable", "manufacturable_with_warnings", etc.
    check_warnings: int
    check_errors: int
    # Optional fields
    submitted_at: str | None = None
    repository_url: str | None = None
    check_version: str | None = None
    check_runtime_seconds: float | None = None
    check_url: str | None = None
    input_file_url: str | None = None
    input_md5: str | None = None
    input_sha256: str | None = None

    @property
    def layout_path(self) -> str:
        """Return relative path for GDS file in package."""
        return f"{self.code}/{self.top_cell}.gds"
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestProjectData::test_project_data_creation -v`

Expected: PASS

**Step 6: Run lint and commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/shuttles/services/ wafer_space/shuttles/tests/test_reticle_package_service.py
git commit -m "feat: add ProjectData dataclass for reticle package"
```

---

## Task 2: Create SlotData Dataclass for Empty Slots

**Files:**
- Modify: `wafer_space/shuttles/services/reticle_package.py`
- Test: `wafer_space/shuttles/tests/test_reticle_package_service.py`

**Step 1: Add test for SlotData**

```python
# Add to test_reticle_package_service.py
from wafer_space.shuttles.services.reticle_package import SlotData


class TestSlotData:
    """Tests for SlotData dataclass."""

    def test_slot_data_empty(self):
        """SlotData for empty slot."""
        slot = SlotData(
            row=0,
            column=0,
            slot_size="1x1",
            project_code=None,
        )
        assert slot.is_empty
        assert slot.tile_width == 2
        assert slot.tile_height == 2

    def test_slot_data_with_project(self):
        """SlotData with assigned project."""
        slot = SlotData(
            row=1,
            column=2,
            slot_size="0p5x1",
            project_code="MOLE",
        )
        assert not slot.is_empty
        assert slot.tile_width == 1
        assert slot.tile_height == 2

    def test_slot_size_to_tiles(self):
        """Test all slot size to tile mappings."""
        assert SlotData(0, 0, "1x1", None).tile_dimensions == (2, 2)
        assert SlotData(0, 0, "0p5x1", None).tile_dimensions == (1, 2)
        assert SlotData(0, 0, "1x0p5", None).tile_dimensions == (2, 1)
        assert SlotData(0, 0, "0p5x0p5", None).tile_dimensions == (1, 1)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestSlotData -v`

Expected: FAIL

**Step 3: Add SlotData dataclass**

```python
# Add to wafer_space/shuttles/services/reticle_package.py after ProjectData

# Mapping from slot size to tile dimensions (width, height)
SLOT_SIZE_TO_TILES: dict[str, tuple[int, int]] = {
    "1x1": (2, 2),
    "0p5x1": (1, 2),
    "1x0p5": (2, 1),
    "0p5x0p5": (1, 1),
}


@dataclass
class SlotData:
    """Data for a shuttle slot (may or may not have a project)."""

    row: int
    column: int
    slot_size: str
    project_code: str | None

    @property
    def is_empty(self) -> bool:
        """Return True if slot has no assigned project."""
        return self.project_code is None

    @property
    def tile_dimensions(self) -> tuple[int, int]:
        """Return (width, height) in tiles."""
        return SLOT_SIZE_TO_TILES.get(self.slot_size, (2, 2))

    @property
    def tile_width(self) -> int:
        """Return width in tiles."""
        return self.tile_dimensions[0]

    @property
    def tile_height(self) -> int:
        """Return height in tiles."""
        return self.tile_dimensions[1]
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestSlotData -v`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add -A && git commit -m "feat: add SlotData dataclass with tile mapping"
```

---

## Task 3: Create Tilemap Grid Builder

**Files:**
- Modify: `wafer_space/shuttles/services/reticle_package.py`
- Test: `wafer_space/shuttles/tests/test_reticle_package_service.py`

**Step 1: Add test for tilemap building**

```python
# Add to test_reticle_package_service.py
from wafer_space.shuttles.services.reticle_package import build_tilemap_grid


class TestBuildTilemapGrid:
    """Tests for tilemap grid building."""

    def test_simple_grid(self):
        """Build tilemap from simple 2x2 slot grid."""
        slots = [
            SlotData(row=0, column=0, slot_size="1x1", project_code="MOLE"),
            SlotData(row=0, column=1, slot_size="1x1", project_code="KIAN"),
            SlotData(row=1, column=0, slot_size="1x1", project_code=None),
            SlotData(row=1, column=1, slot_size="1x1", project_code="CAFE"),
        ]
        grid = build_tilemap_grid(slots, num_rows=2, num_columns=2)

        # Each 1x1 slot becomes 2x2 tiles, so 2x2 slots = 4x4 tiles
        assert len(grid) == 4  # 4 tile rows
        assert len(grid[0]) == 4  # 4 tile columns

        # MOLE in top-left 2x2
        assert grid[0][0] == "MOLE"
        assert grid[0][1] == "MOLE"
        assert grid[1][0] == "MOLE"
        assert grid[1][1] == "MOLE"

        # KIAN in top-right 2x2
        assert grid[0][2] == "KIAN"
        assert grid[0][3] == "KIAN"

        # Empty slot in bottom-left
        assert grid[2][0] == ""
        assert grid[2][1] == ""

        # CAFE in bottom-right
        assert grid[2][2] == "CAFE"

    def test_mixed_slot_sizes(self):
        """Build tilemap with different slot sizes."""
        slots = [
            SlotData(row=0, column=0, slot_size="0p5x0p5", project_code="A001"),
            SlotData(row=0, column=1, slot_size="0p5x0p5", project_code="B002"),
        ]
        grid = build_tilemap_grid(slots, num_rows=1, num_columns=2)

        # 0.5x0.5 slots = 1x1 tiles each
        assert len(grid) == 1
        assert len(grid[0]) == 2
        assert grid[0][0] == "A001"
        assert grid[0][1] == "B002"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestBuildTilemapGrid -v`

Expected: FAIL

**Step 3: Implement build_tilemap_grid**

```python
# Add to wafer_space/shuttles/services/reticle_package.py

def build_tilemap_grid(
    slots: list[SlotData],
    num_rows: int,
    num_columns: int,
) -> list[list[str]]:
    """Build a 2D tilemap grid from slot data.

    Args:
        slots: List of SlotData objects (must be sorted by row, column)
        num_rows: Number of slot rows
        num_columns: Number of slot columns

    Returns:
        2D list of project codes (empty string for unoccupied tiles)
    """
    # Calculate tile grid dimensions
    # We need to sum up the tile heights/widths based on slot sizes
    # For simplicity, assume uniform slot sizes per row/column
    # and calculate based on the slots provided

    # First pass: determine tile dimensions from slot layout
    tile_rows = 0
    tile_cols = 0

    # Group slots by row to calculate tile heights
    row_heights: dict[int, int] = {}
    col_widths: dict[int, int] = {}

    for slot in slots:
        tile_w, tile_h = slot.tile_dimensions
        row_heights[slot.row] = max(row_heights.get(slot.row, 0), tile_h)
        col_widths[slot.column] = max(col_widths.get(slot.column, 0), tile_w)

    # Calculate cumulative positions
    row_offsets = {}
    current = 0
    for r in range(num_rows):
        row_offsets[r] = current
        current += row_heights.get(r, 2)
    tile_rows = current

    col_offsets = {}
    current = 0
    for c in range(num_columns):
        col_offsets[c] = current
        current += col_widths.get(c, 2)
    tile_cols = current

    # Initialize grid with empty strings
    grid: list[list[str]] = [["" for _ in range(tile_cols)] for _ in range(tile_rows)]

    # Fill in project codes
    for slot in slots:
        if slot.project_code is None:
            continue

        tile_w, tile_h = slot.tile_dimensions
        start_row = row_offsets[slot.row]
        start_col = col_offsets[slot.column]

        for dr in range(tile_h):
            for dc in range(tile_w):
                grid[start_row + dr][start_col + dc] = slot.project_code

    return grid
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestBuildTilemapGrid -v`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add -A && git commit -m "feat: add build_tilemap_grid function"
```

---

## Task 4: Create CSV Writers

**Files:**
- Modify: `wafer_space/shuttles/services/reticle_package.py`
- Test: `wafer_space/shuttles/tests/test_reticle_package_service.py`

**Step 1: Add test for CSV generation**

```python
# Add to test_reticle_package_service.py
import csv
import io

from wafer_space.shuttles.services.reticle_package import (
    write_tilemap_csv,
    write_manifest_csv,
)


class TestCSVWriters:
    """Tests for CSV generation functions."""

    def test_write_tilemap_csv(self):
        """Write tilemap grid to CSV format."""
        grid = [
            ["MOLE", "MOLE", "KIAN"],
            ["MOLE", "MOLE", "KIAN"],
            ["", "", "CAFE"],
        ]
        output = io.StringIO()
        write_tilemap_csv(grid, output)

        output.seek(0)
        content = output.read()
        lines = content.strip().split("\n")

        assert len(lines) == 3
        assert lines[0] == "MOLE,MOLE,KIAN"
        assert lines[2] == ",,CAFE"

    def test_write_manifest_csv(self):
        """Write manifest CSV with headers."""
        projects = [
            ProjectData(
                code="CAFE",
                project_name="Cafe Chip",
                project_uuid="uuid1",
                project_url="url1",
                slot_size="1x1",
                slot_positions=["C1"],
                top_cell="CAFE_TOP",
                gds_path="/path/cafe.gds",
                gds_sha256="hash1",
                is_submitted=True,
                check_status="manufacturable",
                check_warnings=0,
                check_errors=0,
            ),
            ProjectData(
                code="MOLE",
                project_name="Mole Detector",
                project_uuid="uuid2",
                project_url="url2",
                slot_size="0p5x1",
                slot_positions=["A1", "A2"],
                top_cell="MOLE_TOP",
                gds_path="/path/mole.gds",
                gds_sha256="hash2",
                is_submitted=True,
                check_status="manufacturable_with_warnings",
                check_warnings=3,
                check_errors=0,
            ),
        ]
        output = io.StringIO()
        write_manifest_csv(projects, output)

        output.seek(0)
        reader = csv.DictReader(output)
        rows = list(reader)

        # Should be sorted by CODE, MOLE has 2 slots so 2 rows
        assert len(rows) == 3  # CAFE x1 + MOLE x2
        assert rows[0]["CODE"] == "CAFE"
        assert rows[1]["CODE"] == "MOLE"
        assert rows[1]["SLOT"] == "0p5x1"
        assert rows[1]["LAYOUT"] == "MOLE/MOLE_TOP.gds"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestCSVWriters -v`

Expected: FAIL

**Step 3: Implement CSV writers**

```python
# Add to wafer_space/shuttles/services/reticle_package.py
import csv
from typing import TextIO


def write_tilemap_csv(grid: list[list[str]], output: TextIO) -> None:
    """Write tilemap grid to CSV format (no headers).

    Args:
        grid: 2D list of project codes
        output: File-like object to write to
    """
    writer = csv.writer(output)
    for row in grid:
        writer.writerow(row)


def write_manifest_csv(projects: list[ProjectData], output: TextIO) -> None:
    """Write manifest CSV with headers, sorted by CODE.

    One row per slot assignment (projects in multiple slots get multiple rows).

    Args:
        projects: List of ProjectData objects
        output: File-like object to write to
    """
    fieldnames = ["CODE", "PROJECT", "SLOT", "TOP", "HASH_SHA256", "LAYOUT"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    # Build rows: one per project-slot combination, sorted by CODE
    rows = []
    for project in projects:
        for _position in project.slot_positions:
            rows.append({
                "CODE": project.code,
                "PROJECT": project.project_name,
                "SLOT": project.slot_size,
                "TOP": project.top_cell,
                "HASH_SHA256": project.gds_sha256,
                "LAYOUT": project.layout_path,
            })

    # Sort by CODE
    rows.sort(key=lambda r: r["CODE"])

    for row in rows:
        writer.writerow(row)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestCSVWriters -v`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add -A && git commit -m "feat: add CSV writers for tilemap and manifest"
```

---

## Task 5: Add Summary and Checks CSV Writers

**Files:**
- Modify: `wafer_space/shuttles/services/reticle_package.py`
- Test: `wafer_space/shuttles/tests/test_reticle_package_service.py`

**Step 1: Add tests**

```python
# Add to TestCSVWriters class
from wafer_space.shuttles.services.reticle_package import (
    write_summary_csv,
    write_checks_csv,
)


    def test_write_summary_csv(self):
        """Write summary CSV with project overview."""
        projects = [
            ProjectData(
                code="MOLE",
                project_name="Mole Detector",
                project_uuid="uuid1",
                project_url="https://example.com/p/1/",
                slot_size="1x1",
                slot_positions=["A1"],
                top_cell="MOLE_TOP",
                gds_path="/path/mole.gds",
                gds_sha256="hash1",
                is_submitted=True,
                check_status="manufacturable",
                check_warnings=0,
                check_errors=0,
                submitted_at="2025-12-15T10:00:00Z",
                repository_url="https://github.com/example/mole",
            ),
        ]
        output = io.StringIO()
        write_summary_csv(projects, output)

        output.seek(0)
        reader = csv.DictReader(output)
        rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["CODE"] == "MOLE"
        assert rows[0]["PROJECT_NAME"] == "Mole Detector"
        assert rows[0]["PROJECT_URL"] == "https://example.com/p/1/"

    def test_write_checks_csv(self):
        """Write checks CSV with manufacturability details."""
        projects = [
            ProjectData(
                code="MOLE",
                project_name="Mole Detector",
                project_uuid="uuid1",
                project_url="url1",
                slot_size="1x1",
                slot_positions=["A1"],
                top_cell="MOLE_TOP",
                gds_path="/path/mole.gds",
                gds_sha256="hash1",
                is_submitted=True,
                check_status="manufacturable_with_warnings",
                check_warnings=5,
                check_errors=0,
                check_version="v2.1.0",
                check_runtime_seconds=120.5,
            ),
        ]
        output = io.StringIO()
        write_checks_csv(projects, output)

        output.seek(0)
        reader = csv.DictReader(output)
        rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["CHECK_STATUS"] == "manufacturable_with_warnings"
        assert rows[0]["CHECK_WARNINGS"] == "5"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestCSVWriters::test_write_summary_csv -v`

Expected: FAIL

**Step 3: Implement summary and checks CSV writers**

```python
# Add to wafer_space/shuttles/services/reticle_package.py

def write_summary_csv(projects: list[ProjectData], output: TextIO) -> None:
    """Write summary CSV with project overview, sorted by CODE.

    Args:
        projects: List of ProjectData objects
        output: File-like object to write to
    """
    fieldnames = [
        "CODE",
        "PROJECT_NAME",
        "PROJECT_URL",
        "SLOT",
        "STATUS",
        "TOP_CELL",
        "SUBMITTED_AT",
        "REPOSITORY_URL",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    # Sort by CODE
    sorted_projects = sorted(projects, key=lambda p: p.code)

    for project in sorted_projects:
        status = "Submitted" if project.is_submitted else "Assigned"
        writer.writerow({
            "CODE": project.code,
            "PROJECT_NAME": project.project_name,
            "PROJECT_URL": project.project_url,
            "SLOT": project.slot_size,
            "STATUS": status,
            "TOP_CELL": project.top_cell,
            "SUBMITTED_AT": project.submitted_at or "",
            "REPOSITORY_URL": project.repository_url or "",
        })


def write_checks_csv(projects: list[ProjectData], output: TextIO) -> None:
    """Write checks CSV with manufacturability details, sorted by CODE.

    Args:
        projects: List of ProjectData objects
        output: File-like object to write to
    """
    fieldnames = [
        "CODE",
        "PROJECT_NAME",
        "CHECK_STATUS",
        "CHECK_WARNINGS",
        "CHECK_ERRORS",
        "CHECK_VERSION",
        "CHECK_RUNTIME_SECONDS",
        "CHECK_URL",
        "INPUT_FILE_URL",
        "INPUT_MD5",
        "INPUT_SHA256",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    sorted_projects = sorted(projects, key=lambda p: p.code)

    for project in sorted_projects:
        writer.writerow({
            "CODE": project.code,
            "PROJECT_NAME": project.project_name,
            "CHECK_STATUS": project.check_status,
            "CHECK_WARNINGS": str(project.check_warnings),
            "CHECK_ERRORS": str(project.check_errors),
            "CHECK_VERSION": project.check_version or "",
            "CHECK_RUNTIME_SECONDS": (
                str(project.check_runtime_seconds)
                if project.check_runtime_seconds is not None
                else ""
            ),
            "CHECK_URL": project.check_url or "",
            "INPUT_FILE_URL": project.input_file_url or "",
            "INPUT_MD5": project.input_md5 or "",
            "INPUT_SHA256": project.input_sha256 or "",
        })
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestCSVWriters -v`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add -A && git commit -m "feat: add summary and checks CSV writers"
```

---

## Task 6: Create README Generator

**Files:**
- Modify: `wafer_space/shuttles/services/reticle_package.py`
- Test: `wafer_space/shuttles/tests/test_reticle_package_service.py`

**Step 1: Add test for README generation**

```python
# Add to test_reticle_package_service.py
from wafer_space.shuttles.services.reticle_package import generate_readme


class TestReadmeGenerator:
    """Tests for README.md generation."""

    def test_generate_readme_header(self):
        """README includes header with metadata."""
        readme = generate_readme(
            shuttle_name="G801",
            generated_at="2025-12-16 14:32:05 UTC",
            hostname="platform.wafer.space",
            git_revision="v1.2.3-45-gabcdef1",
            projects=[],
            slots=[],
            precheck_version="gf180mcu-precheck v2.1.0",
        )

        assert "# G801 Reticle Package" in readme
        assert "2025-12-16 14:32:05 UTC" in readme
        assert "platform.wafer.space" in readme
        assert "v1.2.3-45-gabcdef1" in readme

    def test_generate_readme_with_projects(self):
        """README includes project table."""
        projects = [
            ProjectData(
                code="MOLE",
                project_name="Mole Detector",
                project_uuid="uuid1",
                project_url="url1",
                slot_size="1x1",
                slot_positions=["A1"],
                top_cell="MOLE_TOP",
                gds_path="/path/mole.gds",
                gds_sha256="hash1",
                is_submitted=True,
                check_status="manufacturable",
                check_warnings=0,
                check_errors=0,
            ),
        ]
        readme = generate_readme(
            shuttle_name="G801",
            generated_at="2025-12-16",
            hostname="test",
            git_revision="test",
            projects=projects,
            slots=[],
            precheck_version="v1.0",
        )

        assert "| MOLE |" in readme
        assert "Mole Detector" in readme
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestReadmeGenerator -v`

Expected: FAIL

**Step 3: Implement README generator (basic version)**

```python
# Add to wafer_space/shuttles/services/reticle_package.py

def generate_readme(
    shuttle_name: str,
    generated_at: str,
    hostname: str,
    git_revision: str,
    projects: list[ProjectData],
    slots: list[SlotData],
    precheck_version: str,
) -> str:
    """Generate README.md content for the reticle package.

    Args:
        shuttle_name: Shuttle ID (e.g., "G801")
        generated_at: Timestamp string
        hostname: Server hostname
        git_revision: Git describe output
        projects: List of ProjectData objects
        slots: List of SlotData objects for grid layout
        precheck_version: Current precheck version string

    Returns:
        README.md content as string
    """
    lines = [
        f"# {shuttle_name} Reticle Package",
        "",
        f"**Generated:** {generated_at}",
        f"**Host:** {hostname}",
        f"**Code Revision:** {git_revision}",
        "",
    ]

    # Shuttle summary section
    lines.extend(_generate_summary_section(projects, precheck_version))

    # Grid layout section (simplified for now)
    lines.extend(_generate_grid_section(slots))

    # Projects table
    lines.extend(_generate_projects_table(projects))

    return "\n".join(lines)


def _generate_summary_section(
    projects: list[ProjectData],
    precheck_version: str,
) -> list[str]:
    """Generate shuttle summary section."""
    # Count statistics
    total = len(projects)
    submitted = sum(1 for p in projects if p.is_submitted)
    passing = sum(1 for p in projects if p.check_status == "manufacturable")
    warnings = sum(
        1 for p in projects if p.check_status == "manufacturable_with_warnings"
    )

    return [
        "## Shuttle Summary",
        "",
        f"- **Total projects:** {total}",
        f"- **Submitted:** {submitted}",
        f"- **Passing (clean):** {passing}",
        f"- **Passing (warnings):** {warnings}",
        f"- **Precheck version:** {precheck_version}",
        "",
    ]


def _generate_grid_section(slots: list[SlotData]) -> list[str]:
    """Generate ASCII grid layout section."""
    # Simplified grid - full implementation in later task
    if not slots:
        return ["## Shuttle Layout", "", "(No slots)", ""]

    return [
        "## Shuttle Layout",
        "",
        "See tilemap.csv for detailed layout.",
        "",
    ]


def _generate_projects_table(projects: list[ProjectData]) -> list[str]:
    """Generate projects table section."""
    if not projects:
        return ["## Projects", "", "(No projects)", ""]

    lines = [
        "## Projects",
        "",
        "| CODE | Name | Status | Slot | Top Cell |",
        "|------|------|--------|------|----------|",
    ]

    sorted_projects = sorted(projects, key=lambda p: p.code)
    for p in sorted_projects:
        status = "Submitted" if p.is_submitted else "Assigned"
        if p.check_status == "manufacturable":
            status = "Passing"
        elif p.check_status == "manufacturable_with_warnings":
            status = "Warnings"
        elif p.check_status == "not_manufacturable":
            status = "Failed"
        lines.append(f"| {p.code} | {p.project_name} | {status} | {p.slot_size} | {p.top_cell} |")

    lines.append("")
    return lines
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestReadmeGenerator -v`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add -A && git commit -m "feat: add basic README generator"
```

---

## Task 7: Create info.json Generator

**Files:**
- Modify: `wafer_space/shuttles/services/reticle_package.py`
- Test: `wafer_space/shuttles/tests/test_reticle_package_service.py`

**Step 1: Add test**

```python
# Add to test_reticle_package_service.py
import json

from wafer_space.shuttles.services.reticle_package import generate_project_info_json


class TestInfoJsonGenerator:
    """Tests for info.json generation."""

    def test_generate_project_info_json(self):
        """Generate info.json for a project."""
        project = ProjectData(
            code="MOLE",
            project_name="Mole Detector",
            project_uuid="12345678-1234-1234-1234-123456789abc",
            project_url="https://example.com/projects/123/",
            slot_size="1x1",
            slot_positions=["A1", "A2", "B1", "B2"],
            top_cell="MOLE_TOP",
            gds_path="/path/to/output.gds",
            gds_sha256="abc123def456",
            is_submitted=True,
            check_status="manufacturable",
            check_warnings=2,
            check_errors=0,
            check_version="v2.1.0",
            check_runtime_seconds=127.5,
        )

        info_json = generate_project_info_json(project)
        data = json.loads(info_json)

        assert data["code"] == "MOLE"
        assert data["project"]["name"] == "Mole Detector"
        assert data["project"]["uuid"] == "12345678-1234-1234-1234-123456789abc"
        assert data["manufacturability_check"]["warnings_count"] == 2
        assert data["slot_positions"] == ["A1", "A2", "B1", "B2"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestInfoJsonGenerator -v`

Expected: FAIL

**Step 3: Implement info.json generator**

```python
# Add to wafer_space/shuttles/services/reticle_package.py
import json


def generate_project_info_json(project: ProjectData) -> str:
    """Generate info.json content for a single project.

    Args:
        project: ProjectData object

    Returns:
        JSON string with project details
    """
    data = {
        "code": project.code,
        "project": {
            "uuid": project.project_uuid,
            "name": project.project_name,
            "url": project.project_url,
            "slot_size": project.slot_size,
            "status": "SUBMITTED" if project.is_submitted else "ASSIGNED",
            "submitted_at": project.submitted_at,
            "repository_url": project.repository_url,
        },
        "project_file": {
            "top_cell": project.top_cell,
            "source_url": project.input_file_url,
            "sha256": project.input_sha256,
        },
        "manufacturability_check": {
            "status": "COMPLETED" if project.check_status != "no_check" else "NONE",
            "result": project.check_status,
            "warnings_count": project.check_warnings,
            "errors_count": project.check_errors,
            "version": project.check_version,
            "runtime_seconds": project.check_runtime_seconds,
            "output_gds_sha256": project.gds_sha256,
        },
        "slot_positions": project.slot_positions,
    }

    return json.dumps(data, indent=2)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestInfoJsonGenerator -v`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add -A && git commit -m "feat: add info.json generator"
```

---

## Task 8: Create GDS Hardlink Helper

**Files:**
- Modify: `wafer_space/shuttles/services/reticle_package.py`
- Test: `wafer_space/shuttles/tests/test_reticle_package_service.py`

**Step 1: Add test**

```python
# Add to test_reticle_package_service.py
from pathlib import Path
import tempfile
import shutil

from wafer_space.shuttles.services.reticle_package import create_gds_link


class TestGdsLinkCreation:
    """Tests for GDS file linking."""

    def test_create_hardlink(self):
        """Create hardlink to GDS file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create source file
            source = tmppath / "source.gds"
            source.write_text("GDS content")

            # Create destination
            dest = tmppath / "output" / "MOLE" / "TOP.gds"

            warnings = create_gds_link(source, dest)

            assert dest.exists()
            assert dest.read_text() == "GDS content"
            assert len(warnings) == 0
            # Verify it's a hardlink (same inode)
            assert source.stat().st_ino == dest.stat().st_ino

    def test_fallback_to_copy_cross_filesystem(self):
        """Fall back to copy when hardlink fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            source = tmppath / "source.gds"
            source.write_text("GDS content")

            dest = tmppath / "output" / "MOLE" / "TOP.gds"

            # Force copy mode
            warnings = create_gds_link(source, dest, force_copy=True)

            assert dest.exists()
            assert dest.read_text() == "GDS content"
            assert len(warnings) == 1
            assert "copied" in warnings[0].lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestGdsLinkCreation -v`

Expected: FAIL

**Step 3: Implement GDS link helper**

```python
# Add to wafer_space/shuttles/services/reticle_package.py
import os
import shutil
from pathlib import Path


def create_gds_link(
    source: Path,
    dest: Path,
    *,
    force_copy: bool = False,
) -> list[str]:
    """Create a hardlink to a GDS file, falling back to copy if needed.

    Args:
        source: Path to source GDS file
        dest: Path where link/copy should be created
        force_copy: If True, always copy instead of hardlink

    Returns:
        List of warning messages (empty if hardlink succeeded)
    """
    warnings: list[str] = []

    # Ensure destination directory exists
    dest.parent.mkdir(parents=True, exist_ok=True)

    if force_copy:
        shutil.copy2(source, dest)
        warnings.append(f"Copied {source} to {dest} (forced)")
        return warnings

    try:
        os.link(source, dest)
    except OSError as e:
        # Hardlink failed (likely cross-filesystem), fall back to copy
        shutil.copy2(source, dest)
        warnings.append(
            f"Copied {source} to {dest} (hardlink failed: {e})"
        )

    return warnings
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestGdsLinkCreation -v`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add -A && git commit -m "feat: add GDS hardlink helper with copy fallback"
```

---

## Task 9: Create ReticlePackageService Class

**Files:**
- Modify: `wafer_space/shuttles/services/reticle_package.py`
- Test: `wafer_space/shuttles/tests/test_reticle_package_service.py`

**Step 1: Add test for service initialization**

```python
# Add to test_reticle_package_service.py
from wafer_space.shuttles.services.reticle_package import ReticlePackageService


class TestReticlePackageService:
    """Tests for ReticlePackageService."""

    def test_service_initialization(self):
        """Service can be initialized with shuttle name."""
        service = ReticlePackageService(
            shuttle_name="G801",
            output_path=Path("/tmp/test"),
            allow_pending=False,
        )
        assert service.shuttle_name == "G801"
        assert service.allow_pending is False
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestReticlePackageService::test_service_initialization -v`

Expected: FAIL

**Step 3: Implement service class skeleton**

```python
# Add to wafer_space/shuttles/services/reticle_package.py


class ReticlePackageError(Exception):
    """Exception raised for reticle package generation errors."""

    pass


class ReticlePackageService:
    """Service for generating reticle stitcher packages."""

    def __init__(
        self,
        shuttle_name: str,
        output_path: Path,
        *,
        allow_pending: bool = False,
    ):
        """Initialize the service.

        Args:
            shuttle_name: Shuttle ID (e.g., "G801")
            output_path: Directory path for output
            allow_pending: If True, skip projects without checks
        """
        self.shuttle_name = shuttle_name
        self.output_path = output_path
        self.allow_pending = allow_pending
        self.warnings: list[str] = []

    def generate(self) -> dict[str, int]:
        """Generate the reticle package.

        Returns:
            Dict with counts: projects_included, projects_skipped

        Raises:
            ReticlePackageError: If generation fails
        """
        # Implementation in next task
        raise NotImplementedError("generate() not yet implemented")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestReticlePackageService::test_service_initialization -v`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add -A && git commit -m "feat: add ReticlePackageService skeleton"
```

---

## Task 10: Implement Service generate() Method

**Files:**
- Modify: `wafer_space/shuttles/services/reticle_package.py`
- Test: `wafer_space/shuttles/tests/test_reticle_package_service.py`

This task implements the main `generate()` method that:
1. Validates the shuttle exists
2. Validates output directory doesn't exist
3. Collects project data from database
4. Validates required fields
5. Writes all output files

**Step 1: Add integration test using factories**

```python
# Add to test_reticle_package_service.py
import pytest
from pathlib import Path
import tempfile

from wafer_space.shuttles.services.reticle_package import (
    ReticlePackageService,
    ReticlePackageError,
)


@pytest.mark.django_db
class TestReticlePackageServiceIntegration:
    """Integration tests for ReticlePackageService."""

    def test_generate_fails_if_output_exists(self, tmp_path):
        """Service fails if output directory already exists."""
        output = tmp_path / "G801"
        output.mkdir()

        service = ReticlePackageService(
            shuttle_name="G801",
            output_path=output,
        )

        with pytest.raises(ReticlePackageError, match="already exists"):
            service.generate()

    def test_generate_fails_if_shuttle_not_found(self, tmp_path):
        """Service fails if shuttle doesn't exist."""
        service = ReticlePackageService(
            shuttle_name="XXXX",
            output_path=tmp_path / "output",
        )

        with pytest.raises(ReticlePackageError, match="not found"):
            service.generate()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestReticlePackageServiceIntegration -v`

Expected: FAIL (NotImplementedError or different error)

**Step 3: Implement generate() method**

```python
# Update ReticlePackageService.generate() in reticle_package.py

import socket
import subprocess
from datetime import datetime
from datetime import timezone

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import ProjectFile
from wafer_space.shuttles.config import GridConfig
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot


class ReticlePackageService:
    # ... existing __init__ ...

    def generate(self) -> dict[str, int]:
        """Generate the reticle package.

        Returns:
            Dict with counts: projects_included, projects_skipped

        Raises:
            ReticlePackageError: If generation fails
        """
        # Validate output directory
        if self.output_path.exists():
            msg = f"Output directory already exists: {self.output_path}"
            raise ReticlePackageError(msg)

        # Load shuttle
        try:
            shuttle = Shuttle.objects.get(name=self.shuttle_name)
        except Shuttle.DoesNotExist as e:
            msg = f"Shuttle not found: {self.shuttle_name}"
            raise ReticlePackageError(msg) from e

        # Load grid config
        grid_config = GridConfig.from_file(shuttle.grid_config_file)

        # Collect slot and project data
        slots_data, projects_data = self._collect_data(shuttle, grid_config)

        # Create output directory
        self.output_path.mkdir(parents=True)

        # Generate outputs
        self._write_tilemap(slots_data, grid_config)
        self._write_manifest(projects_data)
        self._write_summary(projects_data)
        self._write_checks(projects_data)
        self._write_readme(shuttle, projects_data, slots_data, grid_config)
        self._write_project_files(projects_data)

        return {
            "projects_included": len(projects_data),
            "projects_skipped": len(self.warnings),
        }

    def _collect_data(
        self,
        shuttle: Shuttle,
        grid_config: GridConfig,
    ) -> tuple[list[SlotData], list[ProjectData]]:
        """Collect slot and project data from database."""
        slots = ShuttleSlot.objects.filter(shuttle=shuttle).select_related(
            "project",
            "project__submitted_file",
        ).order_by("row", "column")

        slots_data: list[SlotData] = []
        projects_data: list[ProjectData] = []
        seen_projects: set[str] = set()

        for slot in slots:
            slot_data = SlotData(
                row=slot.row,
                column=slot.column,
                slot_size=slot.slot_size,
                project_code=slot.project.project_id if slot.project else None,
            )
            slots_data.append(slot_data)

            if slot.project and slot.project.project_id not in seen_projects:
                project_data = self._collect_project_data(slot)
                if project_data:
                    projects_data.append(project_data)
                    seen_projects.add(slot.project.project_id)

        return slots_data, projects_data

    def _collect_project_data(self, slot: ShuttleSlot) -> ProjectData | None:
        """Collect data for a single project from a slot."""
        project = slot.project
        if not project:
            return None

        # Get project file
        project_file = project.submitted_file
        if not project_file and self.allow_pending:
            # Fall back to latest with passing check
            project_file = (
                ProjectFile.objects.filter(
                    project=project,
                    manufacturability_checks__status=ManufacturabilityCheck.Status.FINISHED,
                )
                .order_by("-created_at")
                .first()
            )

        if not project_file:
            if self.allow_pending:
                self.warnings.append(
                    f"Skipping {project.project_id}: no project file with check"
                )
                return None
            msg = f"Project {project.project_id} has no submitted file"
            raise ReticlePackageError(msg)

        # Get manufacturability check
        check = (
            ManufacturabilityCheck.objects.filter(
                project_file=project_file,
                status=ManufacturabilityCheck.Status.FINISHED,
            )
            .order_by("-created_at")
            .first()
        )

        if not check:
            if self.allow_pending:
                self.warnings.append(
                    f"Skipping {project.project_id}: no completed check"
                )
                return None
            msg = f"Project {project.project_id} has no completed check"
            raise ReticlePackageError(msg)

        # Validate required fields
        if not check.output_gds:
            msg = f"Project {project.project_id} check missing output_gds"
            raise ReticlePackageError(msg)

        if not project_file.top_cell:
            msg = f"Project {project.project_id} missing top_cell"
            raise ReticlePackageError(msg)

        # Get all slot positions for this project
        slot_positions = list(
            ShuttleSlot.objects.filter(
                shuttle=slot.shuttle,
                project=project,
            ).values_list("grid_position", flat=True)
        )

        # Determine check status
        check_status = "no_check"
        if check.finished_status:
            check_status = check.finished_status.value

        return ProjectData(
            code=project.project_id,
            project_name=project.name,
            project_uuid=str(project.id),
            project_url=f"/projects/{project.id}/",  # Simplified URL
            slot_size=slot.slot_size,
            slot_positions=slot_positions,
            top_cell=project_file.top_cell,
            gds_path=check.output_gds.path,
            gds_sha256=check.output_gds_sha256 or "",
            is_submitted=project.submitted_file is not None,
            check_status=check_status,
            check_warnings=len(check.warnings) if check.warnings else 0,
            check_errors=len(check.errors) if check.errors else 0,
            submitted_at=(
                project.submitted_at.isoformat() if project.submitted_at else None
            ),
            repository_url=project.repository_url or None,
            check_version=None,  # TODO: Add version tracking
            check_runtime_seconds=(
                check.total_runtime_seconds if hasattr(check, "total_runtime_seconds") else None
            ),
            check_url=f"/admin/projects/manufacturabilitycheck/{check.pk}/change/",
            input_file_url=project_file.source_url or None,
            input_md5=project_file.hash_md5 or None,
            input_sha256=project_file.hash_sha256 or None,
        )

    def _write_tilemap(
        self,
        slots: list[SlotData],
        grid_config: GridConfig,
    ) -> None:
        """Write tilemap.csv."""
        grid = build_tilemap_grid(
            slots,
            num_rows=grid_config.num_rows,
            num_columns=grid_config.num_columns,
        )
        with open(self.output_path / "tilemap.csv", "w") as f:
            write_tilemap_csv(grid, f)

    def _write_manifest(self, projects: list[ProjectData]) -> None:
        """Write manifest.csv."""
        with open(self.output_path / "manifest.csv", "w") as f:
            write_manifest_csv(projects, f)

    def _write_summary(self, projects: list[ProjectData]) -> None:
        """Write summary.csv."""
        with open(self.output_path / "summary.csv", "w") as f:
            write_summary_csv(projects, f)

    def _write_checks(self, projects: list[ProjectData]) -> None:
        """Write checks.csv."""
        with open(self.output_path / "checks.csv", "w") as f:
            write_checks_csv(projects, f)

    def _write_readme(
        self,
        shuttle: Shuttle,
        projects: list[ProjectData],
        slots: list[SlotData],
        grid_config: GridConfig,
    ) -> None:
        """Write README.md."""
        # Get metadata
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        hostname = socket.gethostname()
        try:
            git_revision = subprocess.check_output(
                ["git", "describe", "--always", "--dirty"],
                text=True,
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            git_revision = "unknown"

        readme = generate_readme(
            shuttle_name=shuttle.name,
            generated_at=generated_at,
            hostname=hostname,
            git_revision=git_revision,
            projects=projects,
            slots=slots,
            precheck_version="unknown",  # TODO: Get from settings
        )

        with open(self.output_path / "README.md", "w") as f:
            f.write(readme)

    def _write_project_files(self, projects: list[ProjectData]) -> None:
        """Write info.json and create GDS links for each project."""
        for project in projects:
            project_dir = self.output_path / project.code
            project_dir.mkdir(exist_ok=True)

            # Write info.json
            info_json = generate_project_info_json(project)
            with open(project_dir / "info.json", "w") as f:
                f.write(info_json)

            # Create GDS link
            source = Path(project.gds_path)
            dest = project_dir / f"{project.top_cell}.gds"
            link_warnings = create_gds_link(source, dest)
            self.warnings.extend(link_warnings)
```

**Step 4: Run tests**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py -v`

Expected: Tests should pass (may need to adjust based on actual model structure)

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add -A && git commit -m "feat: implement ReticlePackageService.generate()"
```

---

## Task 11: Create Management Command

**Files:**
- Create: `wafer_space/shuttles/management/commands/generate_reticle_package.py`
- Test: `wafer_space/shuttles/tests/test_generate_reticle_package_command.py`

**Step 1: Add command test**

```python
# wafer_space/shuttles/tests/test_generate_reticle_package_command.py
"""Tests for generate_reticle_package management command."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


class TestGenerateReticlePackageCommand:
    """Tests for the management command."""

    def test_command_requires_output(self):
        """Command fails without --output argument."""
        out = StringIO()
        with pytest.raises(CommandError):
            call_command("generate_reticle_package", "G801", stdout=out)

    def test_command_help(self):
        """Command has help text."""
        out = StringIO()
        call_command("generate_reticle_package", "--help", stdout=out)
        output = out.getvalue()
        assert "reticle" in output.lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/shuttles/tests/test_generate_reticle_package_command.py -v`

Expected: FAIL (command doesn't exist)

**Step 3: Create management command**

```python
# wafer_space/shuttles/management/commands/generate_reticle_package.py
"""Management command to generate reticle stitcher package."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from wafer_space.shuttles.services.reticle_package import ReticlePackageError
from wafer_space.shuttles.services.reticle_package import ReticlePackageService


class Command(BaseCommand):
    """Generate reticle stitcher package for a shuttle."""

    help = "Generate reticle stitcher package with CSV files, GDS links, and README"

    def add_arguments(self, parser):
        parser.add_argument(
            "shuttle_name",
            type=str,
            help="Shuttle ID (e.g., G801)",
        )
        parser.add_argument(
            "--output",
            "-o",
            type=str,
            required=True,
            help="Output directory path (must not exist)",
        )
        parser.add_argument(
            "--allow-pending",
            action="store_true",
            help="Allow projects without completed checks (skip with warning)",
        )

    def handle(self, *args, **options):
        shuttle_name = options["shuttle_name"]
        output_path = Path(options["output"])
        allow_pending = options["allow_pending"]

        self.stdout.write(f"Generating reticle package for {shuttle_name}...")

        service = ReticlePackageService(
            shuttle_name=shuttle_name,
            output_path=output_path,
            allow_pending=allow_pending,
        )

        try:
            result = service.generate()
        except ReticlePackageError as e:
            raise CommandError(str(e)) from e

        # Print warnings
        for warning in service.warnings:
            self.stdout.write(self.style.WARNING(f"Warning: {warning}"))

        # Print summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Package generated at {output_path}\n"
                f"  Projects included: {result['projects_included']}\n"
                f"  Projects skipped: {result['projects_skipped']}\n"
            )
        )
```

**Step 4: Run tests**

Run: `uv run pytest wafer_space/shuttles/tests/test_generate_reticle_package_command.py -v`

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add -A && git commit -m "feat: add generate_reticle_package management command"
```

---

## Task 12: Add Full Integration Test with Factory Data

**Files:**
- Modify: `wafer_space/shuttles/tests/test_reticle_package_service.py`

**Step 1: Create integration test with real database objects**

```python
# Add to test_reticle_package_service.py

@pytest.mark.django_db
class TestReticlePackageFullIntegration:
    """Full integration tests with factory-created data."""

    @pytest.fixture
    def shuttle_with_projects(self):
        """Create a shuttle with projects and checks."""
        from tests.factories import (
            ShuttleFactory,
            ShuttleSlotFactory,
            ProjectFactory,
            ProjectFileFactory,
            ManufacturabilityCheckFactory,
        )

        shuttle = ShuttleFactory(name="TEST")
        # Create a simple 2x2 grid config file
        # ... (setup code depends on actual factory structure)

        return shuttle

    def test_full_package_generation(self, shuttle_with_projects, tmp_path):
        """Generate complete package with all files."""
        output = tmp_path / "TEST"

        service = ReticlePackageService(
            shuttle_name="TEST",
            output_path=output,
            allow_pending=True,
        )

        result = service.generate()

        # Verify all expected files exist
        assert (output / "README.md").exists()
        assert (output / "tilemap.csv").exists()
        assert (output / "manifest.csv").exists()
        assert (output / "summary.csv").exists()
        assert (output / "checks.csv").exists()
```

**Step 2: Run test (may need to create appropriate factories)**

Run: `uv run pytest wafer_space/shuttles/tests/test_reticle_package_service.py::TestReticlePackageFullIntegration -v`

**Step 3: Commit**

```bash
make lint-fix && make lint && make type-check
git add -A && git commit -m "test: add full integration test for reticle package"
```

---

## Task 13: Run Full Test Suite and Final Commit

**Step 1: Run all tests**

```bash
make test
```

**Step 2: Run all quality checks**

```bash
make check-all
```

**Step 3: Final commit if needed**

```bash
git add -A && git commit -m "chore: final cleanup for reticle package feature"
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | ProjectData dataclass | services/reticle_package.py |
| 2 | SlotData dataclass | services/reticle_package.py |
| 3 | Tilemap grid builder | services/reticle_package.py |
| 4 | CSV writers (tilemap, manifest) | services/reticle_package.py |
| 5 | CSV writers (summary, checks) | services/reticle_package.py |
| 6 | README generator | services/reticle_package.py |
| 7 | info.json generator | services/reticle_package.py |
| 8 | GDS hardlink helper | services/reticle_package.py |
| 9 | ReticlePackageService skeleton | services/reticle_package.py |
| 10 | Service generate() method | services/reticle_package.py |
| 11 | Management command | commands/generate_reticle_package.py |
| 12 | Full integration test | tests/ |
| 13 | Final test suite run | - |
