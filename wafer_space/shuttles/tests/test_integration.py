"""Integration tests for shuttle grid layout system."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command

from wafer_space.core.enums import SlotSize
from wafer_space.projects.models import ProjectComplianceCertification
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.users.tests.factories import UserFactory


def create_compliant_project(shuttle, slot_size, project_id, user):
    """Helper to create a project with valid compliance certification."""
    project = ProjectFactory(
        shuttle=shuttle, slot_size=slot_size, project_id=project_id
    )
    ProjectComplianceCertification.objects.create(
        project=project,
        certified_by=user,
        export_control_compliant=True,
        not_restricted_entity=True,
        end_use_statement="Test project for automated testing purposes",
    )
    return project


@pytest.mark.django_db
class TestGridWorkflow:
    """Test end-to-end grid configuration and assignment workflow."""

    def test_complete_workflow(self, tmp_path):
        """Test complete workflow from config to assignment."""
        # Step 1: Create shuttle
        shuttle = Shuttle.objects.create(
            name="G850", description="Production shuttle", status=Shuttle.Status.OPEN
        )

        # Step 2: Create grid configuration
        config_file = tmp_path / "G850-layout.yaml"
        config_file.write_text("""
shuttle: G850
row_heights: [1.0, 0.5]
column_widths: [1.0, 0.5, 1.0]
""")

        # Step 3: Generate grid
        out = StringIO()
        call_command(
            "generate_shuttle_grid", "G850", f"--config-dir={tmp_path}", stdout=out
        )

        # Verify grid created
        slots = list(
            ShuttleSlot.objects.filter(shuttle=shuttle).order_by("row", "column")
        )
        expected_slots = 6  # 2 rows x 3 columns
        assert len(slots) == expected_slots

        # Verify grid positions
        assert slots[0].grid_position == "A1"  # (0, 0)
        assert slots[1].grid_position == "B1"  # (0, 1)
        assert slots[2].grid_position == "C1"  # (0, 2)
        assert slots[3].grid_position == "A2"  # (1, 0)
        assert slots[4].grid_position == "B2"  # (1, 1)
        assert slots[5].grid_position == "C2"  # (1, 2)

        # Verify slot sizes
        assert slots[0].slot_size == SlotSize.FULL  # 1.0 x 1.0
        assert slots[1].slot_size == SlotSize.HALF_HEIGHT  # 1.0 x 0.5
        assert slots[3].slot_size == SlotSize.HALF_WIDTH  # 0.5 x 1.0
        assert slots[4].slot_size == SlotSize.QUARTER  # 0.5 x 0.5

        # Step 4: Create projects with compliance certifications
        user = UserFactory(is_staff=True)
        project_full = create_compliant_project(shuttle, SlotSize.FULL, "FULL", user)
        project_quarter = create_compliant_project(
            shuttle, SlotSize.QUARTER, "QRTR", user
        )

        # Step 5: Assign projects to slots

        # Assign FULL project to A1
        slots[0].reserve(project_full, user)
        assert slots[0].project == project_full
        assert slots[0].status == ShuttleSlot.Status.RESERVED

        # Assign QUARTER project to B2
        slots[4].reserve(project_quarter, user)
        assert slots[4].project == project_quarter

        # Step 6: Verify multi-slot assignment
        slots[2].reserve(project_full, user)  # Assign FULL to C1 as well
        expected_assignments = 2
        assert project_full.shuttle_slots.count() == expected_assignments

        # Step 7: Verify grid dimensions property
        assert shuttle.grid_dimensions == (2, 3)

    def test_grid_regeneration_safety(self, tmp_path):
        """Test that grid regeneration protects assigned projects."""
        shuttle = Shuttle.objects.create(
            name="G851", description="Test shuttle", status=Shuttle.Status.OPEN
        )

        # Create initial grid
        config_v1 = tmp_path / "G851-layout.yaml"
        config_v1.write_text("""
shuttle: G851
row_heights: [1.0]
column_widths: [1.0]
""")

        call_command(
            "generate_shuttle_grid",
            "G851",
            f"--config-dir={tmp_path}",
            stdout=StringIO(),
        )

        # Assign project with compliance certification
        slot = ShuttleSlot.objects.get(shuttle=shuttle)
        user = UserFactory()
        project = create_compliant_project(shuttle, SlotSize.FULL, "TEST", user)
        slot.reserve(project, user)

        # Try to update without --force
        config_v2 = tmp_path / "G851-layout.yaml"
        config_v2.write_text("""
shuttle: G851
row_heights: [1.0, 1.0]
column_widths: [1.0, 1.0]
""")

        with pytest.raises(SystemExit):
            call_command(
                "generate_shuttle_grid",
                "G851",
                f"--config-dir={tmp_path}",
                "--update",
                stdout=StringIO(),
            )

        # Verify original slot still exists
        assert ShuttleSlot.objects.filter(shuttle=shuttle, project=project).exists()

        # Update with --force
        call_command(
            "generate_shuttle_grid",
            "G851",
            f"--config-dir={tmp_path}",
            "--update",
            "--force",
            stdout=StringIO(),
        )

        # Verify new grid created
        expected_grid_size = 4  # 2x2 grid
        assert ShuttleSlot.objects.filter(shuttle=shuttle).count() == expected_grid_size

        # Verify project still on shuttle but no slot
        project.refresh_from_db()
        assert project.shuttle == shuttle
        assert project.shuttle_slots.count() == 0
