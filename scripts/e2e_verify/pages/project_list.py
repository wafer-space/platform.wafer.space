"""Project list page interactions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page

# The list links each project by pk (UUID): /projects/<uuid>/
_PROJECT_HREF = re.compile(r"^/projects/([0-9a-fA-F-]{36})/$")


class ProjectListPage(BasePage):
    """Page Object for the current user's project list."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def project_ids(self) -> list[str]:
        """Return all of the current user's project UUIDs, across all pages.

        The list paginates (20/page via ``?page=N``); we walk pages until one
        yields no new project ids (an empty page, or the paginator clamping).
        """
        ids: list[str] = []
        page_num = 1
        while True:
            self.navigate(f"/projects/?page={page_num}")
            hrefs = self.page.eval_on_selector_all(
                "a[href^='/projects/']",
                "els => els.map(e => e.getAttribute('href'))",
            )
            found = [m.group(1) for h in hrefs if (m := _PROJECT_HREF.match(h or ""))]
            new = [pid for pid in found if pid not in ids]
            if not new:
                return ids
            ids.extend(new)
            page_num += 1
