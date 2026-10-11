"""Project detail page in archived and active states (issue #307)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects.models import ARCHIVED_READ_ONLY_MESSAGE
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project

from .factories import ManufacturabilityCheckFactory
from .factories import ProjectFactory
from .factories import make_downloaded_file

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def detail_page(client: Client, project: Project) -> str:
    client.force_login(project.user)
    response = client.get(reverse("projects:detail", args=[project.pk]))
    return response.content.decode()


def test_active_project_shows_archive_form(client: Client) -> None:
    project = ProjectFactory()
    content = detail_page(client, project)
    assert reverse("projects:archive", args=[project.pk]) in content


def test_archived_project_shows_unarchive_form_and_banner(client: Client) -> None:
    project = ProjectFactory(archived_at=timezone.now())
    content = detail_page(client, project)
    assert reverse("projects:unarchive", args=[project.pk]) in content
    assert "data-archived-banner" in content
    assert "This project was archived on" in content


def test_archived_project_has_no_archive_form(client: Client) -> None:
    project = ProjectFactory(archived_at=timezone.now())
    content = detail_page(client, project)
    assert reverse("projects:archive", args=[project.pk]) not in content


def test_archived_project_disables_edit_and_file_links(client: Client) -> None:
    project = ProjectFactory(archived_at=timezone.now())
    content = detail_page(client, project)
    assert reverse("projects:update", args=[project.pk]) not in content
    assert reverse("projects:submit_url", args=[project.pk]) not in content
    assert ARCHIVED_READ_ONLY_MESSAGE in content


def make_outdated_check(project: Project) -> ManufacturabilityCheck:
    """A finished check on an outdated precheck image (shows Recheck)."""
    cache.clear()  # get_latest_precheck_digest caches for 60 s
    now = timezone.now()
    ManufacturabilityCheckFactory(
        status=ManufacturabilityCheck.Status.FINISHED,
        docker_image_digest="sha256:" + "b" * 64,
        container_started_at=now,
    )
    return ManufacturabilityCheckFactory(
        project=project,
        project_file__project=project,
        project_file__is_active=True,
        status=ManufacturabilityCheck.Status.FINISHED,
        docker_image_digest="sha256:" + "a" * 64,
        container_started_at=now - timedelta(days=1),
    )


def test_active_project_shows_recheck_button(client: Client) -> None:
    """Guard for the next test: the outdated check does render Recheck."""
    project = ProjectFactory()
    check = make_outdated_check(project)
    requeue = reverse("projects:check_drc_update_requeue", args=[check.pk])
    assert requeue in detail_page(client, project)


def test_archived_project_hides_recheck_button(client: Client) -> None:
    project = ProjectFactory(archived_at=timezone.now())
    check = make_outdated_check(project)
    requeue = reverse("projects:check_drc_update_requeue", args=[check.pk])
    assert requeue not in detail_page(client, project)


def test_archive_button_disabled_with_reason_for_owner_with_submitted_file(
    client: Client,
) -> None:
    project = ProjectFactory()
    Project.objects.filter(pk=project.pk).update(
        submitted_file=make_downloaded_file(project),
    )
    content = detail_page(client, project)
    assert reverse("projects:archive", args=[project.pk]) not in content
    assert "Contact staff to archive it" in content
