"""Tests for reticle package generation service."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.projects.tests.factories import ProjectFileFactory
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.shuttles.services.reticle_package import ReticlePackageError
from wafer_space.shuttles.services.reticle_package import generate_package
from wafer_space.shuttles.tests.factories import ShuttleFactory

if TYPE_CHECKING:
    from pathlib import Path


def create_shuttle_with_config(tmp_path: Path, name: str) -> Shuttle:
    """Create a shuttle with a grid config file."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    grid_config_path = config_dir / f"{name}-layout.yaml"

    with grid_config_path.open("w") as f:
        yaml.dump(
            {
                "shuttle": name,
                "row_heights": [1.0],
                "column_widths": [1.0, 1.0],
            },
            f,
        )

    return ShuttleFactory(name=name, grid_config_file=str(grid_config_path))


@pytest.mark.django_db
class TestGeneratePackage:
    """Tests for generate_package function."""

    def test_fails_if_output_exists(self, tmp_path):
        """Fails if output directory already exists."""
        output = tmp_path / "output"
        output.mkdir()

        with pytest.raises(ReticlePackageError, match="exists"):
            generate_package("G801", output)

    def test_fails_if_shuttle_not_found(self, tmp_path):
        """Fails if shuttle doesn't exist."""
        with pytest.raises(Shuttle.DoesNotExist):
            generate_package("XXXX", tmp_path / "output")

    def test_full_package_generation(self, tmp_path):
        """Generate complete package with all files."""
        shuttle = create_shuttle_with_config(tmp_path, "G899")

        # Create GDS files
        gds_dir = tmp_path / "gds"
        gds_dir.mkdir()
        gds1 = gds_dir / "output1.gds"
        gds1.write_text("GDS1")
        gds2 = gds_dir / "output2.gds"
        gds2.write_text("GDS2")

        # Create two projects with checks
        project1 = ProjectFactory(project_id="TST1", slot_size="1x1")
        pf1 = ProjectFileFactory(project=project1, top_cell="TOP1")
        ManufacturabilityCheckFactory(
            project=project1,
            project_file=pf1,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
            output_gds=str(gds1),
            output_gds_sha256="hash1",
        )
        project1.submitted_file = pf1
        project1.save()

        project2 = ProjectFactory(project_id="TST2", slot_size="1x1")
        pf2 = ProjectFileFactory(project=project2, top_cell="TOP2")
        ManufacturabilityCheckFactory(
            project=project2,
            project_file=pf2,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
            warnings=["warn1"],
            output_gds=str(gds2),
            output_gds_sha256="hash2",
        )
        project2.submitted_file = pf2
        project2.save()

        # Create slots
        ShuttleSlot.objects.create(
            shuttle=shuttle, project=project1, row=0, column=0, slot_size="1x1"
        )
        ShuttleSlot.objects.create(
            shuttle=shuttle, project=project2, row=0, column=1, slot_size="1x1"
        )

        # Generate
        output = tmp_path / "output"
        warnings = generate_package("G899", output)

        assert len(warnings) == 0
        assert (output / "tilemap.csv").exists()
        assert (output / "manifest.csv").exists()
        assert (output / "summary.csv").exists()
        assert (output / "checks.csv").exists()
        assert (output / "README.md").exists()
        assert (output / "TST1" / "TOP1.gds").exists()
        assert (output / "TST2" / "TOP2.gds").exists()

    def test_allow_pending_uses_fallback(self, tmp_path):
        """allow_pending uses fallback query when no submitted_file."""
        shuttle = create_shuttle_with_config(tmp_path, "G898")

        gds_dir = tmp_path / "gds"
        gds_dir.mkdir()
        gds = gds_dir / "output.gds"
        gds.write_text("GDS")

        project = ProjectFactory(project_id="FALL", slot_size="1x1")
        pf = ProjectFileFactory(project=project, top_cell="FALL_TOP")
        ManufacturabilityCheckFactory(
            project=project,
            project_file=pf,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
            output_gds=str(gds),
            output_gds_sha256="hash",
        )
        # NOTE: NOT setting project.submitted_file

        ShuttleSlot.objects.create(
            shuttle=shuttle, project=project, row=0, column=0, slot_size="1x1"
        )

        output = tmp_path / "output"
        warnings = generate_package("G898", output, allow_pending=True)

        assert (output / "FALL" / "FALL_TOP.gds").exists()
        assert len(warnings) == 0

    def test_not_manufacturable_skipped_with_allow_pending(self, tmp_path):
        """NOT_MANUFACTURABLE projects are skipped with allow_pending."""
        shuttle = create_shuttle_with_config(tmp_path, "G897")

        gds_dir = tmp_path / "gds"
        gds_dir.mkdir()

        project = ProjectFactory(project_id="FAIL", slot_size="1x1")
        pf = ProjectFileFactory(project=project, top_cell="FAIL_TOP")
        ManufacturabilityCheckFactory(
            project=project,
            project_file=pf,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=False,  # NOT manufacturable
        )
        project.submitted_file = pf
        project.save()

        ShuttleSlot.objects.create(
            shuttle=shuttle, project=project, row=0, column=0, slot_size="1x1"
        )

        output = tmp_path / "output"
        warnings = generate_package("G897", output, allow_pending=True)

        # Skipped from tilemap/manifest
        assert not (output / "FAIL").exists()
        assert "FAIL" not in (output / "tilemap.csv").read_text()
        assert "FAIL" not in (output / "manifest.csv").read_text()

        # Present in summary/checks
        assert "FAIL" in (output / "summary.csv").read_text()
        assert "FAIL" in (output / "checks.csv").read_text()

        assert any("missing value" in w for w in warnings)

    def test_not_manufacturable_raises_without_allow_pending(self, tmp_path):
        """NOT_MANUFACTURABLE raises error without allow_pending."""
        shuttle = create_shuttle_with_config(tmp_path, "G895")

        project = ProjectFactory(project_id="NMAN", slot_size="1x1")
        pf = ProjectFileFactory(project=project, top_cell="NMAN_TOP")
        ManufacturabilityCheckFactory(
            project=project,
            project_file=pf,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=False,
        )
        project.submitted_file = pf
        project.save()

        ShuttleSlot.objects.create(
            shuttle=shuttle, project=project, row=0, column=0, slot_size="1x1"
        )

        output = tmp_path / "output"
        with pytest.raises(ReticlePackageError, match="missing value"):
            generate_package("G895", output, allow_pending=False)
