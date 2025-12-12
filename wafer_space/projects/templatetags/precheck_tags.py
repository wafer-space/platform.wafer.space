"""Template tags for precheck badge rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.urls import reverse
from django.utils.html import format_html

if TYPE_CHECKING:
    from django.utils.safestring import SafeString

    from wafer_space.projects.models import ManufacturabilityCheck
    from wafer_space.projects.models import PrecheckImageRevision

register = template.Library()


@register.simple_tag
def badge_precheck_status(check: ManufacturabilityCheck | None) -> SafeString:
    """Render precheck status badge with version indicator.

    Usage: {% badge_precheck_status check %}
    """
    if not check:
        return format_html(
            '<span class="badge bg-light text-muted border">No check</span>'
        )

    url = reverse("admin:projects_manufacturabilitycheck_change", args=[check.pk])
    icon, label, bg_class = _get_status_display(check)
    version_indicator = _get_version_indicator_html(check)

    return format_html(
        '<a href="{}" class="badge {} text-decoration-none">'
        '<i class="bi bi-{}"></i> {}{}</a>',
        url,
        bg_class,
        icon,
        label,
        version_indicator,
    )


@register.simple_tag
def badge_precheck_version(check: ManufacturabilityCheck | None) -> SafeString:
    """Render precheck version-only badge.

    Usage: {% badge_precheck_version check %}
    """
    if not check or not check.docker_image_digest:
        return format_html("")

    revision = check.precheck_revision
    version_str = _get_version_string(check, revision)
    is_latest = check.is_using_latest_precheck
    icon, icon_class = _get_version_icon(is_latest=is_latest)

    if is_latest:
        bg_class = "bg-success-subtle text-success border-success"
    else:
        bg_class = "bg-warning-subtle text-warning-emphasis border-warning"

    if revision and revision.github_commit_url:
        return format_html(
            '<a href="{}" class="badge {} border text-decoration-none" target="_blank">'
            '{} <i class="bi bi-{} {}"></i></a>',
            revision.github_commit_url,
            bg_class,
            version_str,
            icon,
            icon_class,
        )

    return format_html(
        '<span class="badge {} border">'
        '{} <i class="bi bi-{} {}"></i></span>',
        bg_class,
        version_str,
        icon,
        icon_class,
    )


@register.simple_tag
def badge_precheck_combined(check: ManufacturabilityCheck | None) -> SafeString:
    """Render combined status + version badge.

    Usage: {% badge_precheck_combined check %}
    """
    if not check:
        return format_html(
            '<span class="badge bg-light text-muted border">No check</span>'
        )

    url = reverse("admin:projects_manufacturabilitycheck_change", args=[check.pk])
    icon, label, bg_class = _get_status_display(check)

    if check.docker_image_digest:
        revision = check.precheck_revision
        version_str = _get_version_string(check, revision)
        is_latest = check.is_using_latest_precheck
        version_icon, version_icon_class = _get_version_icon(is_latest=is_latest)
        version_part = format_html(
            ' | {} <i class="bi bi-{} {}"></i>',
            version_str,
            version_icon,
            version_icon_class,
        )
    else:
        version_part = ""

    return format_html(
        '<a href="{}" class="badge {} text-decoration-none">'
        '<i class="bi bi-{}"></i> {}{}</a>',
        url,
        bg_class,
        icon,
        label,
        version_part,
    )


# --- Helper functions ---

# Status display mapping: status -> (icon, label, bg_class)
_STATUS_DISPLAY_MAP: dict[str, tuple[str, str, str]] = {
    "running": ("gear", "Running", "bg-primary"),
    "analyzing": ("gear", "Running", "bg-primary"),
    "pending": ("hourglass-split", "Queued", "bg-warning text-dark"),
    "dispatching": ("hourglass-split", "Queued", "bg-warning text-dark"),
    "starting": ("hourglass-split", "Queued", "bg-warning text-dark"),
    "error": ("exclamation-circle", "Error", "bg-danger"),
    "cancelling": ("slash-circle", "Cancelled", "bg-secondary"),
    "cancelled": ("slash-circle", "Cancelled", "bg-secondary"),
}


def _get_status_display(
    check: ManufacturabilityCheck,
) -> tuple[str, str, str]:
    """Return (icon, label, bg_class) for check status.

    Uses is_manufacturable for finished checks, status for others.
    """
    # For finished checks, show pass/fail based on is_manufacturable
    if check.status == "finished":
        if check.is_manufacturable:
            return ("check-circle", "Passed", "bg-success")
        return ("x-circle", "Failed", "bg-danger")

    # Use mapping for other statuses
    if check.status in _STATUS_DISPLAY_MAP:
        return _STATUS_DISPLAY_MAP[check.status]

    # Fallback for unknown status
    return ("question", str(check.status), "bg-secondary")


def _get_version_indicator_html(check: ManufacturabilityCheck) -> SafeString:
    """Return HTML for version indicator icon."""
    if not check.docker_image_digest:
        return format_html("")

    is_latest = check.is_using_latest_precheck
    icon, icon_class = _get_version_icon(is_latest=is_latest)
    return format_html(' <i class="bi bi-{} {}"></i>', icon, icon_class)


def _get_version_icon(*, is_latest: bool | None) -> tuple[str, str]:
    """Return (icon_name, css_class) for version status."""
    if is_latest is True:
        return ("cloud-check-fill", "text-success")
    if is_latest is False:
        return ("cloud-arrow-up-fill", "text-warning")
    return ("cloud", "text-muted")


def _get_version_string(
    check: ManufacturabilityCheck,
    revision: PrecheckImageRevision | None,
) -> str:
    """Return version string for badge display."""
    if revision:
        if revision.precheck_version:
            return f"v{revision.precheck_version}"
        if revision.git_commit_sha:
            return revision.git_commit_sha[:7]
    return "????"
