"""Incremental container log fetching (issue #251).

Docker's ``logs(since=...)`` is inclusive: lines stamped exactly at
``since`` come back again. Each 15 s poll used to re-append the last line,
after a blank-line separator, whenever the container printed nothing new.
"""

from __future__ import annotations

import logging

import pytest

from wafer_space.projects.docker_utils import parse_docker_timestamp_float
from wafer_space.projects.tasks_checks import _fetch_and_process_logs

from .factories import ManufacturabilityCheckFactory

pytestmark = pytest.mark.django_db

LOGGER = logging.getLogger(__name__)

LINES = [
    "2026-10-11T10:00:00.100000001Z step one",
    "2026-10-11T10:00:01.200000002Z step two",
    "2026-10-11T10:00:45.300000003Z step three",
]


def stamp(line: str) -> float:
    timestamp = parse_docker_timestamp_float(line)
    assert timestamp is not None
    return timestamp


class FakeContainer:
    """Serves the lines printed so far with Docker's inclusive ``since``."""

    def __init__(self) -> None:
        self.printed: list[str] = []

    def logs(self, *, timestamps: bool, since: float | None = None) -> bytes:
        assert timestamps
        lines = [line for line in self.printed if since is None or stamp(line) >= since]
        return "".join(f"{line}\n" for line in lines).encode()


def poll(container: FakeContainer, check) -> None:
    """One do_running poll: fetch, append, then remember the latest stamp."""
    latest, _raw = _fetch_and_process_logs(container, check, LOGGER)
    if latest:
        check.logs_downloaded_until = latest
        check.save(update_fields=["logs_downloaded_until"])


def test_quiet_polls_do_not_repeat_the_last_line() -> None:
    check = ManufacturabilityCheckFactory(processing_logs="")
    container = FakeContainer()

    container.printed = LINES[:2]
    poll(container, check)
    poll(container, check)  # nothing new printed
    poll(container, check)  # nothing new printed
    container.printed = LINES
    poll(container, check)
    poll(container, check)  # nothing new printed

    check.refresh_from_db()
    assert check.processing_logs.splitlines() == [
        "step one",
        "step two",
        "step three",
    ]


def test_first_fetch_keeps_every_line() -> None:
    check = ManufacturabilityCheckFactory(processing_logs="")
    container = FakeContainer()
    container.printed = LINES

    poll(container, check)

    check.refresh_from_db()
    assert check.processing_logs.splitlines() == [
        "step one",
        "step two",
        "step three",
    ]


def test_container_lines_follow_earlier_log_sections() -> None:
    """Container output after an earlier section keeps that section intact."""
    check = ManufacturabilityCheckFactory(processing_logs="=== DISPATCHED ===")
    container = FakeContainer()
    container.printed = LINES[:1]

    poll(container, check)

    check.refresh_from_db()
    assert check.processing_logs == "=== DISPATCHED ===\n\nstep one"


def test_new_line_with_same_float_stamp_is_kept() -> None:
    """Stamps within ~240 ns collide as floats; a new line must not vanish."""
    check = ManufacturabilityCheckFactory(processing_logs="")
    container = FakeContainer()
    first = "2026-10-11T10:00:00.100000001Z first"
    same_float = "2026-10-11T10:00:00.100000002Z second"
    assert stamp(first) == stamp(same_float)

    container.printed = [first]
    poll(container, check)
    container.printed = [first, same_float]
    poll(container, check)

    check.refresh_from_db()
    assert check.processing_logs.splitlines() == ["first", "second"]


def test_partial_line_completed_later_is_not_lost() -> None:
    """Docker returns a completed partial line under its first stamp."""
    check = ManufacturabilityCheckFactory(processing_logs="")
    container = FakeContainer()

    container.printed = ["2026-10-11T10:00:00.100000001Z Progress: 50%"]
    poll(container, check)
    # One element: Docker sends the completed line as a single chunk, still
    # under the partial line's stamp. The concatenation is deliberate.
    container.printed = [
        (
            "2026-10-11T10:00:00.100000001Z Progress: 50%"
            "2026-10-11T10:00:05.000000000Z ... done"
        ),
    ]
    poll(container, check)

    check.refresh_from_db()
    assert "done" in check.processing_logs
