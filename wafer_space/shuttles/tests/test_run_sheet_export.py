"""Tests for the run-sheet JSON page (/shuttles/<name>/run-sheet.json)."""

from __future__ import annotations

import hashlib
from http import HTTPStatus

import pytest
from django.urls import reverse

from wafer_space.core.enums import SlotSize
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.projects.tests.factories import ProjectFileFactory
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.shuttles.tests.factories import ShuttleFactory

SHEET_BEARER = "test-run-sheet-bearer"
BEARER_SHA256 = hashlib.sha256(SHEET_BEARER.encode()).hexdigest()


@pytest.fixture
def token_set(settings):
    settings.RUN_SHEET_TOKEN_SHA256 = BEARER_SHA256


def get(client, name: str, auth: str | None = f"Bearer {SHEET_BEARER}"):
    url = reverse("shuttles:run_sheet_export", kwargs={"name": name})
    headers = {"Authorization": auth} if auth is not None else {}
    return client.get(url, headers=headers)


@pytest.mark.django_db
@pytest.mark.usefixtures("token_set")
class TestRunSheetAccess:
    """Only the run-sheet token reads the page; everything else is a 404."""

    def test_token_reads_the_page(self, client):
        ShuttleFactory(name="G850")

        response = get(client, "G850")

        assert response.status_code == HTTPStatus.OK

    def test_response_is_not_cached(self, client):
        ShuttleFactory(name="G851")

        response = get(client, "G851")

        assert response["Cache-Control"] == "no-store"

    @pytest.mark.parametrize(
        "auth",
        [
            None,
            "",
            "Bearer ",
            "Bearer wrong-token",
            f"Basic {SHEET_BEARER}",
            SHEET_BEARER,
        ],
    )
    def test_anything_but_the_token_is_not_found(self, client, auth):
        ShuttleFactory(name="G852")

        response = get(client, "G852", auth=auth)

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_unknown_shuttle_is_not_found(self, client):
        response = get(client, "G899")

        assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_page_is_disabled_without_the_setting(client, settings):
    settings.RUN_SHEET_TOKEN_SHA256 = None
    ShuttleFactory(name="G853")

    response = get(client, "G853")

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
@pytest.mark.usefixtures("token_set")
class TestRunSheetData:
    """The page lists every non-cancelled project and the shuttle's slots."""

    def test_slots_of_the_shuttle_only(self, client):
        shuttle = ShuttleFactory(name="G854")
        other = ShuttleFactory(name="G855")
        project = ProjectFactory(shuttle=shuttle)
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=1,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.OCCUPIED,
            project=project,
        )
        ShuttleSlot.objects.create(
            shuttle=other, row=0, column=0, slot_size=SlotSize.FULL
        )

        slots = get(client, "G854").json()["slots"]

        assert slots == [
            {
                "position": "B1",
                "slot_size": SlotSize.FULL,
                "status": "occupied",
                "project": str(project.id),
            }
        ]

    def test_cancelled_projects_are_left_out(self, client):
        ShuttleFactory(name="G856")
        kept = ProjectFactory(status=Project.Status.DRAFT)
        ProjectFactory(status=Project.Status.CANCELLED)

        projects = get(client, "G856").json()["projects"]

        assert [p["uuid"] for p in projects] == [str(kept.id)]

    def test_project_fields(self, client):
        shuttle = ShuttleFactory(name="G857")
        project = ProjectFactory(
            shuttle=shuttle,
            chip_on_board=True,
            crowd_supply_order_id="352306",
            repository_url="https://github.com/example/design",
        )
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=1,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.OCCUPIED,
            project=project,
        )

        (got,) = get(client, "G857").json()["projects"]

        assert got == {
            "uuid": str(project.id),
            "project_id": project.project_id,
            "name": project.name,
            "slot_size": project.slot_size,
            "chip_on_board": True,
            "order": "352306",
            "status": project.status,
            "shuttle": "G857",
            "created": project.created_at.isoformat(),
            "owner_name": project.user.name or project.user.username,
            "owner_email": project.user.email,
            "license_type": project.license_type,
            "other_license_spdx_id": project.other_license_spdx_id,
            "repository_url": "https://github.com/example/design",
            "precheck_status": "",
            "precheck_ok": None,
            "precheck_warnings": False,
            "submitted_at": "",
            "slot_positions": ["A2"],
        }

    def test_precheck_is_the_active_files_latest_check(self, client):
        ShuttleFactory(name="G858")
        project = ProjectFactory()
        active = ProjectFileFactory(project=project, is_active=True)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=active,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

        (got,) = get(client, "G858").json()["projects"]

        assert (got["precheck_status"], got["precheck_ok"]) == ("finished", True)
