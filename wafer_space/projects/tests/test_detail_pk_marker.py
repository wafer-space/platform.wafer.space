"""The project page names its pk once its URL no longer does (#150).

The canonical project URL is the full_id once a shuttle is assigned, so the
pk is not in the address bar. scripts/e2e_verify reads it from
``data-project-pk`` to reach the pk-addressed action URLs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from wafer_space.shuttles.models import Shuttle

from .factories import ProjectFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def test_canonical_project_page_names_its_pk(client: Client) -> None:
    shuttle = Shuttle.objects.create(
        name="G887", description="Open run", status=Shuttle.Status.OPEN
    )
    project = ProjectFactory(shuttle=shuttle)
    client.force_login(project.user)

    content = client.get(project.get_absolute_url()).content.decode()

    assert (
        str(project.pk) in project.get_absolute_url(),
        content.count(f'data-project-pk="{project.pk}"'),
    ) == (False, 1)
