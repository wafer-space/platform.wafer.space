"""Management command to populate database with development/test data."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from wafer_space.core.enums import SlotSize
from wafer_space.core.utils import is_production_environment
from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectComplianceCertification
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot

if TYPE_CHECKING:
    from argparse import ArgumentParser

User = get_user_model()


class Command(BaseCommand):
    """Populate the database with useful development/test data."""

    help = "Populate database with development users, shuttles, and test projects"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Add command arguments."""
        parser.add_argument(
            "--reset",
            action="store_true",
            default=False,
            help="Delete existing dev data before creating new data",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Execute the command."""
        # Safety check: refuse to run on production systems
        if is_production_environment():
            msg = (
                "This command cannot run on production systems. "
                "It creates test users with weak passwords. "
                "Production detected via: DEBUG=False, PostgreSQL database, "
                "or prod/stage settings module."
            )
            raise CommandError(msg)

        if options["reset"]:
            self._reset_data()

        # Create users
        mithro = self._create_user(
            username="mithro",
            email="me@mith.ro",
            is_staff=True,
            is_superuser=True,
        )
        testuser = self._create_user(
            username="testuser",
            email="test@example.com",
        )

        # Ensure TOS acceptance
        tos = self._ensure_tos()
        self._ensure_tos_acceptance(mithro, tos)
        self._ensure_tos_acceptance(testuser, tos)

        # Create shuttle and slots
        shuttle = self._create_shuttle()
        self._create_slots(shuttle)

        # Create test projects
        self._create_projects(shuttle, mithro, testuser)

        self.stdout.write(self.style.SUCCESS("\nDevelopment data populated!"))
        self.stdout.write("  Users: mithro (staff/superuser), testuser")
        self.stdout.write(f"  Shuttle: {shuttle.name} (4×4 grid = 16 slots)")
        self.stdout.write("  Projects: 15 test projects with various states")

    def _reset_data(self) -> None:
        """Delete existing development data."""
        self.stdout.write(self.style.WARNING("Resetting dev data..."))

        # Delete test projects on G899 shuttle (cascade handles compliance certs)
        Project.objects.filter(shuttle__name="G899").delete()

        # Delete test shuttle (cascade handles slots)
        Shuttle.objects.filter(name="G899").delete()

        self.stdout.write("  Deleted test projects and shuttle G899")

    def _create_user(
        self,
        *,
        username: str,
        email: str,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> Any:
        """Create or update a user."""
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": username,
                "is_staff": is_staff,
                "is_superuser": is_superuser,
            },
        )

        if not created:
            # Update existing user
            changed = []
            if user.username != username:
                user.username = username
                changed.append("username")
            if is_staff and not user.is_staff:
                user.is_staff = True
                changed.append("is_staff")
            if is_superuser and not user.is_superuser:
                user.is_superuser = True
                changed.append("is_superuser")
            if changed:
                user.save()
                self.stdout.write(f"  Updated {username}: {', '.join(changed)}")
            else:
                self.stdout.write(f"  User {username} already exists")

        # Always set password to username for dev convenience
        user.set_password(username)
        user.save()
        if created:
            self.stdout.write(
                self.style.SUCCESS(f"  Created user: {username} ({email})")
            )

        # Ensure email is verified
        self._ensure_email_verified(user)

        return user

    def _ensure_email_verified(self, user: Any) -> None:
        """Ensure user's email is verified in allauth."""
        email_address, created = EmailAddress.objects.get_or_create(
            user=user,
            email=user.email,
            defaults={
                "verified": True,
                "primary": True,
            },
        )
        if not created and not email_address.verified:
            email_address.verified = True
            email_address.primary = True
            email_address.save()
            self.stdout.write(f"  Verified email for {user.username}")

    def _ensure_tos(self) -> TermsOfService:
        """Ensure a TOS version exists."""
        tos, created = TermsOfService.objects.get_or_create(
            version="1.0.0",
            defaults={"is_active": True},
        )
        if created:
            self.stdout.write(self.style.SUCCESS("  Created TOS version 1.0.0"))
        return tos

    def _ensure_tos_acceptance(self, user: Any, tos: TermsOfService) -> None:
        """Ensure user has accepted TOS."""
        _, created = TermsOfServiceAcceptance.objects.get_or_create(
            user=user,
            tos_version=tos,
        )
        if created:
            self.stdout.write(f"  Created TOS acceptance for {user.username}")

    def _create_shuttle(self) -> Shuttle:
        """Create the development shuttle."""
        shuttle, created = Shuttle.objects.get_or_create(
            name="G899",
            defaults={
                "description": "Development shuttle for testing",
                "status": Shuttle.Status.OPEN,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS("  Created shuttle: G899"))
        else:
            self.stdout.write("  Shuttle G899 already exists")
        return shuttle

    def _create_slots(self, shuttle: Shuttle) -> None:
        """Create a 4×4 grid of slots."""
        if shuttle.slots.exists():
            self.stdout.write("  Slots already exist for shuttle")
            return

        # Create 4×4 grid with varying slot sizes
        slot_sizes = [
            # Row 0: Mixed sizes
            [SlotSize.FULL, SlotSize.FULL, SlotSize.HALF_WIDTH, SlotSize.HALF_WIDTH],
            # Row 1: Full slots
            [SlotSize.FULL, SlotSize.FULL, SlotSize.FULL, SlotSize.FULL],
            # Row 2: Half height and quarter
            [
                SlotSize.HALF_HEIGHT,
                SlotSize.HALF_HEIGHT,
                SlotSize.QUARTER,
                SlotSize.QUARTER,
            ],
            # Row 3: Full slots
            [SlotSize.FULL, SlotSize.FULL, SlotSize.FULL, SlotSize.FULL],
        ]

        for row, sizes in enumerate(slot_sizes):
            for col, size in enumerate(sizes):
                ShuttleSlot.objects.create(
                    shuttle=shuttle,
                    row=row,
                    column=col,
                    slot_size=size,
                    status=ShuttleSlot.Status.AVAILABLE,
                )

        self.stdout.write(self.style.SUCCESS("  Created 16 shuttle slots (4×4 grid)"))

    def _create_projects(self, shuttle: Shuttle, mithro: Any, testuser: Any) -> None:
        """Create test projects with various states."""
        # Project definitions: (id, name, owner, size, is_manufacturable)
        # Project IDs must be exactly 4 uppercase alphanumeric characters
        projects_data = [
            # Full size projects
            ("RV32", "RISC-V Core", mithro, SlotSize.FULL, True),
            ("GP10", "GPIO Controller", mithro, SlotSize.FULL, True),
            ("UA01", "UART Serial", testuser, SlotSize.FULL, True),
            ("SP01", "SPI Controller", testuser, SlotSize.FULL, False),
            ("I2C1", "I2C Interface", mithro, SlotSize.FULL, None),
            ("PW01", "PWM Generator", testuser, SlotSize.FULL, None),
            # Half width projects
            ("AD01", "ADC Frontend", mithro, SlotSize.HALF_WIDTH, True),
            ("DA01", "DAC Output", testuser, SlotSize.HALF_WIDTH, True),
            ("CM01", "Comparator", mithro, SlotSize.HALF_WIDTH, False),
            # Half height projects
            ("CK01", "Clock Generator", testuser, SlotSize.HALF_HEIGHT, True),
            ("RS01", "Reset Controller", mithro, SlotSize.HALF_HEIGHT, None),
            # Quarter size projects
            ("RF01", "Voltage Reference", testuser, SlotSize.QUARTER, True),
            ("OS01", "RC Oscillator", mithro, SlotSize.QUARTER, True),
            ("BF01", "Buffer Cell", testuser, SlotSize.QUARTER, False),
            ("LD01", "LDO Regulator", mithro, SlotSize.QUARTER, None),
        ]

        created_count = 0
        for proj_id, name, owner, size, is_mfg in projects_data:
            project, created = Project.objects.get_or_create(
                project_id=proj_id,
                shuttle=shuttle,
                defaults={
                    "user": owner,
                    "name": name,
                    "description": f"Test project: {name}",
                    "slot_size": size,
                    "is_manufacturable": is_mfg,
                    "status": Project.Status.SUBMITTED,
                },
            )

            if created:
                # Create compliance certification
                ProjectComplianceCertification.objects.create(
                    project=project,
                    export_control_compliant=True,
                    not_restricted_entity=True,
                    end_use_statement="Development/testing purposes",
                    certified_by=owner,
                )
                created_count += 1

        if created_count > 0:
            self.stdout.write(
                self.style.SUCCESS(f"  Created {created_count} test projects")
            )
        else:
            self.stdout.write("  Test projects already exist")
