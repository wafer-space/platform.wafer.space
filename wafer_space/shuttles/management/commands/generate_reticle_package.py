"""Management command to generate reticle stitcher package."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.services.reticle_package import ReticlePackageError
from wafer_space.shuttles.services.reticle_package import generate_package


class Command(BaseCommand):
    """Generate reticle stitcher package for a shuttle."""

    help = "Generate reticle stitcher package with CSV files and GDS links"

    def add_arguments(self, parser):
        parser.add_argument("shuttle_name", help="Shuttle ID (e.g., G801)")
        parser.add_argument("-o", "--output", required=True, help="Output directory")
        parser.add_argument(
            "--allow-pending",
            action="store_true",
            help="Allow projects without completed checks",
        )

    def handle(self, *args, **options):
        output_path = Path(options["output"])

        try:
            warnings = generate_package(
                options["shuttle_name"],
                output_path,
                allow_pending=options["allow_pending"],
            )
        except Shuttle.DoesNotExist as e:
            msg = f"Shuttle not found: {options['shuttle_name']}"
            raise CommandError(msg) from e
        except ReticlePackageError as e:
            raise CommandError(str(e)) from e

        for warning in warnings:
            self.stdout.write(self.style.WARNING(f"Warning: {warning}"))

        self.stdout.write(self.style.SUCCESS(f"Package generated at {output_path}"))
