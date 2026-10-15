"""Operations for creating and managing manufacturability checks.

This module provides functions for check lifecycle operations like
retry creation. It sits between models and services to avoid circular imports.

Import hierarchy:
- check_operations -> models, exceptions
- services -> models, tasks, check_operations
- tasks -> models, exceptions, check_operations
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied
from django.db import transaction

from .exceptions import MaxRetriesExceededError
from .models import ManufacturabilityCheck
from .models import ProjectFile

if TYPE_CHECKING:
    from wafer_space.users.models import User

    from .models import Project

logger = logging.getLogger(__name__)

# Maximum retry attempts for manufacturability checks
MAX_MANUFACTURABILITY_CHECK_RETRIES = 3


def create_retry_check(
    failed_check: ManufacturabilityCheck,
) -> ManufacturabilityCheck:
    """Create a new check as a retry of a failed one.

    Args:
        failed_check: The check that failed (must be in ERROR status)

    Returns:
        New ManufacturabilityCheck in PENDING status

    Raises:
        ValueError: If failed_check is not in ERROR status
        MaxRetriesExceededError: If retry limit reached
    """
    if failed_check.status != ManufacturabilityCheck.Status.ERROR:
        msg = f"Can only retry ERROR checks, not {failed_check.status}"
        raise ValueError(msg)

    # Find original check (handles both first retry and subsequent)
    original = failed_check.parent_check or failed_check

    # Check retry limit
    retry_count = original.retry_checks.count()
    if retry_count >= MAX_MANUFACTURABILITY_CHECK_RETRIES:
        raise MaxRetriesExceededError(
            retry_count=retry_count,
            max_retries=MAX_MANUFACTURABILITY_CHECK_RETRIES,
        )

    return ManufacturabilityCheck.objects.create(
        project=original.project,
        project_file=original.project_file,
        trigger_reason=ManufacturabilityCheck.TriggerReason.RETRY,
        parent_check=original,
    )


class AdminRerunRefusedError(ValueError):
    """A staff re-run of a revision's precheck cannot be queued; says why."""


def create_admin_rerun_check(
    project: Project,
    project_file: ProjectFile,
    *,
    requested_by: User,
) -> ManufacturabilityCheck:
    """Queue a fresh precheck of one revision at a staff user's request (#205).

    The revision is explicit: the caller names which file revision of
    ``project`` to re-check (docs/manufacturable_vs_submitted.md).

    The file row is locked first, so two requests at once cannot both queue
    a check: the second sees the first one's PENDING check and is refused.

    Raises:
        PermissionDenied: ``requested_by`` is not staff.
        AdminRerunRefusedError: the file is not this project's, the project
            is archived, the file is not downloaded and verified yet, or a
            check of it is already in progress.
    """
    if not requested_by.is_staff:
        msg = "Only staff can re-run a precheck"
        raise PermissionDenied(msg)

    with transaction.atomic():
        locked = ProjectFile.objects.select_for_update().get(pk=project_file.pk)
        if locked.project_id != project.pk:
            msg = "That file revision belongs to another project"
            raise AdminRerunRefusedError(msg)
        if project.is_archived:
            msg = "The project is archived, so it is read-only"
            raise AdminRerunRefusedError(msg)
        if not locked.hash_verified:
            msg = "This revision is not downloaded and verified yet"
            raise AdminRerunRefusedError(msg)
        in_progress = locked.manufacturability_checks.filter(
            status__in=ManufacturabilityCheck.Status.in_progress(),
        )
        if in_progress.exists():
            msg = "A check of this revision is already in progress"
            raise AdminRerunRefusedError(msg)

        check = ManufacturabilityCheck.objects.create(
            project=project,
            project_file=locked,
            trigger_reason=ManufacturabilityCheck.TriggerReason.ADMIN_RERUN,
            rerun_requested_by=requested_by,
            parent_check=None,
        )

    logger.info(
        "Staff user %s (pk %s) queued precheck re-run %s of file %s, project %s",
        requested_by.username,
        requested_by.pk,
        check.pk,
        locked.pk,
        project.pk,
    )
    return check
