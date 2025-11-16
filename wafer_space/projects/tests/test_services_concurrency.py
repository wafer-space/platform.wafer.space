"""Tests for manufacturability service concurrency controls."""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.services import ManufacturabilityService

from .constants import TEST_PASSWORD

User = get_user_model()


@pytest.mark.django_db
class TestPerUserConcurrency:
    """Test per-user concurrency limits."""

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_allows_first_check(self, mock_delay, user):
        """Test that first check is allowed."""
        mock_delay.return_value.id = "test-task-id"
        project = Project.objects.create(user=user, name="project1")

        check = ManufacturabilityService.queue_check(project)

        assert check.status == ManufacturabilityCheck.Status.QUEUED

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_blocks_second_check_same_user(self, mock_delay, user):
        """Test that second check is blocked for same user."""
        mock_delay.return_value.id = "test-task-id"
        project1 = Project.objects.create(user=user, name="project1")
        project2 = Project.objects.create(user=user, name="project2")

        # Create first check
        ManufacturabilityService.queue_check(project1)

        # Second check should fail
        with pytest.raises(ValidationError, match=r"already have.*check.*running"):
            ManufacturabilityService.queue_check(project2)

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_allows_check_different_user(self, mock_delay):
        """Test that different users can run checks concurrently."""
        mock_delay.return_value.id = "test-task-id"
        user1 = User.objects.create_user(username="user1", password=TEST_PASSWORD)
        user2 = User.objects.create_user(username="user2", password=TEST_PASSWORD)

        project1 = Project.objects.create(user=user1, name="project1")
        project2 = Project.objects.create(user=user2, name="project2")

        # Both should succeed
        check1 = ManufacturabilityService.queue_check(project1)
        check2 = ManufacturabilityService.queue_check(project2)

        assert check1.status == ManufacturabilityCheck.Status.QUEUED
        assert check2.status == ManufacturabilityCheck.Status.QUEUED

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_allows_check_after_completion(self, mock_delay, user):
        """Test that user can queue new check after completion."""
        mock_delay.return_value.id = "test-task-id"
        project1 = Project.objects.create(user=user, name="project1")
        project2 = Project.objects.create(user=user, name="project2")

        # Create and complete first check
        check1 = ManufacturabilityService.queue_check(project1)
        check1.status = ManufacturabilityCheck.Status.COMPLETED
        check1.save()

        # Second check should succeed
        check2 = ManufacturabilityService.queue_check(project2)
        assert check2.status == ManufacturabilityCheck.Status.QUEUED
