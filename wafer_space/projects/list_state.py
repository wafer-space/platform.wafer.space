"""State shown for each project on the projects list (PR #321).

The state is derived from the authoritative fields defined in
docs/manufacturable_vs_submitted.md, never from ``Project.status``, which
check completions overwrite (issue #354):

1. ``Project.submitted_file`` set: Submitted. It is flagged when that
   revision's latest finished check no longer passes.
2. Otherwise the latest revision (``Project.latest_file``): the verdict of its
   latest *finished* check (an in-flight re-check does not reset it); with no
   finished check, the state of its latest check.

Each verdict also says which precheck version gave it, and whether that is
the latest version (issue #235).

``annotate_list_state`` adds the inputs as queryset annotations, so the list
costs a fixed number of queries however many projects it shows.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import TYPE_CHECKING
from typing import TypedDict

from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Subquery
from django.db.models.functions import Coalesce

from .models import PRECHECK_DIGEST_PREFIX
from .models import DownloadAttempt
from .models import ManufacturabilityCheck
from .models import PrecheckImageRevision
from .models import ProjectFile

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django_stubs_ext import WithAnnotations

    from .models import Project

SUBMITTED_BASIS = "submitted revision"
LATEST_BASIS = "latest revision"


class ListStateAnnotations(TypedDict):
    """The annotations ``annotate_list_state`` adds."""

    state_latest_file_id: int | None
    state_has_file: bool
    state_latest_verdict: bool | None
    state_latest_check_status: str | None
    state_submitted_verdict: bool | None
    state_latest_download_status: str | None
    state_latest_digest: str | None
    state_latest_precheck_version: str | None
    state_latest_git_commit_sha: str | None
    state_latest_stamped_version: str | None
    state_submitted_digest: str | None
    state_submitted_precheck_version: str | None
    state_submitted_git_commit_sha: str | None
    state_submitted_stamped_version: str | None
    state_newest_precheck_digest: str | None


@dataclass(frozen=True)
class PrecheckVersion:
    """The precheck version that gave a verdict, against the latest one."""

    key: str
    label: str
    icon: str
    css: str
    title: str
    # For screen readers: the icon and colour say it only visually.
    status: str
    # Set when the image is recorded but its version is not known yet: its
    # short digest, which staff see on a line of its own.
    image: str = ""


@dataclass(frozen=True)
class ListState:
    """One project's state on the list: what the badge says and why."""

    key: str
    label: str
    css: str
    title: str
    basis: str
    # Set on a submitted project whose latest revision is a newer one.
    newer_revision: ListState | None = None
    # Set on a verdict: the precheck version of the check that gave it.
    precheck: PrecheckVersion | None = None


def annotate_list_state(projects: QuerySet[Project]) -> QuerySet[Project]:
    """Annotate the inputs ``list_state`` needs, one subquery each."""
    finished = ManufacturabilityCheck.Status.FINISHED
    files = ProjectFile.objects.filter(project=OuterRef("pk"))
    latest_file_id = Coalesce(
        Subquery(files.filter(is_active=True).values("pk")[:1]),
        Subquery(files.order_by("-uploaded_at").values("pk")[:1]),
    )
    # Same ordering as ProjectFile.output_check / latest_manufacturability_check.
    latest_file_checks = ManufacturabilityCheck.objects.filter(
        project_file=OuterRef("state_latest_file_id"),
    ).order_by("-created_at")
    submitted_checks = ManufacturabilityCheck.objects.filter(
        project_file=OuterRef("submitted_file"),
        status=finished,
    ).order_by("-created_at")
    latest_verdict_checks = latest_file_checks.filter(status=finished)
    return (
        projects.annotate(state_latest_file_id=latest_file_id)
        .annotate(
            state_has_file=Exists(files),
            state_latest_verdict=Subquery(
                latest_verdict_checks.values("is_manufacturable")[:1]
            ),
            state_latest_check_status=Subquery(latest_file_checks.values("status")[:1]),
            state_submitted_verdict=Subquery(
                submitted_checks.values("is_manufacturable")[:1]
            ),
            # Same ordering as ProjectFile.latest_attempt (-attempt_number).
            state_latest_download_status=Subquery(
                DownloadAttempt.objects.filter(
                    project_file=OuterRef("state_latest_file_id")
                )
                .order_by("-attempt_number")
                .values("status")[:1]
            ),
            state_latest_digest=Subquery(
                latest_verdict_checks.values("docker_image_digest")[:1]
            ),
            state_submitted_digest=Subquery(
                submitted_checks.values("docker_image_digest")[:1]
            ),
            # The version stamped on the check itself (do_analyzing), for an
            # image the catalog has no version for (#421).
            state_latest_stamped_version=Subquery(
                latest_verdict_checks.values("precheck_version")[:1]
            ),
            state_submitted_stamped_version=Subquery(
                submitted_checks.values("precheck_version")[:1]
            ),
            # Uncorrelated: the database evaluates it once for the whole list.
            state_newest_precheck_digest=Subquery(
                ManufacturabilityCheck.latest_precheck_digest_queryset()[:1]
            ),
        )
        .annotate(
            **_revision_fields("state_latest"),
            **_revision_fields("state_submitted"),
        )
    )


def _revision_fields(prefix: str) -> dict[str, Subquery]:
    """The catalogued version fields of the digest annotated as ``prefix``."""
    revision = PrecheckImageRevision.objects.filter(
        digest=OuterRef(f"{prefix}_digest"),
    )
    return {
        f"{prefix}_{field}": Subquery(revision.values(field)[:1])
        for field in ("precheck_version", "git_commit_sha")
    }


NOT_SUBMITTED = "Not submitted for manufacturing"

SUBMITTED = ListState(
    key="submitted",
    label="Submitted",
    css="bg-primary",
    title="Submitted for manufacturing",
    basis=SUBMITTED_BASIS,
)
SUBMITTED_FAILING = ListState(
    key="submitted-failing",
    label="Submitted, now failing",
    css="bg-danger",
    title="Submitted for manufacturing; its latest check failed",
    basis=SUBMITTED_BASIS,
)
NO_FILE = ListState(
    key="no-file",
    label="No file",
    css="bg-light text-muted border",
    title=NOT_SUBMITTED,
    basis="",
)


def _latest(key: str, label: str, css: str) -> ListState:
    """A state describing the latest revision of an unsubmitted project."""
    return ListState(
        key=key, label=label, css=css, title=NOT_SUBMITTED, basis=LATEST_BASIS
    )


# Verdict of the latest finished check on the latest revision.
_BY_VERDICT = {
    True: _latest("manufacturable", "Manufacturable", "bg-success"),
    False: _latest("not-manufacturable", "Not manufacturable", "bg-danger"),
}
CHECKING = _latest("checking", "Checking", "bg-info")
DOWNLOAD_FAILED = _latest("download-failed", "Download failed", "bg-danger")
DOWNLOADING = _latest("downloading", "Downloading", "bg-info")
DOWNLOAD_PENDING = _latest("download-pending", "Download pending", "bg-secondary")
CHECK_ERROR = _latest("check-error", "Check error", "bg-warning")
NOT_CHECKED = _latest("not-checked", "Not checked", "bg-secondary")


def list_state(project: WithAnnotations[Project, ListStateAnnotations]) -> ListState:
    """The list state of a project annotated by ``annotate_list_state``."""
    if project.submitted_file_id is None:
        return _latest_revision_state(project)
    state = SUBMITTED_FAILING if project.state_submitted_verdict is False else SUBMITTED
    state = replace(
        state,
        precheck=_precheck_version(
            project.state_submitted_digest,
            project.state_submitted_precheck_version,
            project.state_submitted_git_commit_sha,
            project.state_submitted_stamped_version,
            newest=project.state_newest_precheck_digest,
        ),
    )
    if project.state_latest_file_id != project.submitted_file_id:
        # Routine: a newer revision was uploaded after submission.
        state = replace(state, newer_revision=_latest_revision_state(project))
    return state


def _latest_revision_state(
    project: WithAnnotations[Project, ListStateAnnotations],
) -> ListState:
    """State of an unsubmitted project, from its latest revision."""
    if not project.state_has_file:
        return NO_FILE
    verdict = project.state_latest_verdict
    if verdict is not None:
        return replace(
            _BY_VERDICT[verdict],
            precheck=_precheck_version(
                project.state_latest_digest,
                project.state_latest_precheck_version,
                project.state_latest_git_commit_sha,
                project.state_latest_stamped_version,
                newest=project.state_newest_precheck_digest,
            ),
        )
    # No finished check yet: describe the latest check instead.
    status = project.state_latest_check_status
    if status is None:
        return _download_state(project.state_latest_download_status)
    if status in ManufacturabilityCheck.Status.in_progress():
        return CHECKING
    if status == ManufacturabilityCheck.Status.ERROR:
        return CHECK_ERROR
    return NOT_CHECKED


def _download_state(download_status: str | None) -> ListState:
    """State of a latest revision that has no check yet: its download."""
    if download_status == DownloadAttempt.Status.FAILED:
        return DOWNLOAD_FAILED
    if download_status == DownloadAttempt.Status.DOWNLOADING:
        return DOWNLOADING
    if download_status == DownloadAttempt.Status.COMPLETED:
        return NOT_CHECKED
    return DOWNLOAD_PENDING


IMAGE_NOT_RECORDED = PrecheckVersion(
    key="unrecorded",
    label="image not recorded",
    icon="question-circle",
    css="text-muted",
    title="The check did not record which precheck image it ran",
    status="version unknown",
)
VERSION_NOT_YET_KNOWN = "version not yet known"


def _precheck_version(
    digest: str | None,
    catalog_version: str | None,
    git_commit_sha: str | None,
    stamped_version: str | None,
    *,
    newest: str | None,
) -> PrecheckVersion:
    """The precheck version of a verdict's check (#421).

    Labelled by the catalog's version, else the version stamped on the
    check, else the catalog's commit; an image none of them describes yet
    is "version not yet known", with its digest in the title. The verdict
    is marked against the most recently started check's digest, the rule
    of ``ManufacturabilityCheck.is_using_latest_precheck``.
    """
    if not digest or not digest.startswith(PRECHECK_DIGEST_PREFIX):
        # No digest: checks before 16 Nov 2025 did not record one.
        # do_dispatching stores "unknown" when the pulled image has no
        # RepoDigests. Neither names an image; short_digest asserts on
        # "unknown", which made the whole list a 500 (#421).
        return IMAGE_NOT_RECORDED
    label = catalog_version or stamped_version or (git_commit_sha or "")[:7]
    marked = _against_newest(digest, newest)
    if label:
        return replace(marked, label=label)
    return replace(
        marked,
        label=VERSION_NOT_YET_KNOWN,
        title=f"{marked.title}; its version is not known yet: image {digest}",
        image=PrecheckImageRevision(digest=digest).short_digest,
    )


def _against_newest(digest: str, newest: str | None) -> PrecheckVersion:
    """Whether ``digest`` is the latest precheck image, without a label yet."""
    if newest is None:
        return PrecheckVersion(
            key="unknown",
            label="",
            icon="cloud",
            css="text-muted",
            title="Precheck version used; the latest version is not known",
            status="latest version unknown",
        )
    if digest == newest:
        return PrecheckVersion(
            key="latest",
            label="",
            icon="cloud-check-fill",
            css="text-success",
            title="Checked with the latest precheck version",
            status="latest",
        )
    return PrecheckVersion(
        key="outdated",
        label="",
        icon="cloud-arrow-up-fill",
        css="text-warning",
        title="Checked with an older precheck version than the latest",
        status="older version",
    )
