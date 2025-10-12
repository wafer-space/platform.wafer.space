"""Tests for TOS acceptance middleware."""

from http import HTTPStatus

import pytest
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from wafer_space.legal.middleware import TOSAcceptanceMiddleware
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.users.tests.factories import UserFactory

from .factories import TermsOfServiceAcceptanceFactory
from .factories import TermsOfServiceFactory


@pytest.fixture
def middleware():
    """Create middleware instance."""

    def get_response(request):
        return HttpResponse("OK")

    return TOSAcceptanceMiddleware(get_response)


@pytest.fixture
def rf():
    """Request factory fixture."""
    return RequestFactory()


@pytest.mark.django_db
class TestTOSAcceptanceMiddleware:
    """Tests for TOSAcceptanceMiddleware."""

    def test_anonymous_user_not_redirected(self, middleware, rf):
        """Test that anonymous users are not redirected."""
        request = rf.get("/")
        request.user = AnonymousUser()
        request.session = {}

        response = middleware(request)

        assert response.status_code == HTTPStatus.OK
        assert response.content == b"OK"

    def test_superuser_bypasses_tos_check(self, middleware, rf):
        """Test that superusers bypass TOS check."""
        user = UserFactory(is_superuser=True)
        request = rf.get("/")
        request.user = user
        request.session = {}

        # Create active TOS that user hasn't accepted
        TermsOfServiceFactory(is_active=True)

        response = middleware(request)

        assert response.status_code == HTTPStatus.OK
        assert response.content == b"OK"

    def test_exempt_urls_not_redirected(self, middleware, rf):
        """Test that exempt URLs are not redirected."""
        user = UserFactory()
        TermsOfServiceFactory(is_active=True)

        exempt_urls = [
            "/accounts/login/",
            "/accounts/logout/",
            "/accounts/signup/",
            "/legal/tos/",
            "/legal/tos/accept/",
            "/admin/",
            "/static/css/style.css",
            "/media/uploads/file.pdf",
        ]

        for url in exempt_urls:
            request = rf.get(url)
            request.user = user
            request.session = {}

            response = middleware(request)

            assert response.status_code == HTTPStatus.OK, f"Failed for {url}"

    def test_user_without_acceptance_should_not_have_accepted(self):
        """Test that user without TOS acceptance returns False.

        The has_accepted_active method should return False for users who have
        not accepted the active TOS version.
        """
        user = UserFactory()
        TermsOfServiceFactory(is_active=True)

        # User has not accepted, should return False
        assert not TermsOfServiceAcceptance.has_accepted_active(user)

    def test_user_with_acceptance_allowed(self, middleware, rf):
        """Test that user with TOS acceptance is allowed through."""
        user = UserFactory()
        active_tos = TermsOfServiceFactory(is_active=True)
        TermsOfServiceAcceptanceFactory(user=user, tos_version=active_tos)

        request = rf.get("/dashboard/")
        request.user = user
        request.session = {}

        response = middleware(request)

        assert response.status_code == HTTPStatus.OK
        assert response.content == b"OK"

    def test_no_active_tos_allowed_through(self, middleware, rf):
        """Test that users are allowed through when no TOS is active."""
        user = UserFactory()
        # Create inactive TOS
        TermsOfServiceFactory(is_active=False)

        request = rf.get("/dashboard/")
        request.user = user
        request.session = {}

        response = middleware(request)

        assert response.status_code == HTTPStatus.OK
        assert response.content == b"OK"

    def test_user_on_tos_accept_page_not_redirected(self, middleware, rf):
        """Test that user on TOS accept page is not redirected again."""
        user = UserFactory()
        TermsOfServiceFactory(is_active=True)

        request = rf.get(reverse("legal:tos_accept"))
        request.user = user
        request.session = {}

        response = middleware(request)

        assert response.status_code == HTTPStatus.OK

    def test_old_acceptance_not_valid_for_new_version(self):
        """Test that acceptance of old TOS version doesn't count for new version."""
        user = UserFactory()

        # User accepted old version
        old_tos = TermsOfServiceFactory(version="1.0.0", is_active=False)
        TermsOfServiceAcceptanceFactory(user=user, tos_version=old_tos)

        # New version is now active
        TermsOfServiceFactory(version="2.0.0", is_active=True)

        # User should not have accepted the new active version
        assert not TermsOfServiceAcceptance.has_accepted_active(user)
