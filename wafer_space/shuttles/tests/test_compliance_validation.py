"""Tests for compliance certification validation in shuttle assignment."""

import pytest

from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectComplianceCertification
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.users.models import User

TEST_PASSWORD = "testpass123"  # noqa: S105 - Test password constant


@pytest.mark.django_db
class TestShuttleReserveComplianceValidation:
    """Test compliance certification validation in ShuttleSlot.reserve()."""

    def test_reserve_requires_compliance_certification(self):
        """Test that reserve() fails if project has no compliance certification."""
        # Arrange: Create shuttle slot and project WITHOUT compliance cert
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        shuttle = Shuttle.objects.create(
            name="G831",
            description="Test Shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=10,
            available_slots=10,
        )
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            slot_number=1,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        project = Project.objects.create(
            user=user,
            name="Test Project",
            description="Test project description",
        )

        # Act & Assert: reserve() should raise ValueError
        expected_msg = (
            "Project must have compliance certification before shuttle assignment"
        )
        with pytest.raises(ValueError, match=expected_msg):
            slot.reserve(project=project, user=user)

        # Verify: Project was not assigned
        slot.refresh_from_db()
        assert slot.project is None

    def test_reserve_requires_complete_attestations(self):
        """Test that reserve() fails if compliance attestations are incomplete."""
        # Arrange: Create project with incomplete compliance (missing attestation)
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        shuttle = Shuttle.objects.create(
            name="G832",
            description="Test Shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=10,
            available_slots=10,
        )
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            slot_number=1,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        project = Project.objects.create(
            user=user,
            name="Test Project",
            description="Test project description",
        )
        ProjectComplianceCertification.objects.create(
            project=project,
            certified_by=user,
            export_control_compliant=True,
            not_restricted_entity=False,  # Incomplete!
            end_use_statement="Valid statement",
            ip_address="192.168.1.1",
            user_agent="Test Browser",
        )

        # Act & Assert: reserve() should raise ValueError
        expected_msg = "Compliance certification is incomplete"
        with pytest.raises(ValueError, match=expected_msg):
            slot.reserve(project=project, user=user)

        # Verify: Project was not assigned
        slot.refresh_from_db()
        assert slot.project is None

    def test_reserve_requires_end_use_statement(self):
        """Test that reserve() fails if end-use statement is missing."""
        # Arrange: Create project with empty end-use statement
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        shuttle = Shuttle.objects.create(
            name="G833",
            description="Test Shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=10,
            available_slots=10,
        )
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            slot_number=1,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        project = Project.objects.create(
            user=user,
            name="Test Project",
            description="Test project description",
        )
        ProjectComplianceCertification.objects.create(
            project=project,
            certified_by=user,
            export_control_compliant=True,
            not_restricted_entity=True,
            end_use_statement="   ",  # Empty (whitespace only)!
            ip_address="192.168.1.1",
            user_agent="Test Browser",
        )

        # Act & Assert: reserve() should raise ValueError
        expected_msg = "End-use statement is required"
        with pytest.raises(ValueError, match=expected_msg):
            slot.reserve(project=project, user=user)

        # Verify: Project was not assigned
        slot.refresh_from_db()
        assert slot.project is None

    def test_reserve_succeeds_with_valid_compliance(self):
        """Test that reserve() succeeds when compliance is valid."""
        # Arrange: Create project with valid compliance certification
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        shuttle = Shuttle.objects.create(
            name="G834",
            description="Test Shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=10,
            available_slots=10,
        )
        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            slot_number=1,
            status=ShuttleSlot.Status.AVAILABLE,
        )
        project = Project.objects.create(
            user=user,
            name="Test Project",
            description="Test project description",
        )
        ProjectComplianceCertification.objects.create(
            project=project,
            certified_by=user,
            export_control_compliant=True,
            not_restricted_entity=True,
            end_use_statement="Building a prototype for educational research",
            ip_address="192.168.1.1",
            user_agent="Test Browser",
        )

        # Act: Reserve the slot
        slot.reserve(project=project, user=user)

        # Assert: Project was assigned successfully
        slot.refresh_from_db()
        assert slot.project == project
