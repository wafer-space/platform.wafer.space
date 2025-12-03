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
            (1.0, 1.0, SlotSize.FULL),
            (0.5, 0.5, SlotSize.QUARTER),
            (1.0, 0.5, SlotSize.HALF_HEIGHT),
            (0.5, 1.0, SlotSize.HALF_WIDTH),
        ],
    )
    def test_calculate_slot_size(self, row_h, col_w, expected):
        """Should calculate correct SlotSize from dimensions."""
        result = GridConfig.calculate_slot_size(row_h, col_w)
        assert result == expected
