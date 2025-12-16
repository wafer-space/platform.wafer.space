"""Service for generating reticle stitcher packages."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import TextIO

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
