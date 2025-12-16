"""Service for generating reticle stitcher packages."""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.shuttles.config import GridConfig
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot


class ReticlePackageError(Exception):
    """Error during reticle package generation."""


class ManifestError(Exception):
    """Error getting manifest data for a project."""

    NOT_MANUFACTURABLE = "not manufacturable"
    NO_TOP_CELL = "no top_cell"


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
    slots = get_slots(shuttle)

    output_path.mkdir(parents=True)
    grid_config = GridConfig.from_file(Path(shuttle.grid_config_file))

    # Write outputs, collecting any issues
    pending: dict[str, list[str]] = {}

    write_tilemap(output_path / "tilemap.csv", slots, grid_config)
    write_summary(output_path / "summary.csv", slots)
    write_checks_csv(output_path / "checks.csv", slots)
    write_readme(output_path / "README.md", shuttle, slots)
    write_manifest_and_copy_gds(output_path, slots, pending)

    # Handle pending issues
    warnings = [f"{code}: {', '.join(issues)}" for code, issues in pending.items()]

    if pending and not allow_pending:
        msg = "Package incomplete:\n" + "\n".join(warnings)
        raise ReticlePackageError(msg)

    return warnings


def write_manifest_and_copy_gds(
    output_path: Path,
    slots: list[ShuttleSlot],
    pending: dict[str, list[str]],
) -> None:
    """Write manifest.csv and copy GDS files for manufacturable projects."""
    seen: set[Any] = set()
    with (output_path / "manifest.csv").open("w") as f:
        writer = csv.writer(f)
        writer.writerow(["CODE", "SLOT", "POSITION", "LAYOUT", "TOP_CELL", "SHA256"])

        for slot in slots:
            if not slot.project or slot.project_id in seen:
                continue
            seen.add(slot.project_id)

            code = slot.project.project_id
            try:
                pf = slot.project.output_file
                check = pf.output_check
                _require_manufacturable(check)
                top_cell = pf.top_cell or _missing("top_cell")
                gds_path = Path(check.output_gds.path)
                sha256 = check.output_gds_sha256
            except (AttributeError, ManifestError) as e:
                pending.setdefault(code, []).append(str(e))
                continue

            writer.writerow(
                [
                    code,
                    slot.slot_size,
                    slot.grid_position,
                    f"{code}/{top_cell}.gds",
                    top_cell,
                    sha256,
                ]
            )

            project_dir = output_path / code
            project_dir.mkdir(exist_ok=True)
            try:
                os.link(gds_path, project_dir / f"{top_cell}.gds")
            except OSError as e:
                pending.setdefault(code, []).append(f"hardlink failed: {e}")


def get_slots(shuttle: Shuttle) -> list[ShuttleSlot]:
    """Get all slots for a shuttle, including empty ones."""
    return list(
        ShuttleSlot.objects.filter(shuttle=shuttle)
        .select_related("project", "project__submitted_file")
        .order_by("row", "column")
    )


def _missing(field: str) -> Any:
    """Raise ManifestError for missing field."""
    msg = f"no {field}"
    raise ManifestError(msg)


def _require_manufacturable(check: ManufacturabilityCheck) -> None:
    """Raise ManifestError if check is not manufacturable."""
    if not check.pk or not check.finished_status:
        raise ManifestError(ManifestError.NOT_MANUFACTURABLE)
    if check.finished_status not in (
        ManufacturabilityCheck.FinishedStatus.MANUFACTURABLE,
        ManufacturabilityCheck.FinishedStatus.MANUFACTURABLE_WITH_WARNINGS,
    ):
        raise ManifestError(ManifestError.NOT_MANUFACTURABLE)


def _is_manufacturable(check: ManufacturabilityCheck) -> bool:
    """Check if a check result is manufacturable."""
    if not check.pk or not check.finished_status:
        return False
    return check.finished_status in (
        ManufacturabilityCheck.FinishedStatus.MANUFACTURABLE,
        ManufacturabilityCheck.FinishedStatus.MANUFACTURABLE_WITH_WARNINGS,
    )


def write_tilemap(
    path: Path, slots: list[ShuttleSlot], grid_config: GridConfig
) -> None:
    """Write tilemap.csv."""
    tile_h, tile_w = 2, 2
    grid = [
        [""] * (grid_config.num_columns * tile_w)
        for _ in range(grid_config.num_rows * tile_h)
    ]

    for slot in slots:
        if not slot.project:
            continue
        check = slot.project.output_file.output_check
        if not _is_manufacturable(check):
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


def write_summary(path: Path, slots: list[ShuttleSlot]) -> None:
    """Write summary.csv."""
    seen: set[Any] = set()
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

            check = slot.project.output_file.output_check
            slot_count = sum(1 for s in slots if s.project_id == slot.project_id)
            status = ""
            if check.pk and check.finished_status:
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


def write_checks_csv(path: Path, slots: list[ShuttleSlot]) -> None:
    """Write checks.csv."""
    seen: set[Any] = set()
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

            check = slot.project.output_file.output_check
            if not check.pk:
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


def write_readme(path: Path, shuttle: Shuttle, slots: list[ShuttleSlot]) -> None:
    """Write README.md."""
    total = len({s.project_id for s in slots if s.project})
    mfg = sum(
        1
        for s in slots
        if s.project and _is_manufacturable(s.project.output_file.output_check)
    )

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
