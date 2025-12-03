"""Test factories for shuttles app."""

from __future__ import annotations

from factory import Sequence
from factory.django import DjangoModelFactory

from wafer_space.shuttles.models import Shuttle


class ShuttleFactory(DjangoModelFactory[Shuttle]):
    """Factory for creating test Shuttle instances."""

    name = Sequence(lambda n: f"G8{n:02d}")
    description = Sequence(lambda n: f"Test Shuttle {n}")
    status = Shuttle.Status.OPEN

    class Meta:
        model = Shuttle
