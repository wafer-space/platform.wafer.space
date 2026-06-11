"""Badge system for consistent status display across the platform.

This module provides a unified way to represent status badges with consistent
colors, icons, and behavior.

Scope: badges for general model state (project status, download status, hash
verification, notification types). Manufacturability check badges are NOT
rendered through this system - they use the check-specific tags in
``wafer_space/projects/templatetags/precheck_tags.py``, which add container
version indicators this system does not model.

Badge Types (semantic meaning):
- SUCCESS: Green - completed successfully, verified, positive outcome
- DANGER: Red - failed, error, requires attention
- WARNING: Yellow - uncertain state, potential issue
- INFO: Light blue - informational, transitional state
- PROCESSING: Blue with spinner - active work in progress
- NEUTRAL: Gray - inactive, pending, default state
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from django.template.loader import render_to_string


class BadgeType(Enum):
    """Semantic badge types that map to Bootstrap CSS classes.

    These represent the visual meaning of a badge, not the specific status.
    Multiple statuses can map to the same badge type.
    """

    SUCCESS = "success"
    DANGER = "danger"
    WARNING = "warning"
    INFO = "info"
    PROCESSING = "processing"
    NEUTRAL = "neutral"


# BadgeType -> Bootstrap CSS class mapping
BADGE_CSS_MAP: dict[BadgeType, str] = {
    BadgeType.SUCCESS: "bg-success",
    BadgeType.DANGER: "bg-danger",
    BadgeType.WARNING: "bg-warning text-dark",
    BadgeType.INFO: "bg-info",
    BadgeType.PROCESSING: "bg-primary",
    BadgeType.NEUTRAL: "bg-secondary",
}


@dataclass(frozen=True)
class BadgeInfo:
    """Immutable badge configuration returned by models.

    Attributes:
        text: The display text for the badge (1-3 words).
        badge_type: The semantic type determining color and style.
        icon: Optional Bootstrap icon class (e.g., "bi-check-circle").
    """

    text: str
    badge_type: BadgeType
    icon: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        """Convert to dictionary for JSON serialization.

        Used for JavaScript real-time status updates.
        """
        return {
            "text": self.text,
            "badge_type": self.badge_type.value,
            "icon": self.icon,
        }


def render_badge_html(badge: BadgeInfo) -> str:
    """Render a BadgeInfo to HTML string for AJAX responses.

    Args:
        badge: BadgeInfo instance to render.

    Returns:
        HTML string suitable for inserting into DOM.
    """
    return render_to_string(
        "core/_badge.html",
        {
            "text": badge.text,
            "css_class": BADGE_CSS_MAP[badge.badge_type],
            "icon": badge.icon,
            "is_processing": badge.badge_type == BadgeType.PROCESSING,
        },
    )
