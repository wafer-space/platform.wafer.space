"""Tests for AJAX endpoint views."""

import json

import pytest
from django.test import Client
from django.test import TestCase
from django.urls import reverse

from wafer_space.core.enums import SlotSize
from wafer_space.projects.models import Project
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.models import User

from .constants import HTTP_BAD_REQUEST
from .constants import HTTP_NOT_FOUND
from .constants import HTTP_OK
from .constants import HTTP_UNAUTHORIZED
from .constants import TEST_PASSWORD


@pytest.mark.django_db
class TestProjectIDCheckView(TestCase):
    """Test ProjectIDCheckView AJAX endpoint."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.shuttle = Shuttle.objects.create(
            name="G800",
            description="Test Shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=10,
            available_slots=10,
        )
        self.url = reverse("projects:check_project_id")

    def test_requires_authentication(self):
        """Test that endpoint requires authentication."""
        response = self.client.get(self.url)
        # Should redirect to login (302) not 401 because of LoginRequiredMixin
        assert response.status_code in (HTTP_UNAUTHORIZED, 302)

    def test_available_project_id(self):
        """Test checking an available project ID."""
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(
            self.url,
            {"shuttle": str(self.shuttle.pk), "project_id": "ABCD"},
        )

        assert response.status_code == HTTP_OK
        data = json.loads(response.content)
        assert data["available"] is True
        assert "available" in data["message"].lower()

    def test_taken_project_id(self):
        """Test checking a project ID that's already taken."""
        # Create project with ID "ABCD"
        Project.objects.create(
            user=self.user,
            name="Existing Project",
            shuttle=self.shuttle,
            project_id="ABCD",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(
            self.url,
            {"shuttle": str(self.shuttle.pk), "project_id": "ABCD"},
        )

        assert response.status_code == HTTP_OK
        data = json.loads(response.content)
        assert data["available"] is False
        assert "taken" in data["message"].lower()

    def test_lowercase_project_id_rejected(self):
        """Test that lowercase project IDs are rejected with validation error."""
        self.client.login(username="testuser", password=TEST_PASSWORD)

        # Query with lowercase - view requires uppercase input
        response = self.client.get(
            self.url,
            {"shuttle": str(self.shuttle.pk), "project_id": "abcd"},
        )

        assert response.status_code == HTTP_OK
        data = json.loads(response.content)
        assert data["available"] is False
        # Rejected due to uppercase requirement, not duplicate detection
        assert "uppercase" in data["message"].lower()

    def test_missing_shuttle_parameter(self):
        """Test error when shuttle parameter is missing."""
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(self.url, {"project_id": "ABCD"})

        assert response.status_code == HTTP_BAD_REQUEST
        data = json.loads(response.content)
        assert data["available"] is False
        assert "missing" in data["message"].lower()

    def test_missing_project_id_parameter(self):
        """Test error when project_id parameter is missing."""
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(self.url, {"shuttle": str(self.shuttle.pk)})

        assert response.status_code == HTTP_BAD_REQUEST
        data = json.loads(response.content)
        assert data["available"] is False
        assert "missing" in data["message"].lower()

    def test_invalid_project_id_length(self):
        """Test validation of project ID length."""
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(
            self.url,
            {"shuttle": str(self.shuttle.pk), "project_id": "ABC"},
        )

        assert response.status_code == HTTP_OK
        data = json.loads(response.content)
        assert data["available"] is False
        assert "4 characters" in data["message"]

    def test_invalid_project_id_non_alphanumeric(self):
        """Test validation of project ID alphanumeric requirement."""
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(
            self.url,
            {"shuttle": str(self.shuttle.pk), "project_id": "AB-D"},
        )

        assert response.status_code == HTTP_OK
        data = json.loads(response.content)
        assert data["available"] is False
        assert "alphanumeric" in data["message"].lower()

    def test_same_id_available_in_different_shuttle(self):
        """Test that same project_id is available in different shuttle."""
        shuttle2 = Shuttle.objects.create(
            name="G801",
            description="Another Shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=10,
            available_slots=10,
        )

        # Use ABCD in first shuttle
        Project.objects.create(
            user=self.user,
            name="Project in G800",
            shuttle=self.shuttle,
            project_id="ABCD",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)

        # Check if ABCD is available in second shuttle
        response = self.client.get(
            self.url,
            {"shuttle": str(shuttle2.pk), "project_id": "ABCD"},
        )

        assert response.status_code == HTTP_OK
        data = json.loads(response.content)
        assert data["available"] is True

    def test_invalid_shuttle_id(self):
        """Test that invalid shuttle ID returns 400 error."""
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(
            self.url,
            {"shuttle": "99999", "project_id": "ABCD"},
        )

        assert response.status_code == HTTP_BAD_REQUEST
        data = json.loads(response.content)
        assert data["available"] is False
        assert "invalid" in data["message"].lower()


@pytest.mark.django_db
class TestShuttleAvailableSizesView(TestCase):
    """Test ShuttleAvailableSizesView AJAX endpoint."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.shuttle = Shuttle.objects.create(
            name="G800",
            description="Test Shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=10,
            available_slots=10,
        )
        self.url = reverse("projects:shuttle_available_sizes")

    def test_requires_authentication(self):
        """Test that endpoint requires authentication."""
        response = self.client.get(self.url)
        # Should redirect to login (302) not 401 because of LoginRequiredMixin
        assert response.status_code in (HTTP_UNAUTHORIZED, 302)

    def test_returns_all_slot_sizes(self):
        """Test that endpoint returns all available slot sizes for Phase A."""
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(self.url, {"shuttle": self.shuttle.pk})

        assert response.status_code == HTTP_OK
        data = json.loads(response.content)
        assert "sizes" in data
        assert len(data["sizes"]) == len(SlotSize.choices)

        # Verify all slot sizes are present
        size_values = [size["value"] for size in data["sizes"]]
        assert SlotSize.FULL in size_values
        assert SlotSize.HALF_WIDTH in size_values
        assert SlotSize.HALF_HEIGHT in size_values
        assert SlotSize.QUARTER in size_values

    def test_size_objects_have_correct_format(self):
        """Test that each size object has value and label."""
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(self.url, {"shuttle": self.shuttle.pk})

        assert response.status_code == HTTP_OK
        data = json.loads(response.content)

        for size in data["sizes"]:
            assert "value" in size
            assert "label" in size
            assert isinstance(size["value"], str)
            assert isinstance(size["label"], str)
            assert len(size["label"]) > 0

    def test_missing_shuttle_parameter(self):
        """Test that missing shuttle parameter returns empty list."""
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(self.url)

        assert response.status_code == HTTP_OK
        data = json.loads(response.content)
        assert data["sizes"] == []

    def test_invalid_shuttle_id(self):
        """Test that invalid shuttle ID returns 404."""
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(self.url, {"shuttle": 99999})

        assert response.status_code == HTTP_NOT_FOUND
        data = json.loads(response.content)
        assert data["sizes"] == []
