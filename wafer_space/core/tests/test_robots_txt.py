"""Tests for /robots.txt (issue #338).

Crawlers fetched the bare OAuth callback URL they found through the login
redirect, and every hit emailed ADMINS. robots.txt keeps well-behaved
crawlers off the login, account and private pages, and leaves the public
pages crawlable.
"""

from __future__ import annotations

from http import HTTPStatus
from urllib.robotparser import RobotFileParser

import pytest
from django.conf import settings
from django.test import Client

EXPECTED_DISALLOWS = {
    "/accounts/",
    f"/{settings.ADMIN_URL}",
    "/users/",
    "/projects/",
    "/shuttles/",
    "/notifications/",
    "/health/",
    "/legal/tos/accept/",
}


@pytest.fixture
def robots_lines() -> list[str]:
    """The lines of /robots.txt, fetched anonymously."""
    response = Client().get("/robots.txt")
    assert response.status_code == HTTPStatus.OK
    return response.content.decode().splitlines()


@pytest.fixture
def robots_parser(robots_lines: list[str]) -> RobotFileParser:
    parser = RobotFileParser()
    parser.parse(robots_lines)
    return parser


def test_robots_txt_is_plain_text() -> None:
    """Crawlers expect text/plain."""
    response = Client().get("/robots.txt")

    assert response.status_code == HTTPStatus.OK
    assert response["Content-Type"] == "text/plain"


def test_robots_txt_disallows_private_paths(robots_lines: list[str]) -> None:
    """Exactly the login, account and private sections are disallowed."""
    disallows = {
        line.removeprefix("Disallow: ")
        for line in robots_lines
        if line.startswith("Disallow: ")
    }

    assert disallows == EXPECTED_DISALLOWS


def test_robots_txt_admin_line_matches_setting(robots_lines: list[str]) -> None:
    """The admin line is rendered from ADMIN_URL, so it can't drift."""
    assert f"Disallow: /{settings.ADMIN_URL}" in robots_lines


def test_robots_txt_has_one_group(robots_lines: list[str]) -> None:
    """A blank line ends a group, which would orphan later Disallow lines."""
    assert robots_lines[0] == "User-agent: *"
    assert "" not in robots_lines


@pytest.mark.parametrize("path", ["/", "/about/", "/legal/tos/"])
def test_public_pages_are_crawlable(robots_parser: RobotFileParser, path: str) -> None:
    """The home, about and ToS pages stay open to crawlers."""
    assert robots_parser.can_fetch("*", path)


def test_oauth_callback_is_not_crawlable(robots_parser: RobotFileParser) -> None:
    """The URL behind the admin emails in #338 is disallowed."""
    assert not robots_parser.can_fetch("*", "/accounts/google/login/callback/")
