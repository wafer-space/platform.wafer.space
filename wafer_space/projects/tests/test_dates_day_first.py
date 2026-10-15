"""Project dates are shown day first, also to US browsers (#412).

The format rules themselves are tested in ``config/tests/test_date_formats``;
these check two pages that showed "Nov 23, 2026" before.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from wafer_space.projects.models import Project
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

# Midday UTC, so the date is the same in any display time zone.
CREATED = datetime.datetime(2026, 11, 23, 12, 0, tzinfo=datetime.UTC)
US_BROWSER = {"Accept-Language": "en-US,en;q=0.9"}


def _project(**fields: object) -> Project:
    project = ProjectFactory(**fields)
    # created_at is auto_now_add, so it is set after creation.
    Project.objects.filter(pk=project.pk).update(created_at=CREATED)
    return project


@pytest.mark.parametrize("accept_language", ["en-US,en;q=0.9", "en-GB", "de"])
def test_projects_list_date_is_not_month_first(
    client: Client, accept_language: str
) -> None:
    """The list's created date was a "M d, Y" literal for every browser."""
    user = UserFactory()
    _project(user=user)
    client.force_login(user)

    html = client.get(
        reverse("projects:list"), headers={"Accept-Language": accept_language}
    ).content.decode()

    assert "Nov 23, 2026" not in html


def test_projects_list_date_is_day_first_for_us_browser(client: Client) -> None:
    """A US browser gets the platform's day-first date."""
    user = UserFactory()
    _project(user=user)
    client.force_login(user)

    html = client.get(reverse("projects:list"), headers=US_BROWSER).content.decode()

    assert "23 Nov 2026" in html


def test_admin_project_list_date_is_day_first_for_us_browser(client: Client) -> None:
    """The admin's datetime columns use the default formats, which were
    "Nov. 23, 2026, noon" for a US browser."""
    _project()
    client.force_login(UserFactory(is_staff=True, is_superuser=True))

    html = client.get(
        reverse("admin:projects_project_changelist"), headers=US_BROWSER
    ).content.decode()

    assert "23 Nov 2026, " in html
    assert "Nov. 23, 2026" not in html
