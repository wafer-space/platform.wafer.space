"""Django admin configuration for projects app."""

from django.contrib import admin

from wafer_space.contrib.admin_mixins import StaffReadOnlyAdminMixin
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectAccessLog


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    """Admin interface for Project model."""

    list_display = ["name", "user", "slot_size", "status", "created_at", "updated_at"]
    list_filter = ["status", "slot_size", "created_at", "updated_at"]
    search_fields = ["name", "description", "user__username"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ProjectAccessLog)
class ProjectAccessLogAdmin(admin.ModelAdmin):
    """Admin interface for ProjectAccessLog model.

    This admin is read-only to preserve audit log integrity.
    Logs cannot be added, modified, or deleted through the admin interface.
    """

    list_display = [
        "accessed_at",
        "admin_user",
        "project",
        "action",
        "ip_address",
        "view_name",
    ]

    list_filter = ["action", "accessed_at", "admin_user"]

    search_fields = [
        "admin_user__username",
        "project__name",
        "ip_address",
    ]

    readonly_fields = [
        "project",
        "admin_user",
        "accessed_at",
        "action",
        "ip_address",
        "user_agent",
        "view_name",
    ]

    def has_add_permission(self, request):
        """Disable add permission - logs created automatically."""
        return False

    def has_change_permission(self, request, obj=None):
        """Disable change permission - logs are immutable."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disable delete permission - logs are permanent."""
        return False


@admin.register(ManufacturabilityCheck)
class ManufacturabilityCheckAdmin(StaffReadOnlyAdminMixin, admin.ModelAdmin):
    """Admin for manufacturability checks."""

    list_display = [
        "project",
        "status",
        "is_manufacturable",
        "celery_job_started_at",
        "celery_job_finished_at",
        "docker_image_digest",
        "rerun_requested_by",
    ]

    list_filter = [
        "status",
        "is_manufacturable",
        "celery_job_started_at",
        "celery_job_finished_at",
    ]

    search_fields = [
        "project__name",
        "project__user__username",
        "docker_image",
    ]

    readonly_fields = [
        "project",
        "celery_job_started_at",
        "celery_job_finished_at",
        "celery_job_id",
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
