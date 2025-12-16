"""Service for generating reticle stitcher packages."""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from django.db.models import OuterRef
from django.db.models import Subquery
from django.db.models.functions import Coalesce

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.shuttles.config import GridConfig
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot

if TYPE_CHECKING:
    from uuid import UUID


class ReticlePackageError(Exception):
    """Error during reticle package generation."""


def generate_package(
    shuttle_name: str,
    output_path: Path,
    *,
    allow_pending: bool = False,
) -> list[str]:
    """Generate a reticle package. Returns list of warnings."""
    if output_path.exists():
        msg = f"Output exists: {output_path}"
        raise ReticlePackageError(msg)

    shuttle = Shuttle.objects.get(name=shuttle_name)
    slots, checks, files, warnings = query_data(shuttle, allow_pending=allow_pending)

    output_path.mkdir(parents=True)
    grid_config = GridConfig.from_file(Path(shuttle.grid_config_file))

    write_tilemap(output_path / "tilemap.csv", slots, checks, grid_config)
    write_manifest(output_path / "manifest.csv", slots, checks, files)
    write_summary(output_path / "summary.csv", slots, checks)
    write_checks_csv(output_path / "checks.csv", slots, checks)
    write_readme(output_path / "README.md", shuttle, slots, checks)
    copy_gds_files(output_path, slots, checks, files)

    return warnings


def query_data(
    shuttle: Shuttle,
    *,
    allow_pending: bool = False,
) -> tuple[
    list[Any], dict[Any, ManufacturabilityCheck | None], dict[Any, Any], list[str]
]:
    """Query slots and build check mapping."""
    # Get the file to use: submitted_file or latest file
    latest_file = Subquery(
        ProjectFile.objects.filter(project_id=OuterRef("project_id"))
        .order_by("-uploaded_at")
        .values("id")[:1]
    )

    slots = list(
        ShuttleSlot.objects.filter(shuttle=shuttle)
        .select_related("project", "project__submitted_file")
        .annotate(file_id=Coalesce("project__submitted_file_id", latest_file))
        .order_by("row", "column")
    )

    # Prefetch files for slots without submitted_file
    file_ids = {s.file_id for s in slots if s.project and not s.project.submitted_file}
    files_by_id = {f.id: f for f in ProjectFile.objects.filter(id__in=file_ids)}

    checks: dict[Any, ManufacturabilityCheck | None] = {}
    warnings: list[str] = []

    for slot in slots:
        if not slot.project or slot.project_id in checks:
            continue

        project = slot.project
        project_file = project.submitted_file or files_by_id.get(slot.file_id)

        if not project_file:
            if allow_pending:
                warnings.append(f"Skipping {project.project_id}: no file")
                checks[slot.project_id] = None
                continue
            msg = f"{project.project_id}: no file"
            raise ReticlePackageError(msg)

        check, warning = _get_check(project, project_file, allow_pending=allow_pending)
        checks[slot.project_id] = check
        if warning:
            warnings.append(warning)

    return slots, checks, files_by_id, warnings


def _get_check(
    project: Project,
    project_file: ProjectFile,
    *,
    allow_pending: bool,
) -> tuple[ManufacturabilityCheck | None, str | None]:
    """Get and validate the manufacturability check."""
    check = (
        ManufacturabilityCheck.objects.filter(
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        .order_by("-created_at")
        .first()
    )

    if not check:
        if allow_pending:
            return None, f"Skipping {project.project_id}: no check"
        msg = f"{project.project_id}: no finished check"
        raise ReticlePackageError(msg)

    not_mfg = ManufacturabilityCheck.FinishedStatus.NOT_MANUFACTURABLE
    if check.finished_status == not_mfg:
        if not allow_pending:
            msg = f"{project.project_id}: not manufacturable"
            raise ReticlePackageError(msg)
        return check, f"{project.project_id}: not manufacturable"

    if not check.output_gds:
        msg = f"{project.project_id}: no output_gds"
        raise ReticlePackageError(msg)
    if not project_file.top_cell:
        msg = f"{project.project_id}: no top_cell"
        raise ReticlePackageError(msg)

    return check, None


def _is_manufacturable(check: ManufacturabilityCheck | None) -> bool:
    """Check if a check result is manufacturable."""
    if not check or not check.finished_status:
        return False
    return check.finished_status in (
        ManufacturabilityCheck.FinishedStatus.MANUFACTURABLE,
        ManufacturabilityCheck.FinishedStatus.MANUFACTURABLE_WITH_WARNINGS,
    )


def write_tilemap(path: Path, slots, checks, grid_config: GridConfig) -> None:
    """Write tilemap.csv."""
    tile_h, tile_w = 2, 2
    grid = [
        [""] * (grid_config.num_columns * tile_w)
        for _ in range(grid_config.num_rows * tile_h)
    ]

    for slot in slots:
        if not slot.project or not _is_manufacturable(checks.get(slot.project_id)):
            continue
        for r in range(tile_h):
            for c in range(tile_w):
                grid[slot.row * tile_h + r][slot.column * tile_w + c] = (
                    slot.project.project_id
                )

    with path.open("w") as f:
        writer = csv.writer(f)
        for row in grid:
            writer.writerow(row)


def write_manifest(path: Path, slots, checks, files) -> None:
    """Write manifest.csv."""
    with path.open("w") as f:
        writer = csv.writer(f)
        writer.writerow(["CODE", "SLOT", "POSITION", "LAYOUT", "TOP_CELL", "SHA256"])

        for slot in slots:
            if not slot.project or not _is_manufacturable(checks.get(slot.project_id)):
                continue
            check = checks[slot.project_id]
            pf = slot.project.submitted_file or files.get(slot.file_id)
            writer.writerow(
                [
                    slot.project.project_id,
                    slot.slot_size,
                    slot.grid_position,
                    f"{slot.project.project_id}/{pf.top_cell}.gds",
                    pf.top_cell,
                    check.output_gds_sha256,
                ]
            )


def write_summary(path: Path, slots, checks) -> None:
    """Write summary.csv."""
    seen: set[UUID] = set()
    with path.open("w") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "CODE",
                "PROJECT_NAME",
                "PROJECT_URL",
                "SLOT_SIZE",
                "SLOT_COUNT",
                "SUBMITTED",
                "CHECK_STATUS",
            ]
        )

        for slot in slots:
            if not slot.project or slot.project_id in seen:
                continue
            seen.add(slot.project_id)

            check = checks.get(slot.project_id)
            slot_count = sum(1 for s in slots if s.project_id == slot.project_id)
            status = ""
            if check and check.finished_status:
                status = check.finished_status.value

            writer.writerow(
                [
                    slot.project.project_id,
                    slot.project.name,
                    f"/projects/{slot.project.id}/",
                    slot.slot_size,
                    slot_count,
                    "yes" if slot.project.submitted_file else "no",
                    status,
                ]
            )


def write_checks_csv(path: Path, slots, checks) -> None:
    """Write checks.csv."""
    seen: set[UUID] = set()
    with path.open("w") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "CODE",
                "CHECK_STATUS",
                "CHECK_WARNINGS",
                "CHECK_ERRORS",
                "OUTPUT_SHA256",
            ]
        )

        for slot in slots:
            if not slot.project or slot.project_id in seen:
                continue
            seen.add(slot.project_id)

            check = checks.get(slot.project_id)
            if not check:
                writer.writerow([slot.project.project_id, "", 0, 0, ""])
            else:
                writer.writerow(
                    [
                        slot.project.project_id,
                        check.finished_status.value if check.finished_status else "",
                        len(check.warnings) if check.warnings else 0,
                        len(check.errors) if check.errors else 0,
                        check.output_gds_sha256 or "",
                    ]
                )


def write_readme(path: Path, shuttle: Shuttle, slots, checks) -> None:
    """Write README.md."""
    project_ids = {s.project_id for s in slots if s.project}
    total = len(project_ids)
    mfg = sum(1 for pid in project_ids if _is_manufacturable(checks.get(pid)))

    path.write_text(f"""# {shuttle.name} Reticle Package

## Summary

- Total Projects: {total}
- Manufacturable: {mfg}
- Not Manufacturable: {total - mfg}

## Files

- `tilemap.csv` - Grid layout
- `manifest.csv` - Project manifest
- `summary.csv` - Project summary
- `checks.csv` - Check details
""")


def copy_gds_files(output_path: Path, slots, checks, files) -> None:
    """Hardlink GDS files."""
    seen: set[UUID] = set()
    for slot in slots:
        if not slot.project or slot.project_id in seen:
            continue
        seen.add(slot.project_id)

        if not _is_manufacturable(checks.get(slot.project_id)):
            continue

        check = checks[slot.project_id]
        pf = slot.project.submitted_file or files.get(slot.file_id)
        project_dir = output_path / slot.project.project_id
        project_dir.mkdir(exist_ok=True)
        os.link(Path(check.output_gds.path), project_dir / f"{pf.top_cell}.gds")
