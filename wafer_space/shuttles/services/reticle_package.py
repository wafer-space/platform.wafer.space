"""Service for generating reticle stitcher packages."""

from __future__ import annotations

from dataclasses import dataclass


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
