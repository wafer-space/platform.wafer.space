"""Hash commands shown to users are safe to paste (#159).

macOS's default shell, zsh, has ``interactive_comments`` off, and cmd.exe
has no ``#`` comments at all. A pasted ``md5 your_design.gds  # MD5`` there
runs ``md5`` on the files ``#`` and ``MD5``. So no command line the site
shows carries an inline ``#`` comment; labels go beside the block.
"""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING

import pytest
from django.conf import settings
from django.urls import reverse

from wafer_space.projects.tests.factories import ProjectFactory

if TYPE_CHECKING:
    from django.test import Client

HASH_COMMAND = re.compile(
    r"\b(md5sum|md5|sha1sum|sha256sum|shasum|Get-FileHash|certutil)\b"
)
CODE_BLOCK = re.compile(r"<code[^>]*>(.*?)</code>", re.DOTALL)
OS_BLOCKS = ("Linux", "macOS", "Windows (PowerShell)", "Windows (Command Prompt)")


def _command_lines(text: str) -> list[str]:
    """The lines of every code block in ``text`` that run a hash command."""
    lines = []
    for block in CODE_BLOCK.findall(text):
        if HASH_COMMAND.search(block):
            lines.extend(html.unescape(block).splitlines())
    return lines


def test_template_hash_commands_have_no_inline_comments() -> None:
    """Every template's hash-command code blocks are free of ``#``."""
    found = {}
    for path in sorted(settings.APPS_DIR.rglob("templates/**/*.html")):
        lines = _command_lines(path.read_text(encoding="utf-8"))
        if lines:
            found[str(path.relative_to(settings.BASE_DIR))] = lines
    commented = {
        path: [line for line in lines if "#" in line] for path, lines in found.items()
    }

    assert found, "no hash-command blocks found; is the template search broken?"
    assert {path: lines for path, lines in commented.items() if lines} == {}


@pytest.mark.django_db
def test_checksum_help_shows_paste_safe_commands(client: Client) -> None:
    """The file-submit page's four OS blocks: three bare commands each."""
    project = ProjectFactory()
    client.force_login(project.user)

    page = client.get(reverse("projects:submit_url", args=[project.pk]))
    blocks = re.findall(
        r"<h6>([^<]+)</h6>\s*<pre[^>]*data-hash-commands[^>]*><code>(.*?)</code>",
        page.content.decode(),
        re.DOTALL,
    )

    lines = {name: body.splitlines() for name, body in blocks}

    assert [(name, len(commands)) for name, commands in lines.items()] == [
        (name, 3) for name in OS_BLOCKS
    ]
    commented = [
        line for commands in lines.values() for line in commands if "#" in line
    ]
    assert commented == []
