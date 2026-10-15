"""Django admin configuration for projects app."""

import uuid
from typing import Any

from django import forms
from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import URLPattern
from django.urls import path
from django.urls import reverse
from django.utils.html import format_html
from simple_history.admin import SimpleHistoryAdmin

from wafer_space.contrib.admin_mixins import StaffReadOnlyAdminMixin
from wafer_space.projects.exceptions import ProjectDuplicationError
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import FileProcessingError
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import ManufacturabilityCheckpoint
from wafer_space.projects.models import ManufacturabilityCheckTask
from wafer_space.projects.models import PrecheckImageRevision
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectAccessLog
from wafer_space.projects.models import ProjectFileChunk
from wafer_space.projects.models import log_tail_expressions
from wafer_space.projects.models import whole_log_lines
from wafer_space.projects.services import ELIGIBLE_TARGET_SHUTTLE_STATUSES
from wafer_space.projects.services import duplicate_project_task
from wafer_space.projects.services import validate_duplication
from wafer_space.shuttles.models import Shuttle


class DuplicateProjectForm(forms.Form):
    """Pick the shuttle to duplicate a project onto."""

    target_shuttle = forms.ModelChoiceField(
        queryset=Shuttle.objects.none(),
        label="Target shuttle",
        help_text="The duplicate is created as a draft on this shuttle.",
    )

    def __init__(
        self,
        *args: Any,
        source_shuttle: Shuttle | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        queryset = Shuttle.objects.filter(
            status__in=ELIGIBLE_TARGET_SHUTTLE_STATUSES,
        ).order_by("name")
        if source_shuttle is not None:
            queryset = queryset.exclude(pk=source_shuttle.pk)
        target_shuttle_field = self.fields["target_shuttle"]
        if isinstance(target_shuttle_field, forms.ModelChoiceField):
            target_shuttle_field.queryset = queryset


class SubmissionOverrideFilter(admin.SimpleListFilter):
    """Filter projects by whether staff submitted them by override (#252)."""

    title = "submitted by override"
    parameter_name = "submission_override"

    def lookups(
        self,
        request: HttpRequest,
        model_admin: "admin.ModelAdmin[Project]",
    ) -> list[tuple[str, str]]:
        return [("yes", "Yes"), ("no", "No")]

    def queryset(
        self,
        request: HttpRequest,
        queryset: QuerySet[Project],
    ) -> QuerySet[Project]:
        if self.value() == "yes":
            return queryset.filter(submission_override_by__isnull=False)
        if self.value() == "no":
            return queryset.filter(submission_override_by__isnull=True)
        return queryset


@admin.register(Project)
class ProjectAdmin(StaffReadOnlyAdminMixin, SimpleHistoryAdmin):
    """Admin interface for Project model."""

    list_display = [
        "name",
        "user",
        "shuttle",
        "project_id",
        "full_id",
        "slot_size",
        "status",
        "crowd_supply_order_id",
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
        "archived_at",
        SubmissionOverrideFilter,
    ]
    search_fields = [
        "name",
        "description",
        "user__username",
        "project_id",
        "crowd_supply_order_id",
        "shuttle__name",
        "repository_url",
        "other_license_spdx_id",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
        "archived_at",
        "submission_override_by",
        "submission_override_reason",
    ]

    def revert_disabled(
        self,
        request: HttpRequest,
        obj: Project | None = None,
    ) -> bool:
        """Never offer simple_history's "Revert" button for projects.

        Tim, issue #345: reverting a project from its history is removed
        for everyone; history versions stay readable.
        """
        return True

    def history_form_view(
        self,
        request: HttpRequest,
        object_id: str,
        version_id: str,
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        """Show a history version read-only; refuse every revert POST.

        simple_history saves the historical version on POST after checking
        only view-or-change permission, so the POST is refused here for all
        users, superusers included (issue #345; #343 for read-only staff).
        """
        if request.method == "POST":
            raise PermissionDenied
        return super().history_form_view(
            request,
            object_id,
            version_id,
            extra_context,
        )

    def get_urls(self) -> list[URLPattern]:
        urls = super().get_urls()
        custom_urls = [
            path(
                "<uuid:object_id>/duplicate/",
                self.admin_site.admin_view(self.duplicate_view),
                name="projects_project_duplicate",
            ),
        ]
        return custom_urls + urls

    def duplicate_view(
        self,
        request: HttpRequest,
        object_id: uuid.UUID,
    ) -> HttpResponse:
        """Intermediate page: pick a target shuttle, then duplicate."""
        project = self.get_object(request, str(object_id))
        if project is None:
            return self._get_obj_does_not_exist_redirect(
                request,
                self.opts,
                str(object_id),
            )
        if not self.has_add_permission(request):
            raise PermissionDenied

        form = DuplicateProjectForm(
            request.POST if request.method == "POST" else None,
            source_shuttle=project.shuttle,
        )
        if request.method == "POST" and form.is_valid():
            target_shuttle = form.cleaned_data["target_shuttle"]
            try:
                # Pre-flight for immediate feedback; the task re-validates.
                validate_duplication(project, target_shuttle)
            except ProjectDuplicationError as exc:
                messages.error(request, str(exc))
            else:
                # The copy writes user-file storage, which deployed web
                # processes cannot do (read-only mount) — it must run in
                # the http:rw:downloads worker. Enqueued without
                # transaction.on_commit: this view writes nothing the
                # task depends on, and on_commit would skip the task in
                # eager-mode tests.
                duplicate_project_task.delay(
                    str(project.pk),
                    target_shuttle.pk,
                    request.user.pk,
                )
                messages.success(
                    request,
                    f"Duplication onto shuttle {target_shuttle.name} has "
                    "been queued. The new draft project will appear on "
                    "that shuttle shortly; the outcome is recorded in "
                    "this project's admin history.",
                )
                return redirect(
                    reverse(
                        "admin:projects_project_change",
                        args=[project.pk],
                    ),
                )

        source_file = project.files.filter(is_active=True).first()
        context = {
            **self.admin_site.each_context(request),
            "title": f"Duplicate {project.name}",
            "opts": self.opts,
            "project": project,
            "source_file": source_file,
            "form": form,
        }
        return TemplateResponse(
            request,
            "admin/projects/project/duplicate_confirm.html",
            context,
        )


@admin.register(ProjectAccessLog)
class ProjectAccessLogAdmin(StaffReadOnlyAdminMixin, admin.ModelAdmin):
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
        "details",
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
        "processing_logs_tail_display",
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
                    "processing_logs_tail_display",
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

    def get_queryset(self, request: HttpRequest) -> QuerySet[ManufacturabilityCheck]:
        """Never load whole logs: they reach megabytes (issue #308)."""
        return super().get_queryset(request).defer("processing_logs")

    @admin.display(description="Processing logs (end)")
    def processing_logs_tail_display(self, obj: ManufacturabilityCheck) -> str:
        """The log's tail, computed in SQL, with a link to the whole log."""
        if not obj.pk:
            return "-"
        tail = log_tail_expressions()
        values = (
            ManufacturabilityCheck.objects.filter(pk=obj.pk)
            .values(
                processing_logs_tail=tail["processing_logs_tail"],
                processing_logs_truncated=tail["processing_logs_truncated"],
            )
            .get()
        )
        truncated = bool(values["processing_logs_truncated"])
        shown = whole_log_lines(
            str(values["processing_logs_tail"] or ""), truncated=truncated
        )
        url = reverse(
            "projects:check_log",
            kwargs={"pk": obj.project_id, "check_id": obj.pk},
        )
        return format_html(
            '<a href="{}">Full log</a>{}<pre style="max-height: 400px; '
            'overflow-y: auto">{}</pre>',
            url,
            " (showing the end)" if truncated else "",
            shown,
        )


@admin.register(PrecheckImageRevision)
class PrecheckImageRevisionAdmin(StaffReadOnlyAdminMixin, admin.ModelAdmin):
    """Admin for PrecheckImageRevision."""

    list_display = [
        "short_digest",
        "precheck_version",
        "git_commit_sha_short",
        "first_seen_at",
        "checks_count",
        "metadata_fetched_at",
        "metadata_fetch_problem",
        "metadata_fetch_attempts",
        "metadata_fetch_last_error",
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

# Admin registrations for download/manufacturability audit models (issue #248)


@admin.register(DownloadAttempt)
class DownloadAttemptAdmin(StaffReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "project_file",
        "attempt_number",
        "status",
        "bytes_downloaded",
        "download_progress_display",
        "started_at",
        "completed_at",
        "last_activity",
    )

    list_filter = (
        "status",
        "started_at",
        "completed_at",
    )

    search_fields = (
        "project_file__original_filename",
        "worker_hostname",
    )

    readonly_fields = (
        "project_file",
        "attempt_number",
        "status",
        "started_at",
        "completed_at",
        "download_started_at",
        "download_completed_at",
        "download_duration_seconds",
        "bytes_downloaded",
        "worker_pid",
        "worker_hostname",
        "task_started_at",
        "last_activity",
    )

    ordering = ("-started_at",)

    @admin.display(description="Progress")
    def download_progress_display(self, obj: DownloadAttempt) -> str:
        return f"{obj.download_progress}%"


@admin.register(FileProcessingError)
class FileProcessingErrorAdmin(StaffReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "download_attempt",
        "error_type",
        "error_message_preview",
        "occurred_at",
    )

    list_filter = (
        "error_type",
        "occurred_at",
    )

    search_fields = (
        "error_message",
        "download_attempt__project_file__original_filename",
    )

    readonly_fields = (
        "download_attempt",
        "error_type",
        "error_message",
        "error_detail",
        "occurred_at",
    )

    ordering = ("-occurred_at",)

    @admin.display(description="Error Message")
    def error_message_preview(self, obj: FileProcessingError) -> str:
        return obj.error_message[:75]


@admin.register(ProjectFileChunk)
class ProjectFileChunkAdmin(StaffReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "download_attempt",
        "chunk_number",
        "bytes_downloaded",
        "timestamp",
    )

    list_filter = ("timestamp",)

    search_fields = ("download_attempt__project_file__original_filename",)

    readonly_fields = (
        "download_attempt",
        "chunk_number",
        "bytes_downloaded",
        "timestamp",
    )

    ordering = ("download_attempt", "chunk_number")


@admin.register(ManufacturabilityCheckTask)
class ManufacturabilityCheckTaskAdmin(StaffReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "manufacturability_check",
        "task_name",
        "task_id",
        "queued_at",
    )

    list_filter = (
        "task_name",
        "queued_at",
    )

    search_fields = ("task_id",)

    readonly_fields = (
        "manufacturability_check",
        "task_name",
        "task_id",
        "queued_at",
    )

    ordering = ("-queued_at",)


@admin.register(ManufacturabilityCheckpoint)
class ManufacturabilityCheckpointAdmin(StaffReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "manufacturability_check",
        "checkpoint_number",
        "elapsed_seconds",
        "cpu_percent_formatted",
        "memory_usage_formatted",
        "timestamp",
    )

    list_filter = (
        "timestamp",
        "container_state",
    )

    search_fields = ("manufacturability_check__id",)

    readonly_fields = (
        "manufacturability_check",
        "checkpoint_number",
        "elapsed_seconds",
        "timestamp",
        "cpu_percent",
        "cpu_total_usage",
        "cpu_system_usage",
        "cpu_online_cpus",
        "memory_usage_bytes",
        "memory_limit_bytes",
        "memory_percent",
        "memory_cache_bytes",
        "block_read_bytes",
        "block_write_bytes",
        "network_rx_bytes",
        "network_tx_bytes",
        "container_state",
        "raw_stats_json",
    )

    ordering = ("manufacturability_check", "checkpoint_number")
