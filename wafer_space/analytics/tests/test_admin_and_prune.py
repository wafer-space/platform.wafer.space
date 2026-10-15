"""RequestLog admin is read-only for everyone; prune deletes only old rows (#379)."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django.utils import timezone

from wafer_space.analytics.models import RequestLog
from wafer_space.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_FORBIDDEN = 403
TWO_4XX_ROWS = 2


def _row(**fields: object) -> RequestLog:
    defaults: dict[str, object] = {
        "request_id": "f" * 32,
        "method": "GET",
        "path": "/projects/",
        "view_name": "projects:list",
        "status": 200,
        "duration_ms": 1,
    }
    defaults.update(fields)
    return RequestLog.objects.create(**defaults)


def _changelist_count(client: Client, params: dict[str, str]) -> int:
    client.force_login(UserFactory(is_staff=True))
    response = client.get(reverse("admin:analytics_requestlog_changelist"), params)
    assert response.status_code == HTTP_OK
    return response.context["cl"].result_count


def test_search_matches_a_path_by_its_beginning(client: Client) -> None:
    _row(path="/projects/abc/files/7/")
    _row(path="/projects/")

    assert _changelist_count(client, {"q": "/projects/abc/"}) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [("request_id", "a" * 32), ("client_ip", "203.0.113.9"), ("username", "ada")],
)
def test_search_matches_id_ip_and_username_exactly(
    client: Client, field: str, value: str
) -> None:
    _row(**{field: value})
    _row()

    assert _changelist_count(client, {"q": value}) == 1


def test_search_matches_an_ipv6_address_in_any_spelling(client: Client) -> None:
    _row(client_ip="2001:db8::1")

    assert _changelist_count(client, {"q": "2001:0db8:0:0:0:0:0:1"}) == 1


@pytest.mark.parametrize("term", ["ADA", "projects/abc", "not-an-ip", "ad"])
def test_search_is_never_a_substring_or_case_blind_match(
    client: Client, term: str
) -> None:
    """Every search must be one an index can answer (except the path prefix)."""
    _row(username="ada", path="/projects/abc/")

    assert _changelist_count(client, {"q": term}) == 0


def test_status_class_filter(client: Client) -> None:
    _row(status=404)
    _row(status=403)
    _row(status=200)

    assert _changelist_count(client, {"status_class": "4"}) == TWO_4XX_ROWS


def test_file_view_filter(client: Client) -> None:
    _row(view_name="projects:file_download")
    _row(view_name="projects:list")

    assert _changelist_count(client, {"file_view": "projects:file_download"}) == 1


@pytest.mark.parametrize("action", ["add", "change", "delete"])
def test_superuser_cannot_edit_the_log(client: Client, action: str) -> None:
    """The log is evidence; nobody adds, edits or deletes rows in the admin.

    The change page itself opens read-only, so the edit is a POST.
    """
    row = _row()
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    args = [] if action == "add" else [row.pk]
    url = reverse(f"admin:analytics_requestlog_{action}", args=args)

    response = client.post(url, {"path": "/edited/", "post": "yes"})

    assert response.status_code == HTTP_FORBIDDEN


def test_prune_deletes_only_rows_older_than_the_cutoff() -> None:
    old = _row()
    RequestLog.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - datetime.timedelta(days=400)
    )
    recent = _row()

    call_command("prune_request_logs", "--older-than", "365")

    assert list(RequestLog.objects.all()) == [recent]


def test_prune_requires_an_age() -> None:
    with pytest.raises(CommandError):
        call_command("prune_request_logs")
