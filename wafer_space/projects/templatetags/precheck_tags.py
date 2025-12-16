"""Template tags for manufacturability check badges with version info.

These tags render badges showing check status and/or container version information.
For status-only badges without version info, use the model's status_badge_html property.

Available tags:
- badge_check_status: Status badge with small version indicator icon
- badge_check_version: Version-only badge (shows container version used)
- badge_check_status_and_version: Full badge with status and version details
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from wafer_space.projects.models import ManufacturabilityCheck

if TYPE_CHECKING:
    from django.utils.safestring import SafeString

    from wafer_space.projects.models import PrecheckImageRevision

register = template.Library()


@register.simple_tag
def badge_check_status(check: ManufacturabilityCheck | None) -> SafeString:
    """Render check status badge with version indicator icon.

    Shows the check status (Running, Queued, Passed, Failed, etc.) with a small
    cloud icon indicating whether the check used the latest container version.

    Usage: {% badge_check_status check %}
    """
    if not check:
        return mark_safe(
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
def badge_check_version(check: ManufacturabilityCheck | None) -> SafeString:
    """Render version-only badge showing container version used.

    Shows the precheck container version (e.g., "v1.2.3" or commit SHA) with
    an icon indicating if it's the latest version. Links to GitHub commit if available.

    Usage: {% badge_check_version check %}
    """
    if not check or not check.docker_image_digest:
        return format_html("")

    revision = check.precheck_revision
    version_str = _get_version_string(revision)
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
        '<span class="badge {} border">{} <i class="bi bi-{} {}"></i></span>',
        bg_class,
        version_str,
        icon,
        icon_class,
    )


@register.simple_tag
def badge_check_status_and_version(
    check: ManufacturabilityCheck | None,
) -> SafeString:
    """Render combined badge with status and full version details.

    Shows check status followed by version string and indicator icon.
    Example: "Passed | v1.2.3 ☁️"

    Usage: {% badge_check_status_and_version check %}
    """
    if not check:
        return mark_safe(
            '<span class="badge bg-light text-muted border">No check</span>'
        )

    url = reverse("admin:projects_manufacturabilitycheck_change", args=[check.pk])
    icon, label, bg_class = _get_status_display(check)

    if check.docker_image_digest:
        revision = check.precheck_revision
        version_str = _get_version_string(revision)
        is_latest = check.is_using_latest_precheck
        version_icon, version_icon_class = _get_version_icon(is_latest=is_latest)
        version_part = format_html(
            ' | {} <i class="bi bi-{} {}"></i>',
            version_str,
            version_icon,
            version_icon_class,
        )
    else:
        version_part = format_html("")

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


def _get_status_display(
    check: ManufacturabilityCheck,
) -> tuple[str, str, str]:
    """Return (icon, label, bg_class) for check status.

    Uses model's _STATUS_METADATA for consistent status rendering.
    For finished checks, shows pass/fail based on is_manufacturable.
    """
    # For finished checks, show pass/fail based on is_manufacturable
    if check.status == ManufacturabilityCheck.Status.FINISHED:
        if check.is_manufacturable:
            return ("check-circle", "Passed", "bg-success")
        return ("x-circle", "Failed", "bg-danger")

    # Use model's centralized status metadata
    meta = ManufacturabilityCheck.get_status_metadata(check.status)

    # Extract icon name from full class (e.g., "bi-clock" -> "clock")
    icon_class = str(meta.get("icon", ""))
    icon = icon_class.replace("bi-", "") if icon_class else "question"

    label = str(meta.get("label", check.status))

    # Build bg_class from color, handling text color for light backgrounds
    color = str(meta.get("color", "secondary"))
    bg_class = "bg-warning text-dark" if color == "warning" else f"bg-{color}"

    return (icon, label, bg_class)


def _get_version_indicator_html(check: ManufacturabilityCheck) -> SafeString:
    """Return HTML for version indicator icon."""
    if not check.docker_image_digest:
        return format_html("")

    is_latest = check.is_using_latest_precheck
    icon, icon_class = _get_version_icon(is_latest=is_latest)
    return format_html(' <i class="bi bi-{} {}"></i>', icon, icon_class)


def _get_version_icon(*, is_latest: bool | None) -> tuple[str, str]:
    """Return (icon_name, css_class) for version status.

    Uses white text to contrast with colored badge backgrounds.
    Icon shape indicates status: check=latest, arrow-up=outdated.
    """
    if is_latest is True:
        return ("cloud-check-fill", "text-white")
    if is_latest is False:
        return ("cloud-arrow-up-fill", "text-white-50")
    return ("cloud", "text-white-50")


def _get_version_string(revision: PrecheckImageRevision | None) -> str:
    """Return version string for badge display."""
    if revision:
        if revision.precheck_version:
            return f"v{revision.precheck_version}"
        if revision.git_commit_sha:
            return revision.git_commit_sha[:7]
    return "????"
