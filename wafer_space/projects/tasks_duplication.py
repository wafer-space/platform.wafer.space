"""Celery task for duplicating a project onto another shuttle.

Runs on the ``http:rw:downloads`` queue because that worker is the only
web-adjacent service allowed to write user-file storage: deployed
gunicorn processes run with ``ProtectSystem=strict`` and the user-files
mount read-only, so the file copy cannot happen in the request cycle.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.contrib.admin.models import ADDITION
from django.contrib.admin.models import CHANGE
from django.contrib.admin.models import LogEntry

from wafer_space.projects.duplication import duplicate_project_to_shuttle
from wafer_space.projects.exceptions import ProjectDuplicationError
from wafer_space.projects.models import Project
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.models import User

logger = logging.getLogger(__name__)


@shared_task(queue="http:rw:downloads")
def duplicate_project_task(
    project_pk: str,
    target_shuttle_pk: int,
    admin_user_pk: int,
) -> dict[str, str]:
    """Duplicate a project onto another shuttle (admin-triggered).

    The admin view validates and enqueues; this task re-validates and
    performs the atomic copy. Outcomes are recorded as admin LogEntry
    rows so the triggering admin can see what happened even though the
    request cycle has already returned.

    No retries by design: expected failures (validation, collisions) are
    caught and recorded, and a blind re-run of a partially-visible copy
    would fail the collision check anyway. The admin simply re-triggers
    from the button if needed.

    Returns:
        dict: {"status": "ok", "duplicate_pk": ...} on success or
        {"status": "failed", "error": ...} when validation/copy failed.
    """
    try:
        project = Project.objects.get(pk=project_pk)
        target_shuttle = Shuttle.objects.get(pk=target_shuttle_pk)
        admin_user = User.objects.get(pk=admin_user_pk)
    except (Project.DoesNotExist, Shuttle.DoesNotExist, User.DoesNotExist) as exc:
        # Objects deleted between enqueue and execution; nothing to
        # attach a LogEntry to, so log and finish cleanly.
        logger.warning("Duplication task arguments no longer exist: %s", exc)
        return {"status": "failed", "error": str(exc)}
    source_shuttle_name = project.shuttle.name if project.shuttle else "(none)"
    source_queryset = Project.objects.filter(pk=project.pk)

    try:
        duplicate = duplicate_project_to_shuttle(
            project=project,
            target_shuttle=target_shuttle,
            admin_user=admin_user,
        )
    except ProjectDuplicationError as exc:
        logger.warning(
            "Duplication of project %s to shuttle %s failed: %s",
            project.pk,
            target_shuttle.name,
            exc,
        )
        LogEntry.objects.log_actions(
            admin_user.pk,
            source_queryset,
            CHANGE,
            f"Duplication to shuttle {target_shuttle.name} FAILED: {exc}",
            single_object=True,
        )
        return {"status": "failed", "error": str(exc)}

    LogEntry.objects.log_actions(
        admin_user.pk,
        Project.objects.filter(pk=duplicate.pk),
        ADDITION,
        f"Duplicated from project {project.pk} (shuttle {source_shuttle_name})",
        single_object=True,
    )
    LogEntry.objects.log_actions(
        admin_user.pk,
        source_queryset,
        CHANGE,
        f"Duplicated to shuttle {target_shuttle.name} as project {duplicate.pk}",
        single_object=True,
    )
    return {"status": "ok", "duplicate_pk": str(duplicate.pk)}
