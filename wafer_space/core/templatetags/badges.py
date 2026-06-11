"""Template tags for rendering badges consistently."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template

from wafer_space.core.badges import BADGE_CSS_MAP
from wafer_space.core.badges import BadgeType
from wafer_space.core.badges import render_badge_html

if TYPE_CHECKING:
    from wafer_space.core.badges import BadgeInfo
    from wafer_space.projects.models import ProjectFile

register = template.Library()


@register.inclusion_tag("core/_badge.html")
def render_badge(badge: BadgeInfo) -> dict[str, str | bool | None]:
    """Render a badge with consistent styling.

    Args:
        badge: BadgeInfo instance with text, type, and optional icon.

    Returns:
        Context dict for the badge template.
    """
    return {
        "text": badge.text,
        "css_class": BADGE_CSS_MAP[badge.badge_type],
        "icon": badge.icon,
        "is_processing": badge.badge_type == BadgeType.PROCESSING,
    }


@register.simple_tag
def render_inline_hash_badge(file: ProjectFile, hash_type: str) -> str:
    """Render inline hash verification badge for a specific hash type.

    Used in templates to show Verified/Mismatch next to each hash value.
    Django's render_to_string returns SafeString, so output is already safe.

    Args:
        file: ProjectFile instance
        hash_type: One of 'md5', 'sha1', 'sha256'

    Returns:
        HTML string for the badge, or empty string if no expected hash.
    """
    badge = file.get_inline_hash_badge(hash_type)
    if badge:
        # render_badge_html uses render_to_string which returns SafeString
        return render_badge_html(badge)
    return ""
