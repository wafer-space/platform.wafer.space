"""The project pages show the description as sanitised markdown (#285).

Staff open other users' project pages, so a description that could carry
script would be stored XSS against staff.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from wafer_space.users.tests.factories import UserFactory

from .factories import ProjectFactory
from .html_elements import parse_html

if TYPE_CHECKING:
    from django.test import Client

    from wafer_space.projects.models import Project

pytestmark = pytest.mark.django_db

PAYLOAD = "alert(1)"
DESCRIPTION = (
    "A **ring oscillator**.\n\n"
    "- see [docs](https://wafer.space/)\n\n"
    f'<script>{PAYLOAD}</script> <img src=x onerror="{PAYLOAD}">\n\n'
    f"[click](javascript:{PAYLOAD})"
)


def payload_reaches_the_page(content: str) -> bool:
    """True when the description's script runs: a script body, handler or link."""
    parsed = parse_html(content)
    attribute_values = [
        value or "" for _, attrs in parsed.elements for value in attrs.values()
    ]
    return any(PAYLOAD in text for text in parsed.scripts + attribute_values)


def detail_page(client: Client, project: Project) -> str:
    response = client.get(project.get_absolute_url(), follow=True)
    return response.content.decode()


class TestDetailPage:
    @pytest.fixture
    def project(self) -> Project:
        return ProjectFactory(description=DESCRIPTION)

    def test_owner_sees_rendered_markdown(
        self, client: Client, project: Project
    ) -> None:
        client.force_login(project.user)
        assert "<strong>ring oscillator</strong>" in detail_page(client, project)

    def test_link_is_rendered_with_nofollow(
        self, client: Client, project: Project
    ) -> None:
        client.force_login(project.user)
        assert (
            '<a href="https://wafer.space/" rel="nofollow noopener noreferrer">docs</a>'
        ) in detail_page(client, project)

    def test_staff_page_carries_no_script_from_the_description(
        self, client: Client, project: Project
    ) -> None:
        client.force_login(UserFactory(is_staff=True))
        assert not payload_reaches_the_page(detail_page(client, project))

    def test_typed_html_is_shown_as_text(
        self, client: Client, project: Project
    ) -> None:
        client.force_login(project.user)
        assert "&lt;script&gt;" in detail_page(client, project)


class TestListPage:
    """The list shows a plain-text excerpt, not markdown syntax or HTML."""

    @pytest.fixture
    def content(self, client: Client) -> str:
        project = ProjectFactory(description=DESCRIPTION)
        client.force_login(project.user)
        return client.get(reverse("projects:list")).content.decode()

    def test_excerpt_has_no_markdown_syntax(self, content: str) -> None:
        assert ("A ring oscillator." in content, "**ring" in content) == (True, False)

    def test_excerpt_carries_no_script(self, content: str) -> None:
        assert not payload_reaches_the_page(content)
