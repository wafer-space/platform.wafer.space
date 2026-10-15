"""RequestLogMiddleware: who fetched what, from where, logged in or not (#379)."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.db import DatabaseError
from django.urls import reverse

from wafer_space.analytics.middleware import REQUEST_ID_HEADER
from wafer_space.analytics.models import RequestLog
from wafer_space.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from django.test import Client
    from pytest_django.fixtures import Settings

    from wafer_space.users.models import User

pytestmark = pytest.mark.django_db

NGINX_REQUEST_ID = "0123456789abcdef0123456789abcdef"
REQUEST_ID_LENGTH = 32
HTTP_OK = 200


@pytest.fixture
def user() -> User:
    return UserFactory()


@pytest.fixture
def logged_in(client: Client, user: User) -> Client:
    client.force_login(user)
    return client


def _file_download_url() -> str:
    return reverse("projects:file_download", kwargs={"pk": uuid.uuid4(), "file_pk": 7})


def test_logged_in_request_is_logged(logged_in: Client, user: User) -> None:
    logged_in.get(reverse("projects:list"))

    row = RequestLog.objects.get()
    assert (row.user, row.username, row.method, row.view_name, row.status) == (
        user,
        user.username,
        "GET",
        "projects:list",
        200,
    )


def test_username_snapshot_never_holds_the_email(
    logged_in: Client,
    user: User,
) -> None:
    logged_in.get(reverse("projects:list"))

    row = RequestLog.objects.get()
    assert user.email not in row.username


def test_path_has_no_query_string(logged_in: Client) -> None:
    logged_in.get(reverse("projects:list") + "?code=secret&state=abc")

    assert RequestLog.objects.get().path == reverse("projects:list")


def test_anonymous_page_view_is_not_logged(client: Client) -> None:
    client.get(reverse("home"))

    assert not RequestLog.objects.exists()


def test_anonymous_file_request_is_logged(client: Client) -> None:
    """A failed or redirected fetch of a file is still a fetch attempt."""
    url = _file_download_url()

    client.get(url)

    row = RequestLog.objects.get()
    assert (row.user, row.username, row.path, row.view_name, row.status) == (
        None,
        "",
        url,
        "projects:file_download",
        302,
    )


def test_route_kwargs_record_what_was_fetched(client: Client) -> None:
    project_pk = uuid.uuid4()
    url = reverse("projects:file_download", kwargs={"pk": project_pk, "file_pk": 7})

    client.get(url)

    assert RequestLog.objects.get().route_kwargs == {
        "pk": str(project_pk),
        "file_pk": 7,
    }


@pytest.mark.parametrize("path", ["/health/", "/static/css/project.css"])
def test_health_and_static_are_never_logged(logged_in: Client, path: str) -> None:
    logged_in.get(path)

    assert not RequestLog.objects.exists()


def test_request_log_admin_pages_are_not_logged(client: Client) -> None:
    """Reading the analytics must not add to them."""
    client.force_login(UserFactory(is_staff=True))

    client.get(reverse("admin:analytics_requestlog_changelist"))

    assert not RequestLog.objects.exists()


def test_client_ip_is_recorded(logged_in: Client) -> None:
    logged_in.get(reverse("projects:list"), REMOTE_ADDR="203.0.113.9")

    assert RequestLog.objects.get().client_ip == "203.0.113.9"


def test_user_agent_and_referrer_are_recorded_without_referrer_query(
    logged_in: Client,
) -> None:
    logged_in.get(
        reverse("projects:list"),
        HTTP_USER_AGENT="curl/8.5.0",
        HTTP_REFERER="https://platform.wafer.space/projects/?token=abc",
    )

    row = RequestLog.objects.get()
    assert (row.user_agent, row.referrer) == (
        "curl/8.5.0",
        "https://platform.wafer.space/projects/",
    )


def test_long_user_agent_is_truncated(logged_in: Client) -> None:
    logged_in.get(reverse("projects:list"), HTTP_USER_AGENT="x" * 5000)

    assert len(RequestLog.objects.get().user_agent) == RequestLog.USER_AGENT_LENGTH


def test_other_headers_and_the_body_are_not_stored(logged_in: Client) -> None:
    logged_in.post(
        reverse("projects:list"),
        data={"password": "body-secret"},
        HTTP_AUTHORIZATION="Bearer header-secret",
    )

    row = RequestLog.objects.values().get()
    stored = repr(row)
    assert ("body-secret" not in stored, "header-secret" not in stored) == (
        True,
        True,
    )


def test_bytes_and_duration_are_recorded(logged_in: Client) -> None:
    response = logged_in.get(reverse("projects:list"))

    row = RequestLog.objects.get()
    assert row.bytes == len(response.content)
    assert row.duration_ms >= 0


def test_trusted_request_id_from_nginx_is_kept_and_echoed(
    logged_in: Client,
    settings: Settings,
) -> None:
    settings.TRUST_X_REAL_IP = True

    response = logged_in.get(
        reverse("projects:list"), HTTP_X_REQUEST_ID=NGINX_REQUEST_ID
    )

    assert (RequestLog.objects.get().request_id, response[REQUEST_ID_HEADER]) == (
        NGINX_REQUEST_ID,
        NGINX_REQUEST_ID,
    )


def test_untrusted_request_id_is_replaced(logged_in: Client) -> None:
    """Without TRUST_X_REAL_IP the header could come from anyone."""
    response = logged_in.get(
        reverse("projects:list"), HTTP_X_REQUEST_ID=NGINX_REQUEST_ID
    )

    request_id = RequestLog.objects.get().request_id
    assert request_id != NGINX_REQUEST_ID
    assert len(request_id) == REQUEST_ID_LENGTH
    assert response[REQUEST_ID_HEADER] == request_id


def test_malformed_request_id_is_replaced(
    logged_in: Client,
    settings: Settings,
) -> None:
    settings.TRUST_X_REAL_IP = True

    logged_in.get(reverse("projects:list"), HTTP_X_REQUEST_ID="not-hex; DROP")

    request_id = RequestLog.objects.get().request_id
    assert request_id != "not-hex; DROP"
    assert len(request_id) == REQUEST_ID_LENGTH


def test_unlogged_request_still_gets_a_request_id(client: Client) -> None:
    response = client.get(reverse("home"))

    assert len(response[REQUEST_ID_HEADER]) == REQUEST_ID_LENGTH


def test_postgres_insert_does_not_wait_for_the_wal_flush(logged_in: Client) -> None:
    """On PostgreSQL the row's transaction commits without a WAL flush.

    Measured on PostgreSQL 17: a plain autocommit INSERT took ~9 ms, almost
    all of it the flush; with synchronous_commit off it took ~1.5 ms.
    """
    fake_connection = MagicMock(vendor="postgresql", in_atomic_block=False)
    cursor = fake_connection.cursor.return_value.__enter__.return_value

    with patch("wafer_space.analytics.middleware.connection", fake_connection):
        logged_in.get(reverse("projects:list"))

    cursor.execute.assert_called_once_with("SET LOCAL synchronous_commit TO OFF")


def test_database_error_is_logged_and_the_response_still_returned(
    logged_in: Client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch.object(
            RequestLog.objects,
            "create",
            side_effect=DatabaseError("relation does not exist"),
        ),
        caplog.at_level(logging.ERROR, logger="wafer_space.analytics"),
    ):
        response = logged_in.get(reverse("projects:list"))

    assert response.status_code == HTTP_OK
    assert [r.levelno for r in caplog.records] == [logging.ERROR]
