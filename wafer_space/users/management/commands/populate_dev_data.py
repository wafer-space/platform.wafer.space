"""Management command to populate database with development/test data."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.utils import timezone

from wafer_space.core.enums import SlotSize
from wafer_space.core.utils import is_production_environment
from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import ManufacturabilityCheckpoint
from wafer_space.projects.models import PrecheckImageRevision
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectComplianceCertification
from wafer_space.projects.models import ProjectFile
from wafer_space.shuttles.config import GridConfig
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

        # Ensure precheck revisions exist for version badge display
        self._ensure_precheck_revisions()

        # Create G899 shuttle (development test shuttle) and slots
        g899 = self._create_shuttle("G899", "Development shuttle for testing")
        self._create_g899_slots(g899)
        self._create_g899_projects(g899, mithro, testuser)

        # Create G801 shuttle (initial shuttle run) and slots
        g801 = self._create_shuttle(
            "G801",
            "Initial shuttle run for wafer.space",
            crowd_supply_url="https://www.crowdsupply.com/wafer-space/gf180mcu-run-1/",
        )
        self._create_g801_slots(g801)
        self._create_g801_projects(g801, mithro, testuser)

        self.stdout.write(self.style.SUCCESS("\nDevelopment data populated!"))
        self.stdout.write("  Users: mithro (staff/superuser), testuser")
        self.stdout.write(f"  Shuttle G899: {g899.name} (4×4 grid = 16 slots)")
        self.stdout.write(f"  Shuttle G801: {g801.name} (5×8 grid = 40 slots)")
        self.stdout.write("  Projects: 15 (G899) + 12 (G801) test projects")

    def _reset_data(self) -> None:
        """Delete existing development data."""
        self.stdout.write(self.style.WARNING("Resetting dev data..."))

        # Delete test projects on G899 and G801 shuttles
        # (cascade handles compliance certs)
        Project.objects.filter(shuttle__name__in=["G899", "G801"]).delete()

        # Delete test shuttles (cascade handles slots)
        Shuttle.objects.filter(name__in=["G899", "G801"]).delete()

        self.stdout.write("  Deleted test projects and shuttles G899, G801")

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

    # Precheck version data - real versions from wafer-space/gf180mcu-precheck
    # Each tuple: (version, digest_suffix, git_sha_prefix, pdk_version)
    PRECHECK_VERSIONS: list[tuple[str, str, str, str]] = [
        ("1.5.3", "a1b2c3d4e5f6", "abc123def456", "1.6.5"),  # Latest
        ("1.5.2", "b2c3d4e5f6a1", "bcd234ef5678", "1.6.4"),
        ("1.5.1", "c3d4e5f6a1b2", "cde345f67890", "1.6.4"),
        ("1.5.0", "d4e5f6a1b2c3", "def456789abc", "1.6.3"),
        ("1.4.5", "e5f6a1b2c3d4", "ef567890abcd", "1.6.3"),
    ]

    def _get_precheck_digest(self, version: str) -> str:
        """Get the digest for a precheck version."""
        for v, suffix, _, _ in self.PRECHECK_VERSIONS:
            if v == version:
                return f"sha256:{suffix * 5}ab"
        # Default to latest
        return f"sha256:{self.PRECHECK_VERSIONS[0][1] * 5}ab"

    # Real GHCR digest to test revision fetching from GitHub
    # This is the OCI index digest from ghcr.io/wafer-space/gf180mcu-precheck:latest
    # (Docker returns the index digest, not the platform-specific manifest digest)
    REAL_GHCR_DIGEST = (
        "sha256:4548ca1351d21cdd7e628e7f21d9567803d704784816e4fa69adcbd77073996f"
    )

    def _ensure_precheck_revisions(self) -> None:
        """Create PrecheckImageRevision records for dev data.

        Creates multiple revisions with real version numbers from
        wafer-space/gf180mcu-precheck to test version badge display.

        Note: Does NOT create a revision for REAL_GHCR_DIGEST so that
        revisions_needs_fetching will discover it and fetch from GitHub.
        """
        created_count = 0
        for version, digest_suffix, git_sha, pdk_version in self.PRECHECK_VERSIONS:
            # Build a 64-char hex digest by repeating the suffix
            digest = f"sha256:{digest_suffix * 5}ab"
            git_commit = f"{git_sha}{git_sha}{git_sha}12345678"[:40]

            _, created = PrecheckImageRevision.objects.update_or_create(
                digest=digest,
                defaults={
                    "precheck_version": version,
                    "git_commit_sha": git_commit,
                    "pdk_version": pdk_version,
                    "tool_versions": {
                        "magic": "8.3.460",
                        "klayout": "0.28.17",
                        "netgen": "1.5.272",
                    },
                    "metadata_fetched_at": timezone.now(),
                },
            )
            if created:
                created_count += 1

        if created_count > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Created {created_count} PrecheckImageRevision records"
                )
            )
        else:
            self.stdout.write("  PrecheckImageRevision records already exist")

    def _create_shuttle(
        self, name: str, description: str, *, crowd_supply_url: str = ""
    ) -> Shuttle:
        """Create a shuttle with given name and description."""
        shuttle, created = Shuttle.objects.get_or_create(
            name=name,
            defaults={
                "description": description,
                "status": Shuttle.Status.OPEN,
                "crowd_supply_url": crowd_supply_url,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"  Created shuttle: {name}"))
        else:
            self.stdout.write(f"  Shuttle {name} already exists")
        return shuttle

    def _create_g899_slots(self, shuttle: Shuttle) -> None:
        """Create a 4×4 grid of slots for G899 development shuttle."""
        if shuttle.slots.exists():
            self.stdout.write(f"  Slots already exist for {shuttle.name}")
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

        self.stdout.write(
            self.style.SUCCESS(f"  Created 16 slots (4×4 grid) for {shuttle.name}")
        )

    def _create_g899_projects(
        self, shuttle: Shuttle, mithro: Any, testuser: Any
    ) -> None:
        """Create test projects for G899 with various states and checks.

        Creates projects demonstrating various multi-check scenarios:
        - Single FINISHED check (manufacturable/not manufacturable)
        - Check in progress (PENDING, RUNNING, ANALYZING)
        - ERROR check with retry chain
        - DRC_UPDATE re-run (multiple checks for same file)
        - No file/checks yet
        """
        # Project definitions with check scenarios
        # check_scenario: "single_pass", "single_fail", "in_progress", "error_retry",
        #                 "drc_update", "no_file"
        # is_submitted: True = submitted to manufacturing, False = still draft
        # slot_pos: (row, col) tuple for slot assignment, or None for unassigned
        # G899 grid layout:
        #   Row 0: FULL(0,0), FULL(0,1), HALF_WIDTH(0,2), HALF_WIDTH(0,3)
        #   Row 1: FULL(1,0), FULL(1,1), FULL(1,2), FULL(1,3)
        #   Row 2: HALF_HEIGHT(2,0), HALF_HEIGHT(2,1), QUARTER(2,2), QUARTER(2,3)
        #   Row 3: FULL(3,0), FULL(3,1), FULL(3,2), FULL(3,3)
        # Each tuple: (proj_id, name, owner, size, scenario, is_submitted, slot_pos)
        projects_data: list[tuple] = [
            # Full size projects - some assigned to slots
            (
                "RV32",
                "RISC-V Core",
                mithro,
                SlotSize.FULL,
                "single_pass",
                True,
                (0, 0),
            ),
            (
                "GP10",
                "GPIO Controller",
                mithro,
                SlotSize.FULL,
                "drc_update",
                True,
                (0, 1),
            ),
            (
                "UA01",
                "UART Serial",
                testuser,
                SlotSize.FULL,
                "single_pass",
                True,
                (1, 0),
            ),
            (
                "SP01",
                "SPI Controller",
                testuser,
                SlotSize.FULL,
                "single_fail",
                True,
                None,
            ),
            (
                "I2C1",
                "I2C Interface",
                mithro,
                SlotSize.FULL,
                "in_progress",
                True,
                None,
            ),
            (
                "PW01",
                "PWM Generator",
                testuser,
                SlotSize.FULL,
                "no_file",
                False,
                None,
            ),
            # Half width projects
            (
                "AD01",
                "ADC Frontend",
                mithro,
                SlotSize.HALF_WIDTH,
                "error_retry",
                True,
                (0, 2),
            ),
            (
                "DA01",
                "DAC Output",
                testuser,
                SlotSize.HALF_WIDTH,
                "single_pass",
                False,
                None,
            ),
            (
                "CM01",
                "Comparator",
                mithro,
                SlotSize.HALF_WIDTH,
                "single_fail",
                True,
                None,
            ),
            # Half height projects
            (
                "CK01",
                "Clock Generator",
                testuser,
                SlotSize.HALF_HEIGHT,
                "single_pass",
                True,
                (2, 0),
            ),
            (
                "RS01",
                "Reset Controller",
                mithro,
                SlotSize.HALF_HEIGHT,
                "in_progress",
                False,
                None,
            ),
            # Quarter size projects
            (
                "RF01",
                "Voltage Reference",
                testuser,
                SlotSize.QUARTER,
                "single_pass",
                True,
                (2, 2),
            ),
            (
                "OS01",
                "RC Oscillator",
                mithro,
                SlotSize.QUARTER,
                "drc_update",
                True,
                None,
            ),
            (
                "BF01",
                "Buffer Cell",
                testuser,
                SlotSize.QUARTER,
                "single_fail",
                False,
                None,
            ),
            (
                "LD01",
                "LDO Regulator",
                mithro,
                SlotSize.QUARTER,
                "no_file",
                False,
                None,
            ),
            # Project with real GHCR digest to test revision fetching
            (
                "FT01",
                "Fetch Test Design",
                mithro,
                SlotSize.QUARTER,
                "real_digest",
                True,
                None,
            ),
        ]

        created_count = 0
        assigned_count = 0
        for idx, proj_data in enumerate(projects_data):
            proj_id, name, owner, size, scenario, is_submitted, slot_pos = proj_data
            # Set status and submitted_at based on is_submitted flag
            if is_submitted:
                status = Project.Status.SUBMITTED
                submitted_at = timezone.now() - timedelta(days=idx + 1)
            else:
                status = Project.Status.DRAFT
                submitted_at = None

            project, created = Project.objects.get_or_create(
                project_id=proj_id,
                shuttle=shuttle,
                defaults={
                    "user": owner,
                    "name": name,
                    "description": f"Test project: {name}",
                    "slot_size": size,
                    "status": status,
                    "submitted_at": submitted_at,
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

                # Create file and checks based on scenario
                self._create_checks_for_project(project, scenario)
                created_count += 1

            # Assign project to slot if specified
            if slot_pos is not None:
                row, col = slot_pos
                assigned = self._assign_project_to_slot(shuttle, project, row, col)
                if assigned:
                    assigned_count += 1

        if created_count > 0:
            self.stdout.write(
                self.style.SUCCESS(f"  Created {created_count} G899 test projects")
            )
        else:
            self.stdout.write("  G899 test projects already exist")

        if assigned_count > 0:
            msg = f"  Assigned {assigned_count} projects to G899 slots"
            self.stdout.write(self.style.SUCCESS(msg))

    def _create_g801_slots(self, shuttle: Shuttle) -> None:
        """Create G801 grid slots from the real YAML configuration.

        Uses shuttles/G801-layout.yaml which defines:
        - 5 rows x 8 columns = 40 slots
        - Row 1: half-height, Rows 2-5: full-height
        - Columns A-G: full-width, Column H: half-width
        """
        if shuttle.slots.exists():
            self.stdout.write(f"  Slots already exist for {shuttle.name}")
            return

        # Load the real G801 grid configuration
        config_path = Path("shuttles/G801-layout.yaml")
        if not config_path.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"  G801 config not found at {config_path}, skipping slots"
                )
            )
            return

        config = GridConfig.from_file(config_path)

        # Create slots from configuration
        slot_count = 0
        for row_idx, row_height in enumerate(config.row_heights):
            for col_idx, col_width in enumerate(config.column_widths):
                slot_size = GridConfig.calculate_slot_size(row_height, col_width)
                ShuttleSlot.objects.create(
                    shuttle=shuttle,
                    row=row_idx,
                    column=col_idx,
                    slot_size=slot_size,
                    status=ShuttleSlot.Status.AVAILABLE,
                )
                slot_count += 1

        # Update shuttle config path
        shuttle.grid_config_file = str(config_path)
        shuttle.save(update_fields=["grid_config_file"])

        grid_desc = f"{config.num_rows}×{config.num_columns}"
        self.stdout.write(
            self.style.SUCCESS(
                f"  Created {slot_count} slots ({grid_desc} grid) for {shuttle.name}"
            )
        )

    def _create_g801_projects(
        self, shuttle: Shuttle, mithro: Any, testuser: Any
    ) -> None:
        """Create test projects for G801 initial shuttle run.

        Creates projects matching the G801 grid slot sizes:
        - FULL (1×1): 28 slots in rows 2-5, cols A-G
        - HALF_HEIGHT (1×0.5): 7 slots in row 1, cols A-G
        - HALF_WIDTH (0.5×1): 4 slots in rows 2-5, col H
        - QUARTER (0.5×0.5): 1 slot in row 1, col H
        """
        # G801 projects - different IDs and names than G899
        # G801 grid layout (5 rows × 8 cols):
        #   Row 0: HALF_HEIGHT (cols 0-6), QUARTER (col 7)
        #   Rows 1-4: FULL (cols 0-6), HALF_WIDTH (col 7)
        # Each tuple: (proj_id, name, owner, size, scenario, is_submitted, slot_pos)
        projects_data: list[tuple] = [
            # Full size projects (28 available in G801) - some assigned
            (
                "MP01",
                "MIPS Processor Core",
                mithro,
                SlotSize.FULL,
                "single_pass",
                True,
                (1, 0),
            ),
            (
                "AR01",
                "ARM Cortex-M0 Core",
                testuser,
                SlotSize.FULL,
                "single_pass",
                True,
                (1, 1),
            ),
            (
                "DM01",
                "DDR Memory Controller",
                mithro,
                SlotSize.FULL,
                "single_fail",
                True,
                None,
            ),
            (
                "ET01",
                "Ethernet MAC",
                testuser,
                SlotSize.FULL,
                "drc_update",
                True,
                (2, 0),
            ),
            (
                "CAN1",
                "CAN Bus Controller",
                mithro,
                SlotSize.FULL,
                "single_pass",
                False,
                None,
            ),
            (
                "FPU1",
                "FPU Accelerator",
                testuser,
                SlotSize.FULL,
                "error_retry",
                True,
                None,
            ),
            # Half-height projects (7 available in G801 row 0)
            (
                "SD01",
                "SD Card Controller",
                mithro,
                SlotSize.HALF_HEIGHT,
                "single_pass",
                True,
                (0, 0),
            ),
            (
                "NV01",
                "NVMe Controller",
                testuser,
                SlotSize.HALF_HEIGHT,
                "single_fail",
                False,
                None,
            ),
            (
                "WD01",
                "Watchdog Timer",
                mithro,
                SlotSize.HALF_HEIGHT,
                "in_progress",
                True,
                None,
            ),
            # Half-width projects (4 available in G801 col 7)
            (
                "US01",
                "USB 2.0 PHY",
                testuser,
                SlotSize.HALF_WIDTH,
                "single_pass",
                True,
                (1, 7),
            ),
            (
                "PC01",
                "PCIe PHY",
                mithro,
                SlotSize.HALF_WIDTH,
                "drc_update",
                False,
                None,
            ),
            # Quarter project (1 available in G801 row 0, col 7)
            (
                "TM01",
                "Temperature Sensor",
                testuser,
                SlotSize.QUARTER,
                "single_pass",
                True,
                (0, 7),
            ),
        ]

        created_count = 0
        assigned_count = 0
        for idx, proj_data in enumerate(projects_data):
            proj_id, name, owner, size, scenario, is_submitted, slot_pos = proj_data
            # Set status and submitted_at based on is_submitted flag
            if is_submitted:
                status = Project.Status.SUBMITTED
                submitted_at = timezone.now() - timedelta(days=idx + 1)
            else:
                status = Project.Status.DRAFT
                submitted_at = None

            project, created = Project.objects.get_or_create(
                project_id=proj_id,
                shuttle=shuttle,
                defaults={
                    "user": owner,
                    "name": name,
                    "description": f"G801 project: {name}",
                    "slot_size": size,
                    "status": status,
                    "submitted_at": submitted_at,
                },
            )

            if created:
                # Create compliance certification
                ProjectComplianceCertification.objects.create(
                    project=project,
                    export_control_compliant=True,
                    not_restricted_entity=True,
                    end_use_statement="G801 shuttle run",
                    certified_by=owner,
                )

                # Create file and checks based on scenario
                self._create_checks_for_project(project, scenario)
                created_count += 1

            # Assign project to slot if specified
            if slot_pos is not None:
                row, col = slot_pos
                assigned = self._assign_project_to_slot(shuttle, project, row, col)
                if assigned:
                    assigned_count += 1

        if created_count > 0:
            self.stdout.write(
                self.style.SUCCESS(f"  Created {created_count} G801 test projects")
            )
        else:
            self.stdout.write("  G801 test projects already exist")

        if assigned_count > 0:
            msg = f"  Assigned {assigned_count} projects to G801 slots"
            self.stdout.write(self.style.SUCCESS(msg))

    def _assign_project_to_slot(
        self, shuttle: Shuttle, project: Project, row: int, col: int
    ) -> bool:
        """Assign a project to a specific slot.

        Returns True if assignment was made, False if slot already occupied.
        """
        try:
            slot = ShuttleSlot.objects.get(shuttle=shuttle, row=row, column=col)
        except ShuttleSlot.DoesNotExist:
            self.stdout.write(
                self.style.WARNING(
                    f"  Slot ({row}, {col}) not found for {shuttle.name}"
                )
            )
            return False

        # Only assign if slot is available (not already occupied)
        if slot.project is not None:
            return False

        slot.project = project
        slot.status = ShuttleSlot.Status.OCCUPIED
        slot.save(update_fields=["project", "status"])
        return True

    def _create_download_attempts(
        self, project_file: ProjectFile, scenario: str
    ) -> None:
        """Create DownloadAttempts for a ProjectFile based on scenario."""
        now = timezone.now()

        if scenario == "single_success":
            # Single successful download
            DownloadAttempt.objects.create(
                project_file=project_file,
                attempt_number=1,
                status=DownloadAttempt.Status.COMPLETED,
                download_started_at=now - timedelta(hours=5, minutes=2),
                download_completed_at=now - timedelta(hours=5),
                download_duration_seconds=120.5,
                bytes_downloaded=project_file.file_size or 1024000,
                worker_hostname="celery-worker-1",
            )

        elif scenario == "retry_success":
            # First attempt failed, second succeeded
            DownloadAttempt.objects.create(
                project_file=project_file,
                attempt_number=1,
                status=DownloadAttempt.Status.FAILED,
                download_started_at=now - timedelta(hours=6),
                download_completed_at=now - timedelta(hours=6) + timedelta(seconds=30),
                download_error="Connection timeout after 30s - server unreachable",
                download_duration_seconds=30.0,
                bytes_downloaded=0,
                worker_hostname="celery-worker-1",
            )
            DownloadAttempt.objects.create(
                project_file=project_file,
                attempt_number=2,
                status=DownloadAttempt.Status.COMPLETED,
                download_started_at=now - timedelta(hours=5, minutes=5),
                download_completed_at=now - timedelta(hours=5),
                download_duration_seconds=300.0,
                bytes_downloaded=project_file.file_size or 2048000,
                worker_hostname="celery-worker-2",
            )

        elif scenario == "multiple_retries":
            # Multiple failed attempts then success
            start1 = now - timedelta(days=1, hours=2)
            DownloadAttempt.objects.create(
                project_file=project_file,
                attempt_number=1,
                status=DownloadAttempt.Status.FAILED,
                download_started_at=start1,
                download_completed_at=start1 + timedelta(seconds=10),
                download_error="HTTP 503 Service Unavailable",
                download_duration_seconds=10.0,
                bytes_downloaded=0,
                worker_hostname="celery-worker-1",
            )
            start2 = now - timedelta(days=1, hours=1)
            DownloadAttempt.objects.create(
                project_file=project_file,
                attempt_number=2,
                status=DownloadAttempt.Status.FAILED,
                download_started_at=start2,
                download_completed_at=start2 + timedelta(minutes=5),
                download_error="Hash mismatch: expected abc123, got def456",
                download_duration_seconds=300.0,
                bytes_downloaded=project_file.file_size or 1024000,
                worker_hostname="celery-worker-1",
            )
            DownloadAttempt.objects.create(
                project_file=project_file,
                attempt_number=3,
                status=DownloadAttempt.Status.COMPLETED,
                download_started_at=now - timedelta(hours=12),
                download_completed_at=now - timedelta(hours=12) + timedelta(minutes=3),
                download_duration_seconds=180.0,
                bytes_downloaded=project_file.file_size or 1024000,
                worker_hostname="celery-worker-2",
            )

        elif scenario == "in_progress":
            # Download currently in progress
            DownloadAttempt.objects.create(
                project_file=project_file,
                attempt_number=1,
                status=DownloadAttempt.Status.DOWNLOADING,
                download_started_at=now - timedelta(minutes=2),
                bytes_downloaded=int((project_file.file_size or 5000000) * 0.45),
                worker_hostname="celery-worker-1",
                worker_pid=12345,
            )

    def _create_checks_for_project(self, project: Project, scenario: str) -> None:
        """Create ProjectFile and ManufacturabilityChecks based on scenario."""
        if scenario == "no_file":
            # No file submitted yet
            return

        now = timezone.now()

        # Determine download and file scenarios based on check scenario
        download_scenario = "single_success"
        create_old_files = False

        if scenario == "drc_update":
            # Multiple files showing file revisions
            download_scenario = "retry_success"
            create_old_files = True
        elif scenario == "error_retry":
            download_scenario = "multiple_retries"
        elif scenario == "in_progress":
            download_scenario = "in_progress"

        # Create old/inactive files for some scenarios (file revision history)
        if create_old_files:
            # Old file v1 - superseded, had a passing check
            old_file_1 = ProjectFile.objects.create(
                project=project,
                original_url=f"https://example.com/files/{project.project_id}_v1.gds",
                source_url=f"https://example.com/files/{project.project_id}_v1.gds",
                original_filename=f"{project.project_id}_v1.gds",
                processed_filename=f"{project.project_id}_v1.gds",
                is_active=False,
                hash_verified=True,
                file_size=980000,
                hash_sha256="a" * 64,
                top_cell=f"{project.project_id}_top",
                content_type="application/octet-stream",
                download_completed_at=now - timedelta(days=14, hours=2),
            )
            self._create_download_attempts(old_file_1, "single_success")
            # v1 had a passing check but was superseded by v2
            v1_check = ManufacturabilityCheck.objects.create(
                project=project,
                project_file=old_file_1,
                status=ManufacturabilityCheck.Status.FINISHED,
                trigger_reason=ManufacturabilityCheck.TriggerReason.INITIAL,
                is_manufacturable=True,
                errors=[],
                warnings=[],
                analysis_completed_at=now - timedelta(days=14),
            )
            ManufacturabilityCheck.objects.filter(pk=v1_check.pk).update(
                created_at=now - timedelta(days=14, hours=1)
            )

            # Old file v2 - had download issues, then failed DRC check
            old_file_2 = ProjectFile.objects.create(
                project=project,
                original_url=f"https://example.com/files/{project.project_id}_v2.gds",
                source_url=f"https://example.com/files/{project.project_id}_v2.gds",
                original_filename=f"{project.project_id}_v2.gds",
                processed_filename=f"{project.project_id}_v2.gds",
                is_active=False,
                hash_verified=True,
                file_size=1050000,
                hash_sha256="b" * 64,
                top_cell=f"{project.project_id}_top",
                content_type="application/octet-stream",
                download_completed_at=now - timedelta(days=10, hours=2),
            )
            self._create_download_attempts(old_file_2, "retry_success")
            # v2 failed manufacturability - that's why v3 was submitted
            v2_check = ManufacturabilityCheck.objects.create(
                project=project,
                project_file=old_file_2,
                status=ManufacturabilityCheck.Status.FINISHED,
                trigger_reason=ManufacturabilityCheck.TriggerReason.INITIAL,
                is_manufacturable=False,
                errors=["DRC violation: Metal density too low in region (500, 500)"],
                warnings=["Consider adding dummy fill"],
                analysis_completed_at=now - timedelta(days=10),
            )
            ManufacturabilityCheck.objects.filter(pk=v2_check.pk).update(
                created_at=now - timedelta(days=10, hours=1)
            )

        # Create the active project file
        # hash_verified=False if still downloading
        is_downloading = scenario == "in_progress"
        file_kwargs: dict[str, Any] = {
            "project": project,
            "original_url": f"https://example.com/files/{project.project_id}.gds",
            "source_url": f"https://example.com/files/{project.project_id}.gds",
            "original_filename": f"{project.project_id}.gds",
            "is_active": True,
            "content_type": "application/octet-stream",
        }
        if is_downloading:
            file_kwargs["file_size"] = 5000000
            file_kwargs["hash_verified"] = False
        else:
            file_kwargs["processed_filename"] = f"{project.project_id}.gds"
            file_kwargs["file_size"] = 1024000
            file_kwargs["hash_verified"] = True
            file_kwargs["hash_sha256"] = "c" * 64
            file_kwargs["top_cell"] = f"{project.project_id}_top"
            file_kwargs["download_completed_at"] = now - timedelta(hours=3)
        project_file = ProjectFile.objects.create(**file_kwargs)
        self._create_download_attempts(project_file, download_scenario)

        project.submitted_file = project_file
        project.save(update_fields=["submitted_file"])

        # Create manufacturability checks based on scenario
        self._create_manufacturability_checks(project, project_file, scenario, now)

    def _create_output_files(self, project_id: str) -> None:
        """Create empty placeholder output files for a manufacturability check."""
        media_root = Path(settings.MEDIA_ROOT)
        check_dir = media_root / "projects" / project_id / "checks"
        check_dir.mkdir(parents=True, exist_ok=True)

        # Create empty placeholder files
        for filename in ["precheck.log", "runs.tar.gz", "output.gds", "layer.tar.gz"]:
            (check_dir / filename).touch()

    def _create_checkpoints(self, check: ManufacturabilityCheck) -> None:
        """Create resource usage checkpoints for a manufacturability check."""
        # Simulate 10 minutes of check runtime with checkpoints every 30 seconds
        for i in range(20):
            elapsed = i * 30.0  # 30 second intervals
            # Simulate varying CPU/memory usage
            cpu = 25.0 + (i % 5) * 15.0  # Varies 25-85%
            mem_mb = 512 + (i * 50)  # Grows from 512MB to ~1.5GB
            ManufacturabilityCheckpoint.objects.create(
                manufacturability_check=check,
                checkpoint_number=i + 1,
                elapsed_seconds=elapsed,
                cpu_percent=cpu,
                cpu_online_cpus=4,
                memory_usage_bytes=mem_mb * 1024 * 1024,
                memory_limit_bytes=4 * 1024 * 1024 * 1024,  # 4GB limit
            )

    def _finished_check_fields(
        self,
        completed_at: Any,
        project_id: str = "XX01",
        precheck_version: str = "1.5.3",
    ) -> dict:
        """Return common fields for a finished check.

        Args:
            completed_at: When the check completed
            project_id: Project ID for output file paths
            precheck_version: Precheck version to use (default: latest 1.5.3)
        """
        # Create output files on disk
        self._create_output_files(project_id)

        # Get version info from PRECHECK_VERSIONS
        pdk_version = "1.6.5"
        for v, _, _, pdk in self.PRECHECK_VERSIONS:
            if v == precheck_version:
                pdk_version = pdk
                break

        digest = self._get_precheck_digest(precheck_version)

        return {
            "docker_server_id": "docker-server-1",
            "docker_container_id": "abc123def456789012345678901234567890abcd",
            "docker_exit_code": 0,
            "docker_image": f"ghcr.io/wafer-space/gf180mcu-precheck:{precheck_version}",
            "docker_image_digest": digest,
            "precheck_version": precheck_version,
            "tool_versions": {
                "magic": "8.3.460",
                "klayout": "0.28.17",
                "netgen": "1.5.272",
                "pdk": pdk_version,
            },
            "dispatching_started_at": completed_at - timedelta(minutes=12),
            "starting_started_at": completed_at - timedelta(minutes=11),
            "container_started_at": completed_at - timedelta(minutes=10),
            "container_finished_at": completed_at - timedelta(seconds=30),
            "last_activity": completed_at,
            "processing_logs": (
                "[INFO] Starting manufacturability check...\n"
                "[INFO] Running DRC checks...\n"
                "[INFO] Running LVS checks...\n"
                "[INFO] Analysis complete.\n"
            ),
            "docker_command": (
                "docker run --rm -v /data/projects:/workspace "
                "ghcr.io/wafer-space/gf180mcu-precheck:latest "
                "--design /workspace/design.gds --pdk gf180mcuD"
            ),
            # Output files created by _create_output_files method
            "log_file": f"projects/{project_id}/checks/precheck.log",
            "runs_archive": f"projects/{project_id}/checks/runs.tar.gz",
            "output_gds": f"projects/{project_id}/checks/output.gds",
            "docker_layer_export": f"projects/{project_id}/checks/layer.tar.gz",
            "log_file_sha256": (
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            ),
            "runs_archive_sha256": (
                "27ae41e4649b934ca495991b7852b855d41d8cd98f00b204e9800998ecf8427e"
            ),
            "output_gds_sha256": (
                "d41d8cd98f00b204e9800998ecf8427e098f6bcd4621d373cade4e832627b4f6"
            ),
            "docker_layer_sha256": (
                "098f6bcd4621d373cade4e832627b4f6e3b0c44298fc1c149afbf4c8996fb924"
            ),
        }

    def _create_manufacturability_checks(
        self,
        project: Project,
        project_file: ProjectFile,
        scenario: str,
        now: Any,
    ) -> None:
        """Create ManufacturabilityChecks based on scenario."""
        if scenario == "single_pass":
            # Recent check with latest version
            completed = now - timedelta(minutes=30)
            check = ManufacturabilityCheck.objects.create(
                project=project,
                project_file=project_file,
                status=ManufacturabilityCheck.Status.FINISHED,
                trigger_reason=ManufacturabilityCheck.TriggerReason.INITIAL,
                is_manufacturable=True,
                errors=[],
                warnings=["Minor: Consider adding ESD protection"],
                analysis_completed_at=completed,
                **self._finished_check_fields(
                    completed, project.project_id, precheck_version="1.5.3"
                ),
            )
            self._create_checkpoints(check)

        elif scenario == "single_fail":
            # Failed check with older version
            completed = now - timedelta(hours=4)
            check = ManufacturabilityCheck.objects.create(
                project=project,
                project_file=project_file,
                status=ManufacturabilityCheck.Status.FINISHED,
                trigger_reason=ManufacturabilityCheck.TriggerReason.INITIAL,
                is_manufacturable=False,
                errors=[
                    "DRC violation: Metal spacing too narrow at (100, 200)",
                    "DRC violation: Via enclosure insufficient at (150, 300)",
                ],
                warnings=[],
                analysis_completed_at=completed,
                **self._finished_check_fields(
                    completed, project.project_id, precheck_version="1.5.1"
                ),
            )
            self._create_checkpoints(check)

        elif scenario == "in_progress":
            started = now - timedelta(minutes=5)
            ManufacturabilityCheck.objects.create(
                project=project,
                project_file=project_file,
                status=ManufacturabilityCheck.Status.RUNNING,
                trigger_reason=ManufacturabilityCheck.TriggerReason.INITIAL,
                docker_server_id="docker-server-1",
                docker_container_id="running123456789012345678901234567890ab",
                docker_image="ghcr.io/wafer-space/gf180mcu-precheck:latest",
                dispatching_started_at=started - timedelta(minutes=2),
                starting_started_at=started - timedelta(minutes=1),
                container_started_at=started,
                last_activity=now - timedelta(seconds=10),
                processing_logs="[INFO] Starting manufacturability check...\n",
            )

        elif scenario == "error_retry":
            self._create_error_retry_checks(project, project_file, now)

        elif scenario == "drc_update":
            self._create_drc_update_checks(project, project_file, now)

        elif scenario == "real_digest":
            # Check with real GHCR digest to test revision fetching
            self._create_real_digest_check(project, project_file, now)

    def _create_error_retry_checks(
        self, project: Project, project_file: ProjectFile, now: Any
    ) -> None:
        """Create error + retry check scenario."""
        error_time = now - timedelta(hours=3)
        original_check = ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            trigger_reason=ManufacturabilityCheck.TriggerReason.INITIAL,
            error_message="Docker container timeout after 300s",
            docker_server_id="docker-server-1",
            docker_container_id="timeout12345678901234567890123456789012",
            docker_image="ghcr.io/wafer-space/gf180mcu-precheck:latest",
            docker_exit_code=137,  # SIGKILL from timeout
            dispatching_started_at=error_time - timedelta(minutes=7),
            starting_started_at=error_time - timedelta(minutes=6),
            container_started_at=error_time - timedelta(minutes=5),
            last_activity=error_time,
            processing_logs=(
                "[INFO] Starting manufacturability check...\n"
                "[INFO] Running DRC checks...\n"
                "[ERROR] Container killed after 300s timeout\n"
            ),
        )
        ManufacturabilityCheck.objects.filter(pk=original_check.pk).update(
            created_at=error_time - timedelta(minutes=10)
        )

        # Retry succeeded with version 1.5.2
        completed = now - timedelta(hours=2)
        retry_check = ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            trigger_reason=ManufacturabilityCheck.TriggerReason.RETRY,
            parent_check=original_check,
            is_manufacturable=True,
            errors=[],
            warnings=[],
            analysis_completed_at=completed,
            **self._finished_check_fields(
                completed, project.project_id, precheck_version="1.5.2"
            ),
        )
        self._create_checkpoints(retry_check)

    def _create_drc_update_checks(
        self, project: Project, project_file: ProjectFile, now: Any
    ) -> None:
        """Create DRC update multi-check scenario showing version progression."""
        # First check - passed with old version 1.4.5
        completed1 = now - timedelta(days=7)
        first_check = ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            trigger_reason=ManufacturabilityCheck.TriggerReason.INITIAL,
            is_manufacturable=True,
            errors=[],
            warnings=[],
            analysis_completed_at=completed1,
            **self._finished_check_fields(
                completed1, project.project_id, precheck_version="1.4.5"
            ),
        )
        ManufacturabilityCheck.objects.filter(pk=first_check.pk).update(
            created_at=completed1 - timedelta(minutes=15)
        )
        self._create_checkpoints(first_check)

        # Second check - DRC rules updated in 1.5.0, now fails
        completed2 = now - timedelta(days=3)
        second_check = ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            trigger_reason=ManufacturabilityCheck.TriggerReason.DRC_UPDATE,
            is_manufacturable=False,
            errors=["New DRC rule violation: Minimum poly width"],
            warnings=[],
            analysis_completed_at=completed2,
            **self._finished_check_fields(
                completed2, project.project_id, precheck_version="1.5.0"
            ),
        )
        ManufacturabilityCheck.objects.filter(pk=second_check.pk).update(
            created_at=completed2 - timedelta(minutes=15)
        )
        self._create_checkpoints(second_check)

        # Third check - admin re-run with latest version 1.5.3
        completed3 = now - timedelta(hours=12)
        third_check = ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            trigger_reason=ManufacturabilityCheck.TriggerReason.ADMIN_RERUN,
            is_manufacturable=True,
            errors=[],
            warnings=[],
            analysis_completed_at=completed3,
            **self._finished_check_fields(
                completed3, project.project_id, precheck_version="1.5.3"
            ),
        )
        self._create_checkpoints(third_check)

    def _create_real_digest_check(
        self, project: Project, project_file: ProjectFile, now: Any
    ) -> None:
        """Create a check with a real GHCR digest to test revision fetching.

        Uses REAL_GHCR_DIGEST which is NOT pre-populated in PrecheckImageRevision,
        so revisions_needs_fetching will discover it and queue a fetch task.
        """
        completed = now - timedelta(hours=1)

        # Get base fields but override the digest with the real one
        fields = self._finished_check_fields(
            completed, project.project_id, precheck_version="1.5.3"
        )
        # Override with real digest that needs fetching
        fields["docker_image_digest"] = self.REAL_GHCR_DIGEST
        # Clear version info since it will be fetched
        fields["precheck_version"] = ""

        check = ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            trigger_reason=ManufacturabilityCheck.TriggerReason.INITIAL,
            is_manufacturable=True,
            errors=[],
            warnings=["Test check for revision fetching"],
            analysis_completed_at=completed,
            **fields,
        )
        self._create_checkpoints(check)
