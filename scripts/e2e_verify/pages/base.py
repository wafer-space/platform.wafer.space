"""Base Page Object Model for all pages."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page


class BasePage:
    """Base page class with common Playwright helpers."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url.rstrip("/")

    def navigate(self, path: str = "") -> None:
        """Navigate to a path relative to base_url."""
        url = f"{self.base_url}{path}"
        self.page.goto(url)

    def screenshot(self, name: str) -> Path:
        """Take a screenshot and save to screenshots/ directory."""
        screenshots_dir = Path("screenshots")
        screenshots_dir.mkdir(exist_ok=True)
        filepath = screenshots_dir / f"{name}.png"
        self.page.screenshot(path=str(filepath))
        return filepath

    def get_current_path(self) -> str:
        """Get the current URL path (without base_url)."""
        url = self.page.url
        if url.startswith(self.base_url):
            return url[len(self.base_url) :]
        return url
