"""Project creation page interactions."""

from __future__ import annotations

import re
import secrets
import string
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class ProjectCreatePage(BasePage):
    """Page Object for project creation."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def create_project(
        self,
        name: str,
        slot_size: str = "0p5x0p5",
        *,
        chip_on_board: bool = False,
        project_id: str | None = None,
        license_type: str = "Apache-2.0",
    ) -> str:
        """Create a new project.

        Args:
            name: Project name
            slot_size: Slot size value (0p5x0p5, 1x1, 0p5x1, 1x0p5)
            chip_on_board: Request chip-on-board (CoB) packaging, which makes
                the precheck run its DRC in CoB mode (``--cob``).
            project_id: 4-char [A-Z0-9] project id, unique within the shuttle.
                A random one is generated when not provided.
            license_type: License to select. Defaults to an OSS license so the
                proprietary-terms URL is not required.

        Returns:
            The project's full id from the redirect URL (e.g. ``G802AB12``).
        """
        if project_id is None:
            alphabet = string.ascii_uppercase + string.digits
            project_id = "".join(secrets.choice(alphabet) for _ in range(4))

        self.navigate("/projects/create/")

        # Fill the form. project_id and name are required; shuttle and slot_size
        # default, and license_type is set to an OSS license so no extra
        # (proprietary-terms) fields become required.
        self.page.fill('input[name="project_id"]', project_id)
        self.page.fill('input[name="name"]', name)
        self.page.select_option('select[name="slot_size"]', slot_size)
        self.page.select_option('select[name="license_type"]', license_type)
        if chip_on_board:
            self.page.check('input[name="chip_on_board"]')

        # Submit form
        self.page.click('button[type="submit"]')

        # Wait for redirect to the project detail page. The negative lookahead
        # excludes '/projects/create/' so a validation failure (which re-renders
        # the create page) surfaces as a timeout instead of a bogus "create" id.
        expect(self.page).to_have_url(re.compile(r"/projects/(?!create/)[\w-]+/$"))

        # Extract the project's full id from the URL
        match = re.search(r"/projects/([\w-]+)/", self.page.url)
        if match:
            return match.group(1)
        msg = f"Could not extract project ID from URL: {self.page.url}"
        raise ValueError(msg)
