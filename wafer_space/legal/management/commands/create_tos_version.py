"""Management command to create a new Terms of Service version."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from wafer_space.legal.models import TermsOfService

User = get_user_model()

# Lorem ipsum placeholder text for TOS
LOREM_IPSUM_TOS = """
Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor
incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis
nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.

1. ACCEPTANCE OF TERMS
Lorem ipsum dolor sit amet, consectetur adipiscing elit. Duis aute irure dolor
in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla
pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui
officia deserunt mollit anim id est laborum.

2. USER OBLIGATIONS
Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium
doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore
veritatis et quasi architecto beatae vitae dicta sunt explicabo. Nemo enim
ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit.

3. INTELLECTUAL PROPERTY
At vero eos et accusamus et iusto odio dignissimos ducimus qui blanditiis
praesentium voluptatum deleniti atque corrupti quos dolores et quas molestias
excepturi sint occaecati cupiditate non provident, similique sunt in culpa qui
officia deserunt mollitia animi, id est laborum et dolorum fuga.

4. PRIVACY AND DATA PROTECTION
Temporibus autem quibusdam et aut officiis debitis aut rerum necessitatibus
saepe eveniet ut et voluptates repudiandae sint et molestiae non recusandae.
Itaque earum rerum hic tenetur a sapiente delectus, ut aut reiciendis
voluptatibus maiores alias consequatur aut perferendis doloribus asperiores
repellat.

5. LIMITATION OF LIABILITY
Nam libero tempore, cum soluta nobis est eligendi optio cumque nihil impedit
quo minus id quod maxime placeat facere possimus, omnis voluptas assumenda est,
omnis dolor repellendus. Temporibus autem quibusdam et aut officiis debitis aut
rerum necessitatibus saepe eveniet.

6. TERMINATION
Quis autem vel eum iure reprehenderit qui in ea voluptate velit esse quam nihil
molestiae consequatur, vel illum qui dolorem eum fugiat quo voluptas nulla
pariatur. At vero eos et accusamus et iusto odio dignissimos ducimus qui
blanditiis praesentium.

7. MODIFICATIONS TO TERMS
Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium
doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore
veritatis et quasi architecto beatae vitae dicta sunt explicabo.

8. GOVERNING LAW
Et harum quidem rerum facilis est et expedita distinctio. Nam libero tempore,
cum soluta nobis est eligendi optio cumque nihil impedit quo minus id quod
maxime placeat facere possimus, omnis voluptas assumenda est, omnis dolor
repellendus.

9. CONTACT INFORMATION
Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor
incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis
nostrud exercitation ullamco laboris.

By accepting these Terms of Service, you acknowledge that you have read,
understood, and agree to be bound by these terms. If you do not agree to these
terms, you may not use our service.

Last Updated: [AUTO-GENERATED DATE]
Version: [AUTO-GENERATED VERSION]
"""


class Command(BaseCommand):
    """Create a new Terms of Service version with lorem ipsum placeholder text."""

    help = "Create a new Terms of Service version"

    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument(
            "version",
            type=str,
            help="Version number (e.g., '1.0.0', '2.0.0')",
        )
        parser.add_argument(
            "--content",
            type=str,
            help="Custom TOS content (default: lorem ipsum placeholder)",
            default=None,
        )
        parser.add_argument(
            "--admin-username",
            type=str,
            help="Username of admin creating this version",
            default=None,
        )
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Activate this version immediately",
        )

    def handle(self, *args, **options):
        """Execute the command."""
        version = options["version"]
        content = options["content"] or LOREM_IPSUM_TOS.strip()
        admin_username = options["admin_username"]
        activate = options["activate"]

        # Check if version already exists
        if TermsOfService.objects.filter(version=version).exists():
            msg = f"TOS version {version} already exists"
            raise CommandError(msg)

        # Get admin user if specified
        created_by = None
        if admin_username:
            try:
                created_by = User.objects.get(username=admin_username)
            except User.DoesNotExist as exc:
                msg = f"User '{admin_username}' does not exist"
                raise CommandError(msg) from exc

        # Create TOS version
        tos = TermsOfService.objects.create(
            version=version,
            content=content,
            is_active=activate,
            created_by=created_by,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully created TOS version {version}",
            ),
        )

        if activate:
            self.stdout.write(
                self.style.SUCCESS(
                    f"TOS version {version} is now active",
                ),
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"TOS version {version} created but not activated. "
                    "Use --activate flag or activate via admin.",
                ),
            )

        self.stdout.write(f"TOS ID: {tos.id}")
        self.stdout.write(f"Content length: {len(content)} characters")
