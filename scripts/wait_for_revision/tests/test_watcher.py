"""Tests for the deployment revision watcher."""

from __future__ import annotations

import pytest
import requests

from scripts.wait_for_revision.watcher import Revision
from scripts.wait_for_revision.watcher import fetch_revision
from scripts.wait_for_revision.watcher import parse_revision
from scripts.wait_for_revision.watcher import wait_for_revision

# A representative footer, matching what test-platform.wafer.space renders.
FOOTER_HTML = """<html><body>
<footer class="text-center text-muted py-2" style="font-size: 0.7rem;">
  <span class="text-muted">test-platform-wafer-space.doc.mithis.com</span>
  <span class="text-muted mx-1">|</span>
  <span class="text-muted">pull/289/head</span>
  <span class="text-muted mx-1">|</span>
  <a href="https://github.com/wafer-space/platform.wafer.space/commit/\
987d426d5ec162f50e6b1b67afd2c58589ca3b79" target="_blank"
     class="text-muted text-decoration-none">v0.0-1784-g987d426</a>
</footer>
</body></html>"""

FULL_SHA = "987d426d5ec162f50e6b1b67afd2c58589ca3b79"


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "", reason: str = "OK") -> None:
        self.status_code = status_code
        self.text = text
        self.reason = reason


# --------------------------- parse_revision ---------------------------


def test_parse_revision_extracts_footer_fields():
    rev = parse_revision(FOOTER_HTML)
    assert rev.commit == FULL_SHA
    assert rev.ref == "pull/289/head"
    assert rev.describe == "v0.0-1784-g987d426"


def test_parse_revision_missing_footer_is_empty():
    rev = parse_revision("<html><body>no footer here</body></html>")
    assert rev == Revision()


# ------------------------------ matches -------------------------------


@pytest.mark.parametrize(
    "expected",
    [
        "987d426",  # short sha prefix
        FULL_SHA,  # full sha
        "987D426",  # case-insensitive
        "pull/289/head",  # deployed ref
        "v0.0-1784-g987d426",  # git-describe
        "1784-g987d426",  # describe substring
    ],
)
def test_matches_accepts_valid_identifiers(expected):
    assert parse_revision(FOOTER_HTML).matches(expected)


@pytest.mark.parametrize("expected", ["6feb497", "pull/290/head", "", "   "])
def test_matches_rejects_other_revisions(expected):
    assert not parse_revision(FOOTER_HTML).matches(expected)


# --------------------------- fetch_revision ---------------------------


def test_fetch_revision_success(monkeypatch):
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: _FakeResponse(200, FOOTER_HTML)
    )
    rev, err = fetch_revision("http://x")
    assert err == ""
    assert rev is not None
    assert rev.commit == FULL_SHA


@pytest.mark.parametrize(
    ("code", "reason"), [(404, "Not Found"), (403, "Forbidden"), (503, "Unavailable")]
)
def test_fetch_revision_reports_error_pages_without_raising(monkeypatch, code, reason):
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: _FakeResponse(code, "oops", reason)
    )
    rev, err = fetch_revision("http://x")
    assert rev is None
    assert str(code) in err
    assert reason in err


def test_fetch_revision_survives_connection_error(monkeypatch):
    def boom(*a, **k):
        msg = "refused"
        raise requests.ConnectionError(msg)

    monkeypatch.setattr(requests, "get", boom)
    rev, err = fetch_revision("http://x")
    assert rev is None
    assert "refused" in err


def test_fetch_revision_no_revision_in_body(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, "<html/>"))
    rev, err = fetch_revision("http://x")
    assert rev is None
    assert "no revision" in err.lower()


# -------------------------- wait_for_revision -------------------------


class _Clock:
    """Fake monotonic clock advanced by the fake sleep, for deterministic tests."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def _seq_fetch(results):
    it = iter(results)

    def fetch(_url, **_kwargs):
        return next(it)

    return fetch


def test_wait_returns_true_when_revision_matches(capsys):
    clock = _Clock()
    match = Revision(commit="6feb4972abcdef", ref="pull/290/head")
    fetch = _seq_fetch(
        [
            (None, "HTTP 503 (Unavailable)"),  # error page — must not stop the loop
            (Revision(commit=FULL_SHA, ref="pull/289/head"), ""),  # old rev
            (match, ""),  # deployed!
        ]
    )
    ok = wait_for_revision(
        "http://x",
        "6feb497",
        interval=5,
        fetch=fetch,
        now=clock.now,
        sleep=clock.sleep,
        clock=lambda: "T",
    )
    assert ok is True
    out = capsys.readouterr().out
    assert "MATCH" in out
    assert "HTTP 503" in out  # the error page was reported, not fatal


def test_wait_times_out_without_match(capsys):
    clock = _Clock()
    fetch = _seq_fetch([(Revision(commit=FULL_SHA), "")] * 100)
    ok = wait_for_revision(
        "http://x",
        "6feb497",
        interval=5,
        timeout=12,
        fetch=fetch,
        now=clock.now,
        sleep=clock.sleep,
        clock=lambda: "T",
    )
    assert ok is False
    assert "timeout" in capsys.readouterr().out.lower()


def test_wait_flushes_and_reports_elapsed(capsys):
    clock = _Clock()
    fetch = _seq_fetch(
        [(Revision(commit=FULL_SHA), ""), (Revision(commit="6feb4972"), "")]
    )
    wait_for_revision(
        "http://x",
        "6feb497",
        interval=7,
        fetch=fetch,
        now=clock.now,
        sleep=clock.sleep,
        clock=lambda: "STAMP",
    )
    out = capsys.readouterr().out
    assert "STAMP" in out  # timestamp printed
    assert "0:00:00" in out  # first poll at zero elapsed
    assert "0:00:07" in out  # elapsed advances by the interval
