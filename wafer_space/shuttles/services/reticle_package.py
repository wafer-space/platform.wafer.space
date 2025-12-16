"""Service for generating reticle stitcher packages."""

from __future__ import annotations

import csv
import json
import os
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import TextIO

if TYPE_CHECKING:
    from pathlib import Path

# Mapping from slot size to tile dimensions (width, height)
SLOT_SIZE_TO_TILES: dict[str, tuple[int, int]] = {
    "1x1": (2, 2),
    "0p5x1": (1, 2),
    "1x0p5": (2, 1),
    "0p5x0p5": (1, 1),
}


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


@dataclass
class PackageMetadata:
    """Metadata for the reticle package."""

    shuttle_name: str
    generated_at: str
    hostname: str
    git_revision: str
    precheck_version: str


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
        rows.extend(
            [
                {
                    "CODE": project.code,
                    "PROJECT": project.project_name,
                    "SLOT": project.slot_size,
                    "TOP": project.top_cell,
                    "HASH_SHA256": project.gds_sha256,
                    "LAYOUT": project.layout_path,
                }
                for _position in project.slot_positions
            ]
        )

    # Sort by CODE
    rows.sort(key=lambda r: r["CODE"])

    for row in rows:
        writer.writerow(row)


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
        writer.writerow(
            {
                "CODE": project.code,
                "PROJECT_NAME": project.project_name,
                "PROJECT_URL": project.project_url,
                "SLOT": project.slot_size,
                "STATUS": status,
                "TOP_CELL": project.top_cell,
                "SUBMITTED_AT": project.submitted_at or "",
                "REPOSITORY_URL": project.repository_url or "",
            }
        )


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
        writer.writerow(
            {
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
            }
        )


def generate_readme(
    metadata: PackageMetadata,
    projects: list[ProjectData],
    slots: list[SlotData],
) -> str:
    """Generate README.md content for the reticle package.

    Args:
        metadata: Package metadata (shuttle name, timestamps, etc.)
        projects: List of ProjectData objects
        slots: List of SlotData objects for grid layout

    Returns:
        README.md content as string
    """
    lines = [
        f"# {metadata.shuttle_name} Reticle Package",
        "",
        f"**Generated:** {metadata.generated_at}",
        f"**Host:** {metadata.hostname}",
        f"**Code Revision:** {metadata.git_revision}",
        "",
    ]

    # Shuttle summary section
    lines.extend(_generate_summary_section(projects, metadata.precheck_version))

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
    warnings_count = sum(
        1 for p in projects if p.check_status == "manufacturable_with_warnings"
    )

    return [
        "## Shuttle Summary",
        "",
        f"- **Total projects:** {total}",
        f"- **Submitted:** {submitted}",
        f"- **Passing (clean):** {passing}",
        f"- **Passing (warnings):** {warnings_count}",
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
        lines.append(
            f"| {p.code} | {p.project_name} | {status} | {p.slot_size} | {p.top_cell} |"
        )

    lines.append("")
    return lines


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
        warnings.append(f"Copied {source} to {dest} (hardlink failed: {e})")

    return warnings


class ReticlePackageError(Exception):
    """Exception raised for reticle package generation errors."""


class ReticlePackageService:
    """Service for generating reticle stitcher packages."""

    def __init__(
        self,
        shuttle_name: str,
        output_path: Path,
        *,
        allow_pending: bool = False,
    ) -> None:
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
        msg = "generate() not yet implemented"
        raise NotImplementedError(msg)
