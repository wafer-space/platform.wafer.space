"""Project creation page interactions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class ProjectCreatePage(BasePage):
    """Page Object for project creation."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def create_project(self, name: str, slot_size: str = "0p5x0p5") -> str:
        """Create a new project.

        Args:
            name: Project name
            slot_size: Slot size value (0p5x0p5, 1x1, 0p5x1, 1x0p5)

        Returns:
            Project UUID from the redirect URL
        """
        self.navigate("/projects/create/")

        # Fill project form
        self.page.fill('input[name="name"]', name)
        self.page.select_option('select[name="slot_size"]', slot_size)

        # Submit form
        self.page.click('button[type="submit"]')

        # Wait for redirect to project detail page
        expect(self.page).to_have_url(re.compile(r"/projects/[\w-]+/$"))

        # Extract project UUID from URL
        match = re.search(r"/projects/([\w-]+)/", self.page.url)
        if match:
            return match.group(1)
        msg = f"Could not extract project ID from URL: {self.page.url}"
        raise ValueError(msg)
