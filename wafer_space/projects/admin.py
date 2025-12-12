"""Django admin configuration for projects app."""

from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from wafer_space.contrib.admin_mixins import StaffReadOnlyAdminMixin
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import PrecheckImageRevision
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectAccessLog


@admin.register(Project)
class ProjectAdmin(SimpleHistoryAdmin):
    """Admin interface for Project model."""

    list_display = [
        "name",
        "user",
        "shuttle",
        "project_id",
        "full_id",
        "slot_size",
        "status",
        "is_public",
        "license_type",
        "created_at",
        "updated_at",
    ]
    list_filter = [
        "status",
        "shuttle",
        "slot_size",
        "is_public",
        "license_type",
        "created_at",
        "updated_at",
    ]
    search_fields = [
        "name",
        "description",
        "user__username",
        "project_id",
        "shuttle__name",
        "repository_url",
        "other_license_spdx_id",
    ]
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
        "trigger_reason",
        "parent_check",
        "is_manufacturable",
        "container_started_at",
        "analysis_completed_at",
        "docker_image_digest",
        "rerun_requested_by",
    ]

    list_filter = [
        "status",
        "trigger_reason",
        "is_manufacturable",
        "container_started_at",
        "analysis_completed_at",
    ]

    search_fields = [
        "project__name",
        "project__user__username",
        "docker_image",
    ]

    readonly_fields = [
        "project",
        "trigger_reason",
        "parent_check",
        "created_at",
        "dispatching_started_at",
        "starting_started_at",
        "container_started_at",
        "container_finished_at",
        "analysis_completed_at",
        "last_activity",
        "is_manufacturable",
        "errors",
        "warnings",
        "error_message",
        "processing_logs",
        "docker_server_id",
        "docker_container_id",
        "docker_image",
        "docker_image_digest",
        "tool_versions",
        "precheck_version",
    ]

    fieldsets = [
        (
            "Project",
            {
                "fields": [
                    "project",
                    "status",
                    "trigger_reason",
                    "parent_check",
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
                    "error_message",
                ]
            },
        ),
        (
            "Timing",
            {
                "fields": [
                    "created_at",
                    "dispatching_started_at",
                    "starting_started_at",
                    "container_started_at",
                    "container_finished_at",
                    "analysis_completed_at",
                ],
                "classes": ["collapse"],
            },
        ),
        (
            "Docker & Version Info",
            {
                "fields": [
                    "docker_server_id",
                    "docker_container_id",
                    "docker_image",
                    "docker_image_digest",
                    "tool_versions",
                    "precheck_version",
                ],
                "classes": ["collapse"],
            },
        ),
        (
            "Processing Logs",
            {
                "fields": [
                    "processing_logs",
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


@admin.register(PrecheckImageRevision)
class PrecheckImageRevisionAdmin(admin.ModelAdmin):
    """Admin for PrecheckImageRevision."""

    list_display = [
        "short_digest",
        "precheck_version",
        "git_commit_sha_short",
        "first_seen_at",
        "checks_count",
        "metadata_fetched_at",
    ]
    list_filter = ["first_seen_at", "metadata_fetched_at"]
    search_fields = ["digest", "git_commit_sha", "precheck_version"]
    readonly_fields = [
        "digest",
        "first_seen_at",
        "short_digest",
        "github_commit_url",
        "ghcr_package_url",
        "checks_count",
        "checks_passed_count",
        "checks_failed_count",
    ]
    ordering = ["-first_seen_at"]

    @admin.display(description="Commit")
    def git_commit_sha_short(self, obj: PrecheckImageRevision) -> str:
        """Display truncated git commit SHA."""
        if obj.git_commit_sha:
            return obj.git_commit_sha[:7]
        return "-"


# Import compliance admin to register it
from .admin_compliance import ProjectComplianceCertificationAdmin  # noqa: E402, F401
