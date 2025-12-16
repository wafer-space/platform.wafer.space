"""Service for generating reticle stitcher packages."""

from __future__ import annotations

from dataclasses import dataclass

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
