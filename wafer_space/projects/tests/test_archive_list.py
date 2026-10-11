"""Archived projects sort last on /projects/ (issue #307)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects.models import Project
from wafer_space.users.tests.factories import UserFactory

from .factories import ProjectFactory

if TYPE_CHECKING:
    from django.test import Client

    from wafer_space.users.models import User

pytestmark = pytest.mark.django_db


def make_projects(user: User) -> None:
    """Create, newest first: an archived one, then two active ones."""
    now = timezone.now()
    for name, age_days, archived in (
        ("New archived", 1, True),
        ("Middle active", 2, False),
        ("Old active", 3, False),
    ):
        project = ProjectFactory(
            user=user,
            name=name,
            archived_at=now if archived else None,
        )
        Project.objects.filter(pk=project.pk).update(
            created_at=now - timedelta(days=age_days),
        )


def listed_names(client: Client, query: str = "") -> list[str]:
    response = client.get(reverse("projects:list") + query)
    return [p.name for p in response.context["projects"]]


def test_owner_list_has_archived_last(client: Client) -> None:
    user = UserFactory()
    make_projects(user)
    client.force_login(user)
    assert listed_names(client) == ["Middle active", "Old active", "New archived"]


def test_staff_list_has_archived_last(client: Client) -> None:
    make_projects(UserFactory())
    client.force_login(UserFactory(is_staff=True))
    assert listed_names(client)[-1] == "New archived"


def test_archived_row_has_badge(client: Client) -> None:
    user = UserFactory()
    make_projects(user)
    client.force_login(user)
    content = client.get(reverse("projects:list")).content.decode()
    assert content.count("data-archived-badge") == 1


def test_archived_projects_after_all_active_across_pages(client: Client) -> None:
    user = UserFactory()
    now = timezone.now()
    for i in range(20):
        active = ProjectFactory(user=user, name=f"Active {i}")
        Project.objects.filter(pk=active.pk).update(
            created_at=now - timedelta(days=i + 1),
        )
    # The newest project of all, so only the archive rule can put it last.
    archived = ProjectFactory(user=user, name="Archived", archived_at=now)
    client.force_login(user)
    assert "Archived" not in listed_names(client)
    assert listed_names(client, "?page=2") == [archived.name]
