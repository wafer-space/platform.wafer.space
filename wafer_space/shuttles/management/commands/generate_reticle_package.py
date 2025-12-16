"""Management command to generate reticle stitcher package."""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from wafer_space.shuttles.services.reticle_package import ReticlePackageError
from wafer_space.shuttles.services.reticle_package import ReticlePackageService


class Command(BaseCommand):
    """Generate reticle stitcher package for a shuttle."""

    help = "Generate reticle stitcher package with CSV files, GDS links, and README"

    def add_arguments(self, parser):
        parser.add_argument(
            "shuttle_name",
            type=str,
            help="Shuttle ID (e.g., G801)",
        )
        parser.add_argument(
            "--output",
            "-o",
            type=str,
            required=True,
            help="Output directory path (must not exist)",
        )
        parser.add_argument(
            "--allow-pending",
            action="store_true",
            help="Allow projects without completed checks (skip with warning)",
        )

    def handle(self, *args, **options):
        shuttle_name = options["shuttle_name"]
        output_path = Path(options["output"])
        allow_pending = options["allow_pending"]

        self.stdout.write(f"Generating reticle package for {shuttle_name}...")

        service = ReticlePackageService(
            shuttle_name=shuttle_name,
            output_path=output_path,
            allow_pending=allow_pending,
        )

        try:
            result = service.generate()
        except ReticlePackageError as e:
            raise CommandError(str(e)) from e

        # Print warnings
        for warning in service.warnings:
            self.stdout.write(self.style.WARNING(f"Warning: {warning}"))

        # Print summary
        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ Package generated at {output_path}\n"
                f"  Projects included: {result['projects_included']}\n"
                f"  Projects skipped: {result['projects_skipped']}\n"
            )
        )
