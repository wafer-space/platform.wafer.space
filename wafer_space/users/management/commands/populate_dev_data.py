"""Management command to populate database with development/test data."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any

from allauth.account.models import EmailAddress
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
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectComplianceCertification
from wafer_space.projects.models import ProjectFile
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
        """Create test projects with various states and manufacturability checks.

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
        projects_data = [
            # Full size projects
            ("RV32", "RISC-V Core", mithro, SlotSize.FULL, "single_pass"),
            ("GP10", "GPIO Controller", mithro, SlotSize.FULL, "drc_update"),
            ("UA01", "UART Serial", testuser, SlotSize.FULL, "single_pass"),
            ("SP01", "SPI Controller", testuser, SlotSize.FULL, "single_fail"),
            ("I2C1", "I2C Interface", mithro, SlotSize.FULL, "in_progress"),
            ("PW01", "PWM Generator", testuser, SlotSize.FULL, "no_file"),
            # Half width projects
            ("AD01", "ADC Frontend", mithro, SlotSize.HALF_WIDTH, "error_retry"),
            ("DA01", "DAC Output", testuser, SlotSize.HALF_WIDTH, "single_pass"),
            ("CM01", "Comparator", mithro, SlotSize.HALF_WIDTH, "single_fail"),
            # Half height projects
            ("CK01", "Clock Generator", testuser, SlotSize.HALF_HEIGHT, "single_pass"),
            ("RS01", "Reset Controller", mithro, SlotSize.HALF_HEIGHT, "in_progress"),
            # Quarter size projects
            ("RF01", "Voltage Reference", testuser, SlotSize.QUARTER, "single_pass"),
            ("OS01", "RC Oscillator", mithro, SlotSize.QUARTER, "drc_update"),
            ("BF01", "Buffer Cell", testuser, SlotSize.QUARTER, "single_fail"),
            ("LD01", "LDO Regulator", mithro, SlotSize.QUARTER, "no_file"),
        ]

        created_count = 0
        for proj_id, name, owner, size, check_scenario in projects_data:
            project, created = Project.objects.get_or_create(
                project_id=proj_id,
                shuttle=shuttle,
                defaults={
                    "user": owner,
                    "name": name,
                    "description": f"Test project: {name}",
                    "slot_size": size,
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

                # Create file and checks based on scenario
                self._create_checks_for_project(project, check_scenario)
                created_count += 1

        if created_count > 0:
            self.stdout.write(
                self.style.SUCCESS(f"  Created {created_count} test projects")
            )
        else:
            self.stdout.write("  Test projects already exist")

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
                is_active=False,
                hash_verified=True,
                file_size=980000,
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
                is_active=False,
                hash_verified=True,
                file_size=1050000,
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
        project_file = ProjectFile.objects.create(
            project=project,
            original_url=f"https://example.com/files/{project.project_id}.gds",
            is_active=True,
            hash_verified=not is_downloading,
            file_size=5000000 if is_downloading else 1024000,
        )
        self._create_download_attempts(project_file, download_scenario)

        project.submitted_file = project_file
        project.save(update_fields=["submitted_file"])

        # Create manufacturability checks based on scenario
        self._create_manufacturability_checks(project, project_file, scenario, now)

    def _create_manufacturability_checks(
        self,
        project: Project,
        project_file: ProjectFile,
        scenario: str,
        now: Any,
    ) -> None:
        """Create ManufacturabilityChecks based on scenario."""
        if scenario == "single_pass":
            ManufacturabilityCheck.objects.create(
                project=project,
                project_file=project_file,
                status=ManufacturabilityCheck.Status.FINISHED,
                trigger_reason=ManufacturabilityCheck.TriggerReason.INITIAL,
                is_manufacturable=True,
                errors=[],
                warnings=["Minor: Consider adding ESD protection"],
                analysis_completed_at=now - timedelta(hours=2),
            )

        elif scenario == "single_fail":
            ManufacturabilityCheck.objects.create(
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
                analysis_completed_at=now - timedelta(hours=1),
            )

        elif scenario == "in_progress":
            ManufacturabilityCheck.objects.create(
                project=project,
                project_file=project_file,
                status=ManufacturabilityCheck.Status.RUNNING,
                trigger_reason=ManufacturabilityCheck.TriggerReason.INITIAL,
                container_started_at=now - timedelta(minutes=5),
            )

        elif scenario == "error_retry":
            self._create_error_retry_checks(project, project_file, now)

        elif scenario == "drc_update":
            self._create_drc_update_checks(project, project_file, now)

    def _create_error_retry_checks(
        self, project: Project, project_file: ProjectFile, now: Any
    ) -> None:
        """Create error + retry check scenario."""
        original_check = ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            trigger_reason=ManufacturabilityCheck.TriggerReason.INITIAL,
            error_message="Docker container timeout after 300s",
            created_at=now - timedelta(hours=3),
        )
        ManufacturabilityCheck.objects.filter(pk=original_check.pk).update(
            created_at=now - timedelta(hours=3)
        )

        ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            trigger_reason=ManufacturabilityCheck.TriggerReason.RETRY,
            parent_check=original_check,
            is_manufacturable=True,
            errors=[],
            warnings=[],
            analysis_completed_at=now - timedelta(hours=2),
        )

    def _create_drc_update_checks(
        self, project: Project, project_file: ProjectFile, now: Any
    ) -> None:
        """Create DRC update multi-check scenario."""
        first_check = ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            trigger_reason=ManufacturabilityCheck.TriggerReason.INITIAL,
            is_manufacturable=True,
            errors=[],
            warnings=[],
            analysis_completed_at=now - timedelta(days=7),
        )
        ManufacturabilityCheck.objects.filter(pk=first_check.pk).update(
            created_at=now - timedelta(days=7, hours=1)
        )

        second_check = ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            trigger_reason=ManufacturabilityCheck.TriggerReason.DRC_UPDATE,
            is_manufacturable=False,
            errors=["New DRC rule violation: Minimum poly width"],
            warnings=[],
            analysis_completed_at=now - timedelta(days=3),
        )
        ManufacturabilityCheck.objects.filter(pk=second_check.pk).update(
            created_at=now - timedelta(days=3, hours=1)
        )

        ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            trigger_reason=ManufacturabilityCheck.TriggerReason.ADMIN_RERUN,
            is_manufacturable=True,
            errors=[],
            warnings=[],
            analysis_completed_at=now - timedelta(hours=12),
        )
