"""Test factories for projects app."""

from __future__ import annotations

from factory import Faker
from factory import SubFactory
from factory.django import DjangoModelFactory

from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.users.tests.factories import UserFactory


class ProjectFactory(DjangoModelFactory[Project]):
    """Factory for creating test Project instances."""

    user = SubFactory(UserFactory)
    name = Faker("catch_phrase")
    description = Faker("text", max_nb_chars=200)
    slot_size = "1x1"

    class Meta:
        model = Project


class ProjectFileFactory(DjangoModelFactory[ProjectFile]):
    """Factory for creating test ProjectFile instances."""

    project = SubFactory(ProjectFactory)
    file = Faker("file_name", extension="gds")
    original_filename = Faker("file_name", extension="gds")
    size = Faker("random_int", min=1000, max=10000000)

    class Meta:
        model = ProjectFile
