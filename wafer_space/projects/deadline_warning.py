"""Warn owners when their shuttle's GDS submission deadline is close (#347).

On-site only (Tim, issues-05: no email for now). A project is warned when
its shuttle is open with a deadline in the next WARNING_WINDOW, it is not
archived, and it still needs its owner to act: nothing is submitted for
manufacturing, or the submitted revision's latest finished check no longer
passes (the "Submitted, now failing" state of the projects list).
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from django.utils import timezone

if TYPE_CHECKING:
    from .models import Project

WARNING = "warning"
URGENT = "urgent"
WARNING_WINDOW = datetime.timedelta(days=14)
URGENT_WINDOW = datetime.timedelta(days=3)


def deadline_warning(project: Project) -> str | None:
    """WARNING, URGENT or None for one project (looks up its submission)."""
    verdict = None
    if project.submitted_file_id is not None:
        assert project.submitted_file is not None
        verdict = project.submitted_file.output_check.is_manufacturable
    return deadline_warning_for(project, submitted_verdict=verdict)


def deadline_warning_for(
    project: Project,
    *,
    submitted_verdict: bool | None,
) -> str | None:
    """The same rule, with the submitted revision's verdict given.

    ``submitted_verdict`` is the latest finished check verdict of the
    submitted revision (None when nothing is submitted or it has no finished
    check). The projects list passes its annotation, so no query is made.
    """
    shuttle = project.shuttle
    if shuttle is None or shuttle.is_closed or project.is_archived:
        return None
    deadline = shuttle.submission_deadline
    if deadline is None:
        return None
    submitted_and_fine = (
        project.submitted_file_id is not None and submitted_verdict is not False
    )
    if submitted_and_fine:
        return None
    remaining = deadline - timezone.now()
    if remaining <= datetime.timedelta(0) or remaining > WARNING_WINDOW:
        return None
    return URGENT if remaining <= URGENT_WINDOW else WARNING


def next_step(project: Project) -> str:
    """What the owner should do now, to show beside the warning."""
    if project.submitted_file_id is not None:
        return (
            "The submitted revision no longer passes its manufacturability "
            "check: upload a fixed revision and submit it."
        )
    if project.latest_file is None:
        return "Submit a file URL for your design."
    if project.can_submit()[0]:
        return "Your latest revision passed its check: Submit for Manufacturing."
    if project.latest_file_manufacturable is False:
        return (
            "Your latest revision failed its manufacturability check: upload "
            "a fixed revision."
        )
    return "Wait for the manufacturability check to finish, then submit."
