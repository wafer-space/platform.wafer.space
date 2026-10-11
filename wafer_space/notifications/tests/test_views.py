"""Opening a notification goes to the page it is about (#150)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import reverse

from wafer_space.notifications.models import Notification
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.projects.tests.factories import ProjectFileFactory
from wafer_space.shuttles.models import Shuttle

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

HTTP_FOUND = 302


def open_notification(client: Client, notification: Notification) -> str:
    client.force_login(notification.user)
    response = client.get(reverse("notifications:mark_read", args=[notification.pk]))
    assert response.status_code == HTTP_FOUND
    return response["Location"]


def test_file_notification_goes_to_canonical_project_page(client: Client) -> None:
    shuttle = Shuttle.objects.create(
        name="G886", description="Open run", status=Shuttle.Status.OPEN
    )
    project = ProjectFactory(shuttle=shuttle)
    notification = Notification.objects.create(
        user=project.user,
        notification_type=Notification.Type.DOWNLOAD_COMPLETE,
        title="Download complete",
        message="Your file is ready.",
        content_object=ProjectFileFactory(project=project),
    )

    assert open_notification(client, notification) == f"/projects/{project.full_id}/"


def test_notification_without_object_goes_to_list(client: Client) -> None:
    notification = Notification.objects.create(
        user=ProjectFactory().user,
        notification_type=Notification.Type.TOS_UPDATE,
        title="Terms updated",
        message="Please review the new terms.",
    )

    assert open_notification(client, notification) == reverse("notifications:list")
