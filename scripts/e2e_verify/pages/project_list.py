"""Project list page interactions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page

# Each list row names its project's pk (UUID) in data-project-row. The row's
# link is the canonical URL, which is the full_id once a shuttle is assigned.
_PROJECT_ROW = "[data-project-row]"


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
            found = self.page.eval_on_selector_all(
                _PROJECT_ROW,
                "els => els.map(e => e.getAttribute('data-project-row'))",
            )
            new = [pid for pid in found if pid not in ids]
            if not new:
                return ids
            ids.extend(new)
            page_num += 1
