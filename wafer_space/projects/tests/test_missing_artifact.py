"""The project page renders when a check's saved artifact is gone (#378).

A check row can name an artifact file that is no longer on disk: a manual
clean-up, a restore that copied the database but not every media file, or
a failed partial save. The check partial used to call ``FieldFile.size`` on
each artifact, which raises ``FileNotFoundError`` for a missing file, so the
whole project page returned 500.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from django.core.files.base import ContentFile

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


DOWNLOAD_FIELDS = ["runs_archive", "output_gds", "docker_layer_export"]


@pytest.mark.django_db
@pytest.mark.parametrize("field", DOWNLOAD_FIELDS)
def test_missing_artifact_is_not_offered_as_a_download(client: Client, field: str):
    """A download link to a file that is gone would only 404, so none is shown."""
    check = _finished_check_with_artifact(field)
    artifact = getattr(check, field)
    url = artifact.url
    artifact.storage.delete(artifact.name)

    content = _project_page(client, check)

    assert url not in content


@pytest.mark.django_db
@pytest.mark.parametrize("field", DOWNLOAD_FIELDS)
def test_present_artifact_is_offered_as_a_download(client: Client, field: str):
    """A file on disk keeps its download link."""
    check = _finished_check_with_artifact(field)

    content = _project_page(client, check)

    assert getattr(check, field).url in content
