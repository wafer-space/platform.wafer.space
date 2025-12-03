"""Django admin configuration for shuttles app."""

from django.contrib import admin

from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleManifest
from wafer_space.shuttles.models import ShuttleSlot


@admin.register(Shuttle)
class ShuttleAdmin(admin.ModelAdmin):
    """Admin interface for Shuttle model."""

    list_display = (
        "name",
        "description",
        "status",
        "max_slots",
        "reserved_slots",
        "available_slots",
        "submission_deadline",
        "created_at",
    )
    list_filter = ("status", "technology_node", "foundry")
    search_fields = ("name", "description", "technology_node", "foundry")
    readonly_fields = ("created_at",)
    fieldsets = (
        (None, {"fields": ("name", "description", "status")}),
        (
            "Grid Configuration",
            {
                "fields": ("grid_config_file",),
                "classes": ("collapse",),
            },
        ),
        (
            "Dates",
            {
                "fields": (
                    "submission_deadline",
                    "production_start_date",
                    "estimated_completion_date",
                    "actual_completion_date",
                    "created_at",
                ),
            },
        ),
        (
            "Manufacturing",
            {
                "fields": ("technology_node", "foundry", "wafer_size"),
                "classes": ("collapse",),
            },
        ),
        (
            "Cost",
            {
                "fields": ("total_cost", "cost_per_slot"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(ShuttleSlot)
class ShuttleSlotAdmin(admin.ModelAdmin):
    """Admin interface for ShuttleSlot model."""

    list_display = (
        "shuttle",
        "grid_position",
        "slot_size",
        "status",
        "project",
        "reserved_by",
        "reserved_at",
    )
    list_filter = ("shuttle", "status", "slot_size")
    search_fields = (
        "shuttle__name",
        "project__name",
        "project__project_id",
        "reserved_by__username",
    )
    readonly_fields = ("created_at", "updated_at", "grid_position")
    raw_id_fields = ("project", "reserved_by")


@admin.register(ShuttleManifest)
class ShuttleManifestAdmin(admin.ModelAdmin):
    """Admin interface for ShuttleManifest model."""

    list_display = (
        "shuttle",
        "version",
        "generated_by",
        "generated_at",
    )
    list_filter = ("shuttle",)
    search_fields = ("shuttle__name", "generated_by__username")
    readonly_fields = ("generated_at", "manifest_data")
    raw_id_fields = ("generated_by",)
