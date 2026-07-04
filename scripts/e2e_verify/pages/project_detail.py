"""Project detail page interactions.

Status is surfaced through Bootstrap badges (``span.badge``). Several statuses
can appear more than once on the page (a per-file badge plus a dedicated check
section), and the plain status words also appear in prose/table headers, so
every check here is scoped to ``span.badge`` and takes the first match.

Badge labels (from the templates / model status metadata):
  - download:  "Downloaded" | "Downloading" | "Download Failed" | "Pending"
  - hash:      "Hash Verified" | "Hash Mismatch" | "Hash Not Verified"
  - precheck:  "Pending" | "Dispatching" | "Starting" | "Running" |
               "Analyzing" | "Cancelling" | "Cancelled" | "Passed" | "Failed"
    (a *finished* check shows "Passed"/"Failed", not "Manufacturable")
"""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Locator
    from playwright.sync_api import Page

# A finished check labels the badge "Failed"; the download badge uses
# "Download Failed". This matches the precheck "Failed" but not the download one.
_CHECK_FAILED = re.compile(r"(?<!Download )Failed")


class ProjectDetailPage(BasePage):
    """Page Object for project detail page with status monitoring."""

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

    def _badge(self, pattern: str | re.Pattern[str]) -> Locator:
        """First status badge whose text matches ``pattern`` (str or regex)."""
        return self.page.locator("span.badge").filter(has_text=pattern).first

    def _wait_badge_reloading(
        self,
        pattern: str | re.Pattern[str],
        timeout_ms: int,
        poll_ms: int = 10_000,
    ) -> None:
        """Poll for a matching badge, reloading the page between checks.

        The detail page live-updates the file (download/hash) badges but not
        the manufacturability-check badge, so we reload to pick up check-status
        transitions (created -> running -> finished).
        """
        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            if self._badge(pattern).is_visible():
                return
            if time.monotonic() >= deadline:
                msg = f"No badge matching {pattern!r} within {timeout_ms} ms"
                raise TimeoutError(msg)
            self.page.wait_for_timeout(poll_ms)
            self.page.reload()

    # ========================================
    # Download / hash status
    # ========================================

    def wait_for_downloaded(self, timeout_ms: int | None = None) -> None:
        """Wait for the file download to reach a terminal state.

        The download badge shows "Downloaded" on success or "Hash Mismatch"
        when the file downloaded but the hash didn't match; either (as well as
        a "Hash Verified" badge) means the download itself completed.
        """
        timeout = timeout_ms or self.DOWNLOAD_TIMEOUT
        expect(
            self._badge(re.compile(r"Downloaded|Hash Verified|Hash Mismatch"))
        ).to_be_visible(timeout=timeout)

    def wait_for_hash_verified(self, timeout_ms: int | None = None) -> None:
        """Wait for hash verification to pass."""
        timeout = timeout_ms or self.HASH_TIMEOUT
        expect(self._badge("Hash Verified")).to_be_visible(timeout=timeout)

    def wait_for_hash_mismatch(self, timeout_ms: int | None = None) -> None:
        """Wait for hash mismatch to be detected."""
        timeout = timeout_ms or self.HASH_TIMEOUT
        expect(self._badge("Hash Mismatch")).to_be_visible(timeout=timeout)

    # ========================================
    # Manufacturability precheck status
    # ========================================

    def wait_for_precheck_running(self, timeout_ms: int | None = None) -> None:
        """Wait for the precheck to be queued or running (any in-progress state)."""
        timeout = timeout_ms or self.PRECHECK_START_TIMEOUT
        self._wait_badge_reloading(
            re.compile(r"Pending|Dispatching|Starting|Running|Analyzing"), timeout
        )

    def wait_for_precheck_complete(self, timeout_ms: int | None = None) -> None:
        """Wait for the precheck to finish (badge shows "Passed" or "Failed")."""
        timeout = timeout_ms or self.PRECHECK_COMPLETE_TIMEOUT
        # DRC can run a long time; reload less aggressively.
        self._wait_badge_reloading(
            re.compile(r"Passed|(?<!Download )Failed"), timeout, poll_ms=30_000
        )

    def wait_for_precheck_cancelled(self, timeout_ms: int | None = None) -> None:
        """Wait for precheck cancellation to be confirmed."""
        timeout = timeout_ms or 30_000
        self._wait_badge_reloading("Cancelled", timeout, poll_ms=3_000)

    def is_manufacturable(self) -> bool:
        """Whether the finished check passed.

        Call after :meth:`wait_for_precheck_complete`. A passing check shows a
        "Passed" badge; a failing one shows "Failed".
        """
        if self._badge(_CHECK_FAILED).is_visible():
            return False
        return self._badge("Passed").is_visible()

    # ========================================
    # Actions
    # ========================================

    def click_cancel_precheck(self) -> None:
        """Click the cancel button for the manufacturability check."""
        # Accept the confirmation dialog before clicking.
        self.page.on("dialog", lambda dialog: dialog.accept())
        self.page.get_by_role("button", name="Cancel").first.click()

    # ========================================
    # Logs
    # ========================================

    def get_precheck_logs(self) -> str:
        """Get the current precheck processing logs."""
        logs_element = self.page.locator("#processing-logs")
        if logs_element.is_visible():
            return logs_element.text_content() or ""
        return ""

    def wait_for_logs_contain(
        self, text: str, timeout_ms: int = 120_000, poll_ms: int = 5_000
    ) -> None:
        """Wait (reloading) for the precheck logs to contain ``text``.

        The #processing-logs element is only rendered once the check has
        produced logs (``{% if check.processing_logs %}``) and the check
        section does not live-update, so reload until it appears.
        """
        deadline = time.monotonic() + timeout_ms / 1000.0
        while True:
            logs = self.page.locator("#processing-logs")
            if logs.count() > 0 and text in (logs.first.text_content() or ""):
                return
            if time.monotonic() >= deadline:
                msg = f"Logs did not contain {text!r} within {timeout_ms} ms"
                raise TimeoutError(msg)
            self.page.wait_for_timeout(poll_ms)
            self.page.reload()
