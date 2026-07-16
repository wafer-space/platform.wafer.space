"""Duplicate a project from one shuttle onto another.

Admin-triggered operation: copies the project metadata, the active
design file (bytes included), and the latest FINISHED manufacturability
check as provenance, then queues a fresh check. See the design spec:
docs/superpowers/specs/2026-07-16-duplicate-project-shuttle-design.md
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.core.files.base import File
from django.db import IntegrityError
from django.db import transaction

from wafer_space.projects.exceptions import ProjectDuplicationError
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
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
    source_file = _validate_duplication(project, target_shuttle)
    try:
        with transaction.atomic():
            new_project = _copy_project(project, target_shuttle)
            new_file = _copy_file(source_file, new_project)
            provenance = _copy_provenance_check(source_file, new_project, new_file)
            ManufacturabilityCheck.objects.create(
                project=new_project,
                project_file=new_file,
                trigger_reason=ManufacturabilityCheck.TriggerReason.DUPLICATED,
                parent_check=provenance,
            )
    except (IntegrityError, ValidationError) as exc:
        msg = f"Duplication failed while saving: {exc}"
        raise ProjectDuplicationError(msg) from exc

    logger.info(
        "Project %s duplicated to %s as %s by %s",
        project.pk,
        target_shuttle.name,
        new_project.pk,
        admin_user,
    )
    return new_project


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


def _copy_project(project: Project, target_shuttle: Shuttle) -> Project:
    """Create the duplicate Project row (crowd_supply_order_id NOT copied)."""
    new_project = Project(
        user=project.user,
        name=project.name,
        description=project.description,
        slot_size=project.slot_size,
        is_public=project.is_public,
        chip_on_board=project.chip_on_board,
        repository_url=project.repository_url,
        license_type=project.license_type,
        other_license_spdx_id=project.other_license_spdx_id,
        proprietary_terms_url=project.proprietary_terms_url,
        proprietary_terms_cached=project.proprietary_terms_cached,
        proprietary_terms_cached_at=project.proprietary_terms_cached_at,
        shuttle=target_shuttle,
        project_id=project.project_id,
        status=Project.Status.DRAFT,
    )
    new_project.save()
    return new_project


def _copy_file(source_file: ProjectFile, new_project: Project) -> ProjectFile:
    """Copy the active file, shaped so recovery scanners ignore it.

    The COMPLETED DownloadAttempt copy makes the derived download_status
    COMPLETED; the sentinel download_task_id keeps the file out of the
    recovery scanner's "pending" queryset.
    """
    new_file = ProjectFile(
        project=new_project,
        file_type=source_file.file_type,
        original_url=source_file.original_url,
        source_url=source_file.source_url,
        expected_hash_md5=source_file.expected_hash_md5,
        expected_hash_sha1=source_file.expected_hash_sha1,
        expected_hash_sha256=source_file.expected_hash_sha256,
        hash_md5=source_file.hash_md5,
        hash_sha1=source_file.hash_sha1,
        hash_sha256=source_file.hash_sha256,
        hash_verified=source_file.hash_verified,
        handler_metadata=source_file.handler_metadata,
        file_size=source_file.file_size,
        original_filename=source_file.original_filename,
        processed_filename=source_file.processed_filename,
        top_cell=source_file.top_cell,
        content_type=source_file.content_type,
        download_started_at=source_file.download_started_at,
        download_completed_at=source_file.download_completed_at,
        download_task_id=f"duplicated:{source_file.pk}",
        is_active=True,
    )
    with source_file.file.open("rb") as source_handle:
        new_file.file.save(
            PurePosixPath(source_file.file.name).name,
            File(source_handle),
            save=False,
        )
    new_file.save()

    # Newest attempt; COMPLETED per validation. The None guard exists for
    # mypy (first() is typed Optional) and for races where attempts were
    # deleted between validation and here.
    source_attempt = source_file.download_attempts.first()
    if source_attempt is None:
        msg = "Source file has no download attempt to copy."
        raise ProjectDuplicationError(msg)
    DownloadAttempt.objects.create(
        project_file=new_file,
        attempt_number=1,
        status=DownloadAttempt.Status.COMPLETED,
        completed_at=source_attempt.completed_at,
        download_started_at=source_attempt.download_started_at,
        download_completed_at=source_attempt.download_completed_at,
        download_duration_seconds=source_attempt.download_duration_seconds,
        bytes_downloaded=source_attempt.bytes_downloaded,
    )
    return new_file


def _copy_provenance_check(
    source_file: ProjectFile,
    new_project: Project,
    new_file: ProjectFile,
) -> ManufacturabilityCheck | None:
    """Copy the latest FINISHED check as an inert provenance record.

    Only FINISHED checks are copied: a copied PENDING row would be
    dispatched as a real run by the periodic check scanner, and copied
    active states would reference Docker containers that don't exist.
    Artifact FileFields stay empty (no storage sharing); their SHA-256
    fields are kept as a record of what the original run produced.
    """
    source_check = (
        source_file.manufacturability_checks.filter(
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        .order_by("-created_at")
        .first()
    )
    if source_check is None:
        return None
    return ManufacturabilityCheck.objects.create(
        project=new_project,
        project_file=new_file,
        status=ManufacturabilityCheck.Status.FINISHED,
        trigger_reason=source_check.trigger_reason,
        docker_server_id=source_check.docker_server_id,
        docker_container_id=source_check.docker_container_id,
        dispatching_started_at=source_check.dispatching_started_at,
        starting_started_at=source_check.starting_started_at,
        container_started_at=source_check.container_started_at,
        container_finished_at=source_check.container_finished_at,
        analysis_completed_at=source_check.analysis_completed_at,
        docker_exit_code=source_check.docker_exit_code,
        is_manufacturable=source_check.is_manufacturable,
        errors=source_check.errors,
        warnings=source_check.warnings,
        processing_logs=source_check.processing_logs,
        log_file_sha256=source_check.log_file_sha256,
        runs_archive_sha256=source_check.runs_archive_sha256,
        output_gds_sha256=source_check.output_gds_sha256,
        docker_layer_sha256=source_check.docker_layer_sha256,
        error_message=source_check.error_message,
        docker_image=source_check.docker_image,
        docker_image_digest=source_check.docker_image_digest,
        docker_command=source_check.docker_command,
        tool_versions=source_check.tool_versions,
        precheck_version=source_check.precheck_version,
    )
