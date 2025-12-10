"""Shuttle views."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from django.contrib.auth.mixins import UserPassesTestMixin
from django.db import transaction
from django.http import JsonResponse
from django.views import View
from django.views.generic import DetailView
from django.views.generic import ListView

from wafer_space.core.enums import SlotSize
from wafer_space.projects.models import Project
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot

if TYPE_CHECKING:
    from django.http import HttpRequest

    from wafer_space.users.models import User


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

        # Calculate statistics by slot size
        stats = {}
        for slot_size in SlotSize:
            # Count slots of this size
            slots = ShuttleSlot.objects.filter(shuttle=shuttle, slot_size=slot_size)
            total_slots = slots.count()
            available_slots = slots.filter(status=ShuttleSlot.Status.AVAILABLE).count()

            # Count projects of this size
            projects = shuttle.projects.filter(slot_size=slot_size)
            projects_count = projects.count()
            assigned_projects = projects.filter(shuttle_slots__isnull=False).distinct()
            assigned_count = assigned_projects.count()

            # Count manufacturable projects
            # Note: is_manufacturable is now a derived property, so we filter in Python
            project_list = list(projects)
            manufacturable_projects = [p for p in project_list if p.is_manufacturable]
            manufacturable_total = len(manufacturable_projects)
            manufacturable_assigned = sum(
                1 for p in manufacturable_projects if p.shuttle_slots.exists()
            )

            stats[slot_size] = {
                "total_slots": total_slots,
                "available_slots": available_slots,
                "projects_count": projects_count,
                "assigned_count": assigned_count,
                "manufacturable_total": manufacturable_total,
                "manufacturable_assigned": manufacturable_assigned,
            }

        context["stats"] = stats

        # Build size labels dict for JavaScript (avoids duplicating in JS)
        context["size_labels"] = {
            size.value: f"{size.label} - {size.name.replace('_', ' ').title()}"
            for size in SlotSize
        }

        # Get all projects on this shuttle with their slot assignments
        projects = shuttle.projects.select_related("user").prefetch_related(
            "shuttle_slots"
        )
        context["projects"] = projects

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
                    "is_manufacturable": project.is_manufacturable,
                    "is_assigned": bool(assigned_slots),
                    "assigned_slots": assigned_slots,
                }
            )
        context["projects_data"] = projects_data

        # Build grid for visualization
        num_rows, num_cols = shuttle.grid_dimensions
        if num_rows > 0 and num_cols > 0:
            grid = [[None for _ in range(num_cols)] for _ in range(num_rows)]
            for slot in shuttle.slots.select_related("project"):
                grid[slot.row][slot.column] = slot
            context["grid"] = grid
            context["columns"] = [
                ShuttleSlot.column_to_letters(i) for i in range(num_cols)
            ]
        else:
            context["grid"] = []
            context["columns"] = []

        return context


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
