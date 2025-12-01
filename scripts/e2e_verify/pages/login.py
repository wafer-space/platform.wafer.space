"""Login page interactions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class LoginPage(BasePage):
    """Page Object for the login page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def login(self, username: str, password: str) -> None:
        """Log in with username and password.

        Args:
            username: Email or username
            password: Password
        """
        self.navigate("/accounts/login/")

        # Fill login form - using name attributes from allauth
        self.page.fill('input[name="login"]', username)
        self.page.fill('input[name="password"]', password)

        # Click sign in button
        self.page.click('button[type="submit"]')

        # Wait for redirect away from login page
        expect(self.page).not_to_have_url(re.compile(r".*/accounts/login/.*"))
