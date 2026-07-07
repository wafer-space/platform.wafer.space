"""Poll a deployed site's footer for its git revision until it matches.

The footer of platform.wafer.space advertises the deployed revision, e.g.::

    ... | pull/289/head | <a href=".../commit/987d426d...">v0.0-1784-g987d426</a>

so a :class:`Revision` is identified by its commit sha, git-describe string, and
the deployed ref. This module fetches and parses that, tolerating error pages
(404/403/503/...) and connection errors without dying, so a deploy watch can
poll steadily through a rollout.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import TextIO

DEFAULT_URL = "https://test-platform.wafer.space"
DEFAULT_INTERVAL_S = 5.0
DEFAULT_REQUEST_TIMEOUT_S = 15.0

# The footer renders a commit link, a git-describe string, and a deployed ref.
_FOOTER_RE = re.compile(r"<footer\b.*?</footer>", re.IGNORECASE | re.DOTALL)
_COMMIT_RE = re.compile(r"/commit/([0-9a-fA-F]{7,40})")
_DESCRIBE_RE = re.compile(r"v\d[\w.]*-\d+-g[0-9a-fA-F]{7,}", re.IGNORECASE)
_REF_RE = re.compile(r"pull/\d+/head|tags/[\w.\-]+|heads/[\w./\-]+", re.IGNORECASE)


@dataclass(frozen=True)
class Revision:
    """The deployed revision as advertised in a page footer."""

    commit: str = ""  # full commit sha from the footer's commit link
    describe: str = ""  # git-describe string, e.g. "v0.0-1784-g987d426"
    ref: str = ""  # deployed ref, e.g. "pull/290/head"

    def matches(self, expected: str) -> bool:
        """Whether ``expected`` identifies this revision.

        ``expected`` may be a commit sha (full or a short prefix), the
        git-describe string (or a substring of it), or the deployed ref such as
        ``"pull/290/head"``. Matching is case-insensitive.
        """
        wanted = expected.strip().lower()
        if not wanted:
            return False
        if self.commit and self.commit.lower().startswith(wanted):
            return True
        if self.describe and wanted in self.describe.lower():
            return True
        return bool(self.ref) and wanted in self.ref.lower()

    def __str__(self) -> str:
        label = " ".join(p for p in (self.ref, self.describe) if p)
        sha = f"({self.commit[:12]}…)" if self.commit else "(no commit)"
        return f"{label} {sha}".strip()


def parse_revision(html: str) -> Revision:
    """Extract the :class:`Revision` from a page's footer.

    Falls back to scanning the whole document if no ``<footer>`` is present, so a
    minor template change does not blind the watcher.
    """
    match = _FOOTER_RE.search(html)
    scope = match.group(0) if match else html
    commit = _COMMIT_RE.search(scope)
    describe = _DESCRIBE_RE.search(scope)
    ref = _REF_RE.search(scope)
    return Revision(
        commit=commit.group(1) if commit else "",
        describe=describe.group(0) if describe else "",
        ref=ref.group(0) if ref else "",
    )


def fetch_revision(
    url: str, *, timeout: float = DEFAULT_REQUEST_TIMEOUT_S
) -> tuple[Revision | None, str]:
    """Fetch and parse the deployed revision. Never raises.

    Returns ``(revision, "")`` on success, or ``(None, message)`` describing an
    HTTP error page (404/403/503/...), a connection/timeout error, or a page
    with no recognisable revision.
    """
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        return None, f"request error: {exc}"
    if resp.status_code != HTTPStatus.OK:
        return None, f"HTTP {resp.status_code} ({resp.reason})"
    revision = parse_revision(resp.text)
    if not (revision.commit or revision.describe or revision.ref):
        return None, "no revision found in page footer"
    return revision, ""


def _format_elapsed(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def wait_for_revision(  # noqa: PLR0913 - injectable seams keep this testable
    url: str,
    expected: str,
    *,
    interval: float = DEFAULT_INTERVAL_S,
    timeout: float | None = None,
    fetch: Callable[[str], tuple[Revision | None, str]] = fetch_revision,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], str] = lambda: time.strftime("%Y-%m-%d %H:%M:%S"),
    out: TextIO | None = None,
) -> bool:
    """Poll ``url`` every ``interval`` s until its footer revision matches.

    Prints one flushed status line per poll: wall-clock time, how long it has
    been waiting, and the currently deployed revision (or the error page seen).
    Error pages are reported but never stop the loop.

    Returns ``True`` on match, or ``False`` if ``timeout`` seconds elapse first
    (``timeout=None`` waits indefinitely).
    """
    stream = out if out is not None else sys.stdout
    start = now()
    while True:
        revision, error = fetch(url)
        elapsed = _format_elapsed(now() - start)
        stamp = clock()
        if revision is None:
            print(f"[{stamp}] waited {elapsed} — {error}", file=stream, flush=True)
        else:
            hit = revision.matches(expected)
            suffix = "  ✓ MATCH" if hit else f"  (waiting for {expected})"
            print(
                f"[{stamp}] waited {elapsed} — deployed: {revision}{suffix}",
                file=stream,
                flush=True,
            )
            if hit:
                return True
        if timeout is not None and now() - start >= timeout:
            print(
                f"[{stamp}] timeout after {_format_elapsed(now() - start)} "
                f"waiting for {expected!r}",
                file=stream,
                flush=True,
            )
            return False
        sleep(interval)
