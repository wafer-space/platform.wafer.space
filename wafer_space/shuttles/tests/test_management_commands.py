from io import StringIO

import pytest
from django.core.management import call_command

from wafer_space.core.enums import SlotSize
from wafer_space.projects.models import Project
from wafer_space.projects.tests.constants import TEST_PASSWORD
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.users.models import User


@pytest.mark.django_db
class TestGenerateShuttleGrid:
    """Test generate_shuttle_grid management command."""

    def test_generate_new_grid(self, tmp_path):
        """Should generate grid from YAML config."""
        # Create shuttle
        shuttle = Shuttle.objects.create(
            name="G850",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=100,
        )

        # Create config file
        config_file = tmp_path / "G850-layout.yaml"
        config_file.write_text("""
shuttle: G850
row_heights: [1.0, 0.5]
column_widths: [1.0, 0.5]
""")

        # Run command
        out = StringIO()
        call_command(
            "generate_shuttle_grid",
            "G850",
            f"--config-dir={tmp_path}",
            stdout=out,
        )

        # Verify slots created
        slots = list(
            ShuttleSlot.objects.filter(shuttle=shuttle).order_by("row", "column")
        )
        expected_slots = 4  # 2 rows x 2 columns
        assert len(slots) == expected_slots

        # Verify positions and sizes
        assert slots[0].row == 0
        assert slots[0].column == 0
        assert slots[0].slot_size == SlotSize.FULL  # 1.0 x 1.0

        assert slots[1].row == 0
        assert slots[1].column == 1
        assert slots[1].slot_size == SlotSize.HALF_HEIGHT  # 1.0 x 0.5

        assert slots[2].row == 1
        assert slots[2].column == 0
        assert slots[2].slot_size == SlotSize.HALF_WIDTH  # 0.5 x 1.0

        assert slots[3].row == 1
        assert slots[3].column == 1
        assert slots[3].slot_size == SlotSize.QUARTER  # 0.5 x 0.5

        # Verify shuttle updated
        shuttle.refresh_from_db()
        assert shuttle.grid_config_file == str(config_file)

    def test_update_requires_force_if_assigned(self, tmp_path):
        """Should require --force flag if slots have assignments."""
        # Create shuttle with slots
        shuttle = Shuttle.objects.create(
            name="G851",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=100,
            available_slots=100,
        )
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.AVAILABLE,
        )

        # Create user and project
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        project = Project.objects.create(
            user=user,
            name="Test Project",
            description="Test project",
            status=Project.Status.DRAFT,
            shuttle=shuttle,
            slot_size=SlotSize.FULL,
        )
        # Assign project to slot (bypassing reserve validation for test)
        slot.project = project
        slot.reserved_by = user
        slot.status = ShuttleSlot.Status.RESERVED
        slot.save()

        # Create new config
        config_file = tmp_path / "G851-layout.yaml"
        config_file.write_text("""
shuttle: G851
row_heights: [1.0]
column_widths: [1.0]
""")

        # Try update without --force
        out = StringIO()
        with pytest.raises(SystemExit):
            call_command(
                "generate_shuttle_grid",
                "G851",
                f"--config-dir={tmp_path}",
                "--update",
                stdout=out,
            )

        output = out.getvalue()
        assert "assigned projects" in output
        assert "Use --force" in output

    def test_dry_run_mode(self, tmp_path):
        """Should preview without creating slots in dry-run mode."""
        shuttle = Shuttle.objects.create(
            name="G852",
            description="Test shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=100,
        )

        config_file = tmp_path / "G852-layout.yaml"
        config_file.write_text("""
shuttle: G852
row_heights: [1.0]
column_widths: [1.0]
""")

        out = StringIO()
        call_command(
            "generate_shuttle_grid",
            "G852",
            f"--config-dir={tmp_path}",
            "--dry-run",
            stdout=out,
        )

        # Verify no slots created
        assert ShuttleSlot.objects.filter(shuttle=shuttle).count() == 0

        # Verify preview in output
        output = out.getvalue()
        assert "DRY RUN" in output
        assert "Would create" in output
