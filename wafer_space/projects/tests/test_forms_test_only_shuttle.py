"""The project form offers a test-only shuttle but never defaults to it (#221)."""

import pytest
from django import forms

from wafer_space.projects.forms import ProjectForm
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _shuttle_field(form: ProjectForm) -> forms.ModelChoiceField:
    field = form.fields["shuttle"]
    assert isinstance(field, forms.ModelChoiceField)
    return field


@pytest.fixture
def test_shuttle() -> Shuttle:
    # Close every seeded shuttle so each test controls what is open.
    Shuttle.objects.update(status=Shuttle.Status.COMPLETED)
    return Shuttle.objects.create(
        name="G891",
        description="Test shuttle",
        status=Shuttle.Status.OPEN,
        is_test_only=True,
    )


@pytest.fixture
def real_shuttle(test_shuttle: Shuttle) -> Shuttle:
    return Shuttle.objects.create(
        name="G892", description="Real run", status=Shuttle.Status.OPEN
    )


def test_test_only_shuttle_is_offered(real_shuttle, test_shuttle):
    field = _shuttle_field(ProjectForm(user=UserFactory()))

    assert field.queryset is not None
    assert set(field.queryset.values_list("name", flat=True)) == {"G891", "G892"}


def test_default_is_the_real_shuttle(real_shuttle):
    form = ProjectForm(user=UserFactory())

    assert form.fields["shuttle"].initial == real_shuttle


def test_no_default_when_only_the_test_shuttle_is_open(test_shuttle):
    form = ProjectForm(user=UserFactory())

    assert form.fields["shuttle"].initial is None


def test_test_only_label_says_so(test_shuttle):
    field = _shuttle_field(ProjectForm(user=UserFactory()))

    assert field.label_from_instance(test_shuttle) == (
        "G891 - Test shuttle (test only, not manufactured)"
    )


def test_real_shuttle_label_unchanged(real_shuttle):
    field = _shuttle_field(ProjectForm(user=UserFactory()))

    assert field.label_from_instance(real_shuttle) == "G892 - Real run"
