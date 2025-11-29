"""Admin interface for compliance certifications."""

from django.contrib import admin

from wafer_space.contrib.admin_mixins import StaffReadOnlyAdminMixin

from .models import ProjectComplianceCertification


@admin.register(ProjectComplianceCertification)
class ProjectComplianceCertificationAdmin(StaffReadOnlyAdminMixin, admin.ModelAdmin):
    """Admin for compliance certifications."""

    list_display = [
        "project",
        "certified_by",
        "certified_at",
        "export_control_compliant",
        "not_restricted_entity",
        "admin_reviewed",
    ]
    list_filter = [
        "export_control_compliant",
        "not_restricted_entity",
        "admin_reviewed",
        "certified_at",
    ]
    search_fields = [
        "project__name",
        "certified_by__username",
        "end_use_statement",
    ]
    readonly_fields = [
        "project",
        "certified_by",
        "certified_at",
        "ip_address",
        "user_agent",
        "export_control_compliant",
        "not_restricted_entity",
        "end_use_statement",
    ]
    fieldsets = [
        (
            "Project Information",
            {
                "fields": [
                    "project",
                    "certified_by",
                    "certified_at",
                ]
            },
        ),
        (
            "Attestations",
            {
                "fields": [
                    "export_control_compliant",
                    "not_restricted_entity",
                    "end_use_statement",
                ]
            },
        ),
        (
            "Tracking",
            {
                "fields": [
                    "ip_address",
                    "user_agent",
                ]
            },
        ),
        (
            "Admin Review",
            {
                "fields": [
                    "admin_reviewed",
                    "admin_reviewer",
                    "admin_notes",
                ]
            },
        ),
    ]

    def has_add_permission(self, request):
        """Disable manual creation - must be done via form."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of certifications."""
        return False
