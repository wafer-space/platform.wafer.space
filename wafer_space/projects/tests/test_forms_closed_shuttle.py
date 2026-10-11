"""The project form follows the shuttle closed rule (#320, #350)."""

import datetime
from http import HTTPStatus

import pytest
from django import forms
from django.urls import reverse

from wafer_space.projects.forms import ProjectForm
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

PAST = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
FUTURE = datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC)


def _names(field: forms.Field) -> set[str]:
    assert isinstance(field, forms.ModelChoiceField)
    queryset = field.queryset
    assert queryset is not None
    return set(queryset.values_list("name", flat=True))


@pytest.fixture
def shuttles() -> dict[str, Shuttle]:
    return {
        "open": Shuttle.objects.create(
            name="G885", description="Open", status="open", submission_deadline=FUTURE
        ),
        "no_deadline": Shuttle.objects.create(
            name="G886", description="No deadline", status="open"
        ),
        # Open status but the deadline has passed: the G802 case in #320.
        "lapsed": Shuttle.objects.create(
            name="G887", description="Lapsed", status="open", submission_deadline=PAST
        ),
        "production": Shuttle.objects.create(
            name="G888", description="Production", status="production"
        ),
    }


def test_create_form_offers_open_shuttles(shuttles):
    form = ProjectForm(user=UserFactory())

    assert {"G885", "G886"} <= _names(form.fields["shuttle"])


def test_create_form_never_offers_closed_shuttles(shuttles):
    form = ProjectForm(user=UserFactory())

    assert _names(form.fields["shuttle"]).isdisjoint({"G887", "G888"})


def test_default_skips_lapsed_open_shuttle(shuttles):
    # Make the lapsed shuttle the oldest "open" one, which the old default
    # (oldest status=open) would have picked.
    Shuttle.objects.filter(name="G887").update(created_at=PAST)

    form = ProjectForm(user=UserFactory())

    assert form.fields["shuttle"].initial.name != "G887"


def test_cob_locked_for_owner_on_closed_shuttle(shuttles):
    project = ProjectFactory(shuttle=shuttles["production"])

    form = ProjectForm(instance=project, user=project.user)

    assert form.fields["chip_on_board"].disabled


def test_cob_editable_for_staff_on_closed_shuttle(shuttles):
    project = ProjectFactory(shuttle=shuttles["production"])

    form = ProjectForm(instance=project, user=UserFactory(is_staff=True))

    assert not form.fields["chip_on_board"].disabled


def test_cob_editable_for_owner_on_open_shuttle(shuttles):
    project = ProjectFactory(shuttle=shuttles["open"])

    form = ProjectForm(instance=project, user=project.user)

    assert not form.fields["chip_on_board"].disabled


def test_owner_rename_saves_but_cob_flip_is_ignored_when_closed(client, shuttles):
    project = ProjectFactory(shuttle=shuttles["lapsed"], chip_on_board=False)
    checks_before = ManufacturabilityCheck.objects.count()
    client.force_login(project.user)

    response = client.post(
        reverse("projects:update", kwargs={"pk": project.pk}),
        {
            "name": "Renamed after close",
            "description": "",
            "chip_on_board": "on",
            "repository_url": "",
            "license_type": "proprietary",
            "other_license_spdx_id": "",
            "proprietary_terms_url": "",
        },
    )

    project.refresh_from_db()
    assert (
        response.status_code,
        project.name,
        project.chip_on_board,
        ManufacturabilityCheck.objects.count(),
    ) == (HTTPStatus.FOUND, "Renamed after close", False, checks_before)
