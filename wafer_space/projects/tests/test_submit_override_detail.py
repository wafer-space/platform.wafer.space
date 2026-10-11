"""Staff override for Submit for Manufacturing: project page (issue #252)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from wafer_space.users.tests.factories import UserFactory

from .test_models_submit_override import REASON
from .test_models_submit_override import make_failed_project

if TYPE_CHECKING:
    from django.test import Client

    from wafer_space.projects.models import Project

pytestmark = pytest.mark.django_db

OVERRIDE_BUTTON = "Submit anyway (staff override)"


def page(client: Client, user, project: Project) -> str:
    client.force_login(user)
    return client.get(project.get_absolute_url()).content.decode()


def test_staff_see_override_form(client: Client) -> None:
    project = make_failed_project()
    content = page(client, UserFactory(is_staff=True), project)
    assert OVERRIDE_BUTTON in content
    assert reverse("projects:submit_override", args=[project.pk]) in content


def test_owner_does_not_see_override_form(client: Client) -> None:
    project = make_failed_project()
    content = page(client, project.user, project)
    assert OVERRIDE_BUTTON not in content


def test_no_override_form_when_normal_submit_works(client: Client) -> None:
    project = make_failed_project(passed=True)
    content = page(client, UserFactory(is_staff=True), project)
    assert OVERRIDE_BUTTON not in content


def test_owner_sees_override_banner(client: Client) -> None:
    project = make_failed_project()
    staff = UserFactory(is_staff=True, username="overrider")
    project.override_submit(staff, REASON)
    content = page(client, project.user, project)
    assert "data-submission-override-banner" in content
    assert "Submitted by staff override" in content
    assert "overrider" in content
    assert REASON in content


def test_no_banner_for_normal_submission(client: Client) -> None:
    project = make_failed_project(passed=True)
    project.submit()
    content = page(client, project.user, project)
    assert "data-submission-override-banner" not in content
