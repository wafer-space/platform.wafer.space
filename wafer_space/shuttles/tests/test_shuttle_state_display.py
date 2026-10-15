"""Every page that names a shuttle says whether it is open or closed (#350)."""

from __future__ import annotations

import datetime
import re
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.tests.test_deadline_include import has_local_time
from wafer_space.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

RUN_PAGE = "https://wafer.space/ws-run1/"
# 16 Dec 2099 23:59:59 AoE.
FUTURE_DEADLINE = datetime.datetime(2099, 12, 17, 11, 59, 59, tzinfo=datetime.UTC)
OPEN_TEXT = "GDS submission deadline: 16 December 2099 @ 11:59 PM AoE"


def visible_text(html: str) -> str:
    """The page text a reader sees: tags dropped, whitespace collapsed."""
    return " ".join(re.sub(r"<[^>]+>", " ", html).split()).replace(" :", ":")


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

    assert (CLOSED_BADGE in content, OPEN_TEXT in visible_text(content)) == (
        True,
        True,
    )


def test_project_detail_shows_closed_and_run_page(
    client: Client, closed: Shuttle
) -> None:
    project = ProjectFactory(shuttle=closed)
    client.force_login(project.user)

    content = client.get(project.get_absolute_url()).content.decode()

    assert (CLOSED_BADGE in content, RUN_PAGE in content) == (True, True)


def test_project_detail_shows_open_deadline(
    client: Client, open_shuttle: Shuttle
) -> None:
    project = ProjectFactory(shuttle=open_shuttle)
    client.force_login(project.user)

    content = client.get(project.get_absolute_url()).content.decode()

    assert OPEN_TEXT in visible_text(content)


def test_project_form_locked_shuttle_shows_closed(
    client: Client, closed: Shuttle
) -> None:
    project = ProjectFactory(shuttle=closed)
    client.force_login(project.user)

    content = client.get(reverse("projects:update", args=[project.pk])).content.decode()

    assert CLOSED_BADGE in content


@pytest.mark.parametrize("url_name", ["shuttles:list", "shuttles:detail"])
def test_lapsed_open_status_never_shows_green(staff: Client, url_name: str) -> None:
    # Status still "open" but the deadline has passed: the only state shown
    # is "Closed"; no green badge may contradict it.
    Shuttle.objects.create(
        name="G896",
        description="Lapsed",
        status=Shuttle.Status.OPEN,
        submission_deadline=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
    )
    kwargs = {} if url_name == "shuttles:list" else {"name": "G896"}

    content = staff.get(reverse(url_name, kwargs=kwargs)).content.decode()

    assert (CLOSED_BADGE in content, "badge bg-success" in content) == (True, False)


def test_project_detail_counts_down_to_open_deadline(
    client: Client,
    open_shuttle: Shuttle,
) -> None:
    """#349: the open shuttle's deadline carries the countdown markers."""
    project = ProjectFactory(shuttle=open_shuttle)
    client.force_login(project.user)
    content = client.get(project.get_absolute_url()).content
    html = content.decode()
    assert 'data-countdown="2099-12-17T11:59:59Z"' in html
    assert has_local_time(html, "2099-12-17T11:59:59Z")


def test_project_detail_closed_shuttle_has_no_countdown(
    client: Client,
    closed: Shuttle,
) -> None:
    project = ProjectFactory(shuttle=closed)
    client.force_login(project.user)
    content = client.get(project.get_absolute_url()).content
    assert b"data-shuttle-deadline" not in content


def test_projects_list_counts_down_to_open_deadline(
    client: Client,
    open_shuttle: Shuttle,
) -> None:
    """#349: the projects list's shuttle column shows the countdown."""
    project = ProjectFactory(shuttle=open_shuttle)
    client.force_login(project.user)
    html = client.get(reverse("projects:list")).content.decode()
    assert 'data-countdown="2099-12-17T11:59:59Z"' in html


def test_projects_list_closed_shuttle_has_no_countdown(
    client: Client,
    closed: Shuttle,
) -> None:
    project = ProjectFactory(shuttle=closed)
    client.force_login(project.user)
    html = client.get(reverse("projects:list")).content.decode()
    assert "data-countdown" not in html
