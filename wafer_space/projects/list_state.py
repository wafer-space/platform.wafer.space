"""State shown for each project on the projects list (PR #321).

The state is derived from the authoritative fields defined in
docs/manufacturable_vs_submitted.md, never from ``Project.status``, which
check completions overwrite (issue #354):

1. ``Project.submitted_file`` set: Submitted. It is flagged when that
   revision's latest finished check no longer passes.
2. Otherwise the latest revision (``Project.latest_file``): the verdict of its
   latest *finished* check (an in-flight re-check does not reset it); with no
   finished check, the state of its latest check.

``annotate_list_state`` adds the inputs as queryset annotations, so the list
costs a fixed number of queries however many projects it shows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import TypedDict

from django.db.models import Exists
from django.db.models import OuterRef
from django.db.models import Subquery
from django.db.models.functions import Coalesce

from .models import ManufacturabilityCheck
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


@dataclass(frozen=True)
class ListState:
    """One project's state on the list: what the badge says and why."""

    key: str
    label: str
    css: str
    title: str
    basis: str


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
    return projects.annotate(state_latest_file_id=latest_file_id).annotate(
        state_has_file=Exists(files),
        state_latest_verdict=Subquery(
            latest_file_checks.filter(status=finished).values("is_manufacturable")[:1]
        ),
        state_latest_check_status=Subquery(latest_file_checks.values("status")[:1]),
        state_submitted_verdict=Subquery(
            submitted_checks.values("is_manufacturable")[:1]
        ),
    )


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
CHECK_ERROR = _latest("check-error", "Check error", "bg-warning")
NOT_CHECKED = _latest("not-checked", "Not checked", "bg-secondary")


def list_state(project: WithAnnotations[Project, ListStateAnnotations]) -> ListState:
    """The list state of a project annotated by ``annotate_list_state``."""
    if project.submitted_file_id is not None:
        if project.state_submitted_verdict is False:
            return SUBMITTED_FAILING
        return SUBMITTED
    return _latest_revision_state(project)


def _latest_revision_state(
    project: WithAnnotations[Project, ListStateAnnotations],
) -> ListState:
    """State of an unsubmitted project, from its latest revision."""
    if not project.state_has_file:
        return NO_FILE
    verdict = project.state_latest_verdict
    if verdict is not None:
        return _BY_VERDICT[verdict]
    # No finished check yet: describe the latest check instead.
    status = project.state_latest_check_status
    if status in ManufacturabilityCheck.Status.in_progress():
        return CHECKING
    if status == ManufacturabilityCheck.Status.ERROR:
        return CHECK_ERROR
    return NOT_CHECKED
