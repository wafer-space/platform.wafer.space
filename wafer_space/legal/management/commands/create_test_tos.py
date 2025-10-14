"""Management command to create test TOS data."""

from datetime import UTC
from datetime import datetime
from pathlib import Path

import frontmatter
from django.core.management.base import BaseCommand

from wafer_space.legal.models import TermsOfService


class Command(BaseCommand):
    """Create test TOS for browser tests."""

    help = "Creates test Terms of Service data for browser tests"

    def handle(self, *args, **options):
        """Create test TOS if it doesn't exist."""
        # Check if markdown file exists
        base_dir = Path(__file__).parent.parent.parent / "tos_versions"
        file_path = base_dir / "1.0.0.md"

        if not file_path.exists():
            # Create test markdown content with front matter
            test_content = """# Terms of Service

## Test Terms of Service

By using this service, you agree to these terms and conditions.

1. You must be at least 18 years old to use this service.
2. You agree to use the service responsibly.
3. You will not use the service for illegal purposes.

These terms are for testing purposes only."""

            post = frontmatter.Post(test_content.strip())

            # Set front matter metadata
            post.metadata["version"] = "1.0.0"
            post.metadata["effective_date"] = "2024-01-01"
            post.metadata["is_active"] = True
            post.metadata["created_at"] = datetime(2024, 1, 1, tzinfo=UTC).isoformat()
            post.metadata["created_by"] = None
            post.metadata["description"] = "Initial Terms of Service"
            post.metadata["requires_reacceptance"] = True

            # Create directory if needed
            base_dir.mkdir(exist_ok=True)

            # Write markdown file with front matter
            with file_path.open("w") as f:
                f.write(frontmatter.dumps(post))

            self.stdout.write(
                self.style.SUCCESS(
                    f"Created test markdown file: {file_path}",
                ),
            )

        # Create or update database entry
        tos, created = TermsOfService.objects.get_or_create(
            version="1.0.0",
            defaults={
                "is_active": True,
            },
        )
        if created:
            self.stdout.write(
                self.style.SUCCESS(f"Created test TOS version {tos.version}")
            )
        # Ensure it's active
        elif not tos.is_active:
            tos.is_active = True
            tos.save()
            self.stdout.write(
                self.style.SUCCESS(f"Activated existing TOS version {tos.version}")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Test TOS version {tos.version} already exists and is active"
                )
            )
