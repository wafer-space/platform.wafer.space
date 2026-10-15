"""The project page renders when a check's saved artifact is gone (#378).

A check row can name an artifact file that is no longer on disk: a manual
clean-up, a restore that copied the database but not every media file, or
a failed partial save. The check partial used to call ``FieldFile.size`` on
each artifact, which raises ``FileNotFoundError`` for a missing file, so the
whole project page returned 500.
"""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.projects.tests.factories import make_downloaded_file

if TYPE_CHECKING:
    from django.test import Client

ARTIFACT_FIELDS = ["log_file", "runs_archive", "output_gds", "docker_layer_export"]
ARTIFACT_BYTES = b"x" * 2048


def _finished_check_with_artifact(field: str) -> ManufacturabilityCheck:
    """A finished check on the active file whose ``field`` holds a saved file."""
    project = ProjectFactory()
    check = ManufacturabilityCheckFactory(
        project=project,
        project_file=make_downloaded_file(project),
        status=ManufacturabilityCheck.Status.FINISHED,
    )
    getattr(check, field).save(f"{field}.bin", ContentFile(ARTIFACT_BYTES))
    return check


def _project_page(client: Client, check: ManufacturabilityCheck) -> str:
    """Fetch the owner's project page and return its HTML, asserting 200."""
    client.force_login(check.project.user)
    response = client.get(check.project.get_absolute_url(), follow=True)
    assert response.status_code == HTTPStatus.OK
    return response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("field", ARTIFACT_FIELDS)
def test_page_renders_when_artifact_file_is_missing(client: Client, field: str):
    """A missing artifact file leaves the page at 200 and says it is missing."""
    check = _finished_check_with_artifact(field)
    artifact = getattr(check, field)
    artifact.storage.delete(artifact.name)
    assert not artifact.storage.exists(artifact.name)

    content = _project_page(client, check)

    assert f'data-artifact-missing="{field}"' in content


@pytest.mark.django_db
@pytest.mark.parametrize("field", ARTIFACT_FIELDS)
def test_present_artifact_shows_its_size(client: Client, field: str):
    """A file that is on disk still shows its size and no missing marker."""
    check = _finished_check_with_artifact(field)

    content = _project_page(client, check)

    assert "2.0\xa0KB" in content
    assert f'data-artifact-missing="{field}"' not in content


# FileField -> check_artifact URL slug (links never use MEDIA_URL).
DOWNLOAD_FIELDS = {
    "runs_archive": "runs-archive",
    "output_gds": "output-layout",
    "docker_layer_export": "docker-layer",
}


def _download_url(check: ManufacturabilityCheck, field: str) -> str:
    """The permission-checked download URL the page links to."""
    return reverse(
        "projects:check_artifact",
        kwargs={
            "pk": check.project_id,
            "check_id": check.pk,
            "artifact": DOWNLOAD_FIELDS[field],
        },
    )


@pytest.mark.django_db
@pytest.mark.parametrize("field", list(DOWNLOAD_FIELDS))
def test_missing_artifact_is_not_offered_as_a_download(client: Client, field: str):
    """A download link to a file that is gone would only 404, so none is shown."""
    check = _finished_check_with_artifact(field)
    artifact = getattr(check, field)
    url = _download_url(check, field)
    artifact.storage.delete(artifact.name)

    content = _project_page(client, check)

    assert url not in content


@pytest.mark.django_db
@pytest.mark.parametrize("field", list(DOWNLOAD_FIELDS))
def test_present_artifact_is_offered_as_a_download(client: Client, field: str):
    """A file on disk keeps its download link."""
    check = _finished_check_with_artifact(field)

    content = _project_page(client, check)

    assert _download_url(check, field) in content


@pytest.mark.django_db
def test_missing_artifact_on_an_older_check_in_history(client: Client):
    """A missing file on a history card, not the latest check, still renders."""
    older = _finished_check_with_artifact("runs_archive")
    ManufacturabilityCheck.objects.filter(pk=older.pk).update(
        created_at=timezone.now() - timedelta(hours=1)
    )
    ManufacturabilityCheckFactory(
        project=older.project,
        project_file=older.project_file,
        status=ManufacturabilityCheck.Status.FINISHED,
    )
    older.runs_archive.storage.delete(older.runs_archive.name)

    content = _project_page(client, older)

    assert "This file has been checked 2 times" in content
    assert 'data-artifact-missing="runs_archive"' in content


@pytest.mark.django_db
def test_missing_log_file_keeps_the_log_link(client: Client):
    """The log link stays: projects:check_log falls back to the database copy."""
    check = _finished_check_with_artifact("log_file")
    check.log_file.storage.delete(check.log_file.name)

    content = _project_page(client, check)

    assert 'data-artifact-missing="log_file"' in content
    assert (
        reverse(
            "projects:check_log", kwargs={"pk": check.project_id, "check_id": check.pk}
        )
        in content
    )


@pytest.mark.django_db
def test_missing_artifact_says_file_missing(client: Client):
    """The visible text tells the reader the file is gone."""
    check = _finished_check_with_artifact("output_gds")
    check.output_gds.storage.delete(check.output_gds.name)

    content = _project_page(client, check)

    assert ">File missing</span>" in content
