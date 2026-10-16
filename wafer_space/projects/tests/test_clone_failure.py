"""A clone that fails in the worker is shown on the source project (#411).

"Clone to open shuttle" says "Cloning ..." before duplicate_project_task
runs. When the copy then fails, the task records a CloneFailure and the
source project's page shows it to the owner and staff until a later copy
to that shuttle succeeds. Celery runs eagerly under pytest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from wafer_space.core.enums import SlotSize
from wafer_space.projects.models import CloneFailure
from wafer_space.projects.models import Project
from wafer_space.projects.tasks_duplication import COPY_FAILED_REASON
from wafer_space.projects.tasks_duplication import duplicate_project_task
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

from .factories import ProjectFactory
from .test_duplication import make_shuttle
from .test_duplication import make_source_project

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

STORAGE_PATH = "/mnt/user-files/projects/some-project/design.gds"


@pytest.fixture
def source() -> Project:
    return make_source_project(shuttle=make_shuttle("G803"), project_id="ABCD")


@pytest.fixture
def open_shuttle() -> Shuttle:
    return make_shuttle("G804")


def clone_in_worker(
    project: Project,
    shuttle: Shuttle,
    *,
    project_id: str = "WXYZ",
) -> dict[str, str]:
    """Run the task as "Clone to open shuttle" queues it."""
    return duplicate_project_task(
        str(project.pk),
        shuttle.pk,
        project.user.pk,
        project_id,
        SlotSize.HALF_WIDTH,
    )


def close(shuttle: Shuttle) -> None:
    shuttle.status = Shuttle.Status.LOCKED
    shuttle.save()


def project_page(client: Client, project: Project) -> str:
    response = client.get(project.get_absolute_url(), follow=True)
    return response.content.decode()


def notice(shuttle: Shuttle) -> str:
    return f'data-clone-failure="{shuttle.name}"'


class TestEachFailureIsRecorded:
    def test_a_shuttle_that_closed_after_enqueue(
        self,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        close(open_shuttle)

        clone_in_worker(source, open_shuttle)

        failure = CloneFailure.objects.get(project=source)
        assert (failure.target_shuttle, failure.requested_by) == (
            open_shuttle,
            source.user,
        )
        assert "not open for submissions" in failure.reason

    def test_an_id_taken_after_enqueue(
        self,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        ProjectFactory(shuttle=open_shuttle, project_id="WXYZ")

        clone_in_worker(source, open_shuttle)

        failure = CloneFailure.objects.get(project=source)
        assert "'WXYZ' is already used on shuttle G804" in failure.reason

    def test_a_storage_error_reads_as_a_failed_copy(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        """The owner's POST runs the copy inline; the write fails."""
        client.force_login(source.user)
        error = OSError(30, "Read-only file system", STORAGE_PATH)

        with patch(
            "wafer_space.projects.duplication._copy_file",
            side_effect=error,
        ):
            client.post(
                reverse("projects:clone", kwargs={"pk": source.pk}),
                {
                    "target_shuttle": open_shuttle.pk,
                    "project_id": "WXYZ",
                    "slot_size": SlotSize.HALF_WIDTH,
                },
            )

        failure = CloneFailure.objects.get(project=source)
        assert failure.reason == COPY_FAILED_REASON

    def test_a_storage_error_shows_no_path_to_the_owner(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        error = OSError(30, "Read-only file system", STORAGE_PATH)
        with patch(
            "wafer_space.projects.duplication._copy_file",
            side_effect=error,
        ):
            clone_in_worker(source, open_shuttle)
        client.force_login(source.user)

        page = project_page(client, source)

        assert notice(open_shuttle) in page
        assert STORAGE_PATH not in page

    def test_a_second_failure_replaces_the_first(
        self,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        ProjectFactory(shuttle=open_shuttle, project_id="WXYZ")
        clone_in_worker(source, open_shuttle)
        close(open_shuttle)

        clone_in_worker(source, open_shuttle)

        [failure] = CloneFailure.objects.filter(project=source)
        assert "not open for submissions" in failure.reason

    def test_the_admin_action_records_none(
        self,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        """Staff duplication failures stay in the admin history only."""
        ProjectFactory(shuttle=open_shuttle, project_id=source.project_id)

        result = duplicate_project_task(
            str(source.pk),
            open_shuttle.pk,
            UserFactory(is_staff=True).pk,
        )

        assert result["status"] == "failed"
        assert not CloneFailure.objects.exists()


class TestTheNotice:
    @pytest.fixture
    def failed(self, source: Project, open_shuttle: Shuttle) -> CloneFailure:
        close(open_shuttle)
        clone_in_worker(source, open_shuttle)
        return CloneFailure.objects.get(project=source)

    def test_the_owner_sees_shuttle_date_reason_and_a_retry_link(
        self,
        client: Client,
        source: Project,
        failed: CloneFailure,
    ) -> None:
        client.force_login(source.user)

        page = project_page(client, source)

        when = timezone.localtime(failed.failed_at).strftime("%Y-%m-%d %H:%M")
        assert "Cloning to shuttle G804 failed" in page
        assert f"on {when}: {failed.reason}" in page
        assert reverse("projects:clone", kwargs={"pk": source.pk}) in page

    def test_staff_see_it(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
        failed: CloneFailure,
    ) -> None:
        client.force_login(UserFactory(is_staff=True))

        assert notice(open_shuttle) in project_page(client, source)

    def test_a_project_with_no_failed_clone_has_none(
        self,
        client: Client,
        source: Project,
    ) -> None:
        client.force_login(source.user)

        assert "data-clone-failure" not in project_page(client, source)


class TestALaterSuccess:
    @pytest.fixture
    def failed(self, source: Project, open_shuttle: Shuttle) -> None:
        close(open_shuttle)
        clone_in_worker(source, open_shuttle)
        open_shuttle.status = Shuttle.Status.OPEN
        open_shuttle.save()

    @pytest.mark.usefixtures("failed")
    def test_a_clone_to_the_same_shuttle_clears_the_notice(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        result = clone_in_worker(source, open_shuttle)
        client.force_login(source.user)

        assert result["status"] == "ok"
        assert notice(open_shuttle) not in project_page(client, source)

    @pytest.mark.usefixtures("failed")
    def test_a_clone_to_another_shuttle_leaves_it(
        self,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        result = clone_in_worker(source, make_shuttle("G805"))

        assert result["status"] == "ok"
        assert CloneFailure.objects.filter(
            project=source,
            target_shuttle=open_shuttle,
        ).exists()
