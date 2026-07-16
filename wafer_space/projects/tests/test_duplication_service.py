"""Tests for the project duplication service."""

from __future__ import annotations

import pytest
from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from wafer_space.projects.exceptions import ProjectDuplicationError
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.services import duplicate_project_to_shuttle
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.models import User

from .constants import TEST_PASSWORD
from .factories import ProjectFactory
from .factories import ProjectFileFactory

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
