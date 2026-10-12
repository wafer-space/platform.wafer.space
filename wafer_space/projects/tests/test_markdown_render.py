"""Project descriptions render as markdown, sanitised (#285).

Any user writes a description and staff open other users' projects, so
the rendered HTML must never carry script, event handlers, raw HTML or
links to anything but http, https and mailto.
"""

from __future__ import annotations

import pytest
from django.template import Context
from django.template import Template
from django.utils.safestring import SafeString

from wafer_space.projects.markdown_render import ALLOWED_TAGS
from wafer_space.projects.markdown_render import render_markdown

from .html_elements import parse_html


class TestFormatting:
    def test_emphasis(self) -> None:
        assert render_markdown("**bold** and *it*") == (
            "<p><strong>bold</strong> and <em>it</em></p>"
        )

    def test_list(self) -> None:
        assert render_markdown("- one\n- two") == (
            "<ul>\n<li>one</li>\n<li>two</li>\n</ul>"
        )

    def test_heading(self) -> None:
        assert render_markdown("## Pinout") == "<h2>Pinout</h2>"

    def test_inline_and_block_code(self) -> None:
        assert render_markdown("`x`\n\n    y = 1") == (
            "<p><code>x</code></p>\n<pre><code>y = 1\n</code></pre>"
        )

    def test_link_is_kept_with_nofollow(self) -> None:
        assert render_markdown("[docs](https://wafer.space/)") == (
            '<p><a href="https://wafer.space/" '
            'rel="nofollow noopener noreferrer">docs</a></p>'
        )

    def test_mailto_link_is_kept(self) -> None:
        assert 'href="mailto:a@example.com"' in render_markdown(
            "[mail](mailto:a@example.com)"
        )

    def test_empty_description(self) -> None:
        assert render_markdown("") == ""

    def test_result_is_marked_safe(self) -> None:
        assert isinstance(render_markdown("x"), SafeString)


class TestRawHtmlIsNotPassedThrough:
    """HTML typed into a description is shown as text."""

    def test_script_block_is_escaped(self) -> None:
        html = render_markdown("<script>alert(1)</script>")
        assert (("<script" in html), ("&lt;script&gt;" in html)) == (False, True)

    def test_inline_script_is_escaped(self) -> None:
        html = render_markdown("hi <script>alert(1)</script> there")
        assert (("<script" in html), ("&lt;script&gt;" in html)) == (False, True)

    def test_harmless_looking_tag_is_escaped_too(self) -> None:
        assert render_markdown("<b>x</b>") == "<p>&lt;b&gt;x&lt;/b&gt;</p>"

    def test_iframe_is_escaped(self) -> None:
        html = render_markdown('<iframe src="https://evil.example/"></iframe>')
        assert "<iframe" not in html

    def test_html_comment_is_escaped(self) -> None:
        assert "<!--" not in render_markdown("<!-- hidden -->")


@pytest.mark.parametrize(
    "source",
    [
        '<img src=x onerror="alert(1)">',
        '<a href="https://x.example/" onclick="alert(1)">x</a>',
        '<div onmouseover="alert(1)">x</div>',
        '<svg onload="alert(1)"></svg>',
        '<body onload="alert(1)">',
        # A link title that tries to break out of its attribute.
        '[x](https://x.example/ "a\\" onmouseover=\\"alert(1)")',
        "[x](https://x.example/ 'a\" onmouseover=\"alert(1)')",
    ],
)
def test_no_event_handler_attribute_survives(source: str) -> None:
    assert parse_html(render_markdown(source)).event_handlers() == []


@pytest.mark.parametrize(
    "source",
    [
        "<script>alert(1)</script>",
        '<img src=x onerror="alert(1)">',
        '<iframe src="https://x.example/"></iframe>',
        '<svg onload="alert(1)"></svg>',
        '<object data="x"></object>',
        "<style>body{display:none}</style>",
        '<form action="https://x.example/"><input></form>',
    ],
)
def test_only_allowlisted_tags_are_emitted(source: str) -> None:
    tags = {tag for tag, _ in parse_html(render_markdown(source)).elements}
    assert tags <= ALLOWED_TAGS


@pytest.mark.parametrize(
    "source",
    [
        "[x](javascript:alert(1))",
        "[x](JavaScript:alert(1))",
        "[x](  javascript:alert(1))",
        "[x](java&#115;cript:alert(1))",
        "[x](&#106;avascript:alert(1))",
        "[x](vbscript:msgbox(1))",
        "[x](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)",
        "[x][ref]\n\n[ref]: javascript:alert(1)",
        "<javascript:alert(1)>",
        "![x](javascript:alert(1))",
    ],
)
def test_links_only_to_http_https_or_mailto(source: str) -> None:
    unsafe = [
        href
        for href in parse_html(render_markdown(source)).hrefs()
        if not href.strip().lower().startswith(("http://", "https://", "mailto:"))
    ]
    assert unsafe == []


def test_images_are_not_rendered() -> None:
    """No third-party fetches (tracking pixels) from a description."""
    assert "<img" not in render_markdown("![chip](https://x.example/a.png)")


def test_filter_renders_in_a_template() -> None:
    template = Template("{% load markdown_tags %}{{ text|markdown }}")
    html = template.render(Context({"text": "**a** <script>x</script>"}))
    assert html == "<p><strong>a</strong> &lt;script&gt;x&lt;/script&gt;</p>"


def test_filter_accepts_none() -> None:
    template = Template("{% load markdown_tags %}{{ text|markdown }}")
    assert template.render(Context({"text": None})) == ""
