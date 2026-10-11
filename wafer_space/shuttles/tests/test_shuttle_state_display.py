"""Every page that names a shuttle says whether it is open or closed (#350)."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

RUN_PAGE = "https://wafer.space/ws-run1/"
# 16 Dec 2099 23:59:59 AoE.
FUTURE_DEADLINE = datetime.datetime(2099, 12, 17, 11, 59, 59, tzinfo=datetime.UTC)
OPEN_TEXT = "GDS due 16 December 2099 @ 11:59 PM AoE"
CLOSED_BADGE = '<i class="bi bi-lock-fill" aria-hidden="true"></i> Closed'


@pytest.fixture
def closed() -> Shuttle:
    return Shuttle.objects.create(
        name="G890",
        description="Past run",
        status=Shuttle.Status.COMPLETED,
        website_url=RUN_PAGE,
    )


@pytest.fixture
def open_shuttle() -> Shuttle:
    return Shuttle.objects.create(
        name="G891",
        description="Current run",
        status=Shuttle.Status.OPEN,
        submission_deadline=FUTURE_DEADLINE,
    )


@pytest.fixture
def staff(client: Client) -> Client:
    client.force_login(UserFactory(is_staff=True))
    return client


@pytest.mark.parametrize("url_name", ["shuttles:detail", "shuttles:assignment"])
def test_staff_shuttle_pages_show_closed_and_run_page(
    staff: Client, closed: Shuttle, url_name: str
) -> None:
    content = staff.get(reverse(url_name, kwargs={"name": "G890"})).content.decode()

    assert (CLOSED_BADGE in content, RUN_PAGE in content) == (True, True)


def test_shuttle_list_shows_closed_and_open(
    staff: Client, closed: Shuttle, open_shuttle: Shuttle
) -> None:
    content = staff.get(reverse("shuttles:list")).content.decode()

    assert (CLOSED_BADGE in content, OPEN_TEXT in content) == (True, True)


def test_project_detail_shows_closed_and_run_page(
    client: Client, closed: Shuttle
) -> None:
    project = ProjectFactory(shuttle=closed)
    client.force_login(project.user)

    content = client.get(reverse("projects:detail", args=[project.pk])).content.decode()

    assert (CLOSED_BADGE in content, RUN_PAGE in content) == (True, True)


def test_project_detail_shows_open_deadline(
    client: Client, open_shuttle: Shuttle
) -> None:
    project = ProjectFactory(shuttle=open_shuttle)
    client.force_login(project.user)

    content = client.get(reverse("projects:detail", args=[project.pk])).content.decode()

    assert OPEN_TEXT in content


def test_project_form_locked_shuttle_shows_closed(
    client: Client, closed: Shuttle
) -> None:
    project = ProjectFactory(shuttle=closed)
    client.force_login(project.user)

    content = client.get(reverse("projects:update", args=[project.pk])).content.decode()

    assert CLOSED_BADGE in content
