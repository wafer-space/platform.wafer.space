"""Tests for reticle package generation service."""

from __future__ import annotations

import csv
import io
import json
import tempfile
from pathlib import Path

import pytest

from wafer_space.shuttles.services.reticle_package import SLOT_SIZE_TO_TILES
from wafer_space.shuttles.services.reticle_package import PackageMetadata
from wafer_space.shuttles.services.reticle_package import ProjectData
from wafer_space.shuttles.services.reticle_package import ReticlePackageError
from wafer_space.shuttles.services.reticle_package import ReticlePackageService
from wafer_space.shuttles.services.reticle_package import SlotData
from wafer_space.shuttles.services.reticle_package import build_tilemap_grid
from wafer_space.shuttles.services.reticle_package import create_gds_link
from wafer_space.shuttles.services.reticle_package import generate_project_info_json
from wafer_space.shuttles.services.reticle_package import generate_readme
from wafer_space.shuttles.services.reticle_package import write_checks_csv
from wafer_space.shuttles.services.reticle_package import write_manifest_csv
from wafer_space.shuttles.services.reticle_package import write_summary_csv
from wafer_space.shuttles.services.reticle_package import write_tilemap_csv


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


class TestCSVWriters:
    """Tests for CSV generation functions."""

    def test_write_tilemap_csv(self):
        """Write tilemap grid to CSV format."""
        grid = [
            ["MOLE", "MOLE", "KIAN"],
            ["MOLE", "MOLE", "KIAN"],
            ["", "", "CAFE"],
        ]
        output = io.StringIO()
        write_tilemap_csv(grid, output)

        output.seek(0)
        content = output.read()
        lines = [line.rstrip() for line in content.strip().split("\n")]

        expected_line_count = 3
        assert len(lines) == expected_line_count
        assert lines[0] == "MOLE,MOLE,KIAN"
        assert lines[2] == ",,CAFE"

    def test_write_manifest_csv(self):
        """Write manifest CSV with headers."""
        projects = [
            ProjectData(
                code="CAFE",
                project_name="Cafe Chip",
                project_uuid="uuid1",
                project_url="url1",
                slot_size="1x1",
                slot_positions=["C1"],
                top_cell="CAFE_TOP",
                gds_path="/path/cafe.gds",
                gds_sha256="hash1",
                is_submitted=True,
                check_status="manufacturable",
                check_warnings=0,
                check_errors=0,
            ),
            ProjectData(
                code="MOLE",
                project_name="Mole Detector",
                project_uuid="uuid2",
                project_url="url2",
                slot_size="0p5x1",
                slot_positions=["A1", "A2"],
                top_cell="MOLE_TOP",
                gds_path="/path/mole.gds",
                gds_sha256="hash2",
                is_submitted=True,
                check_status="manufacturable_with_warnings",
                check_warnings=3,
                check_errors=0,
            ),
        ]
        output = io.StringIO()
        write_manifest_csv(projects, output)

        output.seek(0)
        reader = csv.DictReader(output)
        rows = list(reader)

        # Should be sorted by CODE, MOLE has 2 slots so 2 rows
        expected_row_count = 3  # CAFE x1 + MOLE x2
        assert len(rows) == expected_row_count
        assert rows[0]["CODE"] == "CAFE"
        assert rows[1]["CODE"] == "MOLE"
        assert rows[1]["SLOT"] == "0p5x1"
        assert rows[1]["LAYOUT"] == "MOLE/MOLE_TOP.gds"

    def test_write_summary_csv(self):
        """Write summary CSV with project overview."""
        projects = [
            ProjectData(
                code="MOLE",
                project_name="Mole Detector",
                project_uuid="uuid1",
                project_url="https://example.com/p/1/",
                slot_size="1x1",
                slot_positions=["A1"],
                top_cell="MOLE_TOP",
                gds_path="/path/mole.gds",
                gds_sha256="hash1",
                is_submitted=True,
                check_status="manufacturable",
                check_warnings=0,
                check_errors=0,
                submitted_at="2025-12-15T10:00:00Z",
                repository_url="https://github.com/example/mole",
            ),
        ]
        output = io.StringIO()
        write_summary_csv(projects, output)

        output.seek(0)
        reader = csv.DictReader(output)
        rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["CODE"] == "MOLE"
        assert rows[0]["PROJECT_NAME"] == "Mole Detector"
        assert rows[0]["PROJECT_URL"] == "https://example.com/p/1/"

    def test_write_checks_csv(self):
        """Write checks CSV with manufacturability details."""
        projects = [
            ProjectData(
                code="MOLE",
                project_name="Mole Detector",
                project_uuid="uuid1",
                project_url="url1",
                slot_size="1x1",
                slot_positions=["A1"],
                top_cell="MOLE_TOP",
                gds_path="/path/mole.gds",
                gds_sha256="hash1",
                is_submitted=True,
                check_status="manufacturable_with_warnings",
                check_warnings=5,
                check_errors=0,
                check_version="v2.1.0",
                check_runtime_seconds=120.5,
            ),
        ]
        output = io.StringIO()
        write_checks_csv(projects, output)

        output.seek(0)
        reader = csv.DictReader(output)
        rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["CHECK_STATUS"] == "manufacturable_with_warnings"
        assert rows[0]["CHECK_WARNINGS"] == "5"


class TestReadmeGenerator:
    """Tests for README.md generation."""

    def test_generate_readme_header(self):
        """README includes header with metadata."""
        metadata = PackageMetadata(
            shuttle_name="G801",
            generated_at="2025-12-16 14:32:05 UTC",
            hostname="platform.wafer.space",
            git_revision="v1.2.3-45-gabcdef1",
            precheck_version="gf180mcu-precheck v2.1.0",
        )
        readme = generate_readme(
            metadata=metadata,
            projects=[],
            slots=[],
        )

        assert "# G801 Reticle Package" in readme
        assert "2025-12-16 14:32:05 UTC" in readme
        assert "platform.wafer.space" in readme
        assert "v1.2.3-45-gabcdef1" in readme

    def test_generate_readme_with_projects(self):
        """README includes project table."""
        metadata = PackageMetadata(
            shuttle_name="G801",
            generated_at="2025-12-16",
            hostname="test",
            git_revision="test",
            precheck_version="v1.0",
        )
        projects = [
            ProjectData(
                code="MOLE",
                project_name="Mole Detector",
                project_uuid="uuid1",
                project_url="url1",
                slot_size="1x1",
                slot_positions=["A1"],
                top_cell="MOLE_TOP",
                gds_path="/path/mole.gds",
                gds_sha256="hash1",
                is_submitted=True,
                check_status="manufacturable",
                check_warnings=0,
                check_errors=0,
            ),
        ]
        readme = generate_readme(
            metadata=metadata,
            projects=projects,
            slots=[],
        )

        assert "| MOLE |" in readme
        assert "Mole Detector" in readme


class TestInfoJsonGenerator:
    """Tests for info.json generation."""

    def test_generate_project_info_json(self):
        """Generate info.json for a project."""
        expected_warnings = 2
        project = ProjectData(
            code="MOLE",
            project_name="Mole Detector",
            project_uuid="12345678-1234-1234-1234-123456789abc",
            project_url="https://example.com/projects/123/",
            slot_size="1x1",
            slot_positions=["A1", "A2", "B1", "B2"],
            top_cell="MOLE_TOP",
            gds_path="/path/to/output.gds",
            gds_sha256="abc123def456",
            is_submitted=True,
            check_status="manufacturable",
            check_warnings=expected_warnings,
            check_errors=0,
            check_version="v2.1.0",
            check_runtime_seconds=127.5,
        )

        info_json = generate_project_info_json(project)
        data = json.loads(info_json)

        assert data["code"] == "MOLE"
        assert data["project"]["name"] == "Mole Detector"
        assert data["project"]["uuid"] == "12345678-1234-1234-1234-123456789abc"
        assert data["manufacturability_check"]["warnings_count"] == expected_warnings
        assert data["slot_positions"] == ["A1", "A2", "B1", "B2"]


class TestGdsLinkCreation:
    """Tests for GDS file linking."""

    def test_create_hardlink(self):
        """Create hardlink to GDS file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create source file
            source = tmppath / "source.gds"
            source.write_text("GDS content")

            # Create destination
            dest = tmppath / "output" / "MOLE" / "TOP.gds"

            warnings = create_gds_link(source, dest)

            assert dest.exists()
            assert dest.read_text() == "GDS content"
            assert len(warnings) == 0
            # Verify it's a hardlink (same inode)
            assert source.stat().st_ino == dest.stat().st_ino

    def test_fallback_to_copy_cross_filesystem(self):
        """Fall back to copy when hardlink fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            source = tmppath / "source.gds"
            source.write_text("GDS content")

            dest = tmppath / "output" / "MOLE" / "TOP.gds"

            # Force copy mode
            warnings = create_gds_link(source, dest, force_copy=True)

            assert dest.exists()
            assert dest.read_text() == "GDS content"
            assert len(warnings) == 1
            assert "copied" in warnings[0].lower()


class TestReticlePackageService:
    """Tests for ReticlePackageService."""

    def test_service_initialization(self, tmp_path):
        """Service can be initialized with shuttle name."""
        service = ReticlePackageService(
            shuttle_name="G801",
            output_path=tmp_path / "test",
            allow_pending=False,
        )
        assert service.shuttle_name == "G801"
        assert service.allow_pending is False


@pytest.mark.django_db
class TestReticlePackageServiceIntegration:
    """Integration tests for ReticlePackageService."""

    def test_generate_fails_if_output_exists(self, tmp_path):
        """Service fails if output directory already exists."""
        output = tmp_path / "G801"
        output.mkdir()

        service = ReticlePackageService(
            shuttle_name="G801",
            output_path=output,
        )

        with pytest.raises(ReticlePackageError, match="already exists"):
            service.generate()

    def test_generate_fails_if_shuttle_not_found(self, tmp_path):
        """Service fails if shuttle doesn't exist."""
        service = ReticlePackageService(
            shuttle_name="XXXX",
            output_path=tmp_path / "output",
        )

        with pytest.raises(ReticlePackageError, match="not found"):
            service.generate()
