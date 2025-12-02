"""Shuttle views."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.mixins import UserPassesTestMixin
from django.views.generic import DetailView

from wafer_space.core.enums import SlotSize
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot

if TYPE_CHECKING:
    from django.http import HttpRequest


class StaffRequiredMixin(UserPassesTestMixin):
    """Mixin to require staff access."""

    request: HttpRequest

    def test_func(self) -> bool:
        return self.request.user.is_staff


class ShuttleDetailView(StaffRequiredMixin, DetailView):
    """Detail view for a shuttle."""

    model = Shuttle
    template_name = "shuttles/detail.html"
    context_object_name = "shuttle"


class ShuttleAssignmentView(StaffRequiredMixin, DetailView):
    """Assignment dashboard for managing shuttle slot assignments."""

    model = Shuttle
    template_name = "shuttles/assignment_dashboard.html"
    context_object_name = "shuttle"

    def get_context_data(self, **kwargs):
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

            stats[slot_size] = {
                "total_slots": total_slots,
                "available_slots": available_slots,
                "projects_count": projects_count,
                "assigned_count": assigned_count,
            }

        context["stats"] = stats

        # Get all projects on this shuttle with their slot assignments
        projects = shuttle.projects.all().prefetch_related("shuttle_slots")
        context["projects"] = projects

        return context


class GridPreviewView(StaffRequiredMixin, DetailView):
    """Read-only grid preview showing slot occupancy."""

    model = Shuttle
    template_name = "shuttles/grid_preview.html"
    context_object_name = "shuttle"

    def get_context_data(self, **kwargs):
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
        context["columns"] = [chr(65 + i) for i in range(num_cols)]  # A, B, C, ...

        return context
