"""Projects cannot be deleted outside the Django admin (issue #344)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.urls import NoReverseMatch
from django.urls import reverse

from wafer_space.projects.models import Project

from .constants import HTTP_NOT_FOUND
from .factories import ProjectFactory

if TYPE_CHECKING:
    from django.test import Client


def test_delete_url_name_is_gone() -> None:
    with pytest.raises(NoReverseMatch):
        reverse("projects:delete", args=["00000000-0000-0000-0000-000000000000"])


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "post"])
def test_delete_path_returns_404_and_keeps_project(client: Client, method: str) -> None:
    project = ProjectFactory()
    client.force_login(project.user)
    response = getattr(client, method)(f"/projects/{project.pk}/delete/")
    assert response.status_code == HTTP_NOT_FOUND
    assert Project.objects.filter(pk=project.pk).exists()


def test_no_template_links_to_project_delete() -> None:
    templates_dir = Path(settings.APPS_DIR) / "templates"
    offenders = [
        str(path)
        for path in templates_dir.rglob("*.html")
        if "projects:delete" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_delete_confirm_template_is_gone() -> None:
    templates_dir = Path(settings.APPS_DIR) / "templates"
    template = templates_dir / "projects" / "project_confirm_delete.html"
    assert not template.exists()
