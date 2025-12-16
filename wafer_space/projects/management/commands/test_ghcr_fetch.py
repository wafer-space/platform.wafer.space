"""Management command to test GHCR metadata fetching."""

from __future__ import annotations

import json
from typing import Any

import requests
from django.core.management.base import BaseCommand
from django.core.management.base import CommandParser

from wafer_space.projects.tasks_revisions import _fetch_ghcr_metadata

# Default OCI index digest for ghcr.io/wafer-space/gf180mcu-precheck:latest
DEFAULT_DIGEST = (
    "sha256:4548ca1351d21cdd7e628e7f21d9567803d704784816e4fa69adcbd77073996f"
)


class Command(BaseCommand):
    """Test GHCR metadata fetching against real GitHub Container Registry."""

    help = "Fetch and display metadata from GHCR for a container image digest"

    def add_arguments(self, parser: CommandParser) -> None:
        """Add command arguments."""
        parser.add_argument(
            "digest",
            nargs="?",
            default=DEFAULT_DIGEST,
            help=f"SHA256 digest to fetch (default: {DEFAULT_DIGEST[:40]}...)",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output as JSON instead of formatted text",
        )

    def handle(self, *args: Any, **options: Any) -> str | None:
        """Execute the command."""
        digest: str = options["digest"]
        output_json: bool = options["json"]

        self.stdout.write(f"Fetching metadata for digest: {digest[:40]}...")
        self.stdout.write("")

        try:
            metadata = _fetch_ghcr_metadata(digest)
        except requests.RequestException as exc:
            self.stderr.write(self.style.ERROR(f"Failed to fetch metadata: {exc}"))
            return None

        if output_json:
            # Convert datetime to ISO format for JSON serialization
            json_data = {
                "digest": digest,
                "image_created_at": (
                    metadata["image_created_at"].isoformat()
                    if metadata.get("image_created_at")
                    else None
                ),
                "git_commit_sha": metadata.get("git_commit_sha", ""),
                "precheck_version": metadata.get("precheck_version", ""),
            }
            self.stdout.write(json.dumps(json_data, indent=2))
        else:
            self.stdout.write(self.style.SUCCESS("Metadata fetched successfully!"))
            self.stdout.write("")
            created = metadata.get("image_created_at")
            commit = metadata.get("git_commit_sha")
            version = metadata.get("precheck_version")
            self.stdout.write(f"  Image Created:     {created}")
            self.stdout.write(f"  Git Commit SHA:    {commit}")
            self.stdout.write(f"  Precheck Version:  {version}")

        return None
