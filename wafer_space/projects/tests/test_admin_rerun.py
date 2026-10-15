"""Staff re-run of one revision's precheck (#205).

Staff queue a fresh check of a named file revision; it is recorded as
ADMIN_RERUN with the requesting user. Owners cannot: they re-upload.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from html.parser import HTMLParser
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any

import pytest
from django.core.exceptions import PermissionDenied
from django.template import Context
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects.check_operations import AdminRerunRefusedError
from wafer_space.projects.check_operations import create_admin_rerun_check
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.templatetags.rerun_tags import rerun_check_button
from wafer_space.projects.templatetags.rerun_tags import revision_name
from wafer_space.shuttles.tests.factories import ShuttleFactory
from wafer_space.users.tests.factories import UserFactory

from .factories import ManufacturabilityCheckFactory
from .factories import ProjectFactory
from .factories import ProjectFileFactory

if TYPE_CHECKING:
    from django.test import Client

    from wafer_space.users.models import User

pytestmark = pytest.mark.django_db

Status = ManufacturabilityCheck.Status
ADMIN_RERUN = ManufacturabilityCheck.TriggerReason.ADMIN_RERUN


def verified_file(project: Project) -> ProjectFile:
    """A downloaded, hash-verified revision of ``project``."""
    return ProjectFileFactory(project=project, hash_verified=True)


def admin_reruns(project_file: ProjectFile) -> list[ManufacturabilityCheck]:
    checks = project_file.manufacturability_checks
    return list(checks.filter(trigger_reason=ADMIN_RERUN))


class TestService:
    def test_staff_rerun_is_recorded_with_the_requesting_user(self) -> None:
        staff = UserFactory(is_staff=True)
        project = ProjectFactory()
        revision = verified_file(project)

        check = create_admin_rerun_check(project, revision, requested_by=staff)

        assert (
            check.status,
            check.trigger_reason,
            check.rerun_requested_by,
            check.parent_check,
            check.project_file,
        ) == (Status.PENDING, ADMIN_RERUN, staff, None, revision)

    def test_non_staff_is_refused(self) -> None:
        project = ProjectFactory()
        revision = verified_file(project)

        with pytest.raises(PermissionDenied):
            create_admin_rerun_check(project, revision, requested_by=project.user)
        assert admin_reruns(revision) == []

    def test_another_projects_file_is_refused(self) -> None:
        staff = UserFactory(is_staff=True)
        other_revision = verified_file(ProjectFactory())

        with pytest.raises(AdminRerunRefusedError, match="another project"):
            create_admin_rerun_check(
                ProjectFactory(),
                other_revision,
                requested_by=staff,
            )
        assert admin_reruns(other_revision) == []

    def test_archived_project_is_refused(self) -> None:
        project = ProjectFactory(archived_at=timezone.now())

        with pytest.raises(AdminRerunRefusedError, match="archived"):
            create_admin_rerun_check(
                project,
                verified_file(project),
                requested_by=UserFactory(is_staff=True),
            )

    def test_unverified_file_is_refused(self) -> None:
        project = ProjectFactory()
        revision = ProjectFileFactory(project=project, hash_verified=False)

        with pytest.raises(AdminRerunRefusedError, match="not downloaded"):
            create_admin_rerun_check(
                project,
                revision,
                requested_by=UserFactory(is_staff=True),
            )

    @pytest.mark.parametrize("status", Status.in_progress())
    def test_revision_with_a_check_in_progress_is_refused(self, status: str) -> None:
        project = ProjectFactory()
        revision = verified_file(project)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=revision,
            status=status,
        )

        with pytest.raises(AdminRerunRefusedError, match="already in progress"):
            create_admin_rerun_check(
                project,
                revision,
                requested_by=UserFactory(is_staff=True),
            )

    @pytest.mark.parametrize(
        ("status", "verdict"),
        [(Status.FINISHED, True), (Status.FINISHED, False), (Status.ERROR, None)],
    )
    def test_finished_or_failed_revision_can_be_rerun(
        self,
        *,
        status: str,
        verdict: bool | None,
    ) -> None:
        project = ProjectFactory()
        revision = verified_file(project)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=revision,
            status=status,
            is_manufacturable=verdict,
        )

        create_admin_rerun_check(
            project,
            revision,
            requested_by=UserFactory(is_staff=True),
        )

        assert len(admin_reruns(revision)) == 1

    def test_second_request_while_the_first_is_queued_is_refused(self) -> None:
        """Double submit: the first request's PENDING check blocks the second."""
        staff = UserFactory(is_staff=True)
        project = ProjectFactory()
        revision = verified_file(project)
        create_admin_rerun_check(project, revision, requested_by=staff)

        with pytest.raises(AdminRerunRefusedError, match="already in progress"):
            create_admin_rerun_check(project, revision, requested_by=staff)
        assert len(admin_reruns(revision)) == 1


class TestView:
    @staticmethod
    def url(project: Project, revision: ProjectFile) -> str:
        return reverse(
            "projects:rerun_check",
            kwargs={"pk": project.pk, "file_pk": revision.pk},
        )

    def test_anonymous_is_sent_to_login(self, client: Client) -> None:
        project = ProjectFactory()
        revision = verified_file(project)

        response = client.post(self.url(project, revision))

        assert (response.status_code, admin_reruns(revision)) == (
            HTTPStatus.FOUND,
            [],
        )
        assert reverse("account_login") in response["Location"]

    def test_owner_is_forbidden(self, client: Client) -> None:
        project = ProjectFactory()
        revision = verified_file(project)
        client.force_login(project.user)

        response = client.post(self.url(project, revision))

        assert (response.status_code, admin_reruns(revision)) == (
            HTTPStatus.FORBIDDEN,
            [],
        )

    def test_get_is_not_allowed(self, client: Client) -> None:
        project = ProjectFactory()
        revision = verified_file(project)
        client.force_login(UserFactory(is_staff=True))

        response = client.get(self.url(project, revision))

        assert (response.status_code, admin_reruns(revision)) == (
            HTTPStatus.METHOD_NOT_ALLOWED,
            [],
        )

    def test_staff_post_queues_the_check_and_returns_to_the_project(
        self,
        client: Client,
    ) -> None:
        staff = UserFactory(is_staff=True)
        project = ProjectFactory()
        revision = verified_file(project)
        client.force_login(staff)

        response = client.post(self.url(project, revision))

        [check] = admin_reruns(revision)
        assert (
            response.status_code,
            response["Location"],
            check.rerun_requested_by,
        ) == (HTTPStatus.FOUND, project.get_absolute_url(), staff)

    def test_safe_next_is_followed(self, client: Client) -> None:
        project = ProjectFactory()
        revision = verified_file(project)
        client.force_login(UserFactory(is_staff=True))
        back = reverse("projects:admin_check_status")

        response = client.post(self.url(project, revision), {"next": back})

        assert response["Location"] == back

    def test_offsite_next_is_ignored(self, client: Client) -> None:
        project = ProjectFactory()
        revision = verified_file(project)
        client.force_login(UserFactory(is_staff=True))

        response = client.post(
            self.url(project, revision),
            {"next": "https://evil.example/"},
        )

        assert response["Location"] == project.get_absolute_url()

    def test_refusal_is_reported_and_creates_nothing(self, client: Client) -> None:
        project = ProjectFactory()
        revision = ProjectFileFactory(project=project, hash_verified=False)
        client.force_login(UserFactory(is_staff=True))

        response = client.post(self.url(project, revision), follow=True)

        messages = [str(m) for m in response.context["messages"]]
        assert (admin_reruns(revision), messages) == (
            [],
            ["Precheck not re-run: This revision is not downloaded and verified yet."],
        )


class _RerunForms(HTMLParser):
    """Each staff re-run form on a page: action, button text, disabled, confirm."""

    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict[str, Any]] = []
        self._in_button = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if tag == "form" and "data-rerun-check" in found:
            self.forms.append(
                {
                    "action": found.get("action"),
                    "confirm": "onsubmit" in found,
                    "disabled": False,
                    "text": "",
                },
            )
        elif tag == "button" and self.forms and not self.forms[-1]["text"]:
            self.forms[-1]["disabled"] = "disabled" in found
            self._in_button = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "button":
            self._in_button = False

    def handle_data(self, data: str) -> None:
        if self._in_button:
            text = f"{self.forms[-1]['text']} {data}"
            self.forms[-1]["text"] = " ".join(text.split())


def rerun_forms(client: Client, user: User, project: Project) -> list[dict[str, Any]]:
    client.force_login(user)
    response = client.get(project.get_absolute_url(), follow=True)
    parser = _RerunForms()
    parser.feed(response.content.decode())
    return parser.forms


class TestButton:
    def test_owner_sees_no_button(self, client: Client) -> None:
        project = ProjectFactory()
        verified_file(project)

        assert rerun_forms(client, project.user, project) == []

    def test_unchecked_revision_offers_run_precheck(self, client: Client) -> None:
        project = ProjectFactory()
        revision = verified_file(project)

        assert rerun_forms(client, UserFactory(is_staff=True), project) == [
            {
                "action": TestView.url(project, revision),
                "confirm": False,
                "disabled": False,
                "text": "Run precheck (latest revision)",
            },
        ]

    def test_each_button_names_its_revision(self, client: Client) -> None:
        """Submitted and a newer latest revision: one button each, named."""
        project = ProjectFactory()
        submitted = verified_file(project)
        project.submitted_file = submitted
        project.save()
        ProjectFile.objects.filter(pk=submitted.pk).update(is_active=False)
        latest = verified_file(project)
        for revision, verdict in ((submitted, True), (latest, False)):
            ManufacturabilityCheckFactory(
                project=project,
                project_file=revision,
                status=Status.FINISHED,
                is_manufacturable=verdict,
            )

        forms = rerun_forms(client, UserFactory(is_staff=True), project)

        assert sorted((form["action"], form["text"]) for form in forms) == sorted(
            [
                (TestView.url(project, submitted), "Re-run check (submitted revision)"),
                (TestView.url(project, latest), "Re-run check (latest revision)"),
            ],
        )

    def test_disabled_while_a_check_is_in_progress(self, client: Client) -> None:
        project = ProjectFactory()
        revision = verified_file(project)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=revision,
            status=Status.RUNNING,
        )

        [form] = rerun_forms(client, UserFactory(is_staff=True), project)

        assert form["disabled"] is True

    def test_passed_on_the_latest_version_asks_first(self, client: Client) -> None:
        project = ProjectFactory()
        revision = verified_file(project)
        digest = "sha256:" + "c" * 64
        ManufacturabilityCheckFactory(
            project=project,
            project_file=revision,
            status=Status.FINISHED,
            is_manufacturable=True,
            docker_image_digest=digest,
            container_started_at=timezone.now(),
        )

        [form] = rerun_forms(client, UserFactory(is_staff=True), project)

        assert (form["confirm"], form["text"]) == (
            True,
            "Re-run check (latest revision)",
        )

    def test_failed_revision_reruns_without_asking(self, client: Client) -> None:
        project = ProjectFactory()
        revision = verified_file(project)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=revision,
            status=Status.FINISHED,
            is_manufacturable=False,
        )

        [form] = rerun_forms(client, UserFactory(is_staff=True), project)

        assert form["confirm"] is False

    def test_archived_project_has_no_button(self, client: Client) -> None:
        project = ProjectFactory(archived_at=timezone.now())
        verified_file(project)

        assert rerun_forms(client, UserFactory(is_staff=True), project) == []


class TestTag:
    def test_another_projects_file_raises(self) -> None:
        """A page passing the wrong project fails loudly, never a button."""
        project = ProjectFactory()
        other_revision = verified_file(ProjectFactory())
        request = RequestFactory().get("/")
        request.user = UserFactory(is_staff=True)

        with pytest.raises(ValueError, match="is not a revision of project"):
            rerun_check_button(Context({"request": request}), project, other_revision)

    def test_older_revision_is_named_by_its_upload_time(self) -> None:
        project = ProjectFactory()
        older = verified_file(project)
        ProjectFile.objects.filter(pk=older.pk).update(
            is_active=False,
            uploaded_at=datetime(2026, 10, 3, 9, 4, 5, tzinfo=UTC),
        )
        older.refresh_from_db()

        assert revision_name(project, older) == (
            "revision uploaded 2026-10-03 09:04:05 UTC"
        )


def rerun_forms_at(client: Client, url: str) -> list[dict[str, Any]]:
    client.force_login(UserFactory(is_staff=True))
    parser = _RerunForms()
    parser.feed(client.get(url).content.decode())
    return parser.forms


class TestCheckStatusPage:
    """Offered on a failed or outdated check that is still its file's latest."""

    URL = "projects:admin_check_status"

    def test_failed_latest_check_offers_a_rerun(self, client: Client) -> None:
        project = ProjectFactory()
        revision = verified_file(project)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=revision,
            status=Status.FINISHED,
            is_manufacturable=False,
        )

        forms = rerun_forms_at(client, reverse(self.URL))

        assert [(f["action"], f["text"]) for f in forms] == [
            (TestView.url(project, revision), "Re-run check (latest revision)"),
        ]

    def test_superseded_failure_offers_nothing(self, client: Client) -> None:
        """A newer check of the same file replaces it; only that one counts."""
        project = ProjectFactory()
        revision = verified_file(project)
        failed = ManufacturabilityCheckFactory(
            project=project,
            project_file=revision,
            status=Status.FINISHED,
            is_manufacturable=False,
        )
        ManufacturabilityCheck.objects.filter(pk=failed.pk).update(
            created_at=timezone.now() - timedelta(hours=1),
        )
        ManufacturabilityCheckFactory(
            project=project,
            project_file=revision,
            status=Status.FINISHED,
            is_manufacturable=True,
        )

        assert rerun_forms_at(client, reverse(self.URL)) == []

    def test_passing_check_offers_nothing(self, client: Client) -> None:
        project = ProjectFactory()
        ManufacturabilityCheckFactory(
            project=project,
            project_file=verified_file(project),
            status=Status.FINISHED,
            is_manufacturable=True,
        )

        assert rerun_forms_at(client, reverse(self.URL)) == []


class TestSlotAllocationPage:
    """Per project, on the submitted revision only (Tim's spec, #205)."""

    @staticmethod
    def url(name: str) -> str:
        return reverse("shuttles:assignment", args=[name])

    def test_submitted_project_offers_its_submitted_revision(
        self,
        client: Client,
    ) -> None:
        project = ProjectFactory(shuttle=ShuttleFactory(name="G871"))
        submitted = verified_file(project)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=submitted,
            status=Status.FINISHED,
            is_manufacturable=True,
        )
        project.submitted_file = submitted
        project.save()

        forms = rerun_forms_at(client, self.url("G871"))

        assert [(f["action"], f["text"]) for f in forms] == [
            (TestView.url(project, submitted), "Re-run check (submitted revision)"),
        ]

    def test_unsubmitted_project_offers_nothing(self, client: Client) -> None:
        """No fallback to the latest revision on this page."""
        project = ProjectFactory(shuttle=ShuttleFactory(name="G872"))
        verified_file(project)

        assert rerun_forms_at(client, self.url("G872")) == []
