"""G803 (GF180MCU Run #3) grid matches the published allocation.

The allocation lives in wafer-space/ws-run3-allocation,
layouts/90deg-r1-c1-upgrades.md: 49 slots turned 90° on the reticle. The
platform grid uses the map's own rows and columns (``rotated: true`` in
shuttles/G803-layout.yaml), so a map coordinate is the platform coordinate.
"""

from collections import Counter
from pathlib import Path

import pytest
from django.core.management import call_command

from wafer_space.core.enums import SlotSize
from wafer_space.shuttles.config import GridConfig
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot

LAYOUT = Path("shuttles/G803-layout.yaml")

# Capacity column of the allocation's slot table.
ALLOCATION_CAPACITY = {
    SlotSize.FULL: 20,
    SlotSize.HALF_HEIGHT: 15,
    SlotSize.HALF_WIDTH: 8,
    SlotSize.QUARTER: 6,
}


def _create_g803() -> Shuttle:
    # Explicit name, never ShuttleFactory's G8XX sequence.
    return Shuttle.objects.create(
        name="G803", description="GF180MCU Shuttle Run 3", status=Shuttle.Status.OPEN
    )


class TestG803Layout:
    def test_is_seven_by_seven_and_rotated(self):
        config = GridConfig.from_file(LAYOUT)

        assert (config.num_rows, config.num_columns, config.rotated) == (7, 7, True)

    def test_slot_mix_matches_allocation_capacity(self):
        config = GridConfig.from_file(LAYOUT)

        sizes = Counter(
            config.slot_size_at(row, column)
            for row in range(config.num_rows)
            for column in range(config.num_columns)
        )
        assert sizes == ALLOCATION_CAPACITY


@pytest.mark.django_db
class TestG803Grid:
    def test_generates_allocation_slot_mix(self):
        shuttle = _create_g803()

        call_command("generate_shuttle_grid", "G803")

        sizes = Counter(shuttle.slots.values_list("slot_size", flat=True))
        assert sizes == ALLOCATION_CAPACITY

    def test_slot_sizes_match_the_allocation_map(self):
        # One slot of each size and both map corners, as the published
        # 90deg-r1-c1-upgrades-layout.csv lists them.
        allocation = {
            "A1": SlotSize.HALF_WIDTH,
            "D2": SlotSize.HALF_WIDTH,
            "A3": SlotSize.FULL,
            "D7": SlotSize.FULL,
            "E1": SlotSize.QUARTER,
            "G2": SlotSize.QUARTER,
            "E3": SlotSize.HALF_HEIGHT,
            "G7": SlotSize.HALF_HEIGHT,
        }
        shuttle = _create_g803()
        call_command("generate_shuttle_grid", "G803")

        by_position = {
            slot.grid_position: SlotSize(slot.slot_size)
            for slot in ShuttleSlot.objects.filter(shuttle=shuttle)
        }

        assert {pos: by_position[pos] for pos in allocation} == allocation
