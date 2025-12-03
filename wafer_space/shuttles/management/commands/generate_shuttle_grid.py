"""Management command to generate shuttle grid from YAML configuration."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction

from wafer_space.shuttles.config import GridConfig
from wafer_space.shuttles.config import GridConfigError
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot


class Command(BaseCommand):
    """Generate shuttle grid slots from YAML configuration file."""

    help = "Generate shuttle grid from YAML configuration"

    def add_arguments(self, parser):
        parser.add_argument(
            "shuttle_name",
            type=str,
            help="Name of shuttle to generate grid for",
        )
        parser.add_argument(
            "--config-dir",
            type=str,
            default="shuttles",
            help="Directory containing configuration files (default: shuttles/)",
        )
        parser.add_argument(
            "--update",
            action="store_true",
            help="Update existing grid (requires --force if slots assigned)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force update even if projects are assigned",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without creating slots",
        )

    def handle(self, *args, **options):
        shuttle_name = options["shuttle_name"]
        config_dir = Path(options["config_dir"])
        update = options["update"]
        force = options["force"]
        dry_run = options["dry_run"]

        # Load and validate configuration
        config_path = config_dir / f"{shuttle_name}-layout.yaml"
        config = self._load_config(config_path, shuttle_name)

        # Get shuttle
        shuttle = self._get_shuttle(shuttle_name)

        # Validate existing slots
        self._validate_existing_slots(shuttle, shuttle_name, update=update, force=force)

        if dry_run:
            self.stdout.write(self.style.WARNING("\n=== DRY RUN MODE ===\n"))

        # Generate slots
        self._generate_grid(
            shuttle, config, config_path, update=update, dry_run=dry_run
        )

    def _load_config(self, config_path: Path, shuttle_name: str) -> GridConfig:
        """Load and validate grid configuration from YAML file."""
        if not config_path.exists():
            msg = f"Configuration file not found: {config_path}"
            raise CommandError(msg)

        try:
            config = GridConfig.from_file(config_path)
        except GridConfigError as exc:
            msg = f"Invalid configuration: {exc}"
            raise CommandError(msg) from exc

        if config.shuttle_name != shuttle_name:
            msg = (
                f"Shuttle name mismatch: config has '{config.shuttle_name}', "
                f"expected '{shuttle_name}'"
            )
            raise CommandError(msg)

        return config

    def _get_shuttle(self, shuttle_name: str) -> Shuttle:
        """Get shuttle by name or raise error."""
        try:
            return Shuttle.objects.get(name=shuttle_name)
        except Shuttle.DoesNotExist as exc:
            msg = f"Shuttle not found: {shuttle_name}"
            raise CommandError(msg) from exc

    def _validate_existing_slots(
        self, shuttle: Shuttle, shuttle_name: str, *, update: bool, force: bool
    ) -> None:
        """Validate that existing slots can be updated."""
        existing_slots = ShuttleSlot.objects.filter(shuttle=shuttle)
        if not existing_slots.exists():
            return

        if not update:
            slot_count = existing_slots.count()
            msg = (
                f"Shuttle {shuttle_name} already has {slot_count} slots. "
                "Use --update to regenerate grid."
            )
            raise CommandError(msg)

        # Check for assigned projects
        assigned_slots = existing_slots.exclude(project__isnull=True)
        if assigned_slots.exists() and not force:
            project_identifiers = []
            for slot in assigned_slots.select_related("project"):
                proj = slot.project
                if proj is not None:
                    identifier = proj.project_id if proj.project_id else proj.name
                    project_identifiers.append(identifier)
            project_names = ", ".join(project_identifiers)
            msg = (
                f"Shuttle {shuttle_name} has {assigned_slots.count()} "
                f"assigned projects: {project_names}. "
                "These projects will remain on the shuttle but lose their "
                "slot positions. Use --force to proceed."
            )
            raise CommandError(msg)

    def _generate_grid(
        self,
        shuttle: Shuttle,
        config: GridConfig,
        config_path: Path,
        *,
        update: bool,
        dry_run: bool,
    ):
        """Generate grid slots from configuration."""
        slots_to_create = []

        for row_idx, row_height in enumerate(config.row_heights):
            for col_idx, col_width in enumerate(config.column_widths):
                slot_size = GridConfig.calculate_slot_size(row_height, col_width)

                slot_data = {
                    "shuttle": shuttle,
                    "row": row_idx,
                    "column": col_idx,
                    "slot_size": slot_size,
                    "status": ShuttleSlot.Status.AVAILABLE,
                }
                slots_to_create.append(slot_data)

        # Show preview of grid configuration
        preview_limit = 5

        if dry_run:
            self.stdout.write(
                f"\nWould create {len(slots_to_create)} slots for {shuttle.name}:\n"
            )
            grid_dims = (
                f"Grid dimensions: {config.num_rows} rows x "
                f"{config.num_columns} columns\n"
            )
            self.stdout.write(grid_dims)

            # Show sample slots
            for _idx, slot_data in enumerate(slots_to_create[:preview_limit]):
                temp_slot = ShuttleSlot(**slot_data)
                self.stdout.write(
                    f"  {temp_slot.grid_position}: {slot_data['slot_size']} "
                    f"(row={slot_data['row']}, col={slot_data['column']})"
                )
            if len(slots_to_create) > preview_limit:
                remaining = len(slots_to_create) - preview_limit
                self.stdout.write(f"  ... and {remaining} more\n")
        else:
            with transaction.atomic():
                # Delete existing slots if updating
                if update:
                    deleted_info = ShuttleSlot.objects.filter(shuttle=shuttle).delete()
                    deleted_count = deleted_info[0]
                    self.stdout.write(f"Deleted {deleted_count} existing slots\n")

                # Create new slots
                slots = [ShuttleSlot(**data) for data in slots_to_create]
                ShuttleSlot.objects.bulk_create(slots)

                # Update shuttle config path
                shuttle.grid_config_file = str(config_path)
                shuttle.save()

            grid_info = (
                f"Grid dimensions: {config.num_rows} rows x "
                f"{config.num_columns} columns\n"
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ Created {len(slots_to_create)} slots for {shuttle.name}\n"
                    f"{grid_info}"
                    f"Config file: {config_path}\n"
                )
            )
