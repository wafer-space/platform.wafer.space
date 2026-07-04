"""Management command to create or update the E2E test user."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from typing import Any

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction

if TYPE_CHECKING:
    from argparse import ArgumentParser

User = get_user_model()

# Default values - match scripts/e2e_verify/main.py
DEFAULT_USERNAME = "e2e-test-user"
DEFAULT_EMAIL = "e2e-test@wafer.space"


class Command(BaseCommand):
    """Create or update the E2E test user for automated verification scripts."""

    help = "Create or update the E2E test user with verified email"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Add command arguments."""
        parser.add_argument(
            "--username",
            type=str,
            default=DEFAULT_USERNAME,
            help=f"Username for the test user (default: {DEFAULT_USERNAME})",
        )
        parser.add_argument(
            "--email",
            type=str,
            default=DEFAULT_EMAIL,
            help=f"Email for the test user (default: {DEFAULT_EMAIL})",
        )
        parser.add_argument(
            "--password",
            type=str,
            default=None,
            help="Password for the test user (or use E2E_TEST_PASSWORD env var)",
        )

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        """Execute the command."""
        username = options["username"]
        email = options["email"]
        password = options["password"] or os.environ.get("E2E_TEST_PASSWORD")

        if not password:
            msg = (
                "Password required. Provide via --password or E2E_TEST_PASSWORD "
                "environment variable"
            )
            raise CommandError(msg)

        user, created = User.objects.update_or_create(
            username=username,
            defaults={
                "email": email,
                "is_active": True,
            },
        )

        # Always update password (it may have changed in secrets)
        user.set_password(password)
        user.save()

        # Ensure email is verified (required for login with mandatory verification)
        _email_address, _email_created = EmailAddress.objects.update_or_create(
            user=user,
            email=email,
            defaults={
                "verified": True,
                "primary": True,
            },
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f"Created E2E test user: {username}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Updated E2E test user: {username}"))

        self.stdout.write(f"  Email: {email} (verified)")
        self.stdout.write("  Ready for E2E verification script")
