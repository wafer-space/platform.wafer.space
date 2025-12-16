"""Tests for reticle package generation service."""

from __future__ import annotations

from wafer_space.shuttles.services.reticle_package import SLOT_SIZE_TO_TILES
from wafer_space.shuttles.services.reticle_package import ProjectData
from wafer_space.shuttles.services.reticle_package import SlotData


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
