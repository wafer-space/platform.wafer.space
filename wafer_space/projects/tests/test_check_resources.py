"""A check's resource usage: a summary on the project page, rows behind a link (#429).

The project page rendered a table row for every checkpoint of every check,
and a check can record thousands: G801 2975's page was 5.9 MB. It now shows
one summary line per check, from one aggregate query, and links to
projects:check_resources for the full timeline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import ManufacturabilityCheckpoint
from wafer_space.users.tests.factories import UserFactory

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_METHOD_NOT_ALLOWED
from .constants import HTTP_NOT_FOUND
from .constants import HTTP_OK
from .factories import ManufacturabilityCheckFactory
from .factories import ProjectFactory
from .factories import ProjectFileFactory

if TYPE_CHECKING:
    from django.test import Client

    from wafer_space.projects.models import Project

pytestmark = pytest.mark.django_db

CHECKS = 3
# Growing every check from 1 to 300 checkpoints may add at most this much
# to the project page; the old per-row table added about 230 bytes a row.
PAGE_GROWTH_BUDGET_BYTES = 1024
# ManufacturabilityCheckpoint's table, as it appears in the SQL
CHECKPOINT_TABLE = "projects_manufacturabilitycheckpoint"
GIB = 1024**3


def add_checkpoints(
    check: ManufacturabilityCheck, numbers: range
) -> list[ManufacturabilityCheckpoint]:
    """Checkpoints numbered ``numbers``, 5 s apart, CPU and memory rising."""
    return ManufacturabilityCheckpoint.objects.bulk_create(
        ManufacturabilityCheckpoint(
            manufacturability_check=check,
            checkpoint_number=n,
            elapsed_seconds=n * 5.0,
            cpu_percent=10.0 + n / 10,
            memory_usage_bytes=GIB + n * 1024**2,
            memory_limit_bytes=64 * GIB,
            memory_percent=(GIB + n * 1024**2) * 100 / (64 * GIB),
            raw_stats_json={"checkpoint": n},
        )
        for n in numbers
    )


def finished_checks(project: Project, count: int) -> list[ManufacturabilityCheck]:
    """``count`` finished checks of one active file of ``project``."""
    project_file = ProjectFileFactory(project=project, is_active=True)
    return [
        ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )
        for _ in range(count)
    ]


def project_page(client: Client, project: Project) -> str:
    """The owner's project page, asserting 200."""
    client.force_login(project.user)
    response = client.get(reverse("projects:detail", args=[project.pk]))
    assert response.status_code == HTTP_OK
    return response.content.decode()


def resources_url(check: ManufacturabilityCheck) -> str:
    return reverse(
        "projects:check_resources",
        kwargs={"pk": check.project_id, "check_id": check.pk},
    )


class TestProjectPage:
    def test_page_size_does_not_grow_with_checkpoints(self, client: Client) -> None:
        project = ProjectFactory()
        checks = finished_checks(project, CHECKS)
        for check in checks:
            add_checkpoints(check, range(1))
        small = len(project_page(client, project).encode())

        for check in checks:
            add_checkpoints(check, range(1, 300))
        large = len(project_page(client, project).encode())

        assert large - small <= PAGE_GROWTH_BUDGET_BYTES

    def test_one_checkpoint_query_per_check(self, client: Client) -> None:
        project = ProjectFactory()
        for check in finished_checks(project, CHECKS):
            add_checkpoints(check, range(50))
        client.force_login(project.user)

        with CaptureQueriesContext(connection) as queries:
            response = client.get(reverse("projects:detail", args=[project.pk]))

        assert response.status_code == HTTP_OK
        checkpoint_queries = [
            q["sql"] for q in queries.captured_queries if CHECKPOINT_TABLE in q["sql"]
        ]
        assert len(checkpoint_queries) == CHECKS
        assert all("MAX(" in sql for sql in checkpoint_queries)

    def test_summary_line_gives_count_duration_and_peaks(self, client: Client) -> None:
        project = ProjectFactory()
        (check,) = finished_checks(project, 1)
        add_checkpoints(check, range(121))

        content = project_page(client, project)

        # 121 checkpoints; the last at 600 s; CPU peaks at 22.0 %, memory
        # at 1 GiB + 120 MiB = 1.1 GB, 1.7 % of 64 GiB
        assert "121 checkpoints over 10m" in content
        assert "22.0%" in content
        assert "1.1\xa0GB" in content
        assert "(1.7%)" in content
        assert f'href="{resources_url(check)}"' in content

    def test_no_table_row_per_checkpoint(self, client: Client) -> None:
        project = ProjectFactory()
        (check,) = finished_checks(project, 1)
        add_checkpoints(check, range(20))

        content = project_page(client, project)

        assert "Resource Usage Timeline" not in content
        assert "<td>19</td>" not in content

    def test_check_without_checkpoints_says_none_recorded(self, client: Client) -> None:
        project = ProjectFactory()
        (check,) = finished_checks(project, 1)

        content = project_page(client, project)

        assert "none recorded" in content
        assert resources_url(check) not in content


class TestCheckResourcesView:
    def test_owner_sees_every_checkpoint(self, client: Client) -> None:
        project = ProjectFactory()
        (check,) = finished_checks(project, 1)
        add_checkpoints(check, range(30))
        client.force_login(project.user)

        response = client.get(resources_url(check))

        assert response.status_code == HTTP_OK
        assert list(response.context["checkpoints"]) == list(check.checkpoints.all())
        content = response.content.decode()
        assert "<td>0</td>" in content
        assert "<td>29</td>" in content

    def test_does_not_load_raw_docker_stats(self, client: Client) -> None:
        project = ProjectFactory()
        (check,) = finished_checks(project, 1)
        add_checkpoints(check, range(5))
        client.force_login(project.user)

        with CaptureQueriesContext(connection) as queries:
            response = client.get(resources_url(check))

        assert response.status_code == HTTP_OK
        checkpoint_queries = [
            q["sql"] for q in queries.captured_queries if CHECKPOINT_TABLE in q["sql"]
        ]
        assert checkpoint_queries
        assert not any("raw_stats_json" in sql for sql in checkpoint_queries)

    def test_check_without_checkpoints_says_so(self, client: Client) -> None:
        project = ProjectFactory()
        (check,) = finished_checks(project, 1)
        client.force_login(project.user)

        response = client.get(resources_url(check))

        assert response.status_code == HTTP_OK
        assert "This check recorded no resource usage." in response.content.decode()

    def test_staff_sees_another_users_check(self, client: Client) -> None:
        project = ProjectFactory()
        (check,) = finished_checks(project, 1)
        client.force_login(UserFactory(is_staff=True))

        assert client.get(resources_url(check)).status_code == HTTP_OK

    def test_stranger_gets_403(self, client: Client) -> None:
        project = ProjectFactory()
        (check,) = finished_checks(project, 1)
        client.force_login(UserFactory())

        assert client.get(resources_url(check)).status_code == HTTP_FORBIDDEN

    def test_anonymous_redirected_to_login(self, client: Client) -> None:
        project = ProjectFactory()
        (check,) = finished_checks(project, 1)

        response = client.get(resources_url(check))

        assert response.status_code == HTTP_FOUND
        assert reverse("account_login") in response["Location"]

    def test_check_of_another_project_is_404(self, client: Client) -> None:
        project = ProjectFactory()
        (check,) = finished_checks(project, 1)
        other = ProjectFactory(user=project.user)
        client.force_login(project.user)

        response = client.get(
            reverse(
                "projects:check_resources",
                kwargs={"pk": other.pk, "check_id": check.pk},
            )
        )

        assert response.status_code == HTTP_NOT_FOUND

    def test_post_is_not_allowed(self, client: Client) -> None:
        project = ProjectFactory()
        (check,) = finished_checks(project, 1)
        client.force_login(project.user)

        response = client.post(resources_url(check))

        assert response.status_code == HTTP_METHOD_NOT_ALLOWED
