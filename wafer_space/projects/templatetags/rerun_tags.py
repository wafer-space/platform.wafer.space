"""The staff "Run / Re-run precheck" button for one file revision (#205)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django import template
from django.urls import reverse
from django.utils import formats

from wafer_space.projects.models import ManufacturabilityCheck

if TYPE_CHECKING:
    from wafer_space.projects.models import Project
    from wafer_space.projects.models import ProjectFile

register = template.Library()

CONFIRM_PASSED_LATEST = (
    "This revision already passed its check with the latest precheck version. "
    "Queue another check anyway?"
)


# Not computed: the file's latest check is looked up only when not given.
_LOOK_UP = object()


def revision_name(project: Project, project_file: ProjectFile) -> str:
    """Which revision a button acts on, in words (CLAUDE.md: always say).

    The latest revision is the active file (Project.latest_file); read from
    loaded fields, so lists pay no query per row.
    """
    if project.submitted_file_id == project_file.pk:
        return "submitted revision"
    if project_file.is_active:
        return "latest revision"
    uploaded = formats.date_format(project_file.uploaded_at, "Y-m-d H:i")
    return f"revision uploaded {uploaded}"


@register.inclusion_tag("projects/_rerun_check_button.html", takes_context=True)
def rerun_check_button(
    context: template.Context,
    project: Project,
    project_file: ProjectFile,
    latest_check: Any = _LOOK_UP,
) -> dict[str, Any]:
    """Button state for re-running ``project_file``'s precheck, staff only.

    Hidden for non-staff, archived projects and revisions not downloaded and
    verified yet; disabled while a check of the revision is in progress; asks
    for confirmation when the revision already passed on the latest version.
    The service (create_admin_rerun_check) enforces the same rules.

    Pages that already hold the file's latest check pass it as
    ``latest_check`` (None when the file has none) to save a query per row.
    """
    request = context["request"]
    if project_file.project_id != project.pk:
        msg = f"File {project_file.pk} is not a revision of project {project.pk}"
        raise ValueError(msg)
    if (
        not request.user.is_staff
        or project.is_archived
        or not project_file.hash_verified
    ):
        return {"show": False}

    latest: ManufacturabilityCheck | None = (
        project_file.latest_manufacturability_check
        if latest_check is _LOOK_UP
        else latest_check
    )
    in_progress = (
        latest is not None
        and latest.status in ManufacturabilityCheck.Status.in_progress()
    )
    passed_on_latest = (
        latest is not None
        and latest.status == ManufacturabilityCheck.Status.FINISHED
        and latest.is_manufacturable is True
        and latest.is_using_latest_precheck is True
    )
    return {
        "show": True,
        "url": reverse(
            "projects:rerun_check",
            kwargs={"pk": project.pk, "file_pk": project_file.pk},
        ),
        "action": "Run precheck" if latest is None else "Re-run check",
        "revision": revision_name(project, project_file),
        "disabled": in_progress,
        "confirm": CONFIRM_PASSED_LATEST if passed_on_latest else "",
        "next": request.get_full_path(),
    }
