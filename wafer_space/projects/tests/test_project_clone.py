"""Owners clone a project to a shuttle open to users (#355).

"Clone to open shuttle" reuses the staff duplication path
(projects.duplication, duplicate_project_task on http:rw:downloads).
Celery runs eagerly under pytest, so a POST runs the copy inline.
"""

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone

from wafer_space.core.enums import SlotSize
from wafer_space.projects.models import Project
from wafer_space.projects.tasks_duplication import duplicate_project_task
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

from .test_duplication import make_shuttle
from .test_duplication import make_source_project

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

TEST_ONLY_LABEL = "(test only, not manufactured)"


@pytest.fixture
def source() -> Project:
    """A project on G803, closed: its GDS deadline has passed."""
    shuttle = make_shuttle("G803")
    shuttle.submission_deadline = timezone.now() - timedelta(days=1)
    shuttle.save()
    return make_source_project(shuttle=shuttle, project_id="ABCD")


@pytest.fixture
def open_shuttle() -> Shuttle:
    return make_shuttle("G804")


def clone_url(project: Project) -> str:
    return reverse("projects:clone", kwargs={"pk": project.pk})


def post_clone(
    client: Client,
    project: Project,
    shuttle: Shuttle,
    *,
    project_id: str = "WXYZ",
    slot_size: str = SlotSize.HALF_WIDTH,
) -> Any:
    return client.post(
        clone_url(project),
        {
            "target_shuttle": shuttle.pk,
            "project_id": project_id,
            "slot_size": slot_size,
        },
    )


def clones(shuttle: Shuttle) -> list[Project]:
    return list(Project.objects.filter(shuttle=shuttle))


class TestWho:
    def test_owner_sees_the_link_on_the_project_page(
        self,
        client: Client,
        source: Project,
    ) -> None:
        client.force_login(source.user)

        response = client.get(source.get_absolute_url(), follow=True)

        assert clone_url(source) in response.content.decode()

    def test_owner_clones(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        client.force_login(source.user)

        response = post_clone(client, source, open_shuttle)

        [clone] = clones(open_shuttle)
        assert (response.status_code, clone.user, clone.status) == (
            HTTPStatus.FOUND,
            source.user,
            Project.Status.DRAFT,
        )

    def test_staff_clones_another_users_project(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        client.force_login(UserFactory(is_staff=True))

        post_clone(client, source, open_shuttle)

        [clone] = clones(open_shuttle)
        assert clone.user == source.user

    def test_another_user_cannot_see_the_form(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        client.force_login(UserFactory())

        response = client.get(clone_url(source))

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_another_user_cannot_clone(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        client.force_login(UserFactory())

        response = post_clone(client, source, open_shuttle)

        assert (response.status_code, clones(open_shuttle)) == (
            HTTPStatus.FORBIDDEN,
            [],
        )

    def test_anonymous_is_sent_to_login(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        response = post_clone(client, source, open_shuttle)

        assert (response.status_code, clones(open_shuttle)) == (
            HTTPStatus.FOUND,
            [],
        )
        assert "/accounts/login/" in response["Location"]


class TestWhichShuttles:
    def offered(self, client: Client, project: Project) -> list[Shuttle]:
        client.force_login(project.user)
        response = client.get(clone_url(project))
        return list(response.context["form"].fields["target_shuttle"].queryset)

    def test_only_shuttles_open_to_users_are_offered(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        make_shuttle("G805", status=Shuttle.Status.LOCKED)
        make_shuttle("G806", status=Shuttle.Status.PLANNING)
        past = make_shuttle("G807")
        past.submission_deadline = timezone.now() - timedelta(hours=1)
        past.save()

        assert self.offered(client, source) == [open_shuttle]

    def test_the_projects_own_shuttle_is_not_offered(
        self,
        client: Client,
        open_shuttle: Shuttle,
    ) -> None:
        project = make_source_project(shuttle=open_shuttle, project_id="ABCD")

        assert open_shuttle not in self.offered(client, project)

    def test_test_only_shuttle_is_offered_and_labelled(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        Shuttle.objects.create(name="G800", description="Test", is_test_only=True)
        client.force_login(source.user)

        content = client.get(clone_url(source)).content.decode()

        assert f"G800 - Test {TEST_ONLY_LABEL}" in content

    def test_a_real_run_is_preselected_never_the_test_shuttle(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        Shuttle.objects.create(name="G800", description="Test", is_test_only=True)
        client.force_login(source.user)

        form = client.get(clone_url(source)).context["form"]

        assert form.fields["target_shuttle"].initial == open_shuttle

    def test_nothing_is_preselected_when_only_the_test_shuttle_is_open(
        self,
        client: Client,
        source: Project,
    ) -> None:
        Shuttle.objects.create(name="G800", description="Test", is_test_only=True)
        client.force_login(source.user)

        form = client.get(clone_url(source)).context["form"]

        assert form.fields["target_shuttle"].initial is None

    def test_no_open_shuttle_says_so(
        self,
        client: Client,
        source: Project,
    ) -> None:
        client.force_login(source.user)

        content = client.get(clone_url(source)).content.decode()

        assert ("data-no-open-shuttle" in content, "data-clone-form" in content) == (
            True,
            False,
        )

    def test_test_shuttle_is_a_target_whatever_its_status(
        self,
        client: Client,
        source: Project,
    ) -> None:
        """#374: a test-only shuttle is open whatever its status."""
        g800 = Shuttle.objects.create(
            name="G800",
            description="Test",
            is_test_only=True,
            status=Shuttle.Status.COMPLETED,
        )
        client.force_login(source.user)

        post_clone(client, source, g800)

        assert len(clones(g800)) == 1

    def test_owner_clones_to_the_test_shuttle(
        self,
        client: Client,
        source: Project,
    ) -> None:
        g800 = Shuttle.objects.create(
            name="G800",
            description="Test",
            is_test_only=True,
        )
        client.force_login(source.user)

        post_clone(client, source, g800)

        assert len(clones(g800)) == 1


class TestClosedShuttleRefused:
    @pytest.mark.parametrize("closed_by", ["status", "deadline"])
    def test_post_to_a_closed_shuttle_is_refused(
        self,
        client: Client,
        source: Project,
        closed_by: str,
    ) -> None:
        if closed_by == "status":
            closed = make_shuttle("G805", status=Shuttle.Status.LOCKED)
        else:
            closed = make_shuttle("G805")
            closed.submission_deadline = timezone.now() - timedelta(minutes=1)
            closed.save()
        client.force_login(source.user)

        response = post_clone(client, source, closed)

        assert (response.status_code, clones(closed)) == (HTTPStatus.OK, [])
        assert "target_shuttle" in response.context["form"].errors

    def test_task_refuses_a_shuttle_that_closed_after_enqueue(
        self,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        open_shuttle.status = Shuttle.Status.LOCKED
        open_shuttle.save()

        result = duplicate_project_task(
            str(source.pk),
            open_shuttle.pk,
            source.user.pk,
            "WXYZ",
            SlotSize.FULL,
        )

        assert (result["status"], clones(open_shuttle)) == ("failed", [])
        assert "not open for submissions" in result["error"]

    def test_task_refuses_half_a_clone_request(
        self,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        """A project ID without a slot size is a caller bug, not a duplicate."""
        with pytest.raises(ValueError, match="needs both"):
            duplicate_project_task(
                str(source.pk),
                open_shuttle.pk,
                source.user.pk,
                "WXYZ",
            )
        assert clones(open_shuttle) == []


class TestProjectIdAndSize:
    def test_clone_takes_the_chosen_id_and_size(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        client.force_login(source.user)

        post_clone(
            client,
            source,
            open_shuttle,
            project_id="wxyz",
            slot_size=SlotSize.QUARTER,
        )

        [clone] = clones(open_shuttle)
        assert (clone.project_id, clone.slot_size, clone.name) == (
            "WXYZ",
            SlotSize.QUARTER,
            source.name,
        )

    def test_the_source_id_may_be_kept_on_another_shuttle(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        client.force_login(source.user)

        post_clone(client, source, open_shuttle, project_id=source.project_id)

        [clone] = clones(open_shuttle)
        assert clone.project_id == source.project_id

    def test_an_id_taken_on_the_target_is_refused(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        make_source_project(shuttle=open_shuttle, project_id="WXYZ")
        client.force_login(source.user)

        response = post_clone(client, source, open_shuttle, project_id="WXYZ")

        assert "project_id" in response.context["form"].errors
        assert len(clones(open_shuttle)) == 1

    @pytest.mark.parametrize("bad_id", ["AB", "ABCDE", "AB-D", "ÀBCD"])
    def test_a_malformed_id_is_refused(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
        bad_id: str,
    ) -> None:
        client.force_login(source.user)

        response = post_clone(client, source, open_shuttle, project_id=bad_id)

        errors = response.context["form"].errors
        assert ("project_id" in errors, clones(open_shuttle)) == (True, [])

    def test_an_unknown_slot_size_is_refused(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        client.force_login(source.user)

        response = post_clone(client, source, open_shuttle, slot_size="huge")

        errors = response.context["form"].errors
        assert ("slot_size" in errors, clones(open_shuttle)) == (True, [])


class TestSourceProjects:
    def test_the_original_is_unchanged(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        before = Project.objects.filter(pk=source.pk).values().get()
        files_before = source.files.count()
        client.force_login(source.user)

        post_clone(client, source, open_shuttle)

        after = Project.objects.filter(pk=source.pk).values().get()
        assert (after, source.files.count()) == (before, files_before)

    def test_an_archived_project_can_be_cloned(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        source.archive()
        client.force_login(source.user)

        page = client.get(source.get_absolute_url(), follow=True)
        post_clone(client, source, open_shuttle)

        assert clone_url(source) in page.content.decode()
        [clone] = clones(open_shuttle)
        assert clone.is_archived is False

    def test_a_double_submit_makes_one_clone(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        client.force_login(source.user)

        post_clone(client, source, open_shuttle)
        second = post_clone(client, source, open_shuttle)

        assert len(clones(open_shuttle)) == 1
        assert "project_id" in second.context["form"].errors

    def test_a_second_queued_copy_fails_on_the_unique_id(
        self,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        """Two tasks queued before either ran: the second creates nothing."""
        args = (str(source.pk), open_shuttle.pk, source.user.pk, "WXYZ", SlotSize.FULL)

        first = duplicate_project_task(*args)
        second = duplicate_project_task(*args)

        assert (first["status"], second["status"], len(clones(open_shuttle))) == (
            "ok",
            "failed",
            1,
        )


class TestViewWritesNoFile:
    def test_the_view_only_enqueues(
        self,
        client: Client,
        source: Project,
        open_shuttle: Shuttle,
    ) -> None:
        """The copy is the worker's: the view validates and enqueues only."""
        client.force_login(source.user)
        with (
            patch("wafer_space.projects.views.duplicate_project_task.delay") as delay,
            patch(
                "django.core.files.storage.FileSystemStorage._save",
                side_effect=AssertionError("the view wrote a file"),
            ),
        ):
            response = post_clone(client, source, open_shuttle, slot_size=SlotSize.FULL)

        assert response.status_code == HTTPStatus.FOUND
        delay.assert_called_once_with(
            str(source.pk),
            open_shuttle.pk,
            source.user.pk,
            "WXYZ",
            SlotSize.FULL,
        )
        assert clones(open_shuttle) == []
