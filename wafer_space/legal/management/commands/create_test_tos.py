"""Management command to create test TOS data."""

from django.core.management.base import BaseCommand

from wafer_space.legal.models import TermsOfService


class Command(BaseCommand):
    """Create test TOS for browser tests."""

    help = "Creates test Terms of Service data for browser tests"

    def handle(self, *args, **options):
        """Create test TOS if it doesn't exist."""
        tos, created = TermsOfService.objects.get_or_create(
            version="1.0.0",
            defaults={
                "content": (
                    "Test Terms of Service\n\n"
                    "By using this service, you agree to these terms and conditions.\n\n"
                    "1. You must be at least 18 years old to use this service.\n"
                    "2. You agree to use the service responsibly.\n"
                    "3. You will not use the service for illegal purposes.\n\n"
                    "These terms are for testing purposes only."
                ),
                "is_active": True,
            },
        )
        if created:
            self.stdout.write(
                self.style.SUCCESS(f"Created test TOS version {tos.version}")
            )
        else:
            # Ensure it's active
            if not tos.is_active:
                tos.is_active = True
                tos.save()
                self.stdout.write(
                    self.style.SUCCESS(f"Activated existing TOS version {tos.version}")
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"Test TOS version {tos.version} already exists and is active")
                )