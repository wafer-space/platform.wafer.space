"""Management command to send TOS update notifications to users."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.legal.tasks import send_bulk_tos_notifications

User = get_user_model()

# Constants
MAX_USERS_TO_DISPLAY = 10


class Command(BaseCommand):
    """Send TOS update notification emails to users who haven't accepted."""

    help = "Send TOS update notifications to users"

    def _get_tos_version(self, version_str: str | None):
        """Get TOS version from string or active version."""
        if version_str:
            try:
                return TermsOfService.objects.get(version=version_str)
            except TermsOfService.DoesNotExist as exc:
                msg = f"TOS version {version_str} does not exist"
                raise CommandError(msg) from exc

        tos_version = TermsOfService.get_active()
        if not tos_version:
            msg = (
                "No active TOS version found. "
                "Please specify --version or activate a TOS version."
            )
            raise CommandError(msg)
        return tos_version

    def _parse_user_ids(self, user_ids_str: str | None) -> list[int] | None:
        """Parse user IDs from comma-separated string."""
        if not user_ids_str:
            return None

        try:
            return [int(uid.strip()) for uid in user_ids_str.split(",")]
        except ValueError as exc:
            msg = "Invalid user IDs format. Use comma-separated integers."
            raise CommandError(msg) from exc

    def _run_dry_run(self, tos_version, user_ids: list[int] | None):
        """Run dry run mode and display what would be notified."""
        self.stdout.write(
            self.style.WARNING("DRY RUN MODE - No emails will be sent"),
        )

        # Count users who would be notified
        if user_ids:
            users = User.objects.filter(id__in=user_ids)
        else:
            accepted_user_ids = TermsOfServiceAcceptance.objects.filter(
                tos_version=tos_version,
            ).values_list("user_id", flat=True)

            users = User.objects.filter(is_active=True).exclude(
                id__in=accepted_user_ids,
            )

        count = users.count()
        self.stdout.write(f"Would notify {count} users")

        for user in users[:MAX_USERS_TO_DISPLAY]:
            self.stdout.write(f"  - {user.username} ({user.email})")

        if count > MAX_USERS_TO_DISPLAY:
            remaining = count - MAX_USERS_TO_DISPLAY
            self.stdout.write(f"  ... and {remaining} more users")

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
            help=(
                "Comma-separated list of user IDs to notify "
                "(default: all users who haven't accepted)"
            ),
            default=None,
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without actually sending emails",
        )

    def handle(self, *args, **options):
        """Execute the command."""
        # Get TOS version and parse options
        tos_version = self._get_tos_version(options["version"])
        user_ids = self._parse_user_ids(options["user_ids"])
        dry_run = options["dry_run"]

        version_msg = (
            f"Preparing to send TOS notifications for version {tos_version.version}"
        )
        self.stdout.write(self.style.SUCCESS(version_msg))

        if dry_run:
            self._run_dry_run(tos_version, user_ids)
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
