"""Admin interface for Terms of Service management."""

from django.contrib import admin
from django.contrib import messages
from django.db.models import Count
from django.utils.html import format_html

from .models import TermsOfService
from .models import TermsOfServiceAcceptance
from .models import TermsOfServiceNotification
from .tasks import send_tos_update_email


@admin.register(TermsOfService)
class TermsOfServiceAdmin(admin.ModelAdmin):
    """Admin interface for TermsOfService."""

    list_display = [
        "version",
        "is_active_badge",
        "acceptance_count",
        "created_at",
        "created_by",
    ]
    list_filter = ["is_active", "created_at"]
    search_fields = ["version", "content"]
    readonly_fields = ["created_at", "created_by"]
    date_hierarchy = "created_at"
    actions = ["activate_version", "deactivate_version"]

    fieldsets = (
        (None, {"fields": ("version", "content")}),
        (
            "Status",
            {
                "fields": ("is_active",),
                "description": "Only one TOS version can be active at a time.",
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_at", "created_by"),
                "classes": ("collapse",),
            },
        ),
    )

    def get_queryset(self, request):
        """Optimize queryset with annotation."""
        qs = super().get_queryset(request)
        return qs.annotate(acceptance_count_annotated=Count("acceptances"))

    def is_active_badge(self, obj) -> str:
        """Display active status as a badge."""
        if obj.is_active:
            return format_html('<span style="color: green;">✓ Active</span>')
        return format_html('<span style="color: gray;">○ Inactive</span>')

    is_active_badge.short_description = "Status"  # type: ignore[attr-defined]

    def acceptance_count(self, obj):
        """Display number of acceptances."""
        return obj.acceptance_count_annotated

    acceptance_count.short_description = "Acceptances"  # type: ignore[attr-defined]
    acceptance_count.admin_order_field = "acceptance_count_annotated"  # type: ignore[attr-defined]

    def save_model(self, request, obj, form, change):
        """Save model and set created_by."""
        if not change:  # Only set created_by on creation
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description="Activate selected TOS version")
    def activate_version(self, request, queryset):
        """Activate selected TOS versions."""
        if queryset.count() > 1:
            self.message_user(
                request,
                "Please select only one TOS version to activate.",
                level=messages.ERROR,
            )
            return

        tos = queryset.first()
        if tos:
            tos.is_active = True
            tos.save()
            self.message_user(
                request,
                f"TOS version {tos.version} has been activated.",
                level=messages.SUCCESS,
            )

    @admin.action(description="Deactivate selected TOS versions")
    def deactivate_version(self, request, queryset):
        """Deactivate selected TOS versions."""
        count = queryset.update(is_active=False)
        self.message_user(
            request,
            f"{count} TOS version(s) have been deactivated.",
            level=messages.SUCCESS,
        )


@admin.register(TermsOfServiceAcceptance)
class TermsOfServiceAcceptanceAdmin(admin.ModelAdmin):
    """Admin interface for TermsOfServiceAcceptance."""

    list_display = [
        "user",
        "tos_version",
        "accepted_at",
        "ip_address",
    ]
    list_filter = ["tos_version", "accepted_at"]
    search_fields = ["user__username", "user__email", "ip_address"]
    readonly_fields = ["user", "tos_version", "accepted_at", "ip_address", "user_agent"]
    date_hierarchy = "accepted_at"

    fieldsets = (
        (
            None,
            {
                "fields": ("user", "tos_version", "accepted_at"),
            },
        ),
        (
            "Technical Details",
            {
                "fields": ("ip_address", "user_agent"),
                "classes": ("collapse",),
            },
        ),
    )

    def has_add_permission(self, request) -> bool:
        """Disable manual creation of acceptances."""
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        """Disable deletion of acceptances."""
        return False


@admin.register(TermsOfServiceNotification)
class TermsOfServiceNotificationAdmin(admin.ModelAdmin):
    """Admin interface for TermsOfServiceNotification."""

    list_display = [
        "user",
        "tos_version",
        "status_badge",
        "created_at",
        "sent_at",
    ]
    list_filter = ["status", "tos_version", "created_at", "sent_at"]
    search_fields = ["user__username", "user__email"]
    readonly_fields = ["user", "tos_version", "created_at", "sent_at", "error_message"]
    date_hierarchy = "created_at"
    actions = ["resend_notifications"]

    fieldsets = (
        (
            None,
            {
                "fields": ("user", "tos_version", "status"),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "sent_at"),
            },
        ),
        (
            "Error Details",
            {
                "fields": ("error_message",),
                "classes": ("collapse",),
            },
        ),
    )

    def status_badge(self, obj) -> str:
        """Display status as a colored badge."""
        colors = {
            "pending": "orange",
            "sent": "green",
            "failed": "red",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="color: {};">● {}</span>',
            color,
            obj.get_status_display(),
        )

    status_badge.short_description = "Status"  # type: ignore[attr-defined]

    def has_add_permission(self, request) -> bool:
        """Disable manual creation of notifications."""
        return False

    @admin.action(description="Resend selected notifications")
    def resend_notifications(self, request, queryset):
        """Resend failed or pending notifications."""
        count = 0
        for notification in queryset:
            if notification.status in [
                TermsOfServiceNotification.Status.PENDING,
                TermsOfServiceNotification.Status.FAILED,
            ]:
                send_tos_update_email.delay(notification.id)
                count += 1

        self.message_user(
            request,
            f"{count} notification(s) have been queued for sending.",
            level=messages.SUCCESS,
        )
