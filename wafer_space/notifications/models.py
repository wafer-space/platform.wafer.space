"""Models for notifications system."""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    """User notification with multi-channel delivery support."""

    class Type(models.TextChoices):
        """Notification types."""

        # Download-related
        DOWNLOAD_COMPLETE = "download_complete", "Download Complete"
        DOWNLOAD_FAILED = "download_failed", "Download Failed"
        CHECKSUM_VERIFIED = "checksum_verified", "Checksum Verified"
        CHECKSUM_MISMATCH = "checksum_mismatch", "Checksum Mismatch"

        # Manufacturing-related (future)
        MANUFACTURING_COMPLETE = "manufacturing_complete", "Manufacturing Complete"

        # Legal-related (future migration from TOS app)
        TOS_UPDATE = "tos_update", "Terms of Service Update"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    notification_type = models.CharField(max_length=30, choices=Type.choices)
    title = models.CharField(max_length=200)
    message = models.TextField()

    # Generic foreign key for flexibility
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    object_id = models.UUIDField(null=True, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    # Read status
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at", "is_read"]),
            models.Index(fields=["notification_type"]),
        ]

    def __str__(self):
        return f"{self.get_notification_type_display()} for {self.user.username}"

    def mark_as_read(self):
        """Mark notification as read."""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])
