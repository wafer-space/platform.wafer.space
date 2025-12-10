"""Management command to create a new Terms of Service version."""

from datetime import UTC
from datetime import datetime
from pathlib import Path

import frontmatter
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from wafer_space.legal.models import TermsOfService
from wafer_space.legal.utils import dump_frontmatter_post

User = get_user_model()

# Lorem ipsum placeholder text for TOS in Markdown format
LOREM_IPSUM_TOS = """# Terms of Service

## Introduction

Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod
tempor incididunt ut labore et dolore magna aliqua.

## 1. Acceptance of Terms

Lorem ipsum dolor sit amet, consectetur adipiscing elit. Duis aute irure
dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla
pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui
officia deserunt mollit anim id est laborum.

## 2. User Obligations

Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium
doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore
veritatis et quasi architecto beatae vitae dicta sunt explicabo. Nemo enim
ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit.

### 2.1 Age Requirements
You must be at least 18 years old to use this service.

### 2.2 Responsible Use
You agree to use the service responsibly.

### 2.3 Legal Compliance
You will not use the service for illegal purposes.

## 3. Intellectual Property

At vero eos et accusamus et iusto odio dignissimos ducimus qui blanditiis
praesentium voluptatum deleniti atque corrupti quos dolores et quas molestias
excepturi sint occaecati cupiditate non provident, similique sunt in culpa qui
officia deserunt mollitia animi, id est laborum et dolorum fuga.

## 4. Privacy and Data Protection

Temporibus autem quibusdam et aut officiis debitis aut rerum necessitatibus
saepe eveniet ut et voluptates repudiandae sint et molestiae non recusandae.
Itaque earum rerum hic tenetur a sapiente delectus, ut aut reiciendis
voluptatibus maiores alias consequatur aut perferendis doloribus asperiores
repellat.

## 5. Limitation of Liability

Nam libero tempore, cum soluta nobis est eligendi optio cumque nihil impedit
quo minus id quod maxime placeat facere possimus, omnis voluptas assumenda est,
omnis dolor repellendus. Temporibus autem quibusdam et aut officiis debitis aut
rerum necessitatibus saepe eveniet.

## 6. Termination

Quis autem vel eum iure reprehenderit qui in ea voluptate velit esse quam nihil
molestiae consequatur, vel illum qui dolorem eum fugiat quo voluptas nulla
pariatur. At vero eos et accusamus et iusto odio dignissimos ducimus qui
blanditiis praesentium.

## 7. Modifications to Terms

Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium
doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore
veritatis et quasi architecto beatae vitae dicta sunt explicabo.

## 8. Governing Law

Et harum quidem rerum facilis est et expedita distinctio. Nam libero tempore,
cum soluta nobis est eligendi optio cumque nihil impedit quo minus id quod
maxime placeat facere possimus, omnis voluptas assumenda est, omnis dolor
repellendus.

## 9. Contact Information

Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor
incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis
nostrud exercitation ullamco laboris.

---

By accepting these Terms of Service, you acknowledge that you have read, understood,
and agree to be bound by these terms. If you do not agree to these terms, you may
not use our service.
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
        content = options["content"]
        admin_username = options["admin_username"]
        activate = options["activate"]

        # Check if version already exists in database
        if TermsOfService.objects.filter(version=version).exists():
            msg = f"TOS version {version} already exists in database"
            raise CommandError(msg)

        # Create markdown file
        base_dir = Path(__file__).parent.parent.parent / "tos_versions"
        base_dir.mkdir(exist_ok=True)
        file_path = base_dir / f"{version}.md"

        # Check if file already exists
        if file_path.exists():
            msg = f"Markdown file already exists: {file_path}"
            raise CommandError(msg)

        # Get admin user if specified
        created_by = None
        if admin_username:
            try:
                created_by = User.objects.get(username=admin_username)
            except User.DoesNotExist as exc:
                msg = f"User '{admin_username}' does not exist"
                raise CommandError(msg) from exc

        # Create content with front matter
        if content:
            # Use provided content (assume it's just the body, not full markdown)
            post = frontmatter.Post(content)
        else:
            # Use lorem ipsum template
            post = frontmatter.Post(LOREM_IPSUM_TOS.strip())

        # Set front matter metadata
        post.metadata["version"] = version
        post.metadata["effective_date"] = datetime.now(UTC).strftime("%Y-%m-%d")
        post.metadata["is_active"] = activate
        post.metadata["created_at"] = datetime.now(UTC).isoformat()
        post.metadata["created_by"] = created_by.username if created_by else None
        post.metadata["description"] = f"Terms of Service v{version}"
        post.metadata["requires_reacceptance"] = True

        # Write markdown file with front matter
        # Use dump_frontmatter_post for consistent formatting (issue #153)
        with file_path.open("w") as f:
            f.write(dump_frontmatter_post(post))

        self.stdout.write(
            self.style.SUCCESS(
                f"Created markdown file: {file_path}",
            ),
        )

        # Create database entry
        tos = TermsOfService.objects.create(
            version=version,
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
        self.stdout.write(f"Markdown file: {file_path}")
