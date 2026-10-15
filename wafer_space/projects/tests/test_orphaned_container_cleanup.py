"""The orphan sweep removes duplicate containers of an active check (#187).

An active check owns the one container ``mark_running`` recorded in
``docker_container_id``. Any other container labelled with its id is a
duplicate. Before RUNNING the current attempt's container is not recorded
yet, so every container of a dispatching or starting check is kept.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from dataclasses import field
from unittest.mock import patch

import pytest

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.tasks_checks import _cleanup_container_if_orphaned
from wafer_space.projects.tasks_checks import _site_label

from .factories import ManufacturabilityCheckFactory

pytestmark = pytest.mark.django_db

Status = ManufacturabilityCheck.Status
OWN = "a" * 64
DUPLICATE = "b" * 64
LOGGER = logging.getLogger(__name__)
RECORDED = [Status.RUNNING, Status.ANALYZING, Status.CANCELLING]
NOT_YET_RECORDED = [Status.DISPATCHING, Status.STARTING]


@dataclass
class FakeContainer:
    """The attributes the sweep reads from a docker container."""

    id: str
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def short_id(self) -> str:
        return self.id[:12]


def sweep(check: ManufacturabilityCheck, container_id: str) -> tuple[str, bool]:
    """(result, whether it was stopped) for one container of ``check``."""
    container = FakeContainer(
        id=container_id,
        labels={
            "wafer.space.site": _site_label(),
            "wafer.space.check_id": str(check.pk),
        },
    )
    with patch("wafer_space.projects.tasks_checks.stop_and_remove_container") as stop:
        result = _cleanup_container_if_orphaned(
            container,
            "server-1",
            _site_label(),
            list(Status.active()),
            LOGGER,
        )
    return result, stop.called


@pytest.mark.parametrize("status", RECORDED)
def test_duplicate_of_a_recorded_container_is_removed(status: str) -> None:
    check = ManufacturabilityCheckFactory(status=status, docker_container_id=OWN)

    assert sweep(check, DUPLICATE) == ("removed", True)


@pytest.mark.parametrize("status", RECORDED)
def test_the_recorded_container_is_kept(status: str) -> None:
    check = ManufacturabilityCheckFactory(status=status, docker_container_id=OWN)

    assert sweep(check, OWN) == ("kept", False)


@pytest.mark.parametrize("status", NOT_YET_RECORDED)
def test_containers_of_a_starting_check_are_kept(status: str) -> None:
    """Its container may exist before mark_running records it."""
    check = ManufacturabilityCheckFactory(status=status, docker_container_id="")

    assert sweep(check, DUPLICATE) == ("kept", False)


def test_starting_check_keeps_containers_even_with_a_stale_id() -> None:
    """Never trust an id recorded by an earlier attempt while starting."""
    check = ManufacturabilityCheckFactory(
        status=Status.STARTING,
        docker_container_id=OWN,
    )

    assert sweep(check, DUPLICATE) == ("kept", False)


def test_running_check_without_a_recorded_id_keeps_its_containers() -> None:
    """Nothing to compare against, so nothing is called a duplicate."""
    check = ManufacturabilityCheckFactory(
        status=Status.RUNNING,
        docker_container_id="",
    )

    assert sweep(check, DUPLICATE) == ("kept", False)


def test_finished_check_container_is_still_removed() -> None:
    """The existing rule is unchanged."""
    check = ManufacturabilityCheckFactory(
        status=Status.FINISHED,
        is_manufacturable=True,
        docker_container_id=OWN,
    )

    assert sweep(check, OWN) == ("removed", True)
