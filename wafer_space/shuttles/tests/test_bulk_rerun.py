"""Bulk re-run of the prechecks the assignment page shows as Old (#203).

Staff choose, per run, whether each Old project's submitted or latest
revision is re-checked (Tim, 16 Oct 2026: "Able to choose both").
"""

from __future__ import annotations

import datetime
import re
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from wafer_space.core.enums import SlotSize
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.projects.tests.factories import ProjectFileFactory
from wafer_space.shuttles.services.bulk_rerun import NO_LONGER_OLD
from wafer_space.shuttles.services.bulk_rerun import NO_SUBMITTED_REVISION
from wafer_space.shuttles.services.bulk_rerun import RerunRevision
from wafer_space.shuttles.services.bulk_rerun import outdated_projects
from wafer_space.shuttles.services.bulk_rerun import plan_bulk_rerun
from wafer_space.shuttles.services.bulk_rerun import queue_bulk_rerun
from wafer_space.shuttles.tests.factories import ShuttleFactory
from wafer_space.users.tests.factories import UserFactory

from .test_views import CURRENT_DIGEST
from .test_views import OUTDATED_DIGEST

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.test import Client

    from wafer_space.projects.models import Project
    from wafer_space.projects.models import ProjectFile
    from wafer_space.shuttles.models import Shuttle
    from wafer_space.users.models import User

pytestmark = pytest.mark.django_db

ADMIN_RERUN = ManufacturabilityCheck.TriggerReason.ADMIN_RERUN
SUBMITTED = RerunRevision.SUBMITTED
LATEST = RerunRevision.LATEST
# The fixture's Old projects: moved_on, same and unsubmitted
OLD_COUNT = 3


@pytest.fixture(autouse=True)
def _fresh_latest_digest() -> Iterator[None]:
    # The latest precheck digest is cached for a minute.
    cache.clear()
    yield
    cache.clear()


def finished_check(project_file: ProjectFile, *, digest: str, passed: bool) -> None:
    started = timezone.now() - (
        datetime.timedelta(0)
        if digest == CURRENT_DIGEST
        else datetime.timedelta(days=30)
    )
    ManufacturabilityCheckFactory(
        project=project_file.project,
        project_file=project_file,
        status=ManufacturabilityCheck.Status.FINISHED,
        is_manufacturable=passed,
        docker_image_digest=digest,
        container_started_at=started,
        analysis_completed_at=started,
    )


def revision(project: Project, *, digest: str, passed: bool = True) -> ProjectFile:
    """A new, verified latest revision of ``project`` with a finished check."""
    project.files.update(is_active=False)
    project_file = ProjectFileFactory(
        project=project, hash_verified=True, is_active=True
    )
    finished_check(project_file, digest=digest, passed=passed)
    return project_file


def project_on(
    shuttle: Shuttle, name: str, *, digest: str = OUTDATED_DIGEST, passed: bool = True
) -> Project:
    project = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL, name=name)
    revision(project, digest=digest, passed=passed)
    return project


def submit(project: Project, project_file: ProjectFile) -> None:
    project.submitted_file = project_file
    project.save(update_fields=["submitted_file"])


def reruns(project_file: ProjectFile) -> list[ManufacturabilityCheck]:
    return list(
        project_file.manufacturability_checks.filter(trigger_reason=ADMIN_RERUN)
    )


@pytest.fixture
def staff() -> User:
    return UserFactory(is_staff=True)


@pytest.fixture
def shuttle() -> Shuttle:
    """Old projects in each state a bulk re-run tells apart.

    - ``moved_on``: submitted an older revision, then uploaded the Old one.
    - ``same``: submitted its Old latest revision.
    - ``unsubmitted``: never submitted.
    Plus projects that are not Old: current, failed, and archived.
    """
    shuttle = ShuttleFactory(name="G840")
    # A check on the current version, so OUTDATED_DIGEST is not the latest.
    project_on(shuttle, "current", digest=CURRENT_DIGEST)
    project_on(shuttle, "failed", passed=False)
    archived = project_on(shuttle, "archived")
    archived.archived_at = timezone.now()
    archived.save(update_fields=["archived_at"])

    moved_on = ProjectFactory(shuttle=shuttle, slot_size=SlotSize.FULL, name="moved_on")
    submit(moved_on, revision(moved_on, digest=OUTDATED_DIGEST))
    revision(moved_on, digest=OUTDATED_DIGEST)

    same = project_on(shuttle, "same")
    submit(same, same.files.get())

    project_on(shuttle, "unsubmitted")
    return shuttle


def named(shuttle: Shuttle, name: str) -> Project:
    return shuttle.projects.get(name=name)


def old_names(shuttle: Shuttle) -> list[str]:
    return sorted(p.name for p in outdated_projects(shuttle))


def queue(
    shuttle: Shuttle, revision_kind: RerunRevision, staff: User
) -> list[ManufacturabilityCheck]:
    """Confirm everything the plan lists, as the confirmation page does."""
    plan = plan_bulk_rerun(shuttle, revision_kind)
    result = queue_bulk_rerun(
        shuttle,
        revision_kind,
        requested_by=staff,
        confirmed=[p.project.pk for p in plan.to_queue],
    )
    return result.queued


class TestWhichProjects:
    def test_only_the_projects_the_outdated_filter_shows(
        self, shuttle: Shuttle
    ) -> None:
        assert old_names(shuttle) == ["moved_on", "same", "unsubmitted"]

    def test_the_filter_and_the_page_agree(
        self, shuttle: Shuttle, client: Client, staff: User
    ) -> None:
        """Rows flagged data-precheck-outdated="true" are the bulk set."""
        client.force_login(staff)
        content = client.get(
            reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        ).content.decode()
        flagged = [
            p.name
            for p in shuttle.projects.all()
            if re.search(
                rf'data-precheck-outdated="true">\s*<td class="font-monospace">'
                rf"{re.escape(p.full_id)}</td>",
                content,
            )
        ]

        assert sorted(flagged) == old_names(shuttle)


class TestEachChoiceQueuesTheRightRevisions:
    def test_submitted_checks_each_submitted_revision(
        self, shuttle: Shuttle, staff: User
    ) -> None:
        queued = queue(shuttle, SUBMITTED, staff)

        assert sorted((c.project.name, c.project_file) for c in queued) == [
            ("moved_on", named(shuttle, "moved_on").submitted_file),
            ("same", named(shuttle, "same").submitted_file),
        ]

    def test_latest_checks_each_latest_revision(
        self, shuttle: Shuttle, staff: User
    ) -> None:
        queued = queue(shuttle, LATEST, staff)

        assert sorted((c.project.name, c.project_file) for c in queued) == [
            (pid, named(shuttle, pid).latest_file)
            for pid in ("moved_on", "same", "unsubmitted")
        ]

    def test_moved_on_latest_is_not_its_submitted_revision(
        self, shuttle: Shuttle
    ) -> None:
        """The fixture really tells the two choices apart."""
        moved_on = named(shuttle, "moved_on")

        assert moved_on.latest_file != moved_on.submitted_file

    @pytest.mark.parametrize("revision_kind", [SUBMITTED, LATEST])
    def test_each_is_an_admin_rerun_by_the_staff_user(
        self, shuttle: Shuttle, staff: User, revision_kind: RerunRevision
    ) -> None:
        queued = queue(shuttle, revision_kind, staff)

        assert {(c.trigger_reason, c.rerun_requested_by, c.status) for c in queued} == {
            (ADMIN_RERUN, staff, ManufacturabilityCheck.Status.PENDING)
        }


class TestSkipped:
    def test_no_submitted_revision_is_skipped_under_submitted(
        self, shuttle: Shuttle
    ) -> None:
        plan = plan_bulk_rerun(shuttle, SUBMITTED)

        assert [(p.project.name, p.skip_reason) for p in plan.skipped] == [
            ("unsubmitted", NO_SUBMITTED_REVISION)
        ]

    def test_nothing_is_skipped_under_latest(self, shuttle: Shuttle) -> None:
        assert plan_bulk_rerun(shuttle, LATEST).skipped == []

    def test_a_project_that_stopped_being_old_is_not_queued(
        self, shuttle: Shuttle, staff: User
    ) -> None:
        """Between the confirmation page and the POST, a check passed."""
        same = named(shuttle, "same")
        finished_check(same.files.get(), digest=CURRENT_DIGEST, passed=True)
        cache.clear()

        result = queue_bulk_rerun(
            shuttle, SUBMITTED, requested_by=staff, confirmed=[same.pk]
        )

        reasons = [p.skip_reason for p in result.not_queued if p.project == same]

        assert (result.queued, reasons) == ([], [NO_LONGER_OLD])

    def test_a_project_not_confirmed_is_not_queued(
        self, shuttle: Shuttle, staff: User
    ) -> None:
        """One that became Old after the confirmation page was shown."""
        same = named(shuttle, "same")

        result = queue_bulk_rerun(
            shuttle, LATEST, requested_by=staff, confirmed=[same.pk]
        )

        assert [c.project for c in result.queued] == [same]


class TestTwice:
    @pytest.mark.parametrize("revision_kind", [SUBMITTED, LATEST])
    def test_a_second_run_queues_nothing_twice(
        self, shuttle: Shuttle, staff: User, revision_kind: RerunRevision
    ) -> None:
        plan = plan_bulk_rerun(shuttle, revision_kind)
        confirmed = [p.project.pk for p in plan.to_queue]
        first = queue_bulk_rerun(
            shuttle, revision_kind, requested_by=staff, confirmed=confirmed
        )

        second = queue_bulk_rerun(
            shuttle, revision_kind, requested_by=staff, confirmed=confirmed
        )
        counts = [len(reruns(c.project_file)) for c in first.queued]

        assert (second.queued, counts) == ([], [1] * len(confirmed))

    def test_the_second_run_says_why(self, shuttle: Shuttle, staff: User) -> None:
        queue(shuttle, LATEST, staff)

        plan = plan_bulk_rerun(shuttle, LATEST)
        second = queue_bulk_rerun(
            shuttle,
            LATEST,
            requested_by=staff,
            confirmed=[p.project.pk for p in plan.to_queue],
        )

        assert {p.skip_reason for p in second.not_queued} == {
            "A check of this revision is already in progress"
        }


def test_non_staff_is_refused_by_the_service(shuttle: Shuttle) -> None:
    owner = UserFactory(is_staff=False)
    plan = plan_bulk_rerun(shuttle, LATEST)

    with pytest.raises(PermissionDenied, match="Only staff"):
        queue_bulk_rerun(
            shuttle,
            LATEST,
            requested_by=owner,
            confirmed=[p.project.pk for p in plan.to_queue],
        )


def test_non_staff_is_refused_even_with_nothing_to_queue(shuttle: Shuttle) -> None:
    """The service refuses first, not only through each check it would queue."""
    with pytest.raises(PermissionDenied, match="Only staff can re-run prechecks"):
        queue_bulk_rerun(
            shuttle, LATEST, requested_by=UserFactory(is_staff=False), confirmed=[]
        )


def url(shuttle: Shuttle) -> str:
    return reverse("shuttles:rerun_outdated", kwargs={"name": shuttle.name})


def all_admin_reruns() -> int:
    return ManufacturabilityCheck.objects.filter(trigger_reason=ADMIN_RERUN).count()


class TestConfirmationPage:
    def test_states_the_count_and_the_revision_kind(
        self, shuttle: Shuttle, client: Client, staff: User
    ) -> None:
        client.force_login(staff)

        content = client.get(url(shuttle), {"revision": "submitted"}).content.decode()
        summary = re.search(r"data-rerun-summary>(.*?)</p>", content, re.DOTALL)

        assert summary is not None
        assert " ".join(re.sub(r"<[^>]+>", "", summary.group(1)).split()) == (
            "2 checks of the submitted revision will be queued."
        )

    def test_shows_the_skipped_project_and_why(
        self, shuttle: Shuttle, client: Client, staff: User
    ) -> None:
        client.force_login(staff)

        content = client.get(url(shuttle), {"revision": "submitted"}).content.decode()
        skipped = re.search(r"data-rerun-skip>(.*?)</ul>", content, re.DOTALL)

        assert skipped is not None
        assert f"unsubmitted: {NO_SUBMITTED_REVISION}" in skipped.group(1)

    def test_showing_it_queues_nothing(
        self, shuttle: Shuttle, client: Client, staff: User
    ) -> None:
        client.force_login(staff)

        client.get(url(shuttle), {"revision": "latest"})

        assert all_admin_reruns() == 0

    @pytest.mark.parametrize("value", [None, "", "both", "Latest"])
    def test_a_revision_kind_must_be_chosen(
        self, shuttle: Shuttle, client: Client, staff: User, value: str | None
    ) -> None:
        client.force_login(staff)
        params = {} if value is None else {"revision": value}

        response = client.get(url(shuttle), params)

        assert response.status_code == HTTPStatus.BAD_REQUEST


def confirmed(shuttle: Shuttle, kind: str) -> dict[str, str | list[str]]:
    """The POST the confirmation page's form sends for ``kind``."""
    plan = plan_bulk_rerun(shuttle, RerunRevision(kind))
    return {"revision": kind, "project": [str(p.project.pk) for p in plan.to_queue]}


class TestPost:
    def test_queues_and_goes_back_to_the_assignment_page(
        self, shuttle: Shuttle, client: Client, staff: User
    ) -> None:
        client.force_login(staff)

        response = client.post(url(shuttle), confirmed(shuttle, "latest"))

        assert (response.status_code, response["Location"], all_admin_reruns()) == (
            HTTPStatus.FOUND,
            reverse("shuttles:assignment", kwargs={"name": shuttle.name}),
            OLD_COUNT,
        )

    def test_reports_what_was_queued_and_skipped(
        self, shuttle: Shuttle, client: Client, staff: User
    ) -> None:
        client.force_login(staff)

        queued = ", ".join(
            p.full_id for p in outdated_projects(shuttle) if p.submitted_file
        )

        response = client.post(url(shuttle), confirmed(shuttle, "submitted"))
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        unsubmitted = named(shuttle, "unsubmitted").full_id

        assert texts == [
            f"Queued 2 precheck re-runs of the submitted revision: {queued}.",
            f"{unsubmitted} not re-checked: {NO_SUBMITTED_REVISION}.",
        ]

    def test_double_submit_queues_nothing_twice(
        self, shuttle: Shuttle, client: Client, staff: User
    ) -> None:
        client.force_login(staff)

        client.post(url(shuttle), confirmed(shuttle, "latest"))
        client.post(url(shuttle), confirmed(shuttle, "latest"))

        assert all_admin_reruns() == OLD_COUNT

    def test_an_unknown_project_is_refused(
        self, shuttle: Shuttle, client: Client, staff: User
    ) -> None:
        client.force_login(staff)

        response = client.post(
            url(shuttle), {"revision": "latest", "project": ["not-a-uuid"]}
        )

        assert (response.status_code, all_admin_reruns()) == (
            HTTPStatus.BAD_REQUEST,
            0,
        )


class TestNonStaff:
    @pytest.mark.parametrize("method", ["get", "post"])
    def test_logged_in_non_staff_is_forbidden(
        self, shuttle: Shuttle, client: Client, method: str
    ) -> None:
        client.force_login(UserFactory(is_staff=False))

        response = getattr(client, method)(url(shuttle), {"revision": "latest"})

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_a_non_staff_post_queues_nothing(
        self, shuttle: Shuttle, client: Client
    ) -> None:
        client.force_login(UserFactory(is_staff=False))

        client.post(url(shuttle), confirmed(shuttle, "latest"))

        assert all_admin_reruns() == 0

    def test_anonymous_is_sent_to_log_in(
        self, shuttle: Shuttle, client: Client
    ) -> None:
        response = client.post(url(shuttle), {"revision": "latest"})

        assert (response.status_code, all_admin_reruns()) == (HTTPStatus.FOUND, 0)
        assert "login" in response["Location"]


class TestButton:
    def test_the_assignment_page_offers_both_choices(
        self, shuttle: Shuttle, client: Client, staff: User
    ) -> None:
        client.force_login(staff)

        content = client.get(
            reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        ).content.decode()
        form = re.search(
            r"<form[^>]*data-rerun-outdated>(.*?)</form>", content, re.DOTALL
        )

        assert form is not None
        assert re.findall(r'<option value="(\w*)">', form.group(1)) == [
            "",
            "submitted",
            "latest",
        ]

    def test_the_button_counts_the_outdated_projects(
        self, shuttle: Shuttle, client: Client, staff: User
    ) -> None:
        client.force_login(staff)

        content = client.get(
            reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        ).content.decode()

        assert "Re-run 3 outdated checks…" in content

    def test_no_button_without_outdated_projects(
        self, client: Client, staff: User
    ) -> None:
        shuttle = ShuttleFactory(name="G841")
        project_on(shuttle, "current", digest=CURRENT_DIGEST)
        client.force_login(staff)

        content = client.get(
            reverse("shuttles:assignment", kwargs={"name": shuttle.name})
        ).content.decode()

        assert "data-rerun-outdated" not in content
