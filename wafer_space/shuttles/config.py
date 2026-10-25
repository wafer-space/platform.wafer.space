"""Grid configuration parsing from YAML files."""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml

from wafer_space.core.enums import SlotSize

if TYPE_CHECKING:
    from pathlib import Path

# Valid cell dimension constants
HALF_SIZE = 0.5
FULL_SIZE = 1.0


class GridConfigError(Exception):
    """Error in grid configuration file."""


class GridConfig:
    """Parsed grid configuration from YAML."""

    def __init__(
        self,
        shuttle_name: str,
        row_heights: list[float],
        column_widths: list[float],
        *,
        rotated: bool = False,
    ) -> None:
        """Initialize grid configuration.

        Args:
            shuttle_name: Name of shuttle this config is for
            row_heights: List of row heights (each 0.5 or 1.0)
            column_widths: List of column widths (each 0.5 or 1.0)
            rotated: The slots are turned 90° on the reticle, so the rows
                and columns are the reticle map's and a cell's row height is
                the slot's width (its column width the slot's height)
        """
        self.shuttle_name = shuttle_name
        self.row_heights = row_heights
        self.column_widths = column_widths
        self.rotated = rotated

        # Validate dimensions
        for height in row_heights:
            if height not in (HALF_SIZE, FULL_SIZE):
                msg = f"Row height {height} must be {HALF_SIZE} or {FULL_SIZE}"
                raise GridConfigError(msg)

        for width in column_widths:
            if width not in (HALF_SIZE, FULL_SIZE):
                msg = f"Column width {width} must be {HALF_SIZE} or {FULL_SIZE}"
                raise GridConfigError(msg)

    @property
    def num_rows(self) -> int:
        """Get number of rows in grid."""
        return len(self.row_heights)

    @property
    def num_columns(self) -> int:
        """Get number of columns in grid."""
        return len(self.column_widths)

    @classmethod
    def from_file(cls, config_path: Path) -> GridConfig:
        """Load configuration from YAML file.

        Args:
            config_path: Path to YAML configuration file

        Returns:
            GridConfig instance

        Raises:
            GridConfigError: If configuration is invalid
        """
        try:
            with config_path.open() as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError) as exc:
            msg = f"Failed to read config file: {exc}"
            raise GridConfigError(msg) from exc

        if not isinstance(data, dict):
            msg = "Config file must contain a YAML dictionary"
            raise GridConfigError(msg)

        # Validate required fields
        required_fields = {"shuttle", "row_heights", "column_widths"}
        missing = required_fields - set(data.keys())
        if missing:
            msg = f"Missing required fields: {', '.join(missing)}"
            raise GridConfigError(msg)

        rotated = data.get("rotated", False)
        if not isinstance(rotated, bool):
            msg = f"rotated must be true or false, not {rotated!r}"
            raise GridConfigError(msg)

        return cls(
            shuttle_name=data["shuttle"],
            row_heights=data["row_heights"],
            column_widths=data["column_widths"],
            rotated=rotated,
        )

    def slot_size_at(self, row: int, column: int) -> SlotSize:
        """Return the size of the slot in the given cell.

        A slot's size is width x height in design orientation (a 1x1 is
        3.88 mm wide and 5.07 mm tall). In a rotated grid the design's
        width runs down the reticle, so the cell's row height is the
        slot's width.
        """
        row_height = self.row_heights[row]
        column_width = self.column_widths[column]
        if self.rotated:
            return self.calculate_slot_size(column_width, row_height)
        return self.calculate_slot_size(row_height, column_width)

    @staticmethod
    def calculate_slot_size(row_height: float, column_width: float) -> SlotSize:
        """Calculate SlotSize enum value from dimensions.

        Args:
            row_height: Height of cell (0.5 or 1.0)
            column_width: Width of cell (0.5 or 1.0)

        Returns:
            SlotSize enum value
        """
        if row_height == FULL_SIZE and column_width == FULL_SIZE:
            return SlotSize.FULL
        if row_height == HALF_SIZE and column_width == HALF_SIZE:
            return SlotSize.QUARTER
        if row_height == FULL_SIZE and column_width == HALF_SIZE:
            # width=0.5, height=1.0 -> HALF_WIDTH ("0p5x1")
            return SlotSize.HALF_WIDTH
        if row_height == HALF_SIZE and column_width == FULL_SIZE:
            # width=1.0, height=0.5 -> HALF_HEIGHT ("1x0p5")
            return SlotSize.HALF_HEIGHT
        msg = f"Invalid dimensions: {row_height} x {column_width}"
        raise GridConfigError(msg)
