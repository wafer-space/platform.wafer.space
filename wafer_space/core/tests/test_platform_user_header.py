"""Tests for PlatformUserHeaderMiddleware (issue #379).

Authenticated responses carry the user's primary key in ``X-Platform-User``
so the nginx and gunicorn access logs can record which account made a
request; nginx strips the header before the client sees it
(hetzner-ansible #165). Anonymous responses never carry it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import HttpRequest
from django.http import HttpResponse
from django.test import Client
from django.test import RequestFactory
from django.urls import reverse

from wafer_space.core.middleware import PLATFORM_USER_HEADER
from wafer_space.core.middleware import PlatformUserHeaderMiddleware
from wafer_space.legal.tests.factories import TermsOfServiceFactory
from wafer_space.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from wafer_space.users.models import User

MIDDLEWARE_PATH = "wafer_space.core.middleware.PlatformUserHeaderMiddleware"


def test_registered_right_after_authentication() -> None:
    """It needs request.user, and wraps every later middleware's response."""
    auth = settings.MIDDLEWARE.index(
        "django.contrib.auth.middleware.AuthenticationMiddleware",
    )
    assert settings.MIDDLEWARE[auth + 1] == MIDDLEWARE_PATH


@pytest.mark.django_db
def test_authenticated_response_carries_the_user_pk(client: Client) -> None:
    user = UserFactory()
    client.force_login(user)

    response = client.get("/")

    assert response.headers[PLATFORM_USER_HEADER] == str(user.pk)


@pytest.mark.django_db
def test_anonymous_response_has_no_header(client: Client) -> None:
    response = client.get("/")

    assert PLATFORM_USER_HEADER not in response.headers


@pytest.mark.django_db
def test_terms_redirect_carries_the_user_pk(client: Client) -> None:
    """A later middleware's short-circuit response is wrapped too."""
    TermsOfServiceFactory(is_active=True)
    user = UserFactory()
    client.force_login(user)

    response = client.get(reverse("projects:list"))

    assert (
        response.headers["Location"],
        response.headers[PLATFORM_USER_HEADER],
    ) == (
        reverse("legal:tos_accept"),
        str(user.pk),
    )


def _run(
    request: HttpRequest,
    *,
    user_after_view: User | AnonymousUser,
) -> HttpResponse:
    """Run the middleware around a view that leaves ``user_after_view``."""

    def view(req: HttpRequest) -> HttpResponse:
        req.user = user_after_view
        return HttpResponse()

    return PlatformUserHeaderMiddleware(view)(request)


@pytest.mark.django_db
def test_login_response_carries_the_new_user() -> None:
    """The user is read at response time, so a login is attributed."""
    request = RequestFactory().post("/accounts/login/")
    request.user = AnonymousUser()
    user = UserFactory()

    response = _run(request, user_after_view=user)

    assert response.headers[PLATFORM_USER_HEADER] == str(user.pk)


@pytest.mark.django_db
def test_logout_response_has_no_header() -> None:
    request = RequestFactory().post("/accounts/logout/")
    request.user = UserFactory()

    response = _run(request, user_after_view=AnonymousUser())

    assert PLATFORM_USER_HEADER not in response.headers
