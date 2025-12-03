import pytest
from django.db import IntegrityError

from wafer_space.core.enums import SlotSize
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.shuttles.tests.factories import ShuttleFactory


@pytest.mark.django_db
class TestGridPositioning:
    """Test ShuttleSlot grid positioning functionality."""

    def test_grid_position_single_letter(self):
        """Grid position should return spreadsheet-style notation (A1, B2, etc.)."""
        shuttle = ShuttleFactory(name="G820")
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        assert slot.grid_position == "A1"

    def test_grid_position_various_coordinates(self):
        """Test various row/column combinations."""
        shuttle = ShuttleFactory(name="G821")

        test_cases = [
            (0, 0, "A1"),  # First cell
            (0, 1, "B1"),  # Second column
            (1, 0, "A2"),  # Second row
            (2, 3, "D3"),  # Mid-grid
            (0, 25, "Z1"),  # Last single letter
        ]

        for row, col, expected in test_cases:
            slot = ShuttleSlot.objects.create(
                shuttle=shuttle,
                row=row,
                column=col,
                slot_size=SlotSize.FULL,
                status=ShuttleSlot.Status.AVAILABLE,
            )
            assert slot.grid_position == expected, f"Failed for row={row}, col={col}"

    def test_unique_together_constraint(self):
        """Each (shuttle, row, column) combination must be unique."""
        shuttle = ShuttleFactory(name="G822")
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )

        # Creating duplicate should raise IntegrityError
        with pytest.raises(IntegrityError):
            ShuttleSlot.objects.create(
                shuttle=shuttle,
                row=0,
                column=0,
                slot_size=SlotSize.QUARTER,
                status=ShuttleSlot.Status.AVAILABLE,
            )

    def test_slots_ordered_by_position(self):
        """Slots should be ordered by shuttle, row, then column."""
        shuttle = ShuttleFactory(name="G823")

        # Create slots in random order
        slot_b2 = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=1,
            column=1,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        slot_a1 = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        slot_a2 = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=1,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )

        # Query should return in order
        slots = list(ShuttleSlot.objects.all())
        assert slots == [slot_a1, slot_a2, slot_b2]

    def test_grid_position_multi_letter_columns(self):
        """Test multi-letter column positions for columns >= 26 (AA, AB, etc.)."""
        shuttle = ShuttleFactory(name="G824")

        test_cases = [
            (0, 26, "AA1"),  # First multi-letter (column 26 = AA)
            (0, 27, "AB1"),  # Second multi-letter (column 27 = AB)
            (1, 51, "AZ2"),  # End of AA-AZ range (column 51 = AZ)
            (2, 52, "BA3"),  # Start of BA range (column 52 = BA)
        ]

        for row, col, expected in test_cases:
            slot = ShuttleSlot.objects.create(
                shuttle=shuttle,
                row=row,
                column=col,
                slot_size=SlotSize.FULL,
                status=ShuttleSlot.Status.AVAILABLE,
            )
            assert slot.grid_position == expected, f"Failed for row={row}, col={col}"
