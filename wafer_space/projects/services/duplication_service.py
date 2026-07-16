"""Duplicate a project from one shuttle onto another.

Admin-triggered operation: copies the project metadata, the active
design file (bytes included), and the latest FINISHED manufacturability
check as provenance, then queues a fresh check. See the design spec:
docs/superpowers/specs/2026-07-16-duplicate-project-shuttle-design.md
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from wafer_space.projects.exceptions import ProjectDuplicationError
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.shuttles.models import Shuttle

if TYPE_CHECKING:
    from wafer_space.users.models import User

logger = logging.getLogger(__name__)

# Shuttles a project may be duplicated onto. Runs that are already in
# production (or beyond) never accept new projects.
ELIGIBLE_TARGET_SHUTTLE_STATUSES = (
    Shuttle.Status.PLANNING,
    Shuttle.Status.OPEN,
    Shuttle.Status.FULL,
    Shuttle.Status.LOCKED,
)


def duplicate_project_to_shuttle(
    *,
    project: Project,
    target_shuttle: Shuttle,
    admin_user: User,
) -> Project:
    """Duplicate ``project`` onto ``target_shuttle``.

    Returns the new DRAFT project. Raises ProjectDuplicationError with a
    user-facing message when validation fails; nothing is created in that
    case.
    """
    _validate_duplication(project, target_shuttle)
    raise NotImplementedError


def _validate_duplication(project: Project, target_shuttle: Shuttle) -> ProjectFile:
    """Validate the duplication request, returning the source's active file."""
    if project.shuttle_id is None:
        msg = "Source project is not assigned to a shuttle."
        raise ProjectDuplicationError(msg)

    if project.shuttle_id == target_shuttle.pk:
        msg = "Target shuttle is the same shuttle the project is already on."
        raise ProjectDuplicationError(msg)

    if target_shuttle.status not in ELIGIBLE_TARGET_SHUTTLE_STATUSES:
        msg = (
            f"Shuttle {target_shuttle.name} cannot accept duplicated projects "
            f"(status: {target_shuttle.get_status_display()})."
        )
        raise ProjectDuplicationError(msg)

    collision = Project.objects.filter(
        shuttle=target_shuttle,
        project_id=project.project_id,
    ).exists()
    if collision:
        msg = (
            f"Project ID {project.project_id!r} is already used on shuttle "
            f"{target_shuttle.name}."
        )
        raise ProjectDuplicationError(msg)

    try:
        source_file = project.files.get(is_active=True)
    except ProjectFile.DoesNotExist as exc:
        msg = "Source project has no active file."
        raise ProjectDuplicationError(msg) from exc

    if source_file.download_status != ProjectFile.DownloadStatus.COMPLETED:
        msg = (
            "Source project's file download is not completed "
            f"(status: {source_file.get_download_status_display()})."
        )
        raise ProjectDuplicationError(msg)

    if not source_file.file:
        msg = "Source project's file has no stored content."
        raise ProjectDuplicationError(msg)

    return source_file
