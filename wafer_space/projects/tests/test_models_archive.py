"""Archive rules on Project (issue #307)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from wafer_space.projects.models import ARCHIVED_READ_ONLY_MESSAGE
from wafer_space.projects.models import Project
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.users.tests.factories import UserFactory

from .factories import ProjectFactory
from .factories import ProjectFileFactory

pytestmark = pytest.mark.django_db


def make_project(**kwargs: object) -> Project:
    """Create a project and reload it, as views do (loads _loaded_values)."""
    return Project.objects.get(pk=ProjectFactory(**kwargs).pk)


def make_slot_holding(project: Project) -> ShuttleSlot:
    shuttle = Shuttle.objects.create(name="G880", description="Archive test")
    return ShuttleSlot.objects.create(
        shuttle=shuttle,
        project=project,
        status=ShuttleSlot.Status.RESERVED,
    )


def give_submitted_file(project: Project) -> Project:
    Project.objects.filter(pk=project.pk).update(
        submitted_file=ProjectFileFactory(project=project),
    )
    return Project.objects.get(pk=project.pk)


def test_new_project_is_not_archived() -> None:
    assert make_project().is_archived is False


def test_archive_sets_archived_at() -> None:
    project = make_project()
    project.archive()
    project.refresh_from_db()
    assert project.archived_at is not None


def test_unarchive_clears_archived_at() -> None:
    project = make_project(archived_at=timezone.now())
    project.unarchive()
    project.refresh_from_db()
    assert project.archived_at is None


def test_archive_is_recorded_in_history() -> None:
    project = make_project()
    project.archive()
    latest = project.history.order_by("-history_id").first()
    assert latest is not None
    assert latest.archived_at is not None


def test_can_submit_refuses_archived_project() -> None:
    project = make_project(archived_at=timezone.now())
    assert project.can_submit() == (False, ARCHIVED_READ_ONLY_MESSAGE)


def test_owner_can_archive_own_draft() -> None:
    project = make_project()
    assert project.can_be_archived_by(project.user) == (True, "")


def test_owner_cannot_archive_project_with_submitted_file() -> None:
    project = give_submitted_file(make_project())
    allowed, reason = project.can_be_archived_by(project.user)
    assert allowed is False
    assert "submitted for manufacturing" in reason


def test_staff_can_archive_project_with_submitted_file() -> None:
    project = give_submitted_file(make_project())
    staff = UserFactory(is_staff=True)
    assert project.can_be_archived_by(staff) == (True, "")


def test_nobody_can_archive_project_holding_a_slot() -> None:
    project = make_project()
    make_slot_holding(project)
    staff = UserFactory(is_staff=True)
    allowed, reason = project.can_be_archived_by(staff)
    assert allowed is False
    assert "shuttle slot" in reason


def test_project_can_be_archived_after_slot_released() -> None:
    project = make_project()
    slot = make_slot_holding(project)
    slot.cancel_reservation()
    assert project.can_be_archived_by(project.user) == (True, "")


def test_already_archived_project_cannot_be_archived_again() -> None:
    project = make_project(archived_at=timezone.now())
    assert project.can_be_archived_by(project.user) == (
        False,
        "Project is already archived",
    )


def test_background_status_update_saves_on_archived_project() -> None:
    project = make_project(archived_at=timezone.now())
    project.status = Project.Status.MANUFACTURABLE
    project.save(update_fields=["status"])
    project.refresh_from_db()
    assert project.status == Project.Status.MANUFACTURABLE


def make_project_with_stale_invalid_data(**kwargs: object) -> Project:
    """A project whose stored data no longer passes validation."""
    project = make_project(**kwargs)
    Project.objects.filter(pk=project.pk).update(
        name="",
        repository_url="not a url",
    )
    return Project.objects.get(pk=project.pk)


def test_archive_works_on_project_with_stale_invalid_data() -> None:
    """Abandoned projects may hold old data; archiving must not 500."""
    project = make_project_with_stale_invalid_data()
    project.archive()
    project.refresh_from_db()
    assert project.is_archived


def test_unarchive_works_on_project_with_stale_invalid_data() -> None:
    project = make_project_with_stale_invalid_data(archived_at=timezone.now())
    project.unarchive()
    project.refresh_from_db()
    assert not project.is_archived


def test_full_save_still_validates_every_field() -> None:
    project = make_project_with_stale_invalid_data()
    with pytest.raises(ValidationError):
        project.save()
