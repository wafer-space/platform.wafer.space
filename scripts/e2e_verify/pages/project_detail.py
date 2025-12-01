"""Project detail page interactions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


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

    # ========================================
    # Download status
    # ========================================

    def wait_for_downloading(self, timeout_ms: int | None = None) -> None:
        """Wait for download to start."""
        timeout = timeout_ms or self.DOWNLOAD_TIMEOUT
        expect(self.page.get_by_text("Downloading")).to_be_visible(timeout=timeout)

    def wait_for_downloaded(self, timeout_ms: int | None = None) -> None:
        """Wait for download to complete."""
        timeout = timeout_ms or self.DOWNLOAD_TIMEOUT
        expect(self.page.get_by_text("Downloaded")).to_be_visible(timeout=timeout)

    # ========================================
    # Hash verification status
    # ========================================

    def wait_for_hash_verified(self, timeout_ms: int | None = None) -> None:
        """Wait for hash verification to pass."""
        timeout = timeout_ms or self.HASH_TIMEOUT
        expect(self.page.get_by_text("Hash Verified")).to_be_visible(timeout=timeout)

    def wait_for_hash_mismatch(self, timeout_ms: int | None = None) -> None:
        """Wait for hash mismatch to be detected."""
        timeout = timeout_ms or self.HASH_TIMEOUT
        expect(self.page.get_by_text("Hash Mismatch")).to_be_visible(timeout=timeout)

    # ========================================
    # Manufacturability precheck status
    # ========================================

    def wait_for_precheck_queued(self, timeout_ms: int | None = None) -> None:
        """Wait for precheck to be queued."""
        timeout = timeout_ms or self.PRECHECK_START_TIMEOUT
        expect(self.page.get_by_text("Check Queued")).to_be_visible(timeout=timeout)

    def wait_for_precheck_running(self, timeout_ms: int | None = None) -> None:
        """Wait for precheck to start running."""
        timeout = timeout_ms or self.PRECHECK_START_TIMEOUT
        expect(self.page.get_by_text("Checking...")).to_be_visible(timeout=timeout)

    def wait_for_precheck_complete(self, timeout_ms: int | None = None) -> None:
        """Wait for precheck to finish (either pass or fail)."""
        timeout = timeout_ms or self.PRECHECK_COMPLETE_TIMEOUT
        # Match either "Manufacturable" or "Not Manufacturable"
        expect(
            self.page.get_by_text(re.compile(r"^Manufacturable|^Not Manufacturable"))
        ).to_be_visible(timeout=timeout)

    def wait_for_precheck_cancelled(self, timeout_ms: int | None = None) -> None:
        """Wait for precheck cancellation to be confirmed."""
        timeout = timeout_ms or 30_000
        expect(self.page.get_by_text("Check Cancelled")).to_be_visible(timeout=timeout)

    def is_manufacturable(self) -> bool:
        """Check if the design passed manufacturability check.

        Call after wait_for_precheck_complete().
        """
        # Check for "Manufacturable" but not "Not Manufacturable"
        manufacturable = self.page.get_by_text("Manufacturable").first
        not_manufacturable = self.page.get_by_text("Not Manufacturable").first

        if not_manufacturable.is_visible():
            return False
        return manufacturable.is_visible()

    # ========================================
    # Actions
    # ========================================

    def click_cancel_precheck(self) -> None:
        """Click the cancel button for the manufacturability check."""
        # Set up dialog handler before clicking
        self.page.on("dialog", lambda dialog: dialog.accept())

        # Find and click the Cancel button
        self.page.get_by_role("button", name="Cancel").click()

    # ========================================
    # Logs
    # ========================================

    def get_precheck_logs(self) -> str:
        """Get the current precheck processing logs."""
        logs_element = self.page.locator("#processing-logs")
        if logs_element.is_visible():
            return logs_element.text_content() or ""
        return ""

    def wait_for_logs_contain(self, text: str, timeout_ms: int = 60_000) -> None:
        """Wait for precheck logs to contain specific text."""
        expect(self.page.locator("#processing-logs")).to_contain_text(
            text, timeout=timeout_ms
        )
