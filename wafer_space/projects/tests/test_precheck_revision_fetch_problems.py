"""Staff can see precheck metadata-fetch problems without reading logs (#293)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects.models import MAX_METADATA_FETCH_ATTEMPTS
from wafer_space.projects.models import PrecheckImageRevision
from wafer_space.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

DIGEST = "sha256:" + "c" * 64
PARTIAL_ERROR = "pdk_version unresolved"
GAVE_UP_ERROR = "manifest has no config"


def _partial() -> PrecheckImageRevision:
    return PrecheckImageRevision.objects.create(
        digest=DIGEST,
        metadata_fetched_at=timezone.now(),
        metadata_fetch_last_error=PARTIAL_ERROR,
    )


def _gave_up() -> PrecheckImageRevision:
    return PrecheckImageRevision.objects.create(
        digest="sha256:" + "d" * 64,
        metadata_fetch_attempts=MAX_METADATA_FETCH_ATTEMPTS,
        metadata_fetch_last_error=GAVE_UP_ERROR,
    )


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"metadata_fetched_at": timezone.now()}, ""),
        ({}, ""),
        (
            {
                "metadata_fetched_at": timezone.now(),
                "metadata_fetch_last_error": PARTIAL_ERROR,
            },
            "Partial metadata",
        ),
        (
            {
                "metadata_fetch_attempts": MAX_METADATA_FETCH_ATTEMPTS,
                "metadata_fetch_last_error": GAVE_UP_ERROR,
            },
            "Gave up",
        ),
        (
            {
                "metadata_fetch_attempts": 3,
                "metadata_fetch_last_error": "ghcr unreachable",
            },
            f"Retrying (3/{MAX_METADATA_FETCH_ATTEMPTS})",
        ),
    ],
    ids=["fetched", "not-yet-fetched", "partial", "gave-up", "retrying"],
)
def test_metadata_fetch_problem_label(fields: dict, expected: str) -> None:
    revision = PrecheckImageRevision(digest=DIGEST, **fields)

    assert revision.metadata_fetch_problem == expected


def test_with_fetch_problems_lists_only_rows_with_an_error() -> None:
    partial = _partial()
    gave_up = _gave_up()
    PrecheckImageRevision.objects.create(
        digest="sha256:" + "e" * 64, metadata_fetched_at=timezone.now()
    )

    assert set(PrecheckImageRevision.with_fetch_problems()) == {partial, gave_up}


def test_admin_changelist_shows_the_last_error(client: Client) -> None:
    _gave_up()
    client.force_login(UserFactory(is_staff=True))

    response = client.get(reverse("admin:projects_precheckimagerevision_changelist"))

    assert GAVE_UP_ERROR in response.content.decode()


def test_admin_summary_warns_staff_about_fetch_problems(client: Client) -> None:
    _partial()
    _gave_up()
    client.force_login(UserFactory(is_staff=True))

    html = client.get(reverse("projects:admin_summary")).content.decode()

    assert "data-precheck-metadata-problems" in html
    assert f"Partial metadata: {PARTIAL_ERROR}" in html
    assert f"Gave up: {GAVE_UP_ERROR}" in html


def test_admin_summary_has_no_warning_without_problems(client: Client) -> None:
    PrecheckImageRevision.objects.create(
        digest=DIGEST, metadata_fetched_at=timezone.now()
    )
    client.force_login(UserFactory(is_staff=True))

    html = client.get(reverse("projects:admin_summary")).content.decode()

    assert "data-precheck-metadata-problems" not in html
