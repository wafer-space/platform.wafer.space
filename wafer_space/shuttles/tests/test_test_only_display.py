"""Every page that names a test-only shuttle says "Test only" (#221)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

TEST_ONLY_BADGE = '<i class="bi bi-clipboard2-check" aria-hidden="true"></i> Test only'
MEANING = "Designs are checked but never manufactured"
NOTICE = "G895 is test only: no slot assignment"


@pytest.fixture
def test_shuttle() -> Shuttle:
    return Shuttle.objects.create(
        name="G895",
        description="Test shuttle",
        status=Shuttle.Status.OPEN,
        is_test_only=True,
    )


@pytest.fixture
def staff(client: Client) -> Client:
    client.force_login(UserFactory(is_staff=True))
    return client


@pytest.mark.parametrize(
    ("url_name", "kwargs"),
    [
        ("shuttles:list", {}),
        ("shuttles:detail", {"name": "G895"}),
        ("shuttles:assignment", {"name": "G895"}),
    ],
)
def test_staff_shuttle_pages_say_test_only(
    staff: Client, test_shuttle: Shuttle, url_name: str, kwargs: dict[str, str]
) -> None:
    content = staff.get(reverse(url_name, kwargs=kwargs)).content.decode()

    assert (TEST_ONLY_BADGE in content, MEANING in content) == (True, True)


@pytest.mark.parametrize("url_name", ["projects:detail", "projects:update"])
def test_owner_project_pages_say_test_only(
    client: Client, test_shuttle: Shuttle, url_name: str
) -> None:
    project = ProjectFactory(shuttle=test_shuttle)
    client.force_login(project.user)

    content = client.get(reverse(url_name, args=[project.pk])).content.decode()

    assert TEST_ONLY_BADGE in content


def test_real_shuttle_has_no_test_only_badge(staff: Client) -> None:
    Shuttle.objects.create(
        name="G896", description="Real run", status=Shuttle.Status.OPEN
    )

    content = staff.get(reverse("shuttles:detail", kwargs={"name": "G896"}))

    assert "Test only" not in content.content.decode()


def test_assignment_page_shows_notice_instead_of_grid(
    staff: Client, test_shuttle: Shuttle
) -> None:
    content = staff.get(
        reverse("shuttles:assignment", kwargs={"name": "G895"})
    ).content.decode()

    assert (NOTICE in content, 'id="grid-table"' in content) == (True, False)
