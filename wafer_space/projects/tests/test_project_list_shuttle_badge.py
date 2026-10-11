"""The projects list says when a project's shuttle is closed or test only.

Follow-up to #350 (closed shown everywhere a shuttle is named) and #221
(test-only shuttles), on the list from #321 and #372.
"""

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

FUTURE = datetime.datetime(2099, 12, 17, 11, 59, 59, tzinfo=datetime.UTC)
PAST = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
CLOSED = '<i class="bi bi-lock-fill" aria-hidden="true"></i> Closed'
TEST_ONLY = '<i class="bi bi-clipboard2-check" aria-hidden="true"></i> Test only'


def _list_for_shuttle(client: Client, **shuttle_fields: object) -> str:
    shuttle = Shuttle.objects.create(name="G896", description="Run", **shuttle_fields)
    user = UserFactory()
    ProjectFactory(user=user, shuttle=shuttle)
    client.force_login(user)
    return client.get(reverse("projects:list")).content.decode()


@pytest.mark.parametrize(
    "shuttle_fields",
    [
        {"status": Shuttle.Status.COMPLETED},
        # Status open but the deadline has passed: the G802 case in #320.
        {"status": Shuttle.Status.OPEN, "submission_deadline": PAST},
    ],
    ids=["status", "deadline"],
)
def test_closed_shuttle_says_closed(client: Client, shuttle_fields) -> None:
    content = _list_for_shuttle(client, **shuttle_fields)

    assert (CLOSED in content, "data-shuttle-deadline" in content) == (True, False)


def test_closed_badge_gives_the_reason(client: Client) -> None:
    content = _list_for_shuttle(client, status=Shuttle.Status.COMPLETED)

    assert 'title="Shuttle G896 is closed (Completed)"' in content


def test_open_shuttle_shows_countdown_not_closed(client: Client) -> None:
    content = _list_for_shuttle(
        client, status=Shuttle.Status.OPEN, submission_deadline=FUTURE
    )

    assert (CLOSED in content, "data-shuttle-deadline" in content) == (False, True)


def test_test_only_shuttle_says_test_only(client: Client) -> None:
    content = _list_for_shuttle(
        client,
        status=Shuttle.Status.COMPLETED,
        submission_deadline=PAST,
        is_test_only=True,
    )

    assert (TEST_ONLY in content, CLOSED in content) == (True, False)


def test_project_without_shuttle_has_no_badge(client: Client) -> None:
    user = UserFactory()
    ProjectFactory(user=user, shuttle=None)
    client.force_login(user)

    content = client.get(reverse("projects:list")).content.decode()

    assert (CLOSED in content, TEST_ONLY in content) == (False, False)
