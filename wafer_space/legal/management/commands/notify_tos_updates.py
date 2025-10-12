"""Management command to send TOS update notifications to users."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from wafer_space.legal.models import TermsOfService
from wafer_space.legal.tasks import send_bulk_tos_notifications

User = get_user_model()


class Command(BaseCommand):
    """Send TOS update notification emails to users who haven't accepted."""

    help = "Send TOS update notifications to users"

    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument(
            "--version",
            type=str,
            help="TOS version to notify about (default: active version)",
            default=None,
        )
        parser.add_argument(
            "--user-ids",
            type=str,
            help="Comma-separated list of user IDs to notify (default: all users who haven't accepted)",
            default=None,
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without actually sending emails",
        )

    def handle(self, *args, **options):
        """Execute the command."""
        version_str = options["version"]
        user_ids_str = options["user_ids"]
        dry_run = options["dry_run"]

        # Get TOS version
        if version_str:
            try:
                tos_version = TermsOfService.objects.get(version=version_str)
            except TermsOfService.DoesNotExist as exc:
                msg = f"TOS version {version_str} does not exist"
                raise CommandError(msg) from exc
        else:
            tos_version = TermsOfService.get_active()
            if not tos_version:
                msg = "No active TOS version found. Please specify --version or activate a TOS version."
                raise CommandError(msg)

        # Parse user IDs if provided
        user_ids = None
        if user_ids_str:
            try:
                user_ids = [int(uid.strip()) for uid in user_ids_str.split(",")]
            except ValueError as exc:
                msg = "Invalid user IDs format. Use comma-separated integers."
                raise CommandError(msg) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Preparing to send TOS notifications for version {tos_version.version}",
            ),
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN MODE - No emails will be sent",
                ),
            )

            # Count users who would be notified
            from wafer_space.legal.models import TermsOfServiceAcceptance

            if user_ids:
                users = User.objects.filter(id__in=user_ids)
                count = users.count()
            else:
                accepted_user_ids = TermsOfServiceAcceptance.objects.filter(
                    tos_version=tos_version,
                ).values_list("user_id", flat=True)

                users = User.objects.filter(is_active=True).exclude(
                    id__in=accepted_user_ids,
                )
                count = users.count()

            self.stdout.write(f"Would notify {count} users")

            for user in users[:10]:  # Show first 10
                self.stdout.write(f"  - {user.username} ({user.email})")

            if count > 10:
                self.stdout.write(f"  ... and {count - 10} more users")

            return

        # Send notifications
        self.stdout.write("Queuing notification emails...")

        result = send_bulk_tos_notifications(tos_version.id, user_ids)

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully queued {result['queued']} notification emails",
            ),
        )
        self.stdout.write(f"Total users: {result['total_users']}")
        self.stdout.write(f"Notifications created: {result['created']}")
        self.stdout.write(f"Notifications queued: {result['queued']}")

        if "error" in result:
            self.stdout.write(
                self.style.ERROR(f"Error: {result['error']}"),
            )
