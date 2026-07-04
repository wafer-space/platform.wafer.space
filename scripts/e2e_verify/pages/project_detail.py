"""Project detail page interactions.

Status is surfaced through Bootstrap badges (``span.badge``). The same status
can appear several times on the page -- the file's download/hash badges, the
current check card, and every *previous* check in the history section -- so
reads are scoped: download/hash waits match page-wide, while check-status reads
are scoped to the current check card (``.card.border-primary``) so a file badge
or a stale history check can't satisfy them.

The file (download/hash) badges live-update via JS; the manufacturability-check
badge and the processing-logs block do not, so the precheck waits reload the
page between polls. Every wait logs a heartbeat each poll so long waits (the DRC
can run for a long time) report their state at least once a poll.

Badge labels (from the templates / model status metadata):
  - download:  "Downloaded" | "Downloading" | "Download Failed" | "Pending"
  - hash:      "Hash Verified" | "Hash Mismatch" | "Hash Not Verified"
  - precheck:  "Pending" | "Dispatching" | "Starting" | "Running" |
               "Analyzing" | "Cancelling" | "Cancelled" | "Passed" | "Failed"
    (a *finished* check shows "Passed"/"Failed", not "Manufacturable")
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
from typing import TYPE_CHECKING

from playwright.sync_api import Error as PlaywrightError

from .base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator
    from playwright.sync_api import Page

logger = logging.getLogger(__name__)

# A finished check labels the badge "Failed"; the download badge uses
# "Download Failed". This matches the precheck "Failed" but not the download one.
_CHECK_FAILED = re.compile(r"(?<!Download )Failed")

# Any manufacturability-check status label (used for heartbeat reporting).
_CHECK_STATUS = re.compile(
    r"Pending|Dispatching|Starting|Running|Analyzing|Cancelling|Cancelled"
    r"|Passed|(?<!Download )Failed"
)


class ProjectDetailPage(BasePage):
    """Page Object for project detail page with status monitoring."""

    # How often to print an elapsed/expected progress line during long waits.
    PROGRESS_INTERVAL_S = 30

    # Default timeouts (milliseconds)
    DOWNLOAD_TIMEOUT = 5 * 60 * 1000  # 5 minutes
    HASH_TIMEOUT = 60 * 1000  # 1 minute
    PRECHECK_START_TIMEOUT = 10 * 60 * 1000  # 10 minutes
    PRECHECK_COMPLETE_TIMEOUT = 4 * 60 * 60 * 1000  # 4 hours

    def __init__(self, page: Page, base_url: str, project_id: str) -> None:
        super().__init__(page, base_url)
        self.project_id = project_id

    def go(self) -> None:
        """Navigate to this project's detail page."""
        self.navigate(f"/projects/{self.project_id}/")

    def refresh(self) -> None:
        """Refresh the page."""
        self.page.reload()

    # ========================================
    # Helpers
    # ========================================

    def _badge(self, pattern: str | re.Pattern[str]) -> Locator:
        """First page-wide badge whose text matches ``pattern``.

        Used for the file (download/hash) badges, which live outside the check
        card.
        """
        return self.page.locator("span.badge").filter(has_text=pattern).first

    def _check_card(self) -> Locator:
        """The current check's card (``.card.border-primary`` in _file_display).

        Scoping check reads here excludes both the file's download/hash badges
        and the *history* checks (rendered inside collapsed ``<details>``), so a
        stale or wrong check can't be picked up by a page-wide match.
        """
        return self.page.locator("div.card.border-primary").first

    def _check_badge(self, pattern: str | re.Pattern[str]) -> Locator:
        """First check-status badge (within the current check card) matching."""
        return self._check_card().locator("span.badge").filter(has_text=pattern).first

    def _check_logs(self) -> Locator:
        """The processing-logs element within the current check card."""
        return self._check_card().locator("#processing-logs")

    def current_check_status(self) -> str:
        """Text of the current check's status badge, or a placeholder.

        Read from the current check card only, so a cancelled earlier check
        (now in the history section) is never reported here.
        """
        badge = self._check_badge(_CHECK_STATUS)
        if badge.count() > 0:
            return " ".join((badge.text_content() or "").split())
        return "(no check badge yet)"

    def _heartbeat(self, label: str, start: float) -> None:
        """Log a progress line while waiting for ``label``."""
        elapsed = int(time.monotonic() - start)
        logger.info(
            "   ... waiting for %s: check=%r (elapsed %ds)",
            label,
            self.current_check_status(),
            elapsed,
        )

    def _wait_for_badge(
        self,
        pattern: str | re.Pattern[str],
        timeout_ms: int,
        *,
        label: str,
        check: bool = False,
        poll_ms: int = 5_000,
    ) -> None:
        """Poll until a matching badge is visible, heartbeating each poll.

        ``check=False`` (default) matches a page-wide file (download/hash)
        badge, which live-updates via JS. ``check=True`` matches a
        precheck-status badge: it is scoped to the current check card (so file
        badges and history checks can't satisfy it) and the page is reloaded
        between polls, because the check card does not live-update.
        """
        deadline = time.monotonic() + timeout_ms / 1000.0
        start = time.monotonic()
        while True:
            badge = self._check_badge(pattern) if check else self._badge(pattern)
            # A page reload (ours, or the page's own JS on a status change) can
            # race with this read; treat that as "not yet" and retry next poll.
            with contextlib.suppress(PlaywrightError):
                if badge.is_visible():
                    return
            if time.monotonic() >= deadline:
                msg = f"Timed out waiting for {label} ({timeout_ms} ms)"
                raise TimeoutError(msg)
            self._heartbeat(label, start)
            self.page.wait_for_timeout(poll_ms)
            if check:
                self.page.reload()

    # ========================================
    # Download / hash status
    # ========================================

    def wait_for_downloaded(self, timeout_ms: int | None = None) -> None:
        """Wait for the file download to reach a terminal state.

        The download badge shows "Downloaded" on success or "Hash Mismatch"
        when the file downloaded but the hash didn't match; either (or a
        "Hash Verified" badge) means the download itself completed.
        """
        timeout = timeout_ms or self.DOWNLOAD_TIMEOUT
        self._wait_for_badge(
            re.compile(r"Downloaded|Hash Verified|Hash Mismatch"),
            timeout,
            label="download to complete",
        )

    def wait_for_hash_verified(self, timeout_ms: int | None = None) -> None:
        """Wait for hash verification to pass."""
        timeout = timeout_ms or self.HASH_TIMEOUT
        self._wait_for_badge(
            "Hash Verified", timeout, label="hash verification", poll_ms=3_000
        )

    def wait_for_hash_mismatch(self, timeout_ms: int | None = None) -> None:
        """Wait for hash mismatch to be detected."""
        timeout = timeout_ms or self.HASH_TIMEOUT
        self._wait_for_badge(
            "Hash Mismatch", timeout, label="hash mismatch", poll_ms=3_000
        )

    # ========================================
    # Manufacturability precheck status
    # ========================================

    def wait_for_precheck_running(self, timeout_ms: int | None = None) -> None:
        """Wait for the precheck to be queued or running (any in-progress state).

        Scoped to the check card so the *download* badge's "Pending" label
        (a different badge) can't satisfy the wait.
        """
        timeout = timeout_ms or self.PRECHECK_START_TIMEOUT
        self._wait_for_badge(
            re.compile(r"Pending|Dispatching|Starting|Running|Analyzing"),
            timeout,
            label="precheck to start",
            check=True,
            poll_ms=10_000,
        )

    def wait_for_precheck_complete(
        self, timeout_ms: int | None = None, *, expected_s: int | None = None
    ) -> None:
        """Wait for the precheck to finish, streaming new log lines as they appear.

        The detail page's own JS streams logs into #processing-logs every 5s
        and reloads the page when the check status changes, so we stay on the
        page, print each newly-appended log line, and return once the badge
        shows "Passed" or "Failed". A fallback manual reload guards against a
        stalled page; page reloads race with our DOM reads, so those are caught.

        ``expected_s`` (from the precheck CI, if known) is shown in the periodic
        progress line as an ETA reference.
        """
        timeout = timeout_ms or self.PRECHECK_COMPLETE_TIMEOUT
        terminal = re.compile(r"Passed|(?<!Download )Failed")

        self.go()
        start = time.monotonic()
        deadline = start + timeout / 1000.0
        seen = ""  # full log text already consumed
        pending = ""  # buffered partial (incomplete) trailing line
        last_change = time.monotonic()
        last_beat = 0.0
        poll_ms = 3_000
        idle_reload_s = 90.0

        while True:
            done = False
            try:
                done = self._check_badge(terminal).is_visible()
                logs = self._check_logs()
                text = (logs.first.text_content() or "") if logs.count() else ""
            except PlaywrightError:
                # A page reload (triggered by the page's own JS on a status
                # change) raced with our read; just try again next poll.
                text = seen

            if len(text) > len(seen):
                pending += text[len(seen) :]
                seen = text
                last_change = time.monotonic()
                # Emit only complete lines; keep any partial line buffered.
                *lines, pending = pending.split("\n")
                for line in lines:
                    self._emit_log_line(line)

            if done:
                if pending.strip():
                    self._emit_log_line(pending)
                return
            if time.monotonic() >= deadline:
                msg = f"Precheck did not finish within {timeout} ms"
                raise TimeoutError(msg)

            # Periodic progress line with elapsed / expected.
            if time.monotonic() - last_beat >= self.PROGRESS_INTERVAL_S:
                self._emit_progress(int(time.monotonic() - start), expected_s)
                last_beat = time.monotonic()

            self.page.wait_for_timeout(poll_ms)
            # If nothing has changed for a while, the page's JS poller may have
            # stopped; reload to re-arm it (and to refresh the badge).
            if time.monotonic() - last_change >= idle_reload_s:
                with contextlib.suppress(PlaywrightError):
                    self.page.reload()
                last_change = time.monotonic()

    def _emit_log_line(self, line: str) -> None:
        """Log one streamed precheck log line, with a marker."""
        logger.info("[check] %s", line)

    def _emit_progress(self, elapsed_s: int, expected_s: int | None) -> None:
        """Log an elapsed/expected progress line for the running check."""
        eta = f" / ~{expected_s}s expected" if expected_s else ""
        logger.info(
            "   ... precheck running: elapsed %ds%s, status=%r",
            elapsed_s,
            eta,
            self.current_check_status(),
        )

    def wait_for_precheck_cancelled(self, timeout_ms: int | None = None) -> None:
        """Wait for precheck cancellation to be confirmed."""
        timeout = timeout_ms or 30_000
        self._wait_for_badge(
            "Cancelled", timeout, label="cancellation", check=True, poll_ms=3_000
        )

    def get_check_version_token(self) -> str | None:
        """The precheck version the current check reports, or None.

        The status-and-version badge renders ``<Status> | <version>``, where
        ``<version>`` is a ``sha256:<hex>...`` digest (uncataloged image), a
        semver / git-describe string, or a short git sha. Returns that token
        (trailing ``...`` stripped) or None when no version is shown yet (the
        image has not been pulled, so the badge is just ``<Status>``).
        """
        status = self.current_check_status()
        if "|" not in status:
            return None
        token = status.split("|", 1)[1].strip().removesuffix("...").strip()
        return token or None

    def wait_for_check_version_token(
        self, timeout_ms: int = 300_000, poll_ms: int = 5_000
    ) -> str | None:
        """Reload-poll until the check reports a precheck version; return it.

        Returns None if none appears within ``timeout_ms``.
        """
        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            token = self.get_check_version_token()
            if token:
                return token
            if time.monotonic() >= deadline:
                return None
            self.page.wait_for_timeout(poll_ms)
            with contextlib.suppress(PlaywrightError):
                self.page.reload()

    def is_manufacturable(self) -> bool:
        """Whether the finished check passed.

        Call after :meth:`wait_for_precheck_complete`. A passing check shows a
        "Passed" badge; a failing one shows "Failed".
        """
        if self._check_badge(_CHECK_FAILED).is_visible():
            return False
        return self._check_badge("Passed").is_visible()

    # ========================================
    # Actions
    # ========================================

    def click_cancel_precheck(self) -> None:
        """Click the cancel button for the manufacturability check.

        The confirmation dialog is auto-accepted by a handler registered once
        on the page (see run_full_flow), so we don't add one per click here.
        """
        self.page.get_by_role("button", name="Cancel").first.click()

    def has_cancellable_check(self) -> bool:
        """Whether the page shows a cancellable (in-progress) check."""
        return self.page.get_by_role("button", name="Cancel").count() > 0

    def cancel_check_if_running(self, timeout_ms: int = 180_000) -> bool:
        """Cancel this project's check if one is in progress.

        Waits until the check is reported ``Cancelled`` before returning.
        Returns True if a check was cancelled, False if none was cancellable.
        """
        self.go()
        if not self.has_cancellable_check():
            return False
        self.click_cancel_precheck()
        self.wait_for_precheck_cancelled(timeout_ms=timeout_ms)
        return True

    # ========================================
    # Logs
    # ========================================

    def get_precheck_logs(self) -> str:
        """Get the current precheck processing logs (empty if none rendered)."""
        logs = self._check_logs()
        if logs.count() > 0 and logs.first.is_visible():
            return logs.first.text_content() or ""
        return ""

    def wait_for_logs_contain(
        self, text: str, timeout_ms: int = 120_000, poll_ms: int = 15_000
    ) -> None:
        """Wait (reloading, with heartbeats) for the precheck logs to contain ``text``.

        The #processing-logs element is only rendered once the check has
        produced logs (``{% if check.processing_logs %}``) and the check
        section does not live-update, so reload until it appears.
        """
        deadline = time.monotonic() + timeout_ms / 1000.0
        start = time.monotonic()
        while True:
            logs = self._check_logs()
            if logs.count() > 0 and text in (logs.first.text_content() or ""):
                return
            if time.monotonic() >= deadline:
                msg = f"Logs did not contain {text!r} within {timeout_ms} ms"
                raise TimeoutError(msg)
            self._heartbeat("precheck logs", start)
            self.page.wait_for_timeout(poll_ms)
            self.page.reload()
