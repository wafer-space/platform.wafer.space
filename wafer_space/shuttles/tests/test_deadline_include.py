"""The deadline display include: AoE, local time, countdown (#349)."""

from __future__ import annotations

import datetime
import re

from django.template import Context
from django.template import Template
from django.utils import timezone

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
    assert "12 d left" in html
    assert 'title="GDS submission deadline:' in html


def test_compact_form_past_deadline() -> None:
    past = timezone.now() - datetime.timedelta(hours=1)
    html = COMPACT.render(Context({"deadline": past}))
    assert "Deadline passed" in html
    assert "data-countdown" not in html
