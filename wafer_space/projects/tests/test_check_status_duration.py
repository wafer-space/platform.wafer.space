"""Check-status page: Duration is a check's runtime, not time since it finished (#296).

On 9 Jul 2026 a check that ran about 37 minutes showed a "Duration" of 48h,
because the column rendered ``state_entered_at|duration_since``: how long ago
the check finished.
"""

from __future__ import annotations

from datetime import timedelta
from html.parser import HTMLParser
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.users.tests.factories import UserFactory

from .factories import ManufacturabilityCheckFactory
from .html_elements import parse_html

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

Status = ManufacturabilityCheck.Status


def make_check(
    status: str,
    *,
    created_ago: timedelta,
    ran_for: timedelta | None = None,
    analysed_after: timedelta | None = None,
) -> ManufacturabilityCheck:
    """A check created ``created_ago``; created_at is auto_now_add, so update it."""
    created_at = timezone.now() - created_ago
    check = ManufacturabilityCheckFactory(status=status)
    fields: dict[str, object] = {"created_at": created_at}
    if ran_for is not None:
        fields["container_started_at"] = created_at
        fields["container_finished_at"] = created_at + ran_for
    if analysed_after is not None:
        fields["analysis_completed_at"] = created_at + analysed_after
    ManufacturabilityCheck.objects.filter(pk=check.pk).update(**fields)
    return ManufacturabilityCheck.objects.get(pk=check.pk)


class TestEndToEndDuration:
    def test_finished_check_is_created_to_analysed(self) -> None:
        check = make_check(
            Status.FINISHED,
            created_ago=timedelta(hours=48),
            ran_for=timedelta(minutes=35),
            analysed_after=timedelta(minutes=37),
        )
        assert check.end_to_end_duration == timedelta(minutes=37)

    @pytest.mark.parametrize("status", [Status.ERROR, Status.CANCELLED])
    def test_none_when_no_end_time_is_recorded(self, status: str) -> None:
        check = make_check(status, created_ago=timedelta(hours=2))
        assert check.end_to_end_duration is None

    def test_none_while_running(self) -> None:
        check = make_check(Status.RUNNING, created_ago=timedelta(minutes=5))
        assert check.end_to_end_duration is None


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (Status.FINISHED, True),
        (Status.ERROR, True),
        (Status.CANCELLED, True),
        (Status.PENDING, False),
        (Status.RUNNING, False),
        (Status.CANCELLING, False),
    ],
)
def test_is_terminal(status: str, *, expected: bool) -> None:
    assert make_check(status, created_ago=timedelta(0)).is_terminal is expected


HISTORY_DURATION_TITLE = "Queue plus run time, from created to analysed"


class _DurationColumn(HTMLParser):
    """Text of the Duration column in the table whose header has that title."""

    def __init__(self) -> None:
        super().__init__()
        self.cells: list[str] = []
        self._in_history = False
        self._column = -1
        self._duration_column = -1
        self._cell_text: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._column = -1
        elif tag in {"th", "td"}:
            self._column += 1
            if tag == "th" and dict(attrs).get("title") == HISTORY_DURATION_TITLE:
                self._in_history = True
                self._duration_column = self._column
            if tag == "td" and self._in_history:
                if self._column == self._duration_column:
                    self._cell_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._cell_text is not None:
            self.cells.append(" ".join("".join(self._cell_text).split()))
            self._cell_text = None
        elif tag == "table":
            self._in_history = False

    def handle_data(self, data: str) -> None:
        if self._cell_text is not None:
            self._cell_text.append(data)


def recent_checks_cells(client: Client) -> list[str]:
    """Text of the Duration cell of each Recent Checks row, newest first."""
    client.force_login(UserFactory(is_staff=True))
    parser = _DurationColumn()
    parser.feed(client.get(reverse("projects:admin_check_status")).content.decode())
    parser.close()
    return parser.cells


class TestCheckStatusPage:
    def test_finished_check_shows_its_runtime_not_time_since(
        self, client: Client
    ) -> None:
        """The #296 case: 37 minutes, not the 48 hours since it finished."""
        make_check(
            Status.FINISHED,
            created_ago=timedelta(hours=48),
            ran_for=timedelta(minutes=35),
            analysed_after=timedelta(minutes=37),
        )
        assert recent_checks_cells(client) == ["37m"]

    def test_error_check_shows_dash_with_reason(self, client: Client) -> None:
        make_check(Status.ERROR, created_ago=timedelta(hours=3))
        client.force_login(UserFactory(is_staff=True))
        html = client.get(reverse("projects:admin_check_status")).content.decode()
        titles = [
            attrs.get("title")
            for tag, attrs in parse_html(html).elements
            if tag == "span"
        ]
        assert "No end time is recorded for error checks" in titles

    def test_running_check_shows_in_progress_in_history(self, client: Client) -> None:
        make_check(Status.RUNNING, created_ago=timedelta(minutes=5))
        cells = recent_checks_cells(client)
        assert cells == ["in progress"]

    def test_active_table_header_says_in_state(self, client: Client) -> None:
        """The active tables keep time-in-state, under a header that says so."""
        make_check(Status.RUNNING, created_ago=timedelta(minutes=5))
        client.force_login(UserFactory(is_staff=True))
        html = client.get(reverse("projects:admin_check_status")).content.decode()
        headers = [
            attrs.get("title")
            for tag, attrs in parse_html(html).elements
            if tag == "th"
        ]
        assert any(
            (title or "").startswith("Time since the check entered its current state")
            for title in headers
        )
