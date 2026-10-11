"""Owner shown on the project detail page (issue #304)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from wafer_space.users.tests.factories import UserFactory

from .factories import ProjectFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def owner_line(client: Client, *, name: str, username: str) -> str:
    owner = UserFactory(name=name, username=username)
    project = ProjectFactory(user=owner)
    client.force_login(owner)
    content = client.get(reverse("projects:detail", args=[project.pk])).content
    text = content.decode()
    start = text.index("<strong>Owner:</strong>")
    return " ".join(text[start : text.index("</p>", start)].split())


def test_owner_shows_name(client: Client) -> None:
    line = owner_line(client, name="Ada Lovelace", username="ada")
    assert line == "<strong>Owner:</strong> Ada Lovelace"


def test_owner_without_name_shows_username(client: Client) -> None:
    line = owner_line(client, name="", username="ada")
    assert line == "<strong>Owner:</strong> ada"
