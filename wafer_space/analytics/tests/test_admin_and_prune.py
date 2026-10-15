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


def test_staff_can_search_the_log_by_path(client: Client) -> None:
    _row(path="/projects/abc/files/7/")
    _row(path="/projects/")
    client.force_login(UserFactory(is_staff=True))

    response = client.get(
        reverse("admin:analytics_requestlog_changelist"), {"q": "/files/7/"}
    )

    assert response.status_code == HTTP_OK
    assert response.context["cl"].result_count == 1


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
