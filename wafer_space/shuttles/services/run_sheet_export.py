"""The data a run's spreadsheet (manage-run-gsheet) reads from the platform.

Every non-cancelled project, on any shuttle or none (the sheet matches
Crowd Supply orders to projects and lays unplaced ones onto free slots),
and every ShuttleSlot of one shuttle. Read-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from wafer_space.projects.models import Project
from wafer_space.shuttles.models import ShuttleSlot

if TYPE_CHECKING:
    from wafer_space.projects.models import ManufacturabilityCheck
    from wafer_space.shuttles.models import Shuttle


def _precheck(project: Project) -> ManufacturabilityCheck | None:
    """The check that defines the project's state: the submitted file's
    latest check, else the active file's, else the project's latest."""
    target = project.submitted_file or project.files.filter(is_active=True).first()
    check = (
        target.manufacturability_checks.order_by("-created_at").first()
        if target is not None
        else None
    )
    return check or project.manufacturability_checks.order_by("-created_at").first()


def _project(project: Project) -> dict[str, Any]:
    check = _precheck(project)
    return {
        "uuid": str(project.id),
        "project_id": project.project_id,
        "name": project.name,
        "slot_size": project.slot_size,
        "chip_on_board": project.chip_on_board,
        "order": project.crowd_supply_order_id,
        "status": project.status,
        "shuttle": project.shuttle.name if project.shuttle else "",
        "created": project.created_at.isoformat(),
        "owner_name": getattr(project.user, "name", "") or project.user.username,
        "owner_email": project.user.email,
        "license_type": project.license_type,
        "other_license_spdx_id": project.other_license_spdx_id,
        "repository_url": project.repository_url,
        "precheck_status": check.status if check else "",
        "precheck_ok": check.is_manufacturable if check else None,
        "precheck_warnings": bool(check.warnings) if check else False,
        "submitted_at": (
            project.submitted_at.isoformat() if project.submitted_at else ""
        ),
        "slot_positions": [
            s.grid_position
            for s in sorted(
                project.shuttle_slots.all(), key=lambda s: (s.row, s.column)
            )
            if s.status != ShuttleSlot.Status.CANCELLED
        ],
    }


def run_sheet_data(shuttle: Shuttle) -> dict[str, list[dict[str, Any]]]:
    """``projects``: every non-cancelled project, oldest first; ``slots``:
    ``shuttle``'s slots by row and column, each with its grid position,
    size, status and the UUID of its project ("" for none)."""
    projects = (
        Project.objects.exclude(status=Project.Status.CANCELLED)
        .select_related("shuttle", "user")
        .prefetch_related("shuttle_slots")
        .order_by("created_at")
    )
    slots = ShuttleSlot.objects.filter(shuttle=shuttle).order_by("row", "column")
    return {
        "projects": [_project(p) for p in projects],
        "slots": [
            {
                "position": s.grid_position,
                "slot_size": s.slot_size,
                "status": s.status,
                "project": str(s.project_id) if s.project_id else "",
            }
            for s in slots
        ],
    }
