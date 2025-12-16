"""Tests for reticle package generation service."""

from __future__ import annotations

from wafer_space.shuttles.services.reticle_package import ProjectData


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
