"""Dates are rendered day first or year first, never month first (#412).

``LocaleMiddleware`` picks date formats from the visitor's browser
language, so every language Django offers is checked, not only English.
"""

from __future__ import annotations

import datetime as dt
import re

import pytest
from django.conf import settings
from django.utils import dateformat
from django.utils import formats
from django.utils import translation

# Day 23 and month 11 cannot be mistaken for each other or for the year.
INSTANT = dt.datetime(2026, 11, 23, 14, 5, tzinfo=dt.UTC)
YEAR = "2026"
DAY = "23"
DATE_FORMAT_NAMES = (
    "DATE_FORMAT",
    "DATETIME_FORMAT",
    "SHORT_DATE_FORMAT",
    "SHORT_DATETIME_FORMAT",
)
# en-us is not in settings.LANGUAGES but is what US browsers send; it
# resolves through the en formats.
LANGUAGE_CODES = sorted({code for code, _name in settings.LANGUAGES} | {"en-us"})


def _month_tokens() -> list[str]:
    """The month as the active language writes it: number and names."""
    names = {formats.date_format(INSTANT, code) for code in "FNMbE"}
    return ["11", *(name.rstrip(".") for name in names if name)]


def _position(rendered: str, tokens: list[str]) -> int | None:
    found = [rendered.find(token) for token in tokens if token in rendered]
    return min(found) if found else None


def _parts(rendered: str) -> dict[str, int]:
    """Where the day, month and year start in ``rendered``, if present."""
    parts = {
        "day": _position(rendered, [DAY]),
        "month": _position(rendered, _month_tokens()),
        "year": _position(rendered, [YEAR]),
    }
    return {name: at for name, at in parts.items() if at is not None}


def _order(rendered: str) -> str:
    """Which part of ``rendered`` comes first: day, month or year."""
    found = _parts(rendered)
    assert len(found) == len(("day", "month", "year")), (
        f"{rendered!r} lacks a day, month or year"
    )
    return min(found, key=found.__getitem__)


def _template_date_literals() -> list[tuple[str, str]]:
    """Every literal ``|date:"..."`` format in the repository's templates."""
    literal = re.compile(r"""\|date:\s*(["'])(.+?)\1""")
    found = []
    for path in sorted(settings.APPS_DIR.rglob("templates/**/*")):
        if path.suffix not in {".html", ".txt"}:
            continue
        for match in literal.finditer(path.read_text(encoding="utf-8")):
            relative = path.relative_to(settings.BASE_DIR)
            found.append((str(relative), match.group(2)))
    return found


@pytest.mark.parametrize("language", LANGUAGE_CODES)
def test_date_formats_are_not_month_first(language: str) -> None:
    """Every date format starts with the day or the year (ISO 8601 order)."""
    with translation.override(language):
        rendered = {
            name: formats.date_format(INSTANT, name) for name in DATE_FORMAT_NAMES
        }
        month_first = {
            name: text for name, text in rendered.items() if _order(text) == "month"
        }

    assert not month_first, f"{language} renders month first: {month_first}"


@pytest.mark.parametrize("language", ["en", "en-us"])
def test_english_formats(language: str) -> None:
    """English, including US browsers, gets the platform's own formats."""
    with translation.override(language):
        rendered = [
            formats.date_format(INSTANT, name)
            for name in (*DATE_FORMAT_NAMES, "MONTH_DAY_FORMAT", "TIME_FORMAT")
        ]

    assert rendered == [
        "23 Nov 2026",
        "23 Nov 2026, 14:05",
        "2026-11-23",
        "2026-11-23 14:05",
        "23 November",
        "14:05",
    ]


def test_template_date_literals_are_not_month_first() -> None:
    """A literal ``|date:"..."`` bypasses the settings above, so each one in
    the templates is checked too: month before day only after the year."""
    literals = _template_date_literals()
    with translation.override("en"):
        month_first = []
        for path, date_format in literals:
            found = _parts(dateformat.format(INSTANT, date_format))
            day, month, year = (found.get(n) for n in ("day", "month", "year"))
            if day is None or month is None:
                continue
            if month < day and (year is None or year > month):
                month_first.append((path, date_format))

    assert literals, "no |date literals found; is the template search broken?"
    assert not month_first, f"month-first |date literals: {month_first}"
