"""Tests for the project duplication service."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.db.models import Q
from django.test import TestCase
from django.utils import timezone

from wafer_space.projects.exceptions import ProjectDuplicationError
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.services import duplicate_project_to_shuttle
from wafer_space.projects.tasks_download import ensure_download_tasks_queued
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.models import User

from .constants import TEST_PASSWORD
from .factories import ProjectFactory
from .factories import ProjectFileFactory

if TYPE_CHECKING:
    from django.core.files.storage import Storage

GDS_BYTES = b"fake-gds-content-for-duplication-tests"


def make_shuttle(name: str, status: str = Shuttle.Status.OPEN) -> Shuttle:
    """Create a shuttle with an explicit name (never rely on G801)."""
    return Shuttle.objects.create(
        name=name,
        description=f"Test shuttle {name}",
        status=status,
    )


def make_source_project(
    *,
    shuttle: Shuttle,
    project_id: str = "ABCD",
    with_file: bool = True,
    with_finished_check: bool = True,
) -> Project:
    """Create a fully 'manufactured' source project on the given shuttle."""
    project = ProjectFactory(
        shuttle=shuttle,
        project_id=project_id,
        status=Project.Status.SUBMITTED,
        crowd_supply_order_id="327373",
        repository_url="https://example.com/repo",
    )
    if not with_file:
        return project

    project_file = ProjectFileFactory(
        project=project,
        is_active=True,
        original_filename="design.gds",
        hash_verified=True,
        hash_sha256="a" * 64,
        top_cell="top",
        download_task_id="celery-task-original",
    )
    project_file.file.save("design.gds", ContentFile(GDS_BYTES), save=True)
    DownloadAttempt.objects.create(
        project_file=project_file,
        attempt_number=1,
        status=DownloadAttempt.Status.COMPLETED,
        completed_at=timezone.now(),
        download_started_at=timezone.now(),
        download_completed_at=timezone.now(),
        download_duration_seconds=1.5,
        bytes_downloaded=len(GDS_BYTES),
    )
    if with_finished_check:
        ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
            warnings=["minor spacing"],
            docker_image_digest="sha256:" + "b" * 64,
            precheck_version="v1.2.3",
            log_file_sha256="c" * 64,
        )
    return project


@pytest.mark.django_db
class TestDuplicationValidation(TestCase):
    """Validation failures raise ProjectDuplicationError and create nothing."""

    def setUp(self) -> None:
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=TEST_PASSWORD,
        )
        self.source_shuttle = make_shuttle("G890")
        self.target_shuttle = make_shuttle("G891")

    def assert_fails(self, project: Project, target: Shuttle, match: str) -> None:
        projects_before = Project.objects.count()
        files_before = ProjectFile.objects.count()
        checks_before = ManufacturabilityCheck.objects.count()
        with pytest.raises(ProjectDuplicationError, match=match):
            duplicate_project_to_shuttle(
                project=project,
                target_shuttle=target,
                admin_user=self.admin_user,
            )
        assert Project.objects.count() == projects_before
        assert ProjectFile.objects.count() == files_before
        assert ManufacturabilityCheck.objects.count() == checks_before

    def test_source_without_shuttle_fails(self) -> None:
        project = ProjectFactory(shuttle=None)
        self.assert_fails(project, self.target_shuttle, "not assigned to a shuttle")

    def test_same_shuttle_fails(self) -> None:
        project = make_source_project(shuttle=self.source_shuttle)
        self.assert_fails(project, self.source_shuttle, "same shuttle")

    def test_ineligible_target_status_fails(self) -> None:
        project = make_source_project(shuttle=self.source_shuttle)
        for status in (
            Shuttle.Status.IN_PRODUCTION,
            Shuttle.Status.COMPLETED,
            Shuttle.Status.CANCELLED,
        ):
            self.target_shuttle.status = status
            self.target_shuttle.save()
            self.assert_fails(project, self.target_shuttle, "cannot accept")

    def test_project_id_collision_fails(self) -> None:
        project = make_source_project(shuttle=self.source_shuttle)
        ProjectFactory(shuttle=self.target_shuttle, project_id="ABCD")
        self.assert_fails(project, self.target_shuttle, "already used")

    def test_no_active_file_fails(self) -> None:
        project = make_source_project(shuttle=self.source_shuttle, with_file=False)
        self.assert_fails(project, self.target_shuttle, "active file")

    def test_incomplete_download_fails(self) -> None:
        project = make_source_project(shuttle=self.source_shuttle)
        attempt = DownloadAttempt.objects.get(
            project_file__project=project,
        )
        attempt.status = DownloadAttempt.Status.FAILED
        attempt.save()
        self.assert_fails(project, self.target_shuttle, "download")


@pytest.mark.django_db
class TestDuplicationCopy(TestCase):
    """Happy-path duplication copies exactly what the spec says."""

    def setUp(self) -> None:
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=TEST_PASSWORD,
        )
        self.source_shuttle = make_shuttle("G890")
        self.target_shuttle = make_shuttle("G891")
        self.source = make_source_project(shuttle=self.source_shuttle)
        self.duplicate = duplicate_project_to_shuttle(
            project=self.source,
            target_shuttle=self.target_shuttle,
            admin_user=self.admin_user,
        )

    def test_project_metadata_copied(self) -> None:
        assert self.duplicate.pk != self.source.pk
        assert self.duplicate.user == self.source.user
        assert self.duplicate.name == self.source.name
        assert self.duplicate.description == self.source.description
        assert self.duplicate.slot_size == self.source.slot_size
        assert self.duplicate.is_public == self.source.is_public
        assert self.duplicate.chip_on_board == self.source.chip_on_board
        assert self.duplicate.repository_url == self.source.repository_url
        assert self.duplicate.license_type == self.source.license_type

    def test_project_fresh_fields(self) -> None:
        assert self.duplicate.shuttle == self.target_shuttle
        assert self.duplicate.project_id == self.source.project_id
        assert self.duplicate.status == Project.Status.DRAFT
        assert self.duplicate.submitted_at is None
        assert self.duplicate.submitted_file is None
        assert self.duplicate.crowd_supply_order_id == ""

    def test_source_untouched(self) -> None:
        self.source.refresh_from_db()
        assert self.source.shuttle == self.source_shuttle
        assert self.source.status == Project.Status.SUBMITTED

    def test_file_bytes_copied_to_new_path(self) -> None:
        new_file = self.duplicate.files.get(is_active=True)
        source_file = self.source.files.get(is_active=True)
        assert new_file.file.name != source_file.file.name
        with new_file.file.open("rb") as handle:
            assert handle.read() == GDS_BYTES

    def test_file_metadata_copied(self) -> None:
        new_file = self.duplicate.files.get(is_active=True)
        source_file = self.source.files.get(is_active=True)
        assert new_file.hash_sha256 == source_file.hash_sha256
        assert new_file.hash_verified is True
        assert new_file.original_filename == source_file.original_filename
        assert new_file.top_cell == source_file.top_cell
        assert new_file.replaced_by is None

    def test_file_invisible_to_download_recovery_scanner(self) -> None:
        """Replicates the querysets in ensure_download_tasks_queued."""
        new_file = self.duplicate.files.get(is_active=True)
        assert new_file.download_task_id.startswith("duplicated:")
        assert new_file.download_status == ProjectFile.DownloadStatus.COMPLETED

        pending = ProjectFile.objects.filter(is_active=True).filter(
            Q(download_task_id="") | Q(download_task_id__isnull=True),
        )
        assert new_file not in pending

        queued = (
            ProjectFile.objects.filter(is_active=True)
            .exclude(
                Q(download_task_id="") | Q(download_task_id__isnull=True),
            )
            .exclude(
                download_attempts__status__in=[
                    DownloadAttempt.Status.DOWNLOADING,
                    DownloadAttempt.Status.COMPLETED,
                    DownloadAttempt.Status.FAILED,
                ],
            )
        )
        assert new_file not in queued

    def test_recovery_scanner_task_leaves_duplicate_alone(self) -> None:
        """Run the real scanner: it must not re-queue or fail the duplicate."""
        new_file = self.duplicate.files.get(is_active=True)
        with patch(
            "wafer_space.projects.tasks_download.download_project_file.delay",
        ) as mock_delay:
            result = ensure_download_tasks_queued()

        mock_delay.assert_not_called()
        assert result["created_tasks"] == 0
        assert result["orphaned"] == 0
        new_file.refresh_from_db()
        assert new_file.download_task_id.startswith("duplicated:")
        assert not new_file.download_attempts.filter(
            status=DownloadAttempt.Status.FAILED,
        ).exists()

    def test_download_attempt_copied(self) -> None:
        new_file = self.duplicate.files.get(is_active=True)
        attempt = new_file.download_attempts.get()
        assert attempt.status == DownloadAttempt.Status.COMPLETED
        assert attempt.attempt_number == 1
        assert attempt.bytes_downloaded == len(GDS_BYTES)

    def test_provenance_check_copied(self) -> None:
        new_file = self.duplicate.files.get(is_active=True)
        provenance = new_file.manufacturability_checks.get(
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        assert provenance.is_manufacturable is True
        assert provenance.warnings == ["minor spacing"]
        assert provenance.precheck_version == "v1.2.3"
        assert provenance.log_file_sha256 == "c" * 64
        assert not provenance.log_file
        assert not provenance.runs_archive
        assert not provenance.output_gds
        assert not provenance.docker_layer_export
        assert provenance.parent_check is None

    def test_fresh_check_queued(self) -> None:
        new_file = self.duplicate.files.get(is_active=True)
        fresh = new_file.manufacturability_checks.get(
            status=ManufacturabilityCheck.Status.PENDING,
        )
        assert fresh.trigger_reason == ManufacturabilityCheck.TriggerReason.DUPLICATED
        assert fresh.parent_check is not None
        assert fresh.parent_check.status == ManufacturabilityCheck.Status.FINISHED


@pytest.mark.django_db
class TestDuplicationCheckSelection(TestCase):
    """Provenance uses the latest FINISHED check; non-terminal never copied."""

    def setUp(self) -> None:
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=TEST_PASSWORD,
        )
        self.source_shuttle = make_shuttle("G890")
        self.target_shuttle = make_shuttle("G891")

    def test_newer_pending_check_is_ignored(self) -> None:
        source = make_source_project(shuttle=self.source_shuttle)
        source_file = source.files.get(is_active=True)
        ManufacturabilityCheck.objects.create(
            project=source,
            project_file=source_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        duplicate = duplicate_project_to_shuttle(
            project=source,
            target_shuttle=self.target_shuttle,
            admin_user=self.admin_user,
        )
        new_file = duplicate.files.get(is_active=True)
        finished = new_file.manufacturability_checks.filter(
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        assert finished.count() == 1
        assert finished.get().precheck_version == "v1.2.3"
        # Exactly one PENDING check: the fresh DUPLICATED one, not a copy
        # of the source's pending check.
        pending = new_file.manufacturability_checks.filter(
            status=ManufacturabilityCheck.Status.PENDING,
        )
        assert pending.count() == 1
        assert (
            pending.get().trigger_reason
            == ManufacturabilityCheck.TriggerReason.DUPLICATED
        )

    def test_no_finished_check_skips_provenance(self) -> None:
        source = make_source_project(
            shuttle=self.source_shuttle,
            with_finished_check=False,
        )
        duplicate = duplicate_project_to_shuttle(
            project=source,
            target_shuttle=self.target_shuttle,
            admin_user=self.admin_user,
        )
        new_file = duplicate.files.get(is_active=True)
        checks = new_file.manufacturability_checks.all()
        assert checks.count() == 1
        fresh = checks.get()
        assert fresh.status == ManufacturabilityCheck.Status.PENDING
        assert fresh.parent_check is None


@pytest.mark.django_db
class TestDuplicationAtomicity(TestCase):
    """A failure mid-copy rolls back everything, including the blob."""

    def setUp(self) -> None:
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=TEST_PASSWORD,
        )
        self.source_shuttle = make_shuttle("G890")
        self.target_shuttle = make_shuttle("G891")
        self.source = make_source_project(shuttle=self.source_shuttle)

    def test_integrityerror_rolls_back_and_becomes_duplication_error(self) -> None:
        projects_before = Project.objects.count()
        files_before = ProjectFile.objects.count()

        # Record the copied blob from inside the failing step: the DB
        # rollback discards the rows that would name it, and the media
        # root is shared with parallel tests, so a directory diff would
        # be racy.
        copied_names: list[str] = []
        copied_storages: list[Storage] = []

        def record_and_boom(
            source_file: ProjectFile,
            new_project: Project,
            new_file: ProjectFile,
        ) -> None:
            copied_names.append(new_file.file.name)
            copied_storages.append(new_file.file.storage)
            msg = "boom"
            raise IntegrityError(msg)

        with (
            patch(
                "wafer_space.projects.duplication._copy_provenance_check",
                side_effect=record_and_boom,
            ),
            pytest.raises(ProjectDuplicationError, match="boom"),
        ):
            duplicate_project_to_shuttle(
                project=self.source,
                target_shuttle=self.target_shuttle,
                admin_user=self.admin_user,
            )

        assert Project.objects.count() == projects_before
        assert ProjectFile.objects.count() == files_before
        # The copied storage blob must not be left orphaned.
        assert copied_names
        assert copied_names[0]
        assert not copied_storages[0].exists(copied_names[0])

    def test_failure_inside_copy_file_removes_blob(self) -> None:
        """_copy_file cleans up its own blob when a later step in it fails."""
        copied_names: list[str] = []
        copied_storages: list[Storage] = []

        def record_and_boom(**kwargs: object) -> None:
            new_file = kwargs["project_file"]
            assert isinstance(new_file, ProjectFile)
            copied_names.append(new_file.file.name)
            copied_storages.append(new_file.file.storage)
            msg = "boom"
            raise IntegrityError(msg)

        with (
            patch.object(
                DownloadAttempt.objects,
                "create",
                side_effect=record_and_boom,
            ),
            pytest.raises(ProjectDuplicationError, match="boom"),
        ):
            duplicate_project_to_shuttle(
                project=self.source,
                target_shuttle=self.target_shuttle,
                admin_user=self.admin_user,
            )

        assert copied_names
        assert copied_names[0]
        assert not copied_storages[0].exists(copied_names[0])
