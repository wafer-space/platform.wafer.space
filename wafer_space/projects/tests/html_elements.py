"""Parse HTML the way a browser builds elements, for XSS assertions (#285).

Escaped text such as ``&lt;img onerror="..."&gt;`` is harmless and shows
as text; only real elements and their attributes matter. Substring checks
cannot tell the two apart, so tests parse.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from html.parser import HTMLParser


@dataclass
class ParsedHtml:
    """Every start tag with its decoded attributes, and every script body."""

    elements: list[tuple[str, dict[str, str | None]]] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)

    def event_handlers(self) -> list[tuple[str, str]]:
        """(tag, attribute) for every on* attribute on a real element."""
        return [
            (tag, name)
            for tag, attrs in self.elements
            for name in attrs
            if name.startswith("on")
        ]

    def hrefs(self) -> list[str]:
        return [attrs["href"] or "" for _, attrs in self.elements if "href" in attrs]


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parsed = ParsedHtml()
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.parsed.elements.append((tag, dict(attrs)))
        if tag == "script":
            self._in_script = True
            self.parsed.scripts.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self.parsed.scripts[-1] += data


def parse_html(html: str) -> ParsedHtml:
    parser = _Parser()
    parser.feed(html)
    parser.close()
    return parser.parsed
