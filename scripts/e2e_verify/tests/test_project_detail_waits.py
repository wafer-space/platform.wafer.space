"""The e2e precheck-cancel wait: its default and its failure message (#331).

No browser: ``_check_badge`` and the page are faked, and time is stepped by
a fake clock, so these run in milliseconds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import cast

import pytest

from scripts.e2e_verify.pages import project_detail
from scripts.e2e_verify.pages.project_detail import ProjectDetailPage

if TYPE_CHECKING:
    from playwright.sync_api import Page

STUCK = "Cancelling | 1.5.3"
# The window #331 asks for (and the preflight cancel already used).
ISSUE_331_TIMEOUT_MS = 180_000


@dataclass
class FakeClock:
    """``time.monotonic`` that advances only when the page waits."""

    now: float = 1000.0

    def monotonic(self) -> float:
        return self.now


@dataclass
class FakeBadge:
    """A check badge that becomes visible after ``visible_after`` seconds."""

    clock: FakeClock
    visible_after: float | None

    def is_visible(self) -> bool:
        return self.visible_after is not None and self.clock.now >= self.visible_after


@dataclass
class FakePage:
    """Just enough of a Playwright page: waiting advances the fake clock."""

    clock: FakeClock
    waits: list[int] = field(default_factory=list)

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)
        self.clock.now += ms / 1000.0


def _detail_page(
    monkeypatch: pytest.MonkeyPatch, *, cancelled_after_s: float | None
) -> tuple[ProjectDetailPage, FakePage]:
    """A detail page whose check shows "Cancelled" after the given time."""
    clock = FakeClock()
    monkeypatch.setattr(project_detail.time, "monotonic", clock.monotonic)
    page = FakePage(clock)
    detail = ProjectDetailPage(
        cast("Page", page), "https://example.invalid", "G899TEST"
    )
    visible_after = None if cancelled_after_s is None else clock.now + cancelled_after_s
    monkeypatch.setattr(
        detail, "_check_badge", lambda _pattern: FakeBadge(clock, visible_after)
    )
    monkeypatch.setattr(detail, "current_check_status", lambda: STUCK)
    monkeypatch.setattr(detail, "_safe_reload", lambda: None)
    monkeypatch.setattr(detail, "_heartbeat", lambda _label, _start: None)
    return detail, page


def test_default_cancel_timeout_is_180_s() -> None:
    """The default is #331's 180 s, no longer the 30 s it replaces."""
    assert ProjectDetailPage.CANCEL_TIMEOUT == ISSUE_331_TIMEOUT_MS


def test_wait_uses_the_default_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no timeout given, the wait gives up only after 180 s."""
    detail, _page = _detail_page(monkeypatch, cancelled_after_s=None)

    with pytest.raises(TimeoutError, match=r"after 18\d s"):
        detail.wait_for_precheck_cancelled()


def test_timeout_names_the_status_it_was_stuck_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure says which status the check never left, and for how long."""
    detail, _page = _detail_page(monkeypatch, cancelled_after_s=None)

    with pytest.raises(TimeoutError) as raised:
        detail.wait_for_precheck_cancelled(timeout_ms=30_000)

    assert str(raised.value) == (
        f"Timed out waiting for cancellation after 30 s: stuck at {STUCK!r}"
        " (timeout 30000 ms)"
    )


def test_prompt_cancel_logs_no_lag_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A cancel inside one beat interval returns quietly."""
    detail, _page = _detail_page(monkeypatch, cancelled_after_s=12)

    with caplog.at_level(logging.WARNING, logger=project_detail.logger.name):
        detail.wait_for_precheck_cancelled()

    assert "lagging" not in caplog.text


def test_slow_cancel_is_logged_as_queue_lag(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A cancel slower than two beat intervals passes, but says why it was slow."""
    detail, _page = _detail_page(monkeypatch, cancelled_after_s=95)

    with caplog.at_level(logging.WARNING, logger=project_detail.logger.name):
        detail.wait_for_precheck_cancelled()

    assert "none:ro:checks-orch queue is lagging" in caplog.text
