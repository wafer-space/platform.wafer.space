"""The deadline display include: AoE, local time, countdown (#349)."""

from __future__ import annotations

import datetime
import re

import pytest
from django.template import Context
from django.template import Template
from django.utils import timezone

from wafer_space.shuttles.templatetags.shuttle_dates import compact_countdown

TEMPLATE = Template(
    '{% load shuttle_dates %}{% shuttle_deadline deadline label="GDS due" %}',
)
G803_DEADLINE = datetime.datetime(2026, 12, 17, 11, 59, 59, tzinfo=datetime.UTC)


def render(deadline: datetime.datetime) -> str:
    return TEMPLATE.render(Context({"deadline": deadline}))


def has_local_time(html: str, iso_utc: str) -> bool:
    """The <time> element carries the UTC instant and the JS hook.

    Whitespace between the attributes is the template's layout, not
    behaviour, so any amount is accepted.
    """
    pattern = rf'<time\s+datetime="{re.escape(iso_utc)}"\s+data-local-time>'
    return re.search(pattern, html) is not None


def future(days: int) -> datetime.datetime:
    return timezone.now() + datetime.timedelta(days=days, hours=1)


def test_shows_label_and_aoe_date_with_zone_linked() -> None:
    html = render(G803_DEADLINE)
    assert "GDS due" in html
    assert "16 December 2026 @ 11:59 PM" in html
    assert 'href="https://en.wikipedia.org/wiki/Anywhere_on_Earth"' in html


def test_local_time_element_carries_utc_instant_and_fallback_link() -> None:
    html = render(G803_DEADLINE)
    assert has_local_time(html, "2026-12-17T11:59:59Z")
    assert "fixedtime.html?iso=20261216T2359&amp;p1=3399" in html


def test_future_deadline_counts_down_from_utc_instant() -> None:
    deadline = future(days=10)
    html = render(deadline)
    expected = deadline.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert f'data-countdown="{expected}"' in html
    assert "10 days left" in html


def test_past_deadline_rendered_as_passed_without_countdown() -> None:
    html = render(timezone.now() - datetime.timedelta(minutes=1))
    assert "Deadline passed" in html
    assert "data-countdown" not in html


COMPACT = Template(
    "{% load shuttle_dates %}{% shuttle_deadline deadline compact=True %}",
)


def test_compact_form_counts_down_with_aoe_date_in_title() -> None:
    deadline = future(days=12)
    html = COMPACT.render(Context({"deadline": deadline}))
    expected = deadline.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert f'data-countdown="{expected}"' in html
    assert "data-countdown-compact" in html
    # future() adds an hour, and rendering takes a moment of it.
    assert "12 d 0 h left" in html
    assert 'title="GDS submission deadline:' in html


@pytest.mark.parametrize(
    ("remaining", "expected"),
    [
        (datetime.timedelta(days=29, hours=5, minutes=59), "29 d 5 h left"),
        (datetime.timedelta(days=128, hours=23), "128 d 23 h left"),
        (datetime.timedelta(days=1), "1 d 0 h left"),
        (datetime.timedelta(hours=23, minutes=59, seconds=59), "23 h 59 m left"),
        (datetime.timedelta(minutes=5, seconds=30), "0 h 5 m left"),
        (datetime.timedelta(seconds=1), "0 h 0 m left"),
    ],
)
def test_compact_countdown_matches_the_script_format(
    remaining: datetime.timedelta,
    expected: str,
) -> None:
    """Same words as compactText() in shuttle_deadlines.js (#465)."""
    assert compact_countdown(remaining) == expected


def test_compact_form_past_deadline() -> None:
    past = timezone.now() - datetime.timedelta(hours=1)
    html = COMPACT.render(Context({"deadline": past}))
    assert "Deadline passed" in html
    assert "data-countdown" not in html
