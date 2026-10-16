"""A planning shuttle says it has not opened yet, not "Closed" (#438).

G804 (Run #4) was created in status planning and every page showed it with
the grey "Closed" lock badge, which reads as "this run is over". Each page
that shows a shuttle's state is checked here in all five states: planning,
open, open past its deadline, closed and test only.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from wafer_space.projects.tests.constants import HTTP_OK
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

FUTURE = datetime.datetime(2099, 12, 17, 11, 59, 59, tzinfo=datetime.UTC)
PAST = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
NAME = "G874"

# The state badges, as shuttles/_shuttle_state.html and the projects list
# render them
BADGES = {
    "not open yet": 'aria-hidden="true"></i> Not open yet',
    "closed": 'aria-hidden="true"></i> Closed',
    "open": '<span class="badge bg-success">Open</span>',
    "test only": 'aria-hidden="true"></i> Test only',
}

STATES: dict[str, dict[str, object]] = {
    "planning": {"status": Shuttle.Status.PLANNING},
    "open": {"status": Shuttle.Status.OPEN, "submission_deadline": FUTURE},
    "open past deadline": {"status": Shuttle.Status.OPEN, "submission_deadline": PAST},
    "closed": {"status": Shuttle.Status.COMPLETED},
    # Test only overrides status: a planning test-only shuttle is open (#221)
    "test only": {"status": Shuttle.Status.PLANNING, "is_test_only": True},
}

# The badges shuttles/_shuttle_state.html shows for each state
SHUTTLE_STATE_BADGES = {
    "planning": {"not open yet"},
    "open": {"open"},
    "open past deadline": {"closed"},
    "closed": {"closed"},
    "test only": {"open", "test only"},
}

# The projects list's narrow shuttle column shows no badge for an open
# shuttle, only its deadline
PROJECT_LIST_BADGES = {
    "planning": {"not open yet"},
    "open": set(),
    "open past deadline": {"closed"},
    "closed": {"closed"},
    "test only": {"test only"},
}

CLOSED_REASONS = {
    "planning": f"Shuttle {NAME} has not opened yet",
    "open": None,
    "open past deadline": f"Shuttle {NAME} is closed: its GDS deadline has passed",
    "closed": f"Shuttle {NAME} is closed (Completed)",
    "test only": None,
}


def make_shuttle(state: str) -> Shuttle:
    return Shuttle.objects.create(name=NAME, description="Run", **STATES[state])


def badges_in(content: str) -> set[str]:
    return {name for name, badge in BADGES.items() if badge in content}


def staff_page(client: Client, url_name: str, state: str) -> str:
    """The page as staff; on the list, only this shuttle's card.

    The list also shows the shuttles the migrations create, G801 and the
    rest, which are closed.
    """
    make_shuttle(state)
    client.force_login(UserFactory(is_staff=True))
    if url_name != "shuttles:list":
        url = reverse(url_name, kwargs={"name": NAME})
        return client.get(url).content.decode()
    content = client.get(reverse(url_name)).content.decode()
    start = content.index(f'<h5 class="mb-0">{NAME}</h5>')
    return content[start : content.index("card-footer", start)]


def owner_page(client: Client, url_name: str, state: str) -> str:
    project = ProjectFactory(shuttle=make_shuttle(state))
    client.force_login(project.user)
    if url_name == "projects:detail":
        url = project.get_absolute_url()
    elif url_name == "projects:list":
        url = reverse(url_name)
    else:
        url = reverse(url_name, args=[project.pk])
    response = client.get(url, follow=True)
    assert response.status_code == HTTP_OK
    return response.content.decode()


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize(
    "url_name", ["shuttles:list", "shuttles:detail", "shuttles:assignment"]
)
def test_shuttle_pages_show_the_state(
    client: Client, url_name: str, state: str
) -> None:
    content = staff_page(client, url_name, state)

    assert badges_in(content) == SHUTTLE_STATE_BADGES[state]


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("url_name", ["projects:detail", "projects:update"])
def test_project_pages_show_the_state(
    client: Client, url_name: str, state: str
) -> None:
    content = owner_page(client, url_name, state)

    assert badges_in(content) == SHUTTLE_STATE_BADGES[state]


@pytest.mark.parametrize("state", STATES)
def test_projects_list_shows_the_state(client: Client, state: str) -> None:
    content = owner_page(client, "projects:list", state)

    assert badges_in(content) == PROJECT_LIST_BADGES[state]


@pytest.mark.parametrize("state", STATES)
def test_closed_reason(state: str) -> None:
    assert make_shuttle(state).closed_reason == CLOSED_REASONS[state]


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("planning", True),
        ("open", False),
        ("open past deadline", False),
        ("closed", False),
        ("test only", False),
    ],
)
def test_is_not_open_yet(state: str, *, expected: bool) -> None:
    assert make_shuttle(state).is_not_open_yet is expected


def test_planning_still_refuses_owners() -> None:
    """Only the words change: a planning shuttle stays closed to users."""
    shuttle = make_shuttle("planning")

    assert (shuttle.is_open_to_users(), shuttle.is_closed) == (False, True)


def test_projects_list_badge_gives_the_reason(client: Client) -> None:
    content = owner_page(client, "projects:list", "planning")

    assert f'title="Shuttle {NAME} has not opened yet"' in content


def test_project_page_says_files_can_be_submitted_once_it_opens(
    client: Client,
) -> None:
    content = " ".join(owner_page(client, "projects:detail", "planning").split())

    assert (
        f"Shuttle {NAME} has not opened yet. New design files can be submitted "
        "once it opens."
    ) in content
    assert "can no longer be submitted" not in content


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        ("closed", "is closed (Completed)"),
        ("open past deadline", "is closed: its GDS deadline has passed"),
    ],
)
def test_project_page_on_a_closed_shuttle_keeps_its_wording(
    client: Client, state: str, reason: str
) -> None:
    content = " ".join(owner_page(client, "projects:detail", state).split())

    assert (
        f"Shuttle {NAME} {reason}. New design files can no longer be submitted."
    ) in content


@pytest.mark.parametrize("state", ["open", "test only"])
def test_project_page_on_an_open_shuttle_has_no_alert(
    client: Client, state: str
) -> None:
    content = owner_page(client, "projects:detail", state)

    assert "New design files can" not in content
