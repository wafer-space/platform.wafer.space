"""Models for Terms of Service management."""

from pathlib import Path

import frontmatter
import markdown
from django.conf import settings
from django.db import models
from django.utils import timezone

from .utils import get_tos_versions_directory
from .utils import write_frontmatter_file


class TermsOfService(models.Model):
    """Terms of Service version metadata (content stored in markdown files)."""

    version = models.CharField(
        max_length=50,
        unique=True,
        help_text="Version number (e.g., '1.0.0', '2.0.0')",
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
            # Deactivate all other TOS versions in the database
            TermsOfService.objects.exclude(pk=self.pk).update(is_active=False)
            # Update is_active in all markdown files
            self._update_active_status_in_files()
        super().save(*args, **kwargs)

    @property
    def content_file_path(self) -> Path:
        """Get the path to the markdown file for this version."""
        return get_tos_versions_directory() / f"{self.version}.md"

    @property
    def _frontmatter_post(self):
        """Load and parse the markdown file with front matter."""
        try:
            with self.content_file_path.open() as f:
                return frontmatter.load(f)
        except FileNotFoundError:
            # Return a dummy post with error content
            post = frontmatter.Post(
                f"Terms of Service content for version {self.version} not found."
            )
            post.metadata = {}
            return post

    @property
    def content(self) -> str:
        """Get the raw markdown content from the file (without front matter)."""
        return self._frontmatter_post.content

    @property
    def content_html(self) -> str:
        """Get the rendered HTML content from the markdown file."""
        md = markdown.Markdown(extensions=["extra", "nl2br", "sane_lists"])
        return md.convert(self.content)

    @property
    def metadata(self) -> dict:
        """Get the front matter metadata from the markdown file."""
        return self._frontmatter_post.metadata

    def _update_active_status_in_files(self) -> None:
        """Update is_active status in markdown front matter.

        Only writes files if the is_active status actually changed,
        to avoid spurious file modifications (see GitHub issue #153).
        """
        base_dir = get_tos_versions_directory()
        if not base_dir.exists():
            return

        # Set all files to inactive
        for file_path in base_dir.glob("*.md"):
            if file_path.stem == "README":
                continue

            try:
                with file_path.open() as f:
                    post = frontmatter.load(f)

                # Determine the correct is_active status
                should_be_active = file_path.stem == self.version
                current_is_active = post.metadata.get("is_active", False)

                # Only update if status actually changed
                if current_is_active != should_be_active:
                    post.metadata["is_active"] = should_be_active
                    # Write back to file (with consistent formatting)
                    write_frontmatter_file(file_path, post)
            except (FileNotFoundError, KeyError):
                continue

    @classmethod
    def get_active(cls):
        """Get the currently active Terms of Service version."""
        # Order by -created_at to ensure consistent results
        return cls.objects.filter(is_active=True).order_by("-created_at").first()

    @classmethod
    def get_available_versions(cls) -> list[str]:
        """Get list of available TOS versions from the filesystem."""
        base_dir = get_tos_versions_directory()
        if not base_dir.exists():
            return []

        versions = [
            file_path.stem
            for file_path in base_dir.glob("*.md")
            if file_path.stem != "README"
        ]
        return sorted(versions, reverse=True)

    @classmethod
    def sync_from_files(cls):
        """Sync database with markdown files (useful for initial setup or recovery)."""
        base_dir = get_tos_versions_directory()
        if not base_dir.exists():
            return

        for file_path in base_dir.glob("*.md"):
            if file_path.stem == "README":
                continue

            try:
                with file_path.open() as f:
                    post = frontmatter.load(f)

                version = file_path.stem
                is_active = post.metadata.get("is_active", False)

                # Create or update database entry
                tos, created = cls.objects.get_or_create(
                    version=version,
                    defaults={"is_active": is_active},
                )
                if not created and tos.is_active != is_active:
                    tos.is_active = is_active
                    tos.save(update_fields=["is_active"])
            except (FileNotFoundError, KeyError, ValueError):
                continue


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
