"""Service for generating reticle stitcher packages."""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

from django.conf import settings
from django.utils import timezone

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
    with (output_path / "manifest.csv").open("w") as f:
        writer = csv.writer(f)
        writer.writerow(["CODE", "PROJECT", "SLOT_SIZE", "TOP", "SHA256", "LAYOUT"])

        seen: set[str] = {"????"}
        for slot in sorted(slots, key=lambda s: s.project_code):
            code = slot.project_code
            if code in seen:
                continue
            seen.add(code)
            assert slot.project is not None  # "????" already in seen
            try:
                prj_file = slot.project.output_file

                src_file = Path(prj_file.output_check.output_gds.path).resolve()
                dst_file = f"{code}/{prj_file.top_cell}.gds"

                writer.writerow(
                    [
                        code,
                        slot.project.name,
                        slot.slot_size,
                        prj_file.top_cell,
                        prj_file.output_check.output_gds_sha256,
                        dst_file,
                    ]
                )

                dst_path = output_path / dst_file
                dst_path.parent.mkdir(exist_ok=True)

                os.link(src_file, dst_path)
            except ValueError as e:
                pending.setdefault(code, []).append(f"missing value: {e}")
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
                "STATUS",
                "TOP_CELL",
                "SUBMITTED_AT",
                "REPOSITORY_URL",
            ]
        )

        for slot in slots:
            if not slot.project or slot.project_id in seen:
                continue
            seen.add(slot.project_id)
            prj = slot.project
            prj_file = prj.output_file

            writer.writerow(
                [
                    prj.project_id,
                    prj.name,
                    f"{settings.SITE_URL}/projects/{prj.id}/",
                    slot.slot_size,
                    prj.status,
                    prj_file.top_cell,
                    prj.submitted_at.isoformat() if prj.submitted_at else "",
                    prj.repository_url or "",
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
        )

        for slot in slots:
            if not slot.project or slot.project_id in seen:
                continue
            seen.add(slot.project_id)
            prj = slot.project
            prj_file = prj.output_file
            check = prj_file.output_check

            # Build row values
            base_url = settings.SITE_URL
            if check.pk:
                status = check.finished_status.value if check.finished_status else ""
                warns = len(check.warnings) if check.warnings else 0
                errs = len(check.errors) if check.errors else 0
                version = check.precheck_version
                runtime = ""
                if check.container_started_at and check.container_finished_at:
                    delta = check.container_finished_at - check.container_started_at
                    runtime = f"{delta.total_seconds():.1f}"
                check_url = f"{base_url}/projects/{prj.id}/checks/{check.pk}/"
            else:
                status, warns, errs, version, runtime, check_url = "", 0, 0, "", "", ""

            if prj_file.pk:
                file_url = f"{base_url}/projects/{prj.id}/files/{prj_file.pk}/"
                md5, sha256 = prj_file.hash_md5, prj_file.hash_sha256
            else:
                file_url, md5, sha256 = "", "", ""

            writer.writerow(
                [
                    prj.project_id,
                    prj.name,
                    status,
                    warns,
                    errs,
                    version,
                    runtime,
                    check_url,
                    file_url,
                    md5,
                    sha256,
                ]
            )


def write_readme(path: Path, shuttle: Shuttle, slots: list[ShuttleSlot]) -> None:
    """Write README.md."""
    now = timezone.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Build projects table
    seen: set[Any] = set()
    projects_rows = []
    for slot in sorted(slots, key=lambda s: s.project_code):
        if not slot.project or slot.project_id in seen:
            continue
        seen.add(slot.project_id)
        prj = slot.project
        check = prj.output_file.output_check
        if check.pk and check.finished_status:
            status = check.finished_status.value
        else:
            status = "no_check"
        top = prj.output_file.top_cell
        projects_rows.append(
            f"| {prj.project_id} | {prj.name} | {status} | {slot.slot_size} | {top} |"
        )

    # Build ASCII grid
    grid_lines = _build_ascii_grid(slots, shuttle)

    path.write_text(f"""# {shuttle.name} Reticle Package

**Generated:** {now}
**Host:** {settings.SITE_URL}

## Shuttle Layout

```text
{grid_lines}
```

Legend: [Submitted] [Check] [Version]
  ☑ Submitted    ☐ Not submitted
  ✔ Pass         ⚠ Warnings      ✘ Fail    ? No check
  ★ Current      ☆ Outdated      · N/A

## Projects

| CODE | Name | Status | Slot | Top Cell |
|------|------|--------|------|----------|
{chr(10).join(projects_rows)}
""")


def _build_ascii_grid(slots: list[ShuttleSlot], shuttle: Shuttle) -> str:
    """Build ASCII representation of shuttle grid."""
    if not slots:
        return "(empty)"

    max_row = max(s.row for s in slots)
    max_col = max(s.column for s in slots)

    # Build slot lookup
    slot_map = {(s.row, s.column): s for s in slots}

    lines = []
    # Header row
    cols = "    " + "   ".join(chr(65 + c) for c in range(max_col + 1))
    lines.append(cols)
    lines.append("  " + "+---" * (max_col + 1) + "+")

    for row in range(max_row + 1):
        # Code line
        code_parts = [f"{row + 1} "]
        icon_parts = ["  "]
        for col in range(max_col + 1):
            slot = slot_map.get((row, col))
            if slot and slot.project:
                code_parts.append(f"|{slot.project.project_id:4}")
                check = slot.project.output_file.output_check
                sub = "☑" if slot.project.submitted_file else "☐"
                if not check.pk:
                    chk, ver = "?", "·"
                else:
                    chk = "✔" if _is_manufacturable(check) else "✘"
                    ver = "★" if check.is_using_latest_precheck else "☆"
                icon_parts.append(f"|{sub}{chk}{ver} ")
            else:
                code_parts.append("|    ")
                icon_parts.append("|    ")
        code_parts.append("|")
        icon_parts.append("|")
        lines.append("".join(code_parts))
        lines.append("".join(icon_parts))
        lines.append("  " + "+---" * (max_col + 1) + "+")

    return "\n".join(lines)
