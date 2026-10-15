"""Download a check's saved artifacts behind the project permission (coord-10).

The runs archive, output layout and docker layer export used to be linked
at /media/, which nginx served to anyone holding the URL.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.db.models.fields.files import FieldFile
from django.urls import reverse

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.users.tests.factories import UserFactory

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_METHOD_NOT_ALLOWED
from .constants import HTTP_NOT_FOUND
from .constants import HTTP_OK
from .factories import ManufacturabilityCheckFactory
from .factories import ProjectFactory
from .factories import make_downloaded_file

if TYPE_CHECKING:
    from django.test import Client
    from pytest_django.fixtures import Settings

pytestmark = pytest.mark.django_db

# URL slug -> (FileField, bytes saved into it).
ARTIFACTS = {
    "runs-archive": ("runs_archive", b"runs tar"),
    "output-layout": ("output_gds", b"output oasis"),
    "docker-layer": ("docker_layer_export", b"layer tgz"),
}


def check_with_artifacts(**kwargs: object) -> ManufacturabilityCheck:
    """A finished check with every artifact saved."""
    check = ManufacturabilityCheckFactory(
        status=ManufacturabilityCheck.Status.FINISHED,
        is_manufacturable=True,
        **kwargs,
    )
    for field_name, content in ARTIFACTS.values():
        getattr(check, field_name).save("ignored", ContentFile(content), save=False)
    check.save()
    return check


def artifact_url(check: ManufacturabilityCheck, artifact: str) -> str:
    return reverse(
        "projects:check_artifact",
        kwargs={"pk": check.project_id, "check_id": check.pk, "artifact": artifact},
    )


def body(response) -> bytes:
    return b"".join(response.streaming_content)


@pytest.mark.parametrize("artifact", list(ARTIFACTS))
def test_owner_downloads_each_artifact(client: Client, artifact: str) -> None:
    check = check_with_artifacts()
    client.force_login(check.project.user)
    response = client.get(artifact_url(check, artifact))
    assert (response.status_code, body(response)) == (HTTP_OK, ARTIFACTS[artifact][1])


@pytest.mark.parametrize("artifact", list(ARTIFACTS))
def test_download_is_named_after_the_stored_file(client: Client, artifact: str) -> None:
    check = check_with_artifacts()
    client.force_login(check.project.user)
    response = client.get(artifact_url(check, artifact))
    stored_name = Path(getattr(check, ARTIFACTS[artifact][0]).name).name
    assert response["Content-Disposition"] == (f'attachment; filename="{stored_name}"')


def test_staff_downloads_other_users_artifact(client: Client) -> None:
    check = check_with_artifacts()
    client.force_login(UserFactory(is_staff=True))
    response = client.get(artifact_url(check, "output-layout"))
    assert body(response) == b"output oasis"


@pytest.mark.parametrize("artifact", list(ARTIFACTS))
def test_stranger_gets_403(client: Client, artifact: str) -> None:
    check = check_with_artifacts()
    client.force_login(UserFactory())
    assert client.get(artifact_url(check, artifact)).status_code == HTTP_FORBIDDEN


def test_anonymous_redirected_to_login(client: Client) -> None:
    check = check_with_artifacts()
    response = client.get(artifact_url(check, "output-layout"))
    assert (response.status_code, "/accounts/login/" in response["Location"]) == (
        HTTP_FOUND,
        True,
    )


def test_check_of_another_project_is_404(client: Client) -> None:
    """A check id is valid only under its own project (no cross-project read)."""
    check = check_with_artifacts()
    other = ProjectFactory(user=check.project.user)
    client.force_login(check.project.user)
    url = reverse(
        "projects:check_artifact",
        kwargs={"pk": other.pk, "check_id": check.pk, "artifact": "output-layout"},
    )
    assert client.get(url).status_code == HTTP_NOT_FOUND


def test_unknown_artifact_is_404(client: Client) -> None:
    check = check_with_artifacts()
    client.force_login(check.project.user)
    assert client.get(artifact_url(check, "log-file")).status_code == HTTP_NOT_FOUND


def test_artifact_not_saved_is_404(client: Client) -> None:
    check = ManufacturabilityCheckFactory()
    client.force_login(check.project.user)
    response = client.get(artifact_url(check, "runs-archive"))
    assert response.status_code == HTTP_NOT_FOUND


def test_artifact_gone_from_disk_is_404(client: Client) -> None:
    check = check_with_artifacts()
    check.output_gds.storage.delete(check.output_gds.name)
    client.force_login(check.project.user)
    response = client.get(artifact_url(check, "output-layout"))
    assert response.status_code == HTTP_NOT_FOUND


def test_archived_project_keeps_its_downloads(client: Client) -> None:
    check = check_with_artifacts()
    check.project.archive()
    client.force_login(check.project.user)
    response = client.get(artifact_url(check, "runs-archive"))
    assert response.status_code == HTTP_OK


def test_post_is_not_allowed(client: Client) -> None:
    check = check_with_artifacts()
    client.force_login(check.project.user)
    response = client.post(artifact_url(check, "runs-archive"))
    assert response.status_code == HTTP_METHOD_NOT_ALLOWED


def test_behind_nginx_answers_with_x_accel_redirect(
    client: Client, settings: Settings
) -> None:
    settings.MEDIA_X_ACCEL_REDIRECT_PREFIX = "/protected-media/"
    check = check_with_artifacts()
    client.force_login(check.project.user)
    response = client.get(artifact_url(check, "output-layout"))
    assert response["X-Accel-Redirect"] == ("/protected-media/" + check.output_gds.name)


class TestProjectPage:
    """The project page links artifacts through the view, never MEDIA_URL."""

    @pytest.fixture
    def page(self, client: Client) -> tuple[ManufacturabilityCheck, str]:
        project = ProjectFactory()
        check = check_with_artifacts(
            project=project, project_file=make_downloaded_file(project)
        )
        client.force_login(project.user)
        response = client.get(check.project.get_absolute_url(), follow=True)
        return check, response.content.decode()

    @pytest.mark.parametrize("artifact", list(ARTIFACTS))
    def test_links_each_artifact_through_the_view(
        self, page: tuple[ManufacturabilityCheck, str], artifact: str
    ) -> None:
        check, content = page
        assert artifact_url(check, artifact) in content

    def test_no_media_url_anywhere(
        self, page: tuple[ManufacturabilityCheck, str]
    ) -> None:
        _, content = page
        assert settings.MEDIA_URL not in content


# Missing files (D-media-rebase): a stale row is a 404, never a 500.
# ------------------------------------------------------------------------------


def _break_into_dangling_symlink(field_file) -> None:
    """Replace the stored file with a symlink whose target does not exist."""
    stored = Path(field_file.path)
    stored.unlink()
    stored.symlink_to(stored.with_name("target-that-is-gone"))


def test_artifact_that_is_a_dangling_symlink_is_404(client: Client) -> None:
    """storage.exists() is os.path.lexists, so a dangling symlink once passed."""
    check = check_with_artifacts()
    _break_into_dangling_symlink(check.output_gds)
    client.force_login(check.project.user)

    response = client.get(artifact_url(check, "output-layout"))

    assert response.status_code == HTTP_NOT_FOUND


@pytest.mark.parametrize("breakage", ["deleted", "dangling-symlink"])
def test_behind_nginx_a_missing_artifact_is_404_without_x_accel(
    client: Client, settings: Settings, breakage: str
) -> None:
    """Django answers 404 itself; nginx is never sent a path to a missing file."""
    settings.MEDIA_X_ACCEL_REDIRECT_PREFIX = "/protected-media/"
    check = check_with_artifacts()
    if breakage == "deleted":
        check.output_gds.storage.delete(check.output_gds.name)
    else:
        _break_into_dangling_symlink(check.output_gds)
    client.force_login(check.project.user)

    response = client.get(artifact_url(check, "output-layout"))

    assert (response.status_code, response.has_header("X-Accel-Redirect")) == (
        HTTP_NOT_FOUND,
        False,
    )


def test_artifact_removed_between_check_and_open_is_404(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file vanishing after the presence check is still a 404."""
    check = check_with_artifacts()
    client.force_login(check.project.user)

    def open_after_it_vanished(self, mode: str = "rb"):
        raise FileNotFoundError(self.name)

    monkeypatch.setattr(FieldFile, "open", open_after_it_vanished)

    response = client.get(artifact_url(check, "output-layout"))

    assert response.status_code == HTTP_NOT_FOUND


def test_unreadable_artifact_fails_loudly(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a missing file is a 404: a permission problem is a real error."""
    check = check_with_artifacts()
    client.force_login(check.project.user)

    def size_denied(self, name: str) -> int:
        raise PermissionError(name)

    monkeypatch.setattr(FileSystemStorage, "size", size_denied)

    with pytest.raises(PermissionError):
        client.get(artifact_url(check, "output-layout"))
