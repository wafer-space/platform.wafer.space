"""Tests for reticle package generation service."""

from __future__ import annotations

from wafer_space.shuttles.services.reticle_package import SLOT_SIZE_TO_TILES
from wafer_space.shuttles.services.reticle_package import ProjectData
from wafer_space.shuttles.services.reticle_package import SlotData
from wafer_space.shuttles.services.reticle_package import build_tilemap_grid


class TestProjectData:
    """Tests for ProjectData dataclass."""

    def test_project_data_creation(self):
        """ProjectData can be created with required fields."""
        data = ProjectData(
            code="MOLE",
            project_name="Mole Detector",
            project_uuid="12345678-1234-1234-1234-123456789abc",
            project_url="https://example.com/projects/123/",
            slot_size="1x1",
            slot_positions=["A1", "A2", "B1", "B2"],
            top_cell="MOLE_TOP",
            gds_path="/path/to/output.gds",
            gds_sha256="abc123",
            is_submitted=True,
            check_status="manufacturable",
            check_warnings=2,
            check_errors=0,
        )
        assert data.code == "MOLE"
        assert data.layout_path == "MOLE/MOLE_TOP.gds"


class TestSlotData:
    """Tests for SlotData dataclass."""

    def test_slot_data_empty(self):
        """SlotData for empty slot."""
        slot = SlotData(
            row=0,
            column=0,
            slot_size="1x1",
            project_code=None,
        )
        expected_width, expected_height = SLOT_SIZE_TO_TILES["1x1"]
        assert slot.is_empty
        assert slot.tile_width == expected_width
        assert slot.tile_height == expected_height

    def test_slot_data_with_project(self):
        """SlotData with assigned project."""
        slot = SlotData(
            row=1,
            column=2,
            slot_size="0p5x1",
            project_code="MOLE",
        )
        expected_width, expected_height = SLOT_SIZE_TO_TILES["0p5x1"]
        assert not slot.is_empty
        assert slot.tile_width == expected_width
        assert slot.tile_height == expected_height

    def test_slot_size_to_tiles(self):
        """Test all slot size to tile mappings."""
        assert SlotData(0, 0, "1x1", None).tile_dimensions == SLOT_SIZE_TO_TILES["1x1"]
        assert (
            SlotData(0, 0, "0p5x1", None).tile_dimensions == SLOT_SIZE_TO_TILES["0p5x1"]
        )
        assert (
            SlotData(0, 0, "1x0p5", None).tile_dimensions == SLOT_SIZE_TO_TILES["1x0p5"]
        )
        assert (
            SlotData(0, 0, "0p5x0p5", None).tile_dimensions
            == SLOT_SIZE_TO_TILES["0p5x0p5"]
        )


class TestBuildTilemapGrid:
    """Tests for tilemap grid building."""

    def test_simple_grid(self):
        """Build tilemap from simple 2x2 slot grid."""
        slots = [
            SlotData(row=0, column=0, slot_size="1x1", project_code="MOLE"),
            SlotData(row=0, column=1, slot_size="1x1", project_code="KIAN"),
            SlotData(row=1, column=0, slot_size="1x1", project_code=None),
            SlotData(row=1, column=1, slot_size="1x1", project_code="CAFE"),
        ]
        grid = build_tilemap_grid(slots, num_rows=2, num_columns=2)

        # Each 1x1 slot becomes 2x2 tiles, so 2x2 slots = 4x4 tiles
        expected_tile_rows = 2 * SLOT_SIZE_TO_TILES["1x1"][1]  # 2 rows * 2 tiles/row
        expected_tile_cols = 2 * SLOT_SIZE_TO_TILES["1x1"][0]  # 2 cols * 2 tiles/col
        assert len(grid) == expected_tile_rows
        assert len(grid[0]) == expected_tile_cols

        # MOLE in top-left 2x2
        assert grid[0][0] == "MOLE"
        assert grid[0][1] == "MOLE"
        assert grid[1][0] == "MOLE"
        assert grid[1][1] == "MOLE"

        # KIAN in top-right 2x2
        assert grid[0][2] == "KIAN"
        assert grid[0][3] == "KIAN"

        # Empty slot in bottom-left
        assert grid[2][0] == ""
        assert grid[2][1] == ""

        # CAFE in bottom-right
        assert grid[2][2] == "CAFE"

    def test_mixed_slot_sizes(self):
        """Build tilemap with different slot sizes."""
        slots = [
            SlotData(row=0, column=0, slot_size="0p5x0p5", project_code="A001"),
            SlotData(row=0, column=1, slot_size="0p5x0p5", project_code="B002"),
        ]
        grid = build_tilemap_grid(slots, num_rows=1, num_columns=2)

        # 0.5x0.5 slots = 1x1 tiles each
        expected_tile_rows = 1 * SLOT_SIZE_TO_TILES["0p5x0p5"][1]  # 1 row * 1 tile/row
        expected_tile_cols = 2 * SLOT_SIZE_TO_TILES["0p5x0p5"][0]  # 2 cols * 1 tile/col
        assert len(grid) == expected_tile_rows
        assert len(grid[0]) == expected_tile_cols
        assert grid[0][0] == "A001"
        assert grid[0][1] == "B002"
