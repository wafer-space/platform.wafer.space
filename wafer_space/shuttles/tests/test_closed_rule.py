"""The computed open/closed rule on Shuttle (#320; Tim, issues-09)."""

import datetime

import pytest

from wafer_space.shuttles.models import Shuttle

NOW = datetime.datetime(2026, 12, 17, 11, 59, 59, tzinfo=datetime.UTC)
SECOND = datetime.timedelta(seconds=1)
AOE = datetime.timezone(datetime.timedelta(hours=-12), "AoE")
PAST = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)

# (status, submission_deadline, open to users?)
CASES = [
    (Shuttle.Status.OPEN, None, True),
    (Shuttle.Status.OPEN, NOW + SECOND, True),
    (Shuttle.Status.OPEN, NOW, False),
    (Shuttle.Status.OPEN, NOW - SECOND, False),
    (Shuttle.Status.PLANNING, None, False),
    (Shuttle.Status.FULL, NOW + SECOND, False),
    (Shuttle.Status.LOCKED, NOW + SECOND, False),
    (Shuttle.Status.IN_PRODUCTION, None, False),
    (Shuttle.Status.COMPLETED, NOW - SECOND, False),
    (Shuttle.Status.CANCELLED, None, False),
]


@pytest.mark.django_db
@pytest.mark.parametrize(("status", "deadline", "expected"), CASES)
def test_instance_and_queryset_agree(status, deadline, expected):
    shuttle = Shuttle.objects.create(
        name="G880",
        description="Rule",
        status=status,
        submission_deadline=deadline,
    )

    in_queryset = Shuttle.objects.open_to_users(now=NOW).filter(pk=shuttle.pk).exists()
    assert (shuttle.is_open_to_users(now=NOW), in_queryset) == (expected, expected)


def test_open_until_last_second_of_aoe_day():
    shuttle = Shuttle(
        name="G881",
        status=Shuttle.Status.OPEN,
        submission_deadline=datetime.datetime(2026, 12, 16, 23, 59, 59, tzinfo=AOE),
    )
    before = datetime.datetime(2026, 12, 16, 23, 59, 58, tzinfo=AOE)
    at = datetime.datetime(2026, 12, 16, 23, 59, 59, tzinfo=AOE)

    assert (shuttle.is_open_to_users(now=before), shuttle.is_open_to_users(now=at)) == (
        True,
        False,
    )


def test_closed_reason_for_passed_deadline():
    shuttle = Shuttle(name="G882", status=Shuttle.Status.OPEN, submission_deadline=PAST)

    assert shuttle.closed_reason == (
        "Shuttle G882 is closed: its GDS deadline has passed"
    )


def test_closed_reason_for_status():
    shuttle = Shuttle(name="G883", status=Shuttle.Status.IN_PRODUCTION)

    assert shuttle.closed_reason == "Shuttle G883 is closed (In Production)"


def test_open_shuttle_has_no_reason():
    shuttle = Shuttle(name="G884", status=Shuttle.Status.OPEN)

    assert (shuttle.is_closed, shuttle.closed_reason) == (False, None)
