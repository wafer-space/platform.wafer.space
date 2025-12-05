"""Integration tests for the polling architecture.

This module tests the full lifecycle of the stateless polling architecture
for manufacturability checks, from PENDING to FINISHED state.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import docker.errors
import pytest

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import ManufacturabilityCheckTask
from wafer_space.projects.tasks import checks_dispatching
from wafer_space.projects.tasks import checks_pending
from wafer_space.projects.tasks import checks_running
from wafer_space.projects.tasks import checks_starting
from wafer_space.projects.tasks import do_analyzing
from wafer_space.projects.tasks import do_dispatching
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory
from wafer_space.projects.tests.factories import ProjectFileFactory

# Number of checks for multi-server tests
EXPECTED_DISPATCHED_COUNT = 2


@pytest.mark.django_db
class TestPollingLifecycleIntegration:
    """Integration tests for complete polling lifecycle."""

    def test_pending_to_dispatching_transition(self, settings) -> None:
        """Test PENDING → DISPATCHING transition via checks_pending."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test-server",
                "url": "unix:///var/run/docker.sock",
                "max_concurrent": 4,
                "priority": 1,
            },
        ]

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING,
        )

        result = checks_pending()
        check.refresh_from_db()

        assert check.status == ManufacturabilityCheck.Status.DISPATCHING
        assert check.docker_server_id == "test-server"
        assert check.dispatching_started_at is not None
        assert result["dispatched"] == 1

    def test_dispatching_to_starting_transition(self, settings) -> None:
        """Test DISPATCHING → STARTING via do_dispatching with Docker mock."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 4,
                "priority": 1,
            },
        ]
        settings.PRECHECK_DOCKER_IMAGE = "test-image:latest"

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            docker_server_id="test",
        )

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker:
            mock_client = MagicMock()
            mock_docker.return_value = mock_client

            mock_image = MagicMock()
            mock_image.attrs = {"RepoDigests": ["test-image@sha256:abcd1234"]}
            mock_client.images.pull.return_value = mock_image

            result = do_dispatching(check.id)

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.STARTING
        assert check.docker_image == "test-image:latest"
        assert check.docker_image_digest == "sha256:abcd1234"
        assert result["status"] == "success"

    def test_starting_queues_work_task(self, settings) -> None:
        """Test checks_starting queues do_starting work task."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 4,
                "priority": 1,
            },
        ]

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.STARTING,
            docker_server_id="test",
        )

        result = checks_starting()

        check.refresh_from_db()
        assert result["queued"] == 1
        assert ManufacturabilityCheckTask.objects.filter(
            manufacturability_check=check,
            task_name="do_starting",
        ).exists()

    def test_running_queues_work_task(self, settings) -> None:
        """Test checks_running queues do_running work task."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 4,
                "priority": 1,
            },
        ]

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="test",
            docker_container_id="test-container-123",
        )

        result = checks_running()

        check.refresh_from_db()
        assert result["queued"] == 1
        assert ManufacturabilityCheckTask.objects.filter(
            manufacturability_check=check,
            task_name="do_running",
        ).exists()

    def test_analyzing_to_finished_transition(self, settings) -> None:
        """Test ANALYZING → FINISHED via do_analyzing with Docker mock."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 4,
                "priority": 1,
            },
        ]

        project_file = ProjectFileFactory(
            processed_filename="test.gds",
            top_cell="TOP",
        )
        check = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_server_id="test",
            docker_container_id="test-container",
            docker_exit_code=0,
        )

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker:
            mock_client = MagicMock()
            mock_docker.return_value = mock_client

            mock_container = MagicMock()
            mock_client.containers.get.return_value = mock_container

            success_log = b"[INFO] All checks passed\n[INFO] Design is manufacturable"
            mock_container.get_archive.return_value = (
                iter([success_log]),
                {"name": "precheck.log"},
            )

            result = do_analyzing(check.id)

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.FINISHED
        assert check.is_manufacturable is True
        assert check.analysis_completed_at is not None
        assert result["status"] == "success"

    def test_pending_to_dispatching_assigns_server(self, settings) -> None:
        """Test that checks_pending assigns correct server and transitions status."""
        settings.DOCKER_SERVERS = [
            {
                "id": "primary",
                "url": "unix:///var/run/docker.sock",
                "max_concurrent": 4,
                "priority": 1,
            },
            {
                "id": "secondary",
                "url": "tcp://10.0.0.2:2375",
                "max_concurrent": 2,
                "priority": 2,
            },
        ]

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

        result = checks_pending()

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.DISPATCHING
        assert check.docker_server_id == "primary"  # Uses highest priority
        assert check.dispatching_started_at is not None
        assert result["dispatched"] == 1

    def test_task_deduplication_prevents_double_queueing(self) -> None:
        """Test that ManufacturabilityCheckTask prevents duplicate task queueing."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            docker_server_id="test",
        )

        # First call should queue task
        result1 = checks_dispatching()
        assert result1["queued"] == 1
        assert ManufacturabilityCheckTask.objects.filter(
            manufacturability_check=check
        ).exists()

        # Second call should not queue (task already exists)
        result2 = checks_dispatching()
        assert result2["queued"] == 0
        assert ManufacturabilityCheckTask.objects.filter(
            manufacturability_check=check
        ).count() == 1

    def test_concurrent_limit_respected(self, settings) -> None:
        """Test that per-server concurrent limits are enforced."""
        settings.DOCKER_SERVERS = [
            {
                "id": "limited",
                "url": "unix:///test.sock",
                "max_concurrent": 2,
                "priority": 1,
            },
        ]

        # Create 2 active checks (at limit)
        ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="limited",
        )
        ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.STARTING,
            docker_server_id="limited",
        )

        # Create pending check
        pending_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

        result = checks_pending()

        pending_check.refresh_from_db()
        # Should NOT dispatch - server at capacity
        assert pending_check.status == ManufacturabilityCheck.Status.PENDING
        assert pending_check.docker_server_id == ""
        assert result["dispatched"] == 0

    def test_error_handling_transitions_to_error(self, settings) -> None:
        """Test that errors during Docker operations transition to ERROR state."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 4,
                "priority": 1,
            },
        ]
        settings.PRECHECK_DOCKER_IMAGE = "test-image:latest"

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            docker_server_id="test",
        )

        # Simulate Docker pull failure
        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker:
            mock_client = MagicMock()
            mock_docker.return_value = mock_client
            mock_client.images.pull.side_effect = docker.errors.DockerException(
                "Network error"
            )

            result = do_dispatching(check.id)

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.ERROR
        assert "Network error" in check.error_message
        assert result["status"] == "error"

    def test_cancellation_flow(self, settings) -> None:
        """Test CANCELLING → CANCELLED transition."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 4,
                "priority": 1,
            },
        ]

        # Create check in RUNNING state with container
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="test",
            docker_container_id="test-container-123",
        )

        # Request cancellation
        check.mark_cancelling(reason="User requested cancellation")
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLING

        # Simulate cleanup completing cancellation
        check.mark_cancelled()
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLED
        assert check.docker_container_id == ""  # Cleared on cancellation

    def test_multi_server_distribution(self, settings) -> None:
        """Test that checks are distributed across multiple servers."""
        settings.DOCKER_SERVERS = [
            {
                "id": "server1",
                "url": "unix:///s1.sock",
                "max_concurrent": 1,
                "priority": 1,
            },
            {
                "id": "server2",
                "url": "unix:///s2.sock",
                "max_concurrent": 1,
                "priority": 2,
            },
        ]

        # Create 2 pending checks
        check1 = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        check2 = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

        result = checks_pending()

        check1.refresh_from_db()
        check2.refresh_from_db()

        # Both should be dispatched
        assert result["dispatched"] == EXPECTED_DISPATCHED_COUNT
        assert check1.status == ManufacturabilityCheck.Status.DISPATCHING
        assert check2.status == ManufacturabilityCheck.Status.DISPATCHING

        # First check gets highest priority server
        assert check1.docker_server_id == "server1"
        # Second check overflows to second server
        assert check2.docker_server_id == "server2"

    def test_work_task_cleans_up_tracking_on_completion(self, settings) -> None:
        """Test that work tasks delete ManufacturabilityCheckTask on completion."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 4,
                "priority": 1,
            },
        ]
        settings.PRECHECK_DOCKER_IMAGE = "test-image:latest"

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            docker_server_id="test",
        )

        # Create tracking task
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id="test-task-id",
            task_name="do_dispatching",
        )

        # Execute work task
        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker:
            mock_client = MagicMock()
            mock_docker.return_value = mock_client

            mock_image = MagicMock()
            mock_image.attrs = {"RepoDigests": ["test@sha256:abc"]}
            mock_client.images.pull.return_value = mock_image

            do_dispatching(check.id)

        # Tracking task should be deleted
        assert not ManufacturabilityCheckTask.objects.filter(
            manufacturability_check=check
        ).exists()

    def test_status_change_during_processing_skips_work(self, settings) -> None:
        """Test that work tasks skip processing if status changed."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 4,
                "priority": 1,
            },
        ]

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            docker_server_id="test",
        )

        # Change status before work task runs
        check.status = ManufacturabilityCheck.Status.CANCELLED
        check.save()

        # Work task should skip
        result = do_dispatching(check.id)

        assert result["status"] == "skipped"
        assert result["reason"] == "status_changed"

    def test_beat_tasks_are_idempotent(self, settings) -> None:
        """Test that beat tasks can be run multiple times safely."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 4,
                "priority": 1,
            },
        ]

        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

        # First run transitions to DISPATCHING
        result1 = checks_pending()
        assert result1["dispatched"] == 1

        # Second run does nothing (check already dispatched)
        result2 = checks_pending()
        assert result2["dispatched"] == 0

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.DISPATCHING

    def test_analyzing_with_manufacturability_failure(self, settings) -> None:
        """Test ANALYZING → FINISHED with manufacturing errors."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 4,
                "priority": 1,
            },
        ]

        project_file = ProjectFileFactory(
            processed_filename="test.gds",
            top_cell="TOP",
        )
        check = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_server_id="test",
            docker_container_id="test-container",
            docker_exit_code=1,
        )

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker:
            mock_client = MagicMock()
            mock_docker.return_value = mock_client

            mock_container = MagicMock()
            mock_container.id = "test-container"
            mock_client.containers.get.return_value = mock_container

            # Mock failed precheck output
            failure_log = b"""
Precheck Summary:
[ERROR] DRC violation at (100, 200)
[ERROR] Metal spacing violation
[INFO] Design is NOT manufacturable
"""
            mock_container.get_archive.return_value = (
                iter([failure_log]),
                {"name": "precheck.log"},
            )

            result = do_analyzing(check.id)

            check.refresh_from_db()
            assert check.status == ManufacturabilityCheck.Status.FINISHED
            assert check.is_manufacturable is False
            assert len(check.errors) > 0
            assert result["status"] == "success"
