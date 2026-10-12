"""Template filter for user-written markdown (#285)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template

from wafer_space.projects.markdown_render import render_markdown

if TYPE_CHECKING:
    from django.utils.safestring import SafeString

register = template.Library()


@register.filter(name="markdown")
def markdown_filter(value: str | None) -> SafeString:
    """Render a description as sanitised HTML: {{ project.description|markdown }}."""
    return render_markdown(value or "")
