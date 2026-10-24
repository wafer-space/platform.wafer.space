"""G803 (GF180MCU Run #3) grid matches the published allocation.

The allocation lives in wafer-space/ws-run3-allocation,
layouts/90deg-r1-c1-upgrades.md: 49 slots, drawn turned 90°. The platform
grid is its transpose (see the comments in shuttles/G803-layout.yaml), so a
map coordinate becomes a platform coordinate by swapping letter and number.
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
    def test_is_seven_by_seven(self):
        config = GridConfig.from_file(LAYOUT)

        assert (config.num_rows, config.num_columns) == (7, 7)

    def test_slot_mix_matches_allocation_capacity(self):
        config = GridConfig.from_file(LAYOUT)

        sizes = Counter(
            GridConfig.calculate_slot_size(height, width)
            for height in config.row_heights
            for width in config.column_widths
        )
        assert sizes == ALLOCATION_CAPACITY


@pytest.mark.django_db
class TestG803Grid:
    def test_generates_allocation_slot_mix(self):
        shuttle = _create_g803()

        call_command("generate_shuttle_grid", "G803")

        sizes = Counter(shuttle.slots.values_list("slot_size", flat=True))
        assert sizes == ALLOCATION_CAPACITY

    @pytest.mark.parametrize(
        ("map_position", "platform_position", "size"),
        [
            # Map D2 is a ½×1 (half width, full height) slot.
            ("D2", "B4", SlotSize.HALF_WIDTH),
            # Map G7 is a 1×½ slot; the diagonal maps onto itself.
            ("G7", "G7", SlotSize.HALF_HEIGHT),
            # Map A1 is a ½×1 slot (unallocated in the published layout).
            ("A1", "A1", SlotSize.HALF_WIDTH),
            # Map C3 is a 1×1 slot.
            ("C3", "C3", SlotSize.FULL),
            # Map E1 is a ½×½ slot.
            ("E1", "A5", SlotSize.QUARTER),
        ],
    )
    def test_map_position_transposes_to_platform_position(
        self, map_position, platform_position, size
    ):
        shuttle = _create_g803()
        call_command("generate_shuttle_grid", "G803")

        slot = next(
            s
            for s in ShuttleSlot.objects.filter(shuttle=shuttle)
            if s.grid_position == platform_position
        )

        assert (slot.grid_position, slot.slot_size) == (platform_position, size), (
            f"map {map_position}"
        )
