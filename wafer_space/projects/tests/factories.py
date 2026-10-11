"""Test factories for projects app."""

from __future__ import annotations

from factory import Faker
from factory import Sequence
from factory import SubFactory
from factory.django import DjangoModelFactory

from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.users.tests.factories import UserFactory

_BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ID_DIGITS = 3


def factory_project_id(n: int) -> str:
    """'T' plus ``n`` as three base-36 digits: always a valid 4-character ID.

    The old ``f"T{n:03d}"`` became 5 characters once a test run had made
    1000 projects, failing whichever test came next on project_id
    validation. Base 36 gives 46,656 distinct IDs before wrapping.
    """
    n %= len(_BASE36) ** _ID_DIGITS
    digits = ""
    for _ in range(_ID_DIGITS):
        n, digit = divmod(n, len(_BASE36))
        digits = _BASE36[digit] + digits
    return f"T{digits}"


class ProjectFactory(DjangoModelFactory[Project]):
    """Factory for creating test Project instances."""

    user = SubFactory(UserFactory)
    name = Faker("catch_phrase")
    description = Faker("text", max_nb_chars=200)
    slot_size = "1x1"
    status = Project.Status.DRAFT
    project_id = Sequence(factory_project_id)

    class Meta:
        model = Project


class ProjectFileFactory(DjangoModelFactory[ProjectFile]):
    """Factory for creating test ProjectFile instances."""

    project = SubFactory(ProjectFactory)
    file = Faker("file_name", extension="gds")
    original_filename = Faker("file_name", extension="gds")
    file_size = Faker("random_int", min=1000, max=10000000)

    class Meta:
        model = ProjectFile


class ManufacturabilityCheckFactory(DjangoModelFactory[ManufacturabilityCheck]):
    """Factory for creating test ManufacturabilityCheck instances."""

    project = SubFactory(ProjectFactory)
    project_file = SubFactory(ProjectFileFactory, project=project)
    status = ManufacturabilityCheck.Status.PENDING
    docker_server_id = ""
    trigger_reason = ManufacturabilityCheck.TriggerReason.INITIAL
    parent_check = None

    class Meta:
        model = ManufacturabilityCheck


def make_downloaded_file(project: Project) -> ProjectFile:
    """An active file whose download has completed (no work in progress)."""
    project_file = ProjectFileFactory(
        project=project,
        is_active=True,
        download_task_id="completed-task",
    )
    DownloadAttempt.objects.create(
        project_file=project_file,
        attempt_number=1,
        status=DownloadAttempt.Status.COMPLETED,
    )
    return project_file
