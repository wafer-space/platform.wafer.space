import pytest

from wafer_space.core.enums import SlotSize
from wafer_space.shuttles.config import GridConfig
from wafer_space.shuttles.config import GridConfigError


class TestGridConfig:
    """Test YAML grid configuration parsing."""

    def test_parse_valid_config(self, tmp_path):
        """Should parse valid YAML configuration."""
        config_file = tmp_path / "test-layout.yaml"
        config_file.write_text("""
shuttle: TEST01
row_heights: [1.0, 0.5, 1.0]
column_widths: [1.0, 0.5, 1.0, 0.5]
""")

        config = GridConfig.from_file(config_file)

        expected_rows = 3
        expected_columns = 4

        assert config.shuttle_name == "TEST01"
        assert config.row_heights == [1.0, 0.5, 1.0]
        assert config.column_widths == [1.0, 0.5, 1.0, 0.5]
        assert config.num_rows == expected_rows
        assert config.num_columns == expected_columns

    def test_reject_invalid_dimensions(self, tmp_path):
        """Should reject dimensions other than 0.5 or 1.0."""
        config_file = tmp_path / "bad-layout.yaml"
        config_file.write_text("""
shuttle: TEST02
row_heights: [1.0, 0.75, 1.0]
column_widths: [1.0]
""")

        with pytest.raises(GridConfigError, match=r"must be 0\.5 or 1\.0"):
            GridConfig.from_file(config_file)

    def test_reject_missing_fields(self, tmp_path):
        """Should reject config missing required fields."""
        config_file = tmp_path / "incomplete.yaml"
        config_file.write_text("""
shuttle: TEST03
row_heights: [1.0]
""")

        with pytest.raises(GridConfigError, match="Missing required field"):
            GridConfig.from_file(config_file)

    @pytest.mark.parametrize(
        ("row_h", "col_w", "expected"),
        [
            # SlotSize format is <width>x<height>
            # column_width -> slot width, row_height -> slot height
            (1.0, 1.0, SlotSize.FULL),  # width=1, height=1 -> "1x1"
            (0.5, 0.5, SlotSize.QUARTER),  # width=0.5, height=0.5 -> "0p5x0p5"
            # row_height=1.0, column_width=0.5 -> width=0.5, height=1.0 -> HALF_WIDTH
            (1.0, 0.5, SlotSize.HALF_WIDTH),  # "0p5x1" (width=0.5, height=1)
            # row_height=0.5, column_width=1.0 -> width=1.0, height=0.5 -> HALF_HEIGHT
            (0.5, 1.0, SlotSize.HALF_HEIGHT),  # "1x0p5" (width=1, height=0.5)
        ],
    )
    def test_calculate_slot_size(self, row_h, col_w, expected):
        """Should calculate correct SlotSize from dimensions.

        SlotSize values use format <width>x<height>:
        - HALF_WIDTH = "0p5x1" means width=0.5, height=1.0
        - HALF_HEIGHT = "1x0p5" means width=1.0, height=0.5

        The function parameters map directly:
        - column_width -> slot width
        - row_height -> slot height
        """
        result = GridConfig.calculate_slot_size(row_h, col_w)
        assert result == expected
