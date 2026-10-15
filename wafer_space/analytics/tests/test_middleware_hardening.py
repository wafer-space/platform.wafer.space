"""RequestLogMiddleware with hostile or unusual requests (#379 review)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from wafer_space.analytics.middleware import REDACTED
from wafer_space.analytics.models import RequestLog
from wafer_space.legal.tests.factories import TermsOfServiceFactory
from wafer_space.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from wafer_space.users.models import User

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_NOT_FOUND = 404
HTTP_SERVER_ERROR = 500
CONFIRM_KEY = "MQ:1tSecretKeyValue:abcdef"


@pytest.fixture
def user() -> User:
    return UserFactory()


@pytest.fixture
def logged_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


def test_malformed_referer_does_not_break_the_page(logged_in: Client) -> None:
    response = logged_in.get(reverse("projects:list"), HTTP_REFERER="http://[bad/x")

    assert response.status_code == HTTP_OK
    assert RequestLog.objects.get().referrer == ""


def test_referer_credentials_are_dropped(logged_in: Client) -> None:
    logged_in.get(
        reverse("projects:list"),
        HTTP_REFERER="https://user:secret@example.com:8443/page?x=1#frag",
    )

    assert RequestLog.objects.get().referrer == "https://example.com:8443/page"


def test_long_method_is_truncated(logged_in: Client) -> None:
    logged_in.generic("VERSION-CONTROL", reverse("projects:list"))

    assert RequestLog.objects.get().method == "VERSION-CO"


def test_nul_is_stripped_from_stored_text(logged_in: Client) -> None:
    """PostgreSQL rejects NUL in text and jsonb; the row must still be written."""
    logged_in.get("/no-such-page/%00x/", HTTP_USER_AGENT="agent\x00x")

    row = RequestLog.objects.get()
    assert (row.path, row.user_agent) == ("/no-such-page/x/", "agentx")


def test_email_confirmation_key_is_not_stored(logged_in: Client) -> None:
    logged_in.get(reverse("account_confirm_email", kwargs={"key": CONFIRM_KEY}))

    row = RequestLog.objects.values().get()
    assert CONFIRM_KEY not in repr(row)
    assert row["route_kwargs"] == {"key": REDACTED}


def test_password_reset_key_is_not_stored(logged_in: Client) -> None:
    url = reverse(
        "account_reset_password_from_key",
        kwargs={"uidb36": "4c", "key": "set-password-token-abc"},
    )

    logged_in.get(url)

    row = RequestLog.objects.values().get()
    assert "set-password-token-abc" not in repr(row)
    assert row["route_kwargs"] == {"uidb36": REDACTED, "key": REDACTED}


def test_referer_from_a_secret_page_is_redacted(logged_in: Client) -> None:
    secret_page = reverse("account_confirm_email", kwargs={"key": CONFIRM_KEY})

    logged_in.get(
        reverse("projects:list"),
        HTTP_REFERER=f"https://platform.wafer.space{secret_page}",
    )

    assert CONFIRM_KEY not in RequestLog.objects.get().referrer


def test_file_fetch_redirected_to_tos_keeps_its_view_name(logged_in: Client) -> None:
    """The ToS middleware answers before URL resolution; the row still says
    which file was asked for."""
    TermsOfServiceFactory(is_active=True)
    project_pk = uuid.uuid4()
    url = reverse("projects:file_download", kwargs={"pk": project_pk, "file_pk": 7})

    logged_in.get(url)

    row = RequestLog.objects.get()
    assert (row.view_name, row.route_kwargs) == (
        "projects:file_download",
        {"pk": str(project_pk), "file_pk": 7},
    )


def test_logged_in_404_is_logged_without_a_view_name(logged_in: Client) -> None:
    logged_in.get("/no-such-page/")

    row = RequestLog.objects.get()
    assert (row.status, row.view_name) == (HTTP_NOT_FOUND, "")


def test_view_error_is_still_logged(user: User) -> None:
    client = Client(raise_request_exception=False)
    client.force_login(user)

    with patch(
        "wafer_space.projects.views.ProjectListView.get",
        side_effect=RuntimeError("boom"),
    ):
        client.get(reverse("projects:list"))

    assert RequestLog.objects.get().status == HTTP_SERVER_ERROR


def test_no_commit_setting_change_inside_an_outer_transaction(
    logged_in: Client,
) -> None:
    """SET LOCAL would apply to the whole outer transaction, so skip it."""
    fake_connection = MagicMock(vendor="postgresql", in_atomic_block=True)
    cursor = fake_connection.cursor.return_value.__enter__.return_value

    with patch("wafer_space.analytics.middleware.connection", fake_connection):
        logged_in.get(reverse("projects:list"))

    cursor.execute.assert_not_called()
