"""File URL submission page interactions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class FileSubmitPage(BasePage):
    """Page Object for file URL submission."""

    def __init__(self, page: Page, base_url: str, project_id: str) -> None:
        super().__init__(page, base_url)
        self.project_id = project_id

    def submit_file(self, url: str, sha256_hash: str | None = None) -> None:
        """Submit a file URL for download.

        Args:
            url: URL to download file from
            sha256_hash: Optional SHA256 hash for verification
                (without 'sha256:' prefix)
        """
        self.navigate(f"/projects/{self.project_id}/submit-url/")

        # Fill URL field
        self.page.fill('input[name="url"]', url)

        # Fill SHA256 hash if provided
        if sha256_hash:
            # Remove prefix if present
            hash_value = sha256_hash
            if hash_value.startswith("sha256:"):
                hash_value = hash_value[7:]
            self.page.fill('input[name="expected_hash_sha256"]', hash_value)

        # Submit form
        self.page.click('button[type="submit"]')

        # Wait for the redirect to the project detail page. The negative
        # lookahead excludes the submit-url page we were on, so a validation
        # failure (which re-renders submit-url) surfaces here instead of
        # passing because the URL still shares the /projects/<id>/ prefix.
        expect(self.page).to_have_url(
            re.compile(rf"/projects/{self.project_id}/(?!submit-url)")
        )
