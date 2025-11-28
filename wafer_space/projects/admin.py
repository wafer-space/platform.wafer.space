"""Django admin configuration for projects app."""

from django.contrib import admin

from wafer_space.contrib.admin_mixins import StaffReadOnlyAdminMixin

from .models import ManufacturabilityCheck


@admin.register(ManufacturabilityCheck)
class ManufacturabilityCheckAdmin(StaffReadOnlyAdminMixin, admin.ModelAdmin):
    """Admin for manufacturability checks."""

    list_display = [
        "project",
        "status",
        "is_manufacturable",
        "started_at",
        "completed_at",
        "docker_image_digest",
        "rerun_requested_by",
    ]

    list_filter = [
        "status",
        "is_manufacturable",
        "started_at",
        "completed_at",
    ]

    search_fields = [
        "project__name",
        "project__user__username",
        "docker_image",
    ]

    readonly_fields = [
        "project",
        "started_at",
        "completed_at",
        "task_id",
        "is_manufacturable",
        "errors",
        "warnings",
        "processing_logs",
        "docker_image",
        "docker_image_digest",
        "tool_versions",
        "precheck_version",
        "last_activity",
    ]

    fieldsets = [
        (
            "Project",
            {
                "fields": [
                    "project",
                    "status",
                ]
            },
        ),
        (
            "Results",
            {
                "fields": [
                    "is_manufacturable",
                    "errors",
                    "warnings",
                ]
            },
        ),
        (
            "Processing",
            {
                "fields": [
                    "started_at",
                    "completed_at",
                    "task_id",
                    "processing_logs",
                ],
                "classes": ["collapse"],
            },
        ),
        (
            "Version Information",
            {
                "fields": [
                    "docker_image",
                    "docker_image_digest",
                    "tool_versions",
                    "precheck_version",
                    "last_activity",
                ],
                "classes": ["collapse"],
            },
        ),
        (
            "Admin Controls",
            {
                "fields": [
                    "rerun_requested_by",
                    "rerun_reason",
                ],
                "classes": ["collapse"],
            },
        ),
    ]


# Import compliance admin to register it
from .admin_compliance import ProjectComplianceCertificationAdmin  # noqa: E402, F401
