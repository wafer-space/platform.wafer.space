"""Tests for reticle package generation service."""

from __future__ import annotations

import csv
import io
import json
import tempfile
from pathlib import Path

import pytest
import yaml

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.projects.tests.factories import ProjectFileFactory
from wafer_space.shuttles.models import ShuttleSlot
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
from wafer_space.shuttles.tests.factories import ShuttleFactory


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

    def test_full_package_generation(self, tmp_path):  # noqa: PLR0915
        """Generate complete package with all files using factory-created data.

        This is a comprehensive integration test that validates the entire package
        generation workflow. Test complexity is intentional and necessary.
        """
        # Create a temporary grid config file
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        grid_config_path = config_dir / "TEST-layout.yaml"

        grid_config = {
            "shuttle": "G899",
            "row_heights": [1.0, 1.0],  # 2 rows, both full height
            "column_widths": [1.0, 1.0],  # 2 columns, both full width
        }
        with grid_config_path.open("w") as f:
            yaml.dump(grid_config, f)

        # Create shuttle with grid config
        shuttle = ShuttleFactory(
            name="G899",
            grid_config_file=str(grid_config_path),
        )

        # Create first project with completed check
        gds_dir = tmp_path / "gds"
        gds_dir.mkdir()

        project1 = ProjectFactory(
            name="Test Project One",
            project_id="TST1",
            slot_size="1x1",
        )
        project_file1 = ProjectFileFactory(project=project1, top_cell="TOP_CELL_1")
        output_gds1 = gds_dir / "output1.gds"
        output_gds1.write_text("FAKE GDS CONTENT 1")

        ManufacturabilityCheckFactory(
            project=project1,
            project_file=project_file1,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
            warnings=[],
            errors=[],
            output_gds=str(output_gds1),
            output_gds_sha256="abc123hash1",
        )
        project1.submitted_file = project_file1
        project1.save()

        # Create second project with warnings
        project2 = ProjectFactory(
            name="Test Project Two",
            project_id="TST2",
            slot_size="1x1",
        )
        project_file2 = ProjectFileFactory(project=project2, top_cell="TOP_CELL_2")
        output_gds2 = gds_dir / "output2.gds"
        output_gds2.write_text("FAKE GDS CONTENT 2")

        # Has warnings = MANUFACTURABLE_WITH_WARNINGS
        ManufacturabilityCheckFactory(
            project=project2,
            project_file=project_file2,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
            warnings=["Warning 1", "Warning 2"],
            errors=[],
            output_gds=str(output_gds2),
            output_gds_sha256="def456hash2",
        )
        project2.submitted_file = project_file2
        project2.save()

        # Create shuttle slots (2x2 grid: 2 with projects, 2 empty)
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            project=project1,
            row=0,
            column=0,
            slot_size="1x1",
            status=ShuttleSlot.Status.RESERVED,
        )
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            project=project2,
            row=0,
            column=1,
            slot_size="1x1",
            status=ShuttleSlot.Status.RESERVED,
        )
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            project=None,
            row=1,
            column=0,
            slot_size="1x1",
            status=ShuttleSlot.Status.AVAILABLE,
        )
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            project=None,
            row=1,
            column=1,
            slot_size="1x1",
            status=ShuttleSlot.Status.AVAILABLE,
        )

        # Generate the package
        output = tmp_path / "G899_OUTPUT"
        service = ReticlePackageService(
            shuttle_name="G899",
            output_path=output,
            allow_pending=False,
        )

        result = service.generate()

        # Verify result counts (2 projects created above)
        expected_projects = 2
        assert result["projects_included"] == expected_projects
        assert result["projects_skipped"] == 0

        # Verify all expected files exist
        assert (output / "README.md").exists()
        assert (output / "tilemap.csv").exists()
        assert (output / "manifest.csv").exists()
        assert (output / "summary.csv").exists()
        assert (output / "checks.csv").exists()

        # Verify project directories and files
        assert (output / "TST1").exists()
        assert (output / "TST1" / "info.json").exists()
        assert (output / "TST1" / "TOP_CELL_1.gds").exists()

        assert (output / "TST2").exists()
        assert (output / "TST2" / "info.json").exists()
        assert (output / "TST2" / "TOP_CELL_2.gds").exists()

        # Verify GDS files have correct content
        assert (output / "TST1" / "TOP_CELL_1.gds").read_text() == "FAKE GDS CONTENT 1"
        assert (output / "TST2" / "TOP_CELL_2.gds").read_text() == "FAKE GDS CONTENT 2"

        # Verify tilemap.csv has correct grid (2x2 slots = 4x4 tiles)
        tilemap_content = (output / "tilemap.csv").read_text()
        lines = tilemap_content.strip().split("\n")
        expected_tile_rows = 4  # 2 slot rows * 2 tiles per row
        assert len(lines) == expected_tile_rows

        # First row should have TST1 and TST2
        assert "TST1" in lines[0]
        assert "TST2" in lines[0]

        # Verify manifest.csv
        manifest_content = (output / "manifest.csv").read_text()
        assert "TST1" in manifest_content
        assert "TST2" in manifest_content
        assert "TOP_CELL_1" in manifest_content
        assert "TOP_CELL_2" in manifest_content

        # Verify README.md
        readme_content = (output / "README.md").read_text()
        assert "# G899 Reticle Package" in readme_content
        assert "Test Project One" in readme_content
        assert "Test Project Two" in readme_content

    def test_allow_pending_uses_fallback_query(self, tmp_path):
        """Test allow_pending falls back to latest file with passing check.

        This tests the fallback code path where project.submitted_file is None
        but a ProjectFile exists with a passing ManufacturabilityCheck. The
        service should find this file via the fallback query using uploaded_at
        ordering.

        Regression test: This would have caught the 'created_at' vs 'uploaded_at'
        bug since ProjectFile uses 'uploaded_at', not 'created_at'.
        """
        # Create grid config
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        grid_config_path = config_dir / "fallback-layout.yaml"

        grid_config = {
            "shuttle": "G898",
            "row_heights": [1.0],
            "column_widths": [1.0],
        }
        with grid_config_path.open("w") as f:
            yaml.dump(grid_config, f)

        shuttle = ShuttleFactory(
            name="G898",
            grid_config_file=str(grid_config_path),
        )

        # Create project WITHOUT setting submitted_file
        project = ProjectFactory(
            name="Fallback Test Project",
            project_id="FALL",
            slot_size="1x1",
        )

        # Create GDS file
        gds_dir = tmp_path / "gds"
        gds_dir.mkdir()
        output_gds = gds_dir / "fallback_output.gds"
        output_gds.write_text("FAKE GDS FOR FALLBACK TEST")

        # Create ProjectFile with passing check - but DON'T set submitted_file
        project_file = ProjectFileFactory(project=project, top_cell="FALLBACK_TOP")
        ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
            warnings=[],
            errors=[],
            output_gds=str(output_gds),
            output_gds_sha256="fallbackhash123",
        )

        # NOTE: We intentionally do NOT set project.submitted_file here!
        # This forces the service to use the fallback query.
        assert project.submitted_file is None

        # Create shuttle slot
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            project=project,
            row=0,
            column=0,
            slot_size="1x1",
            status=ShuttleSlot.Status.RESERVED,
        )

        # Generate with allow_pending=True to use fallback query
        output = tmp_path / "G898_OUTPUT"
        service = ReticlePackageService(
            shuttle_name="G898",
            output_path=output,
            allow_pending=True,  # Required for fallback query
        )

        result = service.generate()

        # Verify the project was included via fallback query
        assert result["projects_included"] == 1
        assert result["projects_skipped"] == 0

        # Verify files were created
        assert (output / "FALL").exists()
        assert (output / "FALL" / "info.json").exists()
        assert (output / "FALL" / "FALLBACK_TOP.gds").exists()
        assert (output / "FALL" / "FALLBACK_TOP.gds").read_text() == (
            "FAKE GDS FOR FALLBACK TEST"
        )

        # Verify manifest includes the project
        manifest_content = (output / "manifest.csv").read_text()
        assert "FALL" in manifest_content
        assert "FALLBACK_TOP" in manifest_content

    def test_fallback_query_skips_not_manufacturable(self, tmp_path):
        """Test fallback skips projects with NOT_MANUFACTURABLE status.

        Projects that fail manufacturability checks (is_manufacturable=False)
        are skipped since they typically have no output_gds and cannot be
        included in the reticle package.
        """
        # Create grid config
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        grid_config_path = config_dir / "failing-layout.yaml"

        grid_config = {
            "shuttle": "G897",
            "row_heights": [1.0],
            "column_widths": [1.0],
        }
        with grid_config_path.open("w") as f:
            yaml.dump(grid_config, f)

        shuttle = ShuttleFactory(
            name="G897",
            grid_config_file=str(grid_config_path),
        )

        # Create project without submitted_file
        project = ProjectFactory(
            name="Failing Check Project",
            project_id="FAIL",
            slot_size="1x1",
        )

        # Create GDS file (even though it won't be used)
        gds_dir = tmp_path / "gds"
        gds_dir.mkdir()
        output_gds = gds_dir / "failing_output.gds"
        output_gds.write_text("FAKE GDS FOR FAILING CHECK")

        # Create ProjectFile with FAILING check (is_manufacturable=False)
        project_file = ProjectFileFactory(project=project, top_cell="FAILING_TOP")
        ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=False,  # FAILING check
            warnings=["Critical warning"],
            errors=["Fatal error"],
            output_gds=str(output_gds),
            output_gds_sha256="failinghash123",
        )

        assert project.submitted_file is None

        # Create shuttle slot
        ShuttleSlot.objects.create(
            shuttle=shuttle,
            project=project,
            row=0,
            column=0,
            slot_size="1x1",
            status=ShuttleSlot.Status.RESERVED,
        )

        # Generate with allow_pending=True
        output = tmp_path / "G897_OUTPUT"
        service = ReticlePackageService(
            shuttle_name="G897",
            output_path=output,
            allow_pending=True,
        )

        result = service.generate()

        # Project should be SKIPPED due to not manufacturable
        assert result["projects_included"] == 0
        assert result["projects_skipped"] == 1

        # Verify project directory was NOT created
        assert not (output / "FAIL").exists()

    def test_not_manufacturable_raises_without_allow_pending(self, tmp_path):
        """Test NOT_MANUFACTURABLE raises error when allow_pending=False."""
        # Create grid config
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        grid_config_path = config_dir / "error-layout.yaml"

        grid_config = {
            "shuttle": "G895",
            "row_heights": [1.0],
            "column_widths": [1.0],
        }
        with grid_config_path.open("w") as f:
            yaml.dump(grid_config, f)

        shuttle = ShuttleFactory(
            name="G895",
            grid_config_file=str(grid_config_path),
        )

        project = ProjectFactory(
            name="Not Manufacturable Project",
            project_id="NMAN",
            slot_size="1x1",
        )

        gds_dir = tmp_path / "gds"
        gds_dir.mkdir()
        output_gds = gds_dir / "nman_output.gds"
        output_gds.write_text("FAKE GDS")

        project_file = ProjectFileFactory(project=project, top_cell="NMAN_TOP")
        ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=False,
            output_gds=str(output_gds),
            output_gds_sha256="nmanhash",
        )
        project.submitted_file = project_file
        project.save()

        ShuttleSlot.objects.create(
            shuttle=shuttle,
            project=project,
            row=0,
            column=0,
            slot_size="1x1",
            status=ShuttleSlot.Status.RESERVED,
        )

        output = tmp_path / "G895_OUTPUT"
        service = ReticlePackageService(
            shuttle_name="G895",
            output_path=output,
            allow_pending=False,  # Should raise error
        )

        with pytest.raises(ReticlePackageError, match="not manufacturable"):
            service.generate()
