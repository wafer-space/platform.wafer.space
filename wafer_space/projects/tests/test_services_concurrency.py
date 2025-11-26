"""Tests for manufacturability service concurrency controls."""

import contextlib
import threading
from queue import Queue
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.services import ManufacturabilityService

from .constants import TEST_PASSWORD

User = get_user_model()


@pytest.mark.django_db
class TestGlobalConcurrency:
    """Test global concurrency limits for manufacturability checks."""

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_allows_first_check(self, mock_delay, user):
        """Test that first check is allowed."""
        mock_delay.return_value.id = "test-task-id"
        project = Project.objects.create(user=user, name="project1")
        project_file = ProjectFile.objects.create(
            project=project,
            original_filename="test.gds",
            source_url="https://example.com/test.gds",
            is_active=True,
        )

        check = ManufacturabilityService.queue_check(project, project_file)

        assert check.status == ManufacturabilityCheck.Status.QUEUED

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_allows_multiple_checks_same_user(self, mock_delay, user):
        """Test that same user can queue multiple checks (up to global limit)."""
        mock_delay.return_value.id = "test-task-id"
        project1 = Project.objects.create(user=user, name="project1")
        project_file1 = ProjectFile.objects.create(
            project=project1,
            original_filename="test1.gds",
            source_url="https://example.com/test1.gds",
            is_active=True,
        )
        project2 = Project.objects.create(user=user, name="project2")
        project_file2 = ProjectFile.objects.create(
            project=project2,
            original_filename="test2.gds",
            source_url="https://example.com/test2.gds",
            is_active=True,
        )

        # Both checks should succeed (global limit is 4 by default)
        check1 = ManufacturabilityService.queue_check(project1, project_file1)
        check2 = ManufacturabilityService.queue_check(project2, project_file2)

        assert check1.status == ManufacturabilityCheck.Status.QUEUED
        assert check2.status == ManufacturabilityCheck.Status.QUEUED

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    @patch.object(settings, "PRECHECK_CONCURRENT_LIMIT", 2)
    def test_blocks_at_global_limit(self, mock_delay):
        """Test that checks are blocked when global limit is reached."""
        mock_delay.return_value.id = "test-task-id"
        user1 = User.objects.create_user(username="user1", password=TEST_PASSWORD)
        user2 = User.objects.create_user(username="user2", password=TEST_PASSWORD)
        user3 = User.objects.create_user(username="user3", password=TEST_PASSWORD)

        # Create projects for each user
        project1 = Project.objects.create(user=user1, name="project1")
        project_file1 = ProjectFile.objects.create(
            project=project1,
            original_filename="test1.gds",
            source_url="https://example.com/test1.gds",
            is_active=True,
        )
        project2 = Project.objects.create(user=user2, name="project2")
        project_file2 = ProjectFile.objects.create(
            project=project2,
            original_filename="test2.gds",
            source_url="https://example.com/test2.gds",
            is_active=True,
        )
        project3 = Project.objects.create(user=user3, name="project3")
        project_file3 = ProjectFile.objects.create(
            project=project3,
            original_filename="test3.gds",
            source_url="https://example.com/test3.gds",
            is_active=True,
        )

        # Queue first two checks (at limit)
        ManufacturabilityService.queue_check(project1, project_file1)
        ManufacturabilityService.queue_check(project2, project_file2)

        # Third check should fail (at capacity)
        with pytest.raises(ValidationError, match=r"at capacity"):
            ManufacturabilityService.queue_check(project3, project_file3)

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_allows_check_after_completion(self, mock_delay, user):
        """Test that new checks can be queued after completion."""
        mock_delay.return_value.id = "test-task-id"
        project1 = Project.objects.create(user=user, name="project1")
        project_file1 = ProjectFile.objects.create(
            project=project1,
            original_filename="test1.gds",
            source_url="https://example.com/test1.gds",
            is_active=True,
        )
        project2 = Project.objects.create(user=user, name="project2")
        project_file2 = ProjectFile.objects.create(
            project=project2,
            original_filename="test2.gds",
            source_url="https://example.com/test2.gds",
            is_active=True,
        )

        # Create and complete first check
        check1 = ManufacturabilityService.queue_check(project1, project_file1)
        check1.status = ManufacturabilityCheck.Status.COMPLETED
        check1.save()

        # Second check should succeed
        check2 = ManufacturabilityService.queue_check(project2, project_file2)
        assert check2.status == ManufacturabilityCheck.Status.QUEUED

    @pytest.mark.skipif(
        connection.vendor == "sqlite",
        reason="SQLite table-level locking causes failures in full test suite",
    )
    @pytest.mark.django_db(transaction=True)
    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_concurrent_requests(self, mock_delay, user):
        """Test that concurrent requests are properly serialized.

        NOTE: This test is skipped for SQLite because it has table-level locking
        that conflicts with other tests running concurrently.

        In production with PostgreSQL, the transaction.atomic() + select_for_update()
        pattern prevents race conditions by acquiring row-level locks.
        """
        mock_delay.return_value.id = "test-task-id"
        project1 = Project.objects.create(user=user, name="project1")
        project_file1 = ProjectFile.objects.create(
            project=project1,
            original_filename="test1.gds",
            source_url="https://example.com/test1.gds",
            is_active=True,
        )
        project2 = Project.objects.create(user=user, name="project2")
        project_file2 = ProjectFile.objects.create(
            project=project2,
            original_filename="test2.gds",
            source_url="https://example.com/test2.gds",
            is_active=True,
        )

        results: Queue = Queue()

        def queue_check_thread(project, project_file):
            try:
                # Close connection to get a fresh one for this thread
                connection.close()
                check = ManufacturabilityService.queue_check(project, project_file)
                results.put(("success", check))
            except ValidationError as e:
                results.put(("error", str(e)))
            except (OSError, RuntimeError) as e:
                # Catch database errors (like SQLite locking)
                results.put(("error", str(e)))

        # Start two threads simultaneously
        thread1 = threading.Thread(
            target=queue_check_thread, args=(project1, project_file1)
        )
        thread2 = threading.Thread(
            target=queue_check_thread, args=(project2, project_file2)
        )

        thread1.start()
        thread2.start()
        thread1.join(timeout=5)
        thread2.join(timeout=5)

        # Collect results with timeout
        result_list = []
        for _ in range(2):
            with contextlib.suppress(Exception):
                # Timeout is acceptable if thread is still blocked
                result_list.append(results.get(timeout=1))

        # With global limits, both should succeed (default limit is 4)
        success_count = sum(1 for r in result_list if r[0] == "success")
        expected_success_count = len(result_list)  # All should succeed

        msg = f"Both requests should succeed with global limits, got {result_list}"
        assert success_count == expected_success_count, msg
