"""Template tags for rendering badges consistently."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template

from wafer_space.core.badges import BADGE_CSS_MAP
from wafer_space.core.badges import BadgeType

if TYPE_CHECKING:
    from wafer_space.core.badges import BadgeInfo

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
