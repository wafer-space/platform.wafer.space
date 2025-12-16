"""Service for generating reticle stitcher packages."""

from __future__ import annotations

import csv
import json
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from typing import TextIO

if TYPE_CHECKING:
    from wafer_space.projects.models import Project
    from wafer_space.projects.models import ProjectFile
    from wafer_space.shuttles.config import GridConfig
    from wafer_space.shuttles.models import Shuttle
    from wafer_space.shuttles.models import ShuttleSlot

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
        # Import here to avoid circular imports
        from wafer_space.shuttles.config import GridConfig  # noqa: PLC0415
        from wafer_space.shuttles.models import Shuttle  # noqa: PLC0415

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
        grid_config = GridConfig.from_file(Path(shuttle.grid_config_file))

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
        from wafer_space.shuttles.models import ShuttleSlot  # noqa: PLC0415

        slots = (
            ShuttleSlot.objects.filter(shuttle=shuttle)
            .select_related(
                "project",
                "project__submitted_file",
            )
            .order_by("row", "column")
        )

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

    def _get_project_file(self, project: Project) -> ProjectFile | None:
        """Get the project file to use for package generation.

        Returns the submitted_file if set, otherwise falls back to the latest
        file with a passing check (when allow_pending is True).
        """
        from wafer_space.projects.models import ManufacturabilityCheck  # noqa: PLC0415
        from wafer_space.projects.models import ProjectFile  # noqa: PLC0415

        project_file = project.submitted_file
        if not project_file and self.allow_pending:
            # Fall back to latest with passing check
            project_file = (
                ProjectFile.objects.filter(
                    project=project,
                    manufacturability_checks__status=ManufacturabilityCheck.Status.FINISHED,
                )
                .order_by("-uploaded_at")
                .first()
            )
        return project_file

    def _collect_project_data(self, slot: ShuttleSlot) -> ProjectData | None:
        """Collect data for a single project from a slot."""
        from wafer_space.projects.models import ManufacturabilityCheck  # noqa: PLC0415

        project = slot.project
        if not project:
            return None

        # Get project file
        project_file = self._get_project_file(project)
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

        # Skip projects that failed manufacturability check
        not_manufacturable = ManufacturabilityCheck.FinishedStatus.NOT_MANUFACTURABLE
        if check.finished_status == not_manufacturable:
            self.warnings.append(
                f"Skipping {project.project_id}: not manufacturable (check {check.pk})"
            )
            return None

        # Validate required fields
        if not check.output_gds:
            msg = (
                f"Project {project.project_id} check missing output_gds. "
                f"Check ID: {check.pk}, status: {check.status}, "
                f"finished_status: {check.finished_status}, "
                f"is_manufacturable: {check.is_manufacturable}, "
                f"created_at: {check.created_at}"
            )
            raise ReticlePackageError(msg)

        if not project_file.top_cell:
            msg = f"Project {project.project_id} missing top_cell"
            raise ReticlePackageError(msg)

        # Get all slot positions for this project
        from wafer_space.shuttles.models import ShuttleSlot  # noqa: PLC0415

        project_slots = ShuttleSlot.objects.filter(
            shuttle=slot.shuttle,
            project=project,
        )
        slot_positions = [s.grid_position for s in project_slots]

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
                check.total_runtime_seconds
                if hasattr(check, "total_runtime_seconds")
                else None
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
        with (self.output_path / "tilemap.csv").open("w") as f:
            write_tilemap_csv(grid, f)

    def _write_manifest(self, projects: list[ProjectData]) -> None:
        """Write manifest.csv."""
        with (self.output_path / "manifest.csv").open("w") as f:
            write_manifest_csv(projects, f)

    def _write_summary(self, projects: list[ProjectData]) -> None:
        """Write summary.csv."""
        with (self.output_path / "summary.csv").open("w") as f:
            write_summary_csv(projects, f)

    def _write_checks(self, projects: list[ProjectData]) -> None:
        """Write checks.csv."""
        with (self.output_path / "checks.csv").open("w") as f:
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
        generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        hostname = socket.gethostname()
        try:
            git_revision = subprocess.check_output(
                ["git", "describe", "--always", "--dirty"],  # noqa: S607
                text=True,
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            git_revision = "unknown"

        metadata = PackageMetadata(
            shuttle_name=shuttle.name,
            generated_at=generated_at,
            hostname=hostname,
            git_revision=git_revision,
            precheck_version="unknown",  # TODO: Get from settings
        )

        readme = generate_readme(
            metadata=metadata,
            projects=projects,
            slots=slots,
        )

        with (self.output_path / "README.md").open("w") as f:
            f.write(readme)

    def _write_project_files(self, projects: list[ProjectData]) -> None:
        """Write info.json and create GDS links for each project."""
        for project in projects:
            project_dir = self.output_path / project.code
            project_dir.mkdir(exist_ok=True)

            # Write info.json
            info_json = generate_project_info_json(project)
            with (project_dir / "info.json").open("w") as f:
                f.write(info_json)

            # Create GDS link
            source = Path(project.gds_path)
            dest = project_dir / f"{project.top_cell}.gds"
            link_warnings = create_gds_link(source, dest)
            self.warnings.extend(link_warnings)
