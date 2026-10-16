"""Shuttle views."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from typing import Any
from typing import cast
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views import View
from django.views.generic import DetailView
from django.views.generic import ListView

from wafer_space.core.enums import SlotSize
from wafer_space.projects.models import Project
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.shuttles.services.bulk_rerun import BulkRerunResult
from wafer_space.shuttles.services.bulk_rerun import RerunRevision
from wafer_space.shuttles.services.bulk_rerun import passed_on_outdated_precheck
from wafer_space.shuttles.services.bulk_rerun import plan_bulk_rerun
from wafer_space.shuttles.services.bulk_rerun import queue_bulk_rerun

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http import HttpResponse

    from wafer_space.users.models import User


# "Show" filter on the assignment page (#342): value, label. The values are
# read by filterTable() in shuttles/js/assignment_dashboard.js.
SHOW_FILTER_CHOICES = (
    ("all", "All projects"),
    ("assigned", "Assigned"),
    ("unassigned", "Unassigned"),
    ("unassigned-cs", "Unassigned with CS order"),
    ("unassigned-mfg", "Unassigned and manufacturable"),
    ("unassigned-ready", "Unassigned, CS order and manufacturable"),
    # Passed, but on an outdated precheck version: may need re-checking (#203)
    ("outdated", "Latest revision passed on an outdated precheck version"),
)


class StaffRequiredMixin(UserPassesTestMixin):
    """Mixin to require staff access."""

    request: HttpRequest

    def test_func(self) -> bool:
        return self.request.user.is_staff


class ShuttleListView(StaffRequiredMixin, ListView):
    """List all shuttles."""

    model = Shuttle
    template_name = "shuttles/list.html"
    context_object_name = "shuttles"
    ordering = ("-created_at",)


class ShuttleDetailView(StaffRequiredMixin, DetailView):
    """Detail view for a shuttle."""

    model = Shuttle
    template_name = "shuttles/detail.html"
    context_object_name = "shuttle"
    slug_field = "name"
    slug_url_kwarg = "name"


class ShuttleAssignmentView(StaffRequiredMixin, DetailView):
    """Assignment dashboard for managing shuttle slot assignments."""

    model = Shuttle
    template_name = "shuttles/assignment_dashboard.html"
    context_object_name = "shuttle"
    slug_field = "name"
    slug_url_kwarg = "name"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        shuttle = self.object

        # Fetch all projects once; the same instances feed the stats, the
        # template table, the JS data and the grid slots below, so the
        # cached per-instance manufacturability properties are only
        # computed once per project.
        all_projects = list(
            shuttle.projects.filter(archived_at__isnull=True)
            .select_related("user")
            .prefetch_related("shuttle_slots")
        )
        projects_by_pk = {p.pk: p for p in all_projects}

        # Calculate statistics by slot size
        stats = {}
        for slot_size in SlotSize:
            # Count slots of this size
            slots = ShuttleSlot.objects.filter(shuttle=shuttle, slot_size=slot_size)
            total_slots = slots.count()
            available_slots = slots.filter(status=ShuttleSlot.Status.AVAILABLE).count()

            project_list = [p for p in all_projects if p.slot_size == slot_size]
            projects_count = len(project_list)
            # shuttle_slots is prefetched, so .all() hits the cache
            assigned_count = sum(1 for p in project_list if p.shuttle_slots.all())

            # Count manufacturable projects (latest file revision passing its
            # precheck — see docs/manufacturable_vs_submitted.md)
            manufacturable_projects = [
                p for p in project_list if p.latest_file_manufacturable
            ]
            manufacturable_total = len(manufacturable_projects)
            manufacturable_assigned = sum(
                1 for p in manufacturable_projects if p.shuttle_slots.all()
            )
            # Of those, the ones whose passing check ran an outdated precheck
            # version and may need re-checking (#203). A version that cannot
            # be compared (no digest recorded) counts as neither.
            outdated_projects = [
                p for p in manufacturable_projects if passed_on_outdated_precheck(p)
            ]
            outdated_total = len(outdated_projects)
            outdated_assigned = sum(
                1 for p in outdated_projects if p.shuttle_slots.all()
            )

            # Count projects with a CrowdSupply order and CoB packaging
            cs_order_projects = [p for p in project_list if p.crowd_supply_order_id]
            cs_order_total = len(cs_order_projects)
            cs_order_assigned = sum(
                1 for p in cs_order_projects if p.shuttle_slots.all()
            )
            cob_count = sum(1 for p in project_list if p.chip_on_board)

            stats[slot_size] = {
                "total_slots": total_slots,
                "available_slots": available_slots,
                "projects_count": projects_count,
                "assigned_count": assigned_count,
                "manufacturable_total": manufacturable_total,
                "manufacturable_assigned": manufacturable_assigned,
                "outdated_total": outdated_total,
                "outdated_assigned": outdated_assigned,
                "cs_order_total": cs_order_total,
                "cs_order_assigned": cs_order_assigned,
                "cob_count": cob_count,
            }

        context["stats"] = stats

        # Build size labels dict for JavaScript (avoids duplicating in JS)
        context["size_labels"] = {
            size.value: f"{size.label} - {size.name.replace('_', ' ').title()}"
            for size in SlotSize
        }

        projects = all_projects
        context["projects"] = projects

        # A closed shuttle's useful view is what was assigned to it (#342)
        context["show_filter_choices"] = SHOW_FILTER_CHOICES
        context["show_filter_default"] = "assigned" if shuttle.is_closed else "all"
        # The bulk re-run acts on the projects the "outdated" filter shows
        context["outdated_count"] = sum(
            1 for p in projects if passed_on_outdated_precheck(p)
        )
        context["rerun_revision_choices"] = RerunRevision.choices

        # Build slots_by_project data for JavaScript
        slots_by_project = {}
        for project in projects:
            slots_by_project[str(project.pk)] = [
                {
                    "id": slot.pk,
                    "position": slot.grid_position,
                    "size": slot.slot_size,
                }
                for slot in project.shuttle_slots.all()
            ]
        context["slots_by_project"] = slots_by_project

        # Build projects data for autocomplete
        projects_data = []
        for project in projects:
            assigned_slots = [
                slot.grid_position for slot in project.shuttle_slots.all()
            ]
            projects_data.append(
                {
                    "pk": project.pk,
                    "project_id": project.project_id or "",
                    "name": project.name,
                    "slot_size": project.slot_size,
                    "latest_file_manufacturable": project.latest_file_manufacturable,
                    "is_assigned": bool(assigned_slots),
                    "assigned_slots": assigned_slots,
                }
            )
        context["projects_data"] = projects_data

        # Build grid for visualization
        num_rows, num_cols = shuttle.grid_dimensions
        if num_rows > 0 and num_cols > 0:
            grid = [[None for _ in range(num_cols)] for _ in range(num_rows)]
            for slot in shuttle.slots.all():
                # Reuse the already-fetched project instances so the grid
                # tooltip hits their cached manufacturability properties.
                if slot.project_id in projects_by_pk:
                    slot.project = projects_by_pk[slot.project_id]
                grid[slot.row][slot.column] = slot
            context["grid"] = grid
            context["columns"] = [
                ShuttleSlot.column_to_letters(i) for i in range(num_cols)
            ]
        else:
            context["grid"] = []
            context["columns"] = []

        return context


def rerun_revision_or_none(value: str | None) -> RerunRevision | None:
    """The revision kind a bulk re-run request names, or None if it is invalid."""
    if value not in RerunRevision.values:
        return None
    return RerunRevision(value)


def report_bulk_rerun(request: HttpRequest, result: BulkRerunResult) -> None:
    """Tell the staff user what a bulk re-run queued and what it did not."""
    if result.queued:
        projects = ", ".join(c.project.full_id for c in result.queued)
        messages.success(
            request,
            f"Queued {len(result.queued)} precheck re-runs of the "
            f"{result.revision.label}: {projects}.",
        )
    else:
        messages.info(request, "No precheck re-runs were queued.")
    # One message per reason: a shuttle can have dozens of unsubmitted projects
    by_reason: dict[str, list[str]] = {}
    for planned in result.not_queued:
        by_reason.setdefault(planned.skip_reason, []).append(planned.project.full_id)
    for reason, full_ids in by_reason.items():
        messages.warning(
            request,
            f"{len(full_ids)} not re-checked, {reason}: {', '.join(full_ids)}.",
        )


class BulkRerunOutdatedView(StaffRequiredMixin, View):
    """Re-run the prechecks of the projects the "outdated" filter shows (#203).

    GET states what would be queued, for the revision kind chosen on the
    assignment page; POST queues it. Nothing is queued without the POST.
    """

    def get(self, request: HttpRequest, name: str) -> HttpResponse:
        shuttle = get_object_or_404(Shuttle, name=name)
        revision = rerun_revision_or_none(request.GET.get("revision"))
        if revision is None:
            return HttpResponseBadRequest("Choose the submitted or latest revision.")
        plan = plan_bulk_rerun(shuttle, revision)
        return render(
            request,
            "shuttles/rerun_outdated_confirm.html",
            {"shuttle": shuttle, "plan": plan},
        )

    def post(self, request: HttpRequest, name: str) -> HttpResponse:
        shuttle = get_object_or_404(Shuttle, name=name)
        revision = rerun_revision_or_none(request.POST.get("revision"))
        if revision is None:
            return HttpResponseBadRequest("Choose the submitted or latest revision.")
        confirmed = parse_confirmed(request.POST.getlist("project"))
        if confirmed is None:
            return HttpResponseBadRequest("Unknown project or revision.")
        result = queue_bulk_rerun(
            shuttle,
            revision,
            requested_by=cast("User", request.user),
            confirmed=confirmed,
        )
        report_bulk_rerun(request, result)
        return redirect("shuttles:assignment", name=shuttle.name)


def parse_confirmed(values: list[str]) -> dict[UUID, int] | None:
    """The confirmation form's "<project pk>:<file pk>" values, or None if bad."""
    confirmed: dict[UUID, int] = {}
    for value in values:
        project_pk, _, file_pk = value.partition(":")
        try:
            confirmed[UUID(project_pk)] = int(file_pk)
        except ValueError:
            return None
    return confirmed


class GridPreviewView(StaffRequiredMixin, DetailView):
    """Read-only grid preview showing slot occupancy."""

    model = Shuttle
    template_name = "shuttles/grid_preview.html"
    context_object_name = "shuttle"
    slug_field = "name"
    slug_url_kwarg = "name"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        shuttle = self.object

        # Get grid dimensions
        num_rows, num_cols = shuttle.grid_dimensions

        if num_rows == 0 or num_cols == 0:
            context["grid"] = []
            context["columns"] = []
            return context

        # Build grid as 2D array
        grid = [[None for _ in range(num_cols)] for _ in range(num_rows)]

        for slot in shuttle.slots.select_related("project"):
            grid[slot.row][slot.column] = slot

        context["grid"] = grid
        context["columns"] = [ShuttleSlot.column_to_letters(i) for i in range(num_cols)]

        return context


class AssignProjectView(StaffRequiredMixin, View):
    """Assign a project to a slot."""

    def post(self, request: HttpRequest, name: str) -> JsonResponse:
        try:
            # Look up shuttle by name
            shuttle = Shuttle.objects.get(name=name)

            data = json.loads(request.body)
            project_pk = data.get("project_pk")
            slot_id = data.get("slot_id")

            if not project_pk or not slot_id:
                return JsonResponse(
                    {"success": False, "error": "Missing project_pk or slot_id"},
                    status=400,
                )

            with transaction.atomic():
                # Get objects with row locking
                slot = ShuttleSlot.objects.select_for_update().get(
                    pk=slot_id, shuttle=shuttle
                )
                project = Project.objects.get(pk=project_pk, shuttle=shuttle)

                # Attempt reservation
                try:
                    # Cast is safe - StaffRequiredMixin ensures authenticated user
                    warning = slot.reserve(project, cast("User", request.user))
                    response_data: dict[str, bool | str] = {"success": True}
                    if warning:
                        response_data["warning"] = warning
                    return JsonResponse(response_data)
                except ValueError as exc:
                    return JsonResponse(
                        {"success": False, "error": str(exc)}, status=400
                    )

        except Shuttle.DoesNotExist:
            return JsonResponse(
                {"success": False, "error": "Shuttle not found"}, status=404
            )
        except (ShuttleSlot.DoesNotExist, Project.DoesNotExist):
            return JsonResponse(
                {"success": False, "error": "Slot or project not found"}, status=404
            )
        except json.JSONDecodeError:
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)


class RemoveAssignmentView(StaffRequiredMixin, View):
    """Remove a project from a slot."""

    def post(self, _request: HttpRequest, name: str, slot_id: int) -> JsonResponse:
        try:
            # Look up shuttle by name
            shuttle = Shuttle.objects.get(name=name)

            with transaction.atomic():
                slot = ShuttleSlot.objects.select_for_update().get(
                    pk=slot_id, shuttle=shuttle
                )
                slot.cancel_reservation()
                return JsonResponse({"success": True})
        except Shuttle.DoesNotExist:
            return JsonResponse(
                {"success": False, "error": "Shuttle not found"}, status=404
            )
        except ShuttleSlot.DoesNotExist:
            return JsonResponse(
                {"success": False, "error": "Slot not found"}, status=404
            )
