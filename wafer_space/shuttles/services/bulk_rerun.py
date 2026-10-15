"""Re-run, in bulk, the prechecks a shuttle's assignment page shows as Old (#203).

"Old" is the page's show filter: the project's latest file revision passed
its precheck, but on an outdated precheck version. For each run, staff choose
which revision of each such project is re-checked: the one submitted for
manufacturing, or the latest (Tim, 16 Oct 2026: "Able to choose both"). The
two differ whenever a project uploaded after submitting
(docs/manufacturable_vs_submitted.md).

Each check is queued through ``create_admin_rerun_check`` (#205), so it is
recorded as ADMIN_RERUN with the requesting user, and a revision with a check
already in progress is refused rather than queued twice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied
from django.db import models

from wafer_space.projects.check_operations import AdminRerunRefusedError
from wafer_space.projects.check_operations import create_admin_rerun_check

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from wafer_space.projects.models import ManufacturabilityCheck
    from wafer_space.projects.models import Project
    from wafer_space.projects.models import ProjectFile
    from wafer_space.shuttles.models import Shuttle
    from wafer_space.users.models import User

logger = logging.getLogger(__name__)

NO_SUBMITTED_REVISION = "no revision has been submitted for manufacturing"
NO_LONGER_OLD = "no longer passed on an outdated precheck version"
REVISION_CHANGED = "its {revision} changed after the confirmation page was shown"


class RerunRevision(models.TextChoices):
    """Which revision of each Old project a bulk re-run checks."""

    SUBMITTED = "submitted", "submitted revision"
    LATEST = "latest", "latest revision"


def passed_on_outdated_precheck(project: Project) -> bool:
    """Whether ``project`` is Old: its latest revision passed, on an old version.

    A version that cannot be compared (no digest recorded) is not Old.
    """
    check = project.latest_file_finished_check
    return (
        bool(project.latest_file_manufacturable)
        and check is not None
        and check.is_using_latest_precheck is False
    )


def outdated_projects(shuttle: Shuttle) -> list[Project]:
    """The shuttle's projects the assignment page's Old filter shows."""
    projects = (
        shuttle.projects.filter(archived_at__isnull=True)
        .select_related("submitted_file")
        .order_by("project_id", "pk")
    )
    return [p for p in projects if passed_on_outdated_precheck(p)]


@dataclass(frozen=True)
class PlannedRerun:
    """One Old project and the revision a bulk re-run would check."""

    project: Project
    project_file: ProjectFile | None
    skip_reason: str = ""


@dataclass(frozen=True)
class BulkRerunPlan:
    """What a bulk re-run of one revision kind would queue, and skip."""

    revision: RerunRevision
    to_queue: list[PlannedRerun]
    skipped: list[PlannedRerun]


def plan_for(project: Project, revision: RerunRevision) -> PlannedRerun:
    """The revision of ``project`` that ``revision`` names, or why there is none."""
    if revision == RerunRevision.LATEST:
        return PlannedRerun(project, project.latest_file)
    if project.submitted_file is None:
        return PlannedRerun(project, None, NO_SUBMITTED_REVISION)
    return PlannedRerun(project, project.submitted_file)


def plan_bulk_rerun(shuttle: Shuttle, revision: RerunRevision) -> BulkRerunPlan:
    """What re-running the shuttle's Old projects' ``revision`` would do."""
    plans = [plan_for(p, revision) for p in outdated_projects(shuttle)]
    return BulkRerunPlan(
        revision=revision,
        to_queue=[p for p in plans if not p.skip_reason],
        skipped=[p for p in plans if p.skip_reason],
    )


@dataclass(frozen=True)
class BulkRerunResult:
    """The checks a bulk re-run queued, and each project it did not."""

    revision: RerunRevision
    queued: list[ManufacturabilityCheck]
    not_queued: list[PlannedRerun]


def queue_bulk_rerun(
    shuttle: Shuttle,
    revision: RerunRevision,
    *,
    requested_by: User,
    confirmed: Mapping[UUID, int],
) -> BulkRerunResult:
    """Queue one ADMIN_RERUN check per Old project the staff user confirmed.

    ``confirmed`` maps each project the confirmation page listed to the file
    revision it said would be checked. A revision is checked only if it was
    confirmed and its project is still Old, so nothing is queued unseen: not
    a project that became Old after the page was shown, nor a revision
    submitted or uploaded since. Each project not checked is in
    ``not_queued`` with the reason.

    Raises:
        PermissionDenied: ``requested_by`` is not staff; nothing is queued.
    """
    if not requested_by.is_staff:
        msg = "Only staff can re-run prechecks"
        raise PermissionDenied(msg)

    confirmed_pks = set(confirmed)
    changed = REVISION_CHANGED.format(revision=revision.label)
    plan = plan_bulk_rerun(shuttle, revision)
    still_old = {p.project.pk for p in plan.to_queue + plan.skipped}
    queued: list[ManufacturabilityCheck] = []
    # A skip is reported whether or not the page listed it: it queues nothing
    not_queued = list(plan.skipped)
    not_queued += [
        PlannedRerun(project, None, NO_LONGER_OLD)
        for project in shuttle.projects.filter(pk__in=confirmed_pks - still_old)
    ]
    for planned in plan.to_queue:
        if planned.project.pk not in confirmed_pks or planned.project_file is None:
            continue
        if confirmed[planned.project.pk] != planned.project_file.pk:
            not_queued.append(PlannedRerun(planned.project, None, changed))
            continue
        try:
            check = create_admin_rerun_check(
                planned.project,
                planned.project_file,
                requested_by=requested_by,
            )
        except AdminRerunRefusedError as exc:
            not_queued.append(
                PlannedRerun(planned.project, planned.project_file, str(exc))
            )
        else:
            queued.append(check)

    logger.info(
        "Staff user %s (pk %s) queued %d precheck re-runs of the %s of shuttle "
        "%s's outdated projects; %d not queued",
        requested_by.username,
        requested_by.pk,
        len(queued),
        revision.label,
        shuttle.name,
        len(not_queued),
    )
    return BulkRerunResult(revision=revision, queued=queued, not_queued=not_queued)
