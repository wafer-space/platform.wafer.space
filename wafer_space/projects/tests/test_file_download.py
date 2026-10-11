"""Download the stored input layout of a file revision (issue #254)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from wafer_space.users.tests.factories import UserFactory

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_NOT_FOUND
from .constants import HTTP_OK
from .factories import ProjectFactory
from .factories import ProjectFileFactory

if TYPE_CHECKING:
    from django.test import Client
    from pytest_django.fixtures import SettingsWrapper

    from wafer_space.projects.models import ProjectFile

pytestmark = pytest.mark.django_db

CONTENT = b"GDSII stand-in bytes"


def stored_revision(**kwargs: object) -> ProjectFile:
    """A revision whose layout is stored on the platform."""
    revision = ProjectFileFactory(original_filename="chip_top.gds", **kwargs)
    revision.file.save("chip_top.gds", ContentFile(CONTENT), save=True)
    return revision


def download_url(revision: ProjectFile) -> str:
    return reverse(
        "projects:file_download",
        args=[revision.project.pk, revision.pk],
    )


def body(response) -> bytes:
    return b"".join(response.streaming_content)


def test_url_matches_reticle_package_link() -> None:
    """check_results.csv already writes /projects/<id>/files/<pk>/."""
    revision = stored_revision()
    assert download_url(revision) == (
        f"/projects/{revision.project.pk}/files/{revision.pk}/"
    )


def test_owner_downloads_stored_file(client: Client) -> None:
    revision = stored_revision()
    client.force_login(revision.project.user)
    response = client.get(download_url(revision))
    assert response.status_code == HTTP_OK
    assert body(response) == CONTENT
    assert response["Content-Disposition"] == ('attachment; filename="chip_top.gds"')


def test_staff_downloads_other_users_file(client: Client) -> None:
    revision = stored_revision()
    client.force_login(UserFactory(is_staff=True))
    response = client.get(download_url(revision))
    assert body(response) == CONTENT


def test_stranger_gets_403(client: Client) -> None:
    revision = stored_revision()
    client.force_login(UserFactory())
    assert client.get(download_url(revision)).status_code == HTTP_FORBIDDEN


def test_anonymous_redirected_to_login(client: Client) -> None:
    revision = stored_revision()
    response = client.get(download_url(revision))
    assert response.status_code == HTTP_FOUND
    assert "/accounts/login/" in response["Location"]


def test_revision_without_stored_file_is_404(client: Client) -> None:
    revision = ProjectFileFactory(file=None)
    client.force_login(revision.project.user)
    assert client.get(download_url(revision)).status_code == HTTP_NOT_FOUND


def test_stored_file_missing_on_disk_is_404(client: Client) -> None:
    revision = stored_revision()
    revision.file.storage.delete(revision.file.name)
    client.force_login(revision.project.user)
    assert client.get(download_url(revision)).status_code == HTTP_NOT_FOUND


def test_revision_of_another_project_is_404(client: Client) -> None:
    revision = stored_revision()
    other = ProjectFactory(user=revision.project.user)
    client.force_login(revision.project.user)
    url = reverse("projects:file_download", args=[other.pk, revision.pk])
    assert client.get(url).status_code == HTTP_NOT_FOUND


def test_project_page_links_stored_file(client: Client) -> None:
    revision = stored_revision(is_active=True)
    client.force_login(revision.project.user)
    detail = revision.project.get_absolute_url()
    content = client.get(detail).content.decode()
    assert download_url(revision) in content


def test_project_page_has_no_link_without_stored_file(client: Client) -> None:
    revision = ProjectFileFactory(file=None, is_active=True)
    client.force_login(revision.project.user)
    detail = revision.project.get_absolute_url()
    content = client.get(detail).content.decode()
    assert download_url(revision) not in content


def test_extracted_archive_downloads_under_processed_name(client: Client) -> None:
    """A .gz source is stored extracted; the name must match the content."""
    revision = ProjectFileFactory(
        original_filename="chip_top.gds.gz",
        processed_filename="chip_top.gds",
    )
    revision.file.save("chip_top.gds", ContentFile(CONTENT), save=True)
    client.force_login(revision.project.user)
    response = client.get(download_url(revision))
    assert response["Content-Disposition"] == ('attachment; filename="chip_top.gds"')


def test_behind_nginx_answers_with_x_accel_redirect(
    client: Client, settings: SettingsWrapper
) -> None:
    """Deployed, nginx sends the layout; gunicorn does not stream it (coord-10)."""
    settings.MEDIA_X_ACCEL_REDIRECT_PREFIX = "/protected-media/"
    revision = stored_revision()
    client.force_login(revision.project.user)
    response = client.get(download_url(revision))
    assert (response["X-Accel-Redirect"], response.content) == (
        "/protected-media/" + revision.file.name,
        b"",
    )


def test_behind_nginx_stranger_still_gets_403(
    client: Client, settings: SettingsWrapper
) -> None:
    settings.MEDIA_X_ACCEL_REDIRECT_PREFIX = "/protected-media/"
    revision = stored_revision()
    client.force_login(UserFactory())
    response = client.get(download_url(revision))
    assert (response.status_code, response.has_header("X-Accel-Redirect")) == (
        HTTP_FORBIDDEN,
        False,
    )
