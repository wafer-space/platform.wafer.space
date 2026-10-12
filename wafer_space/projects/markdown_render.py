"""Render user-written markdown (project descriptions) to safe HTML (#285).

Descriptions are written by any user and read by staff on that user's
project page, so the output is an XSS surface. Two layers keep it safe:

1. Python-Markdown runs with its raw-HTML handling removed, so HTML typed
   into a description is escaped and shown as text, never passed through.
2. nh3 then cleans the result against a small allowlist of tags and
   attributes. A link's scheme must be http, https or mailto; relative
   links (no scheme) pass, as nh3 allows them. It is the layer that holds
   if markdown ever emits something unexpected.
"""

from __future__ import annotations

import markdown
import nh3
from django.utils.safestring import SafeString

ALLOWED_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "ul",
}
ALLOWED_ATTRIBUTES = {"a": {"href", "title"}}
ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}
# Links in user content point anywhere: no referrer, no ranking credit.
LINK_REL = "nofollow noopener noreferrer"

_CLEANER = nh3.Cleaner(
    tags=ALLOWED_TAGS,
    attributes=ALLOWED_ATTRIBUTES,
    url_schemes=ALLOWED_URL_SCHEMES,
    link_rel=LINK_REL,
)


def _markdown_without_raw_html() -> markdown.Markdown:
    """A Markdown converter that escapes raw HTML instead of passing it."""
    converter = markdown.Markdown(extensions=["sane_lists"])
    converter.preprocessors.deregister("html_block")
    converter.inlinePatterns.deregister("html")
    return converter


def render_markdown(text: str) -> SafeString:
    """Render user markdown to sanitised HTML that is safe to mark safe."""
    html = _markdown_without_raw_html().convert(text)
    # Safe by construction: nh3 has just cleaned it against the allowlist.
    return SafeString(_CLEANER.clean(html))
