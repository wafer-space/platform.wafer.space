"""A test-only shuttle (#221) never gets slots, a manifest or a package."""

import json
from http import HTTPStatus
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from wafer_space.core.enums import SlotSize
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.shuttles.services.reticle_package import ReticlePackageError
from wafer_space.shuttles.services.reticle_package import generate_package
from wafer_space.users.tests.factories import UserFactory

SLOT_REFUSAL = "G890 is a test-only shuttle; its projects are never placed in slots"


@pytest.fixture
def test_shuttle() -> Shuttle:
    return Shuttle.objects.create(
        name="G890",
        description="Test shuttle",
        status=Shuttle.Status.OPEN,
        is_test_only=True,
    )


@pytest.fixture
def test_slot(test_shuttle: Shuttle) -> ShuttleSlot:
    # Built directly: a test-only shuttle never gets a grid from the command.
    return ShuttleSlot.objects.create(
        shuttle=test_shuttle, row=0, column=0, slot_size=SlotSize.FULL
    )


@pytest.mark.django_db
def test_reserve_refuses_test_only_shuttle(test_slot):
    project = ProjectFactory(shuttle=test_slot.shuttle, slot_size=SlotSize.FULL)

    with pytest.raises(ValueError, match=SLOT_REFUSAL):
        test_slot.reserve(project, UserFactory(is_staff=True))
    test_slot.refresh_from_db()
    assert (test_slot.status, test_slot.project) == (
        ShuttleSlot.Status.AVAILABLE,
        None,
    )


@pytest.mark.django_db
def test_assign_view_returns_400_for_test_only_shuttle(client, test_slot):
    project = ProjectFactory(shuttle=test_slot.shuttle, slot_size=SlotSize.FULL)
    client.force_login(UserFactory(is_staff=True))

    response = client.post(
        reverse("shuttles:assign_project", kwargs={"name": "G890"}),
        data=json.dumps({"project_pk": str(project.pk), "slot_id": test_slot.pk}),
        content_type="application/json",
    )

    assert (response.status_code, response.json()) == (
        HTTPStatus.BAD_REQUEST,
        {"success": False, "error": SLOT_REFUSAL},
    )


@pytest.mark.django_db
def test_manifest_refuses_test_only_shuttle(test_shuttle):
    with pytest.raises(ValueError, match="G890 is a test-only shuttle; it has no"):
        test_shuttle.generate_manifest()


@pytest.mark.django_db
def test_package_refuses_test_only_shuttle_and_writes_nothing(test_shuttle, tmp_path):
    output = tmp_path / "package"

    with pytest.raises(ReticlePackageError, match="test-only shuttle"):
        generate_package("G890", output)
    assert not output.exists()


@pytest.mark.django_db
def test_grid_command_refuses_test_only_shuttle(test_shuttle, tmp_path):
    layout = Path("shuttles/G803-layout.yaml").read_text()
    (tmp_path / "G890-layout.yaml").write_text(
        layout.replace("shuttle: G803", "shuttle: G890")
    )

    with pytest.raises(CommandError, match="G890 is a test-only shuttle; it has no"):
        call_command("generate_shuttle_grid", "G890", config_dir=str(tmp_path))
    assert not test_shuttle.slots.exists()
