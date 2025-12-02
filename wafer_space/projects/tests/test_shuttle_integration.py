"""Tests for Project shuttle integration properties and methods."""

import pytest
from django.db import IntegrityError
from django.test import TestCase

from wafer_space.projects.models import PROJECT_ID_LENGTH
from wafer_space.projects.models import Project
from wafer_space.shuttles.models import SHUTTLE_ID_LENGTH
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.users.models import User

from .constants import TEST_PASSWORD


@pytest.mark.django_db
class TestProjectShuttleProperties(TestCase):
    """Test Project properties related to shuttle integration."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.shuttle = Shuttle.objects.create(
            name="G801",
            description="Test Shuttle Run",
            status=Shuttle.Status.OPEN,
            max_slots=10,
            available_slots=10,
        )

    def test_full_id_with_shuttle_and_project_id(self):
        """Test full_id property returns 8-character manufacturing ID."""
        project = Project.objects.create(
            user=self.user,
            name="Test Project",
            shuttle=self.shuttle,
            project_id="ABCD",
        )
        assert project.full_id == "G801ABCD"
        assert len(project.full_id) == SHUTTLE_ID_LENGTH + PROJECT_ID_LENGTH

    def test_full_id_without_shuttle_returns_empty(self):
        """Test full_id returns empty string when shuttle is None."""
        project = Project.objects.create(
            user=self.user,
            name="Test Project",
            project_id="ABCD",
        )
        assert project.full_id == ""

    def test_full_id_without_project_id_returns_empty(self):
        """Test full_id returns empty string when project_id is empty."""
        project = Project.objects.create(
            user=self.user,
            name="Test Project",
            shuttle=self.shuttle,
            project_id="",
        )
        assert project.full_id == ""

    def test_full_id_without_both_returns_empty(self):
        """Test full_id returns empty string when both are None/empty."""
        project = Project.objects.create(
            user=self.user,
            name="Test Project",
        )
        assert project.full_id == ""

    def test_shuttle_run_display_with_shuttle(self):
        """Test shuttle_run_display property returns formatted string."""
        project = Project.objects.create(
            user=self.user,
            name="Test Project",
            shuttle=self.shuttle,
            project_id="ABCD",
        )
        expected = "Test Shuttle Run: G801"
        assert project.shuttle_run_display == expected

    def test_shuttle_run_display_without_shuttle(self):
        """Test shuttle_run_display returns empty string when no shuttle."""
        project = Project.objects.create(
            user=self.user,
            name="Test Project",
        )
        assert project.shuttle_run_display == ""

    def test_shuttle_positions_returns_queryset(self):
        """Test shuttle_positions property returns related shuttle slots."""
        project = Project.objects.create(
            user=self.user,
            name="Test Project",
            shuttle=self.shuttle,
            project_id="ABCD",
        )

        # Create some shuttle slots for this project
        slot1 = ShuttleSlot.objects.create(
            shuttle=self.shuttle,
            slot_number=1,
            project=project,
            status=ShuttleSlot.Status.RESERVED,
        )
        slot2 = ShuttleSlot.objects.create(
            shuttle=self.shuttle,
            slot_number=2,
            project=project,
            status=ShuttleSlot.Status.RESERVED,
        )

        # Get shuttle positions
        positions = project.shuttle_positions
        expected_slot_count = 2  # We created slot1 and slot2
        assert positions.count() == expected_slot_count
        assert slot1 in positions
        assert slot2 in positions

    def test_shuttle_positions_empty_when_no_slots(self):
        """Test shuttle_positions returns empty queryset when no slots."""
        project = Project.objects.create(
            user=self.user,
            name="Test Project",
            shuttle=self.shuttle,
            project_id="ABCD",
        )
        positions = project.shuttle_positions
        assert positions.count() == 0

    def test_unique_constraint_on_shuttle_and_project_id(self):
        """Test that (shuttle, project_id) must be unique."""
        # Create first project
        Project.objects.create(
            user=self.user,
            name="First Project",
            shuttle=self.shuttle,
            project_id="TEST",
        )

        # Try to create second project with same shuttle and project_id
        with pytest.raises(IntegrityError):
            Project.objects.create(
                user=self.user,
                name="Second Project",
                shuttle=self.shuttle,
                project_id="TEST",
            )

    def test_same_project_id_allowed_in_different_shuttles(self):
        """Test that same project_id can be used in different shuttles."""
        shuttle2 = Shuttle.objects.create(
            name="G802",
            description="Another Shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=10,
            available_slots=10,
        )

        # Create projects with same project_id in different shuttles
        project1 = Project.objects.create(
            user=self.user,
            name="Project in G801",
            shuttle=self.shuttle,
            project_id="TEST",
        )
        project2 = Project.objects.create(
            user=self.user,
            name="Project in G802",
            shuttle=shuttle2,
            project_id="TEST",
        )

        # Both should succeed
        assert project1.full_id == "G801TEST"
        assert project2.full_id == "G802TEST"
