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
    from .models import ProjectFile

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
    # A test-only shuttle never closes (#221), so its deadline never applies.
    if (
        shuttle is None
        or shuttle.is_closed
        or shuttle.is_test_only
        or project.is_archived
    ):
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
    """What the owner should do now, to show beside the warning.

    Read from the latest revision's own state (download, latest check,
    finished verdict), never from Project.status (#354).
    """
    latest = project.latest_file
    if project.submitted_file_id is not None:
        newer_passes = (
            latest is not None
            and latest.pk != project.submitted_file_id
            and latest.hash_verified
            and project.latest_file_manufacturable is True
        )
        if newer_passes:
            return "A newer revision passed its check: submit it for manufacturing."
        return (
            "The submitted revision no longer passes its manufacturability "
            "check: upload a fixed revision and submit it."
        )
    if latest is None:
        return "Submit a file URL for your design."
    return _latest_revision_step(project, latest)


def _latest_revision_step(project: Project, latest: ProjectFile) -> str:
    download = latest.download_status
    if download == latest.DownloadStatus.FAILED:
        return "The file download failed: submit the file URL again."
    if download != latest.DownloadStatus.COMPLETED:
        return "Wait for the file download and the check to finish, then submit."
    verdict = project.latest_file_manufacturable
    if verdict is True and latest.hash_verified:
        return "Your latest revision passed its check: Submit for Manufacturing."
    if verdict is False:
        return (
            "Your latest revision failed its manufacturability check: upload "
            "a fixed revision."
        )
    check = latest.latest_manufacturability_check
    if check is not None and check.status in check.Status.terminal():
        return (
            "The manufacturability check ended with an error: upload the "
            "file again or contact staff."
        )
    return "Wait for the manufacturability check to finish, then submit."
