"""Models for Terms of Service management."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class TermsOfService(models.Model):
    """Terms of Service version with content."""

    version = models.CharField(
        max_length=50,
        unique=True,
        help_text="Version number (e.g., '1.0.0', '2.0.0')",
    )
    content = models.TextField(
        help_text="Full text of the Terms of Service (lorem ipsum for now)",
    )
    is_active = models.BooleanField(
        default=False,
        help_text="Whether this is the currently active version",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_tos_versions",
        help_text="Admin user who created this version",
    )

    class Meta:
        verbose_name = "Terms of Service"
        verbose_name_plural = "Terms of Service"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self) -> str:
        """String representation."""
        status = " (Active)" if self.is_active else ""
        return f"TOS v{self.version}{status}"

    def save(self, *args, **kwargs) -> None:
        """Override save to ensure only one active TOS at a time."""
        if self.is_active:
            # Deactivate all other TOS versions
            TermsOfService.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    @classmethod
    def get_active(cls):
        """Get the currently active Terms of Service version."""
        return cls.objects.filter(is_active=True).first()


class TermsOfServiceAcceptance(models.Model):
    """User acceptance of a specific TOS version."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tos_acceptances",
    )
    tos_version = models.ForeignKey(
        TermsOfService,
        on_delete=models.CASCADE,
        related_name="acceptances",
    )
    accepted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address from which the user accepted",
    )
    user_agent = models.TextField(
        blank=True,
        help_text="Browser user agent string",
    )

    class Meta:
        verbose_name = "TOS Acceptance"
        verbose_name_plural = "TOS Acceptances"
        ordering = ["-accepted_at"]
        unique_together = [["user", "tos_version"]]
        indexes = [
            models.Index(fields=["user", "-accepted_at"]),
            models.Index(fields=["tos_version"]),
        ]

    def __str__(self) -> str:
        """String representation."""
        return f"{self.user.username} accepted TOS v{self.tos_version.version}"

    @classmethod
    def has_accepted_active(cls, user) -> bool:
        """Check if user has accepted the currently active TOS."""
        if user.is_anonymous or not user.is_authenticated:
            return False

        active_tos = TermsOfService.get_active()
        if not active_tos:
            return True  # No active TOS, so no acceptance required

        return cls.objects.filter(
            user=user,
            tos_version=active_tos,
        ).exists()


class TermsOfServiceNotification(models.Model):
    """Email notification tracking for TOS updates."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tos_notifications",
    )
    tos_version = models.ForeignKey(
        TermsOfService,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(
        blank=True,
        help_text="Error message if sending failed",
    )

    class Meta:
        verbose_name = "TOS Notification"
        verbose_name_plural = "TOS Notifications"
        ordering = ["-created_at"]
        unique_together = [["user", "tos_version"]]
        indexes = [
            models.Index(fields=["user", "tos_version"]),
            models.Index(fields=["status"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self) -> str:
        """String representation."""
        return f"{self.user.username} - TOS v{self.tos_version.version} - {self.status}"

    def mark_as_sent(self) -> None:
        """Mark notification as successfully sent."""
        self.status = self.Status.SENT
        self.sent_at = timezone.now()
        self.error_message = ""
        self.save(update_fields=["status", "sent_at", "error_message"])

    def mark_as_failed(self, error_message: str) -> None:
        """Mark notification as failed with error message."""
        self.status = self.Status.FAILED
        self.error_message = error_message
        self.save(update_fields=["status", "error_message"])
