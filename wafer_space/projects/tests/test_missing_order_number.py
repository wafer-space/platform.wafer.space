"""Warn, never block, when submitting without a CrowdSupply order number (#348)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escapejs

from wafer_space.projects.models import MISSING_ORDER_NUMBER_WARNING
from wafer_space.projects.models import Project
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

from .factories import ProjectFactory
from .html_elements import parse_html
from .test_models_submit_override import REASON
from .test_models_submit_override import add_checked_revision
from .test_models_submit_override import make_failed_project

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

ORDER_NUMBER = "327373"
# The confirm() text is a JS string literal, so the warning is JS-escaped there
WARNING_IN_DIALOG = escapejs(MISSING_ORDER_NUMBER_WARNING)


def make_submittable_project(**kwargs: object) -> Project:
    """A project whose latest revision passed its precheck."""
    project = ProjectFactory(**kwargs)
    add_checked_revision(project, passed=True)
    return Project.objects.get(pk=project.pk)


def warning_banners(response) -> int:
    """How many missing-order-number banners the page renders."""
    return sum(
        1
        for _, attrs in parse_html(response.content.decode()).elements
        if "data-missing-order-number" in attrs
    )


def submit_confirm_text(response) -> str:
    """The confirm() text on the Submit for Manufacturing form."""
    submit_url = reverse("projects:submit", args=[response.context["project"].pk])
    for tag, attrs in parse_html(response.content.decode()).elements:
        if tag == "form" and attrs.get("action") == submit_url:
            return attrs["onsubmit"] or ""
    msg = "no Submit for Manufacturing form on the page"
    raise AssertionError(msg)


class TestWarningProperty:
    def test_warns_without_order_number(self) -> None:
        project = ProjectFactory(crowd_supply_order_id="")
        assert project.missing_order_number_warning == MISSING_ORDER_NUMBER_WARNING

    def test_silent_with_order_number(self) -> None:
        project = ProjectFactory(crowd_supply_order_id=ORDER_NUMBER)
        assert project.missing_order_number_warning == ""

    def test_silent_on_test_only_shuttle(self) -> None:
        """Designs on a test-only shuttle are never manufactured (#221)."""
        shuttle = Shuttle.objects.create(
            name="G896",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
            is_test_only=True,
        )
        project = ProjectFactory(shuttle=shuttle, crowd_supply_order_id="")
        assert project.missing_order_number_warning == ""


class TestSubmitView:
    def _submit(self, client: Client, project: Project):
        client.force_login(project.user)
        return client.post(reverse("projects:submit", args=[project.pk]), follow=True)

    def test_submits_and_warns_without_order_number(self, client: Client) -> None:
        """A warning, not a block: the revision is still submitted."""
        project = make_submittable_project(crowd_supply_order_id="")
        response = self._submit(client, project)
        project.refresh_from_db()
        messages = [str(m) for m in response.context["messages"]]
        assert project.submitted_file is not None
        assert MISSING_ORDER_NUMBER_WARNING in messages

    def test_no_warning_with_order_number(self, client: Client) -> None:
        project = make_submittable_project(crowd_supply_order_id=ORDER_NUMBER)
        response = self._submit(client, project)
        messages = [str(m) for m in response.context["messages"]]
        assert MISSING_ORDER_NUMBER_WARNING not in messages


def test_staff_override_warns_without_order_number(client: Client) -> None:
    project = make_failed_project()
    client.force_login(UserFactory(is_staff=True))
    response = client.post(
        reverse("projects:submit_override", args=[project.pk]),
        {"reason": REASON},
        follow=True,
    )
    project.refresh_from_db()
    messages = [str(m) for m in response.context["messages"]]
    assert project.submitted_file is not None
    assert MISSING_ORDER_NUMBER_WARNING in messages


class TestProjectPage:
    def _detail(self, client: Client, project: Project):
        client.force_login(project.user)
        return client.get(project.get_absolute_url())

    def test_submittable_project_shows_warning_before_submitting(
        self, client: Client
    ) -> None:
        project = make_submittable_project(crowd_supply_order_id="")
        response = self._detail(client, project)
        assert warning_banners(response) == 1
        assert WARNING_IN_DIALOG in submit_confirm_text(response)

    def test_no_warning_with_order_number(self, client: Client) -> None:
        project = make_submittable_project(crowd_supply_order_id=ORDER_NUMBER)
        response = self._detail(client, project)
        assert warning_banners(response) == 0
        assert WARNING_IN_DIALOG not in submit_confirm_text(response)

    def test_not_yet_submittable_project_shows_no_warning(self, client: Client) -> None:
        """Nothing to warn about until the Submit button can be used."""
        project = ProjectFactory(crowd_supply_order_id="")
        add_checked_revision(project, passed=False)
        assert warning_banners(self._detail(client, project)) == 0

    def test_submitted_project_shows_warning_once(self, client: Client) -> None:
        """After submitting, the Submitted card carries the one warning."""
        project = make_submittable_project(crowd_supply_order_id="")
        project.submit()
        add_checked_revision(project, passed=True)
        project = Project.objects.get(pk=project.pk)
        assert warning_banners(self._detail(client, project)) == 1


def test_test_only_shuttle_submit_gives_no_warning(client: Client) -> None:
    """A test-only shuttle never manufactures, so no order is needed (#221)."""
    shuttle = Shuttle.objects.create(
        name="G895",
        description="Test shuttle",
        status=Shuttle.Status.OPEN,
        is_test_only=True,
    )
    project = make_submittable_project(shuttle=shuttle, crowd_supply_order_id="")
    client.force_login(project.user)
    response = client.post(reverse("projects:submit", args=[project.pk]), follow=True)
    messages = [str(m) for m in response.context["messages"]]
    project.refresh_from_db()
    assert project.submitted_file is not None
    assert MISSING_ORDER_NUMBER_WARNING not in messages
    assert warning_banners(response) == 0


def test_staff_override_card_shows_warning(client: Client) -> None:
    """Staff who can only override still see the warning before submitting."""
    project = make_failed_project()
    client.force_login(UserFactory(is_staff=True))
    assert warning_banners(client.get(project.get_absolute_url())) == 1


def test_archived_submitted_project_hides_edit_link(client: Client) -> None:
    """Archived projects are read-only, so the warning offers no Edit link."""
    project = make_submittable_project(crowd_supply_order_id="")
    project.submit()
    Project.objects.filter(pk=project.pk).update(archived_at=timezone.now())
    client.force_login(project.user)
    response = client.get(project.get_absolute_url())
    edit_url = reverse("projects:update", args=[project.pk])
    links = [
        attrs.get("href")
        for tag, attrs in parse_html(response.content.decode()).elements
        if tag == "a" and "alert-link" in (attrs.get("class") or "")
    ]
    assert warning_banners(response) == 1
    assert edit_url not in links
