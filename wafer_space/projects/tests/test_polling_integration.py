"""Integration tests for the polling architecture.

This module tests the full lifecycle of the stateless polling architecture
for manufacturability checks, from PENDING to FINISHED state.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock
from unittest.mock import patch

import docker.errors
import pytest

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import ManufacturabilityCheckTask
from wafer_space.projects.models import PrecheckImageRevision
from wafer_space.projects.tasks import checks_dispatching
from wafer_space.projects.tasks import checks_pending
from wafer_space.projects.tasks import checks_running
from wafer_space.projects.tasks import checks_starting
from wafer_space.projects.tasks import do_analyzing
from wafer_space.projects.tasks import do_dispatching
from wafer_space.projects.tasks_checks import _resolve_check_versions
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
        # Success requires all three: DRC clear messages + success message
        # processing_logs is populated by do_running, so set it here
        success_logs = """Check for Magic DRC errors clear.
Check for KLayout DRC errors clear.
Precheck successfully completed."""
        check = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_server_id="test",
            docker_container_id="test-container",
            docker_exit_code=0,
            processing_logs=success_logs,
        )

        # Mock get_docker_client for container extraction
        mock_path = "wafer_space.projects.tasks_checks.get_docker_client"
        with patch(mock_path) as mock_get_docker_client:
            mock_client = MagicMock()
            mock_get_docker_client.return_value = mock_client

            mock_container = MagicMock()
            mock_client.containers.get.return_value = mock_container

            # get_archive returns (iterator_of_bytes, stat_dict)
            mock_container.get_archive.return_value = (
                iter([b"tar content"]),
                {"name": "file.tar"},
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
        assert (
            ManufacturabilityCheckTask.objects.filter(
                manufacturability_check=check
            ).count()
            == 1
        )

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

    def test_dispatch_serialization_blocks_on_dispatching(self, settings) -> None:
        """Test that new dispatches are blocked when a check is DISPATCHING."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 4,  # Plenty of capacity
                "priority": 1,
            },
        ]

        # Create a check already in DISPATCHING (doing image pull)
        ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.DISPATCHING,
            docker_server_id="test",
        )

        # Create pending check
        pending_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

        result = checks_pending()

        pending_check.refresh_from_db()
        # Should NOT dispatch - serialization blocks concurrent Docker operations
        assert pending_check.status == ManufacturabilityCheck.Status.PENDING
        assert pending_check.docker_server_id == ""
        assert result["dispatched"] == 0

    def test_dispatch_serialization_blocks_on_starting(self, settings) -> None:
        """Test that new dispatches are blocked when a check is STARTING."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 4,  # Plenty of capacity
                "priority": 1,
            },
        ]

        # Create a check already in STARTING (creating container)
        ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.STARTING,
            docker_server_id="test",
        )

        # Create pending check
        pending_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

        result = checks_pending()

        pending_check.refresh_from_db()
        # Should NOT dispatch - serialization blocks concurrent Docker operations
        assert pending_check.status == ManufacturabilityCheck.Status.PENDING
        assert pending_check.docker_server_id == ""
        assert result["dispatched"] == 0

    def test_dispatch_serialization_allows_after_running(self, settings) -> None:
        """Test that new dispatches are allowed once previous check is RUNNING."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 4,  # Plenty of capacity
                "priority": 1,
            },
        ]

        # Create a check already in RUNNING (Docker operations complete)
        ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_server_id="test",
        )

        # Create pending check
        pending_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

        result = checks_pending()

        pending_check.refresh_from_db()
        # SHOULD dispatch - previous check is past initialization
        assert pending_check.status == ManufacturabilityCheck.Status.DISPATCHING
        assert pending_check.docker_server_id == "test"
        assert result["dispatched"] == 1

    def test_dispatch_serialization_full_lifecycle(self, settings) -> None:
        """Test serialization through complete state machine transitions.

        Starts with two PENDING checks and walks the first through each state,
        verifying the second doesn't dispatch until the first reaches RUNNING.
        """
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 4,  # Plenty of capacity
                "priority": 1,
            },
        ]

        # Create two pending checks (check1 created first, so dispatched first)
        check1 = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )
        check2 = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

        # Step 1: First checks_pending() - only check1 should dispatch
        result = checks_pending()
        check1.refresh_from_db()
        check2.refresh_from_db()

        assert result["dispatched"] == 1
        assert check1.status == ManufacturabilityCheck.Status.DISPATCHING
        assert check1.docker_server_id == "test"
        assert check2.status == ManufacturabilityCheck.Status.PENDING
        assert check2.docker_server_id == ""

        # Step 2: While check1 is DISPATCHING, check2 should NOT dispatch
        result = checks_pending()
        check2.refresh_from_db()

        assert result["dispatched"] == 0
        assert check2.status == ManufacturabilityCheck.Status.PENDING

        # Step 3: Transition check1 to STARTING (image pull complete)
        check1.mark_starting(
            docker_image="test-image:latest",
            docker_image_digest="sha256:abc123",
        )
        assert check1.status == ManufacturabilityCheck.Status.STARTING

        # Step 4: While check1 is STARTING, check2 should still NOT dispatch
        result = checks_pending()
        check2.refresh_from_db()

        assert result["dispatched"] == 0
        assert check2.status == ManufacturabilityCheck.Status.PENDING

        # Step 5: Transition check1 to RUNNING (container created and started)
        check1.mark_running(
            docker_container_id="container123",
            docker_command="/run/precheck.sh",
        )
        assert check1.status == ManufacturabilityCheck.Status.RUNNING

        # Step 6: NOW check2 should be dispatched
        result = checks_pending()
        check2.refresh_from_db()

        assert result["dispatched"] == 1
        assert check2.status == ManufacturabilityCheck.Status.DISPATCHING
        assert check2.docker_server_id == "test"

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
        # Design failure: DRC tools completed but exit_code=1 (errors found)
        failure_logs = """Precheck Summary:
[ERROR] DRC violation at (100, 200)
[ERROR] Metal spacing violation
Check for Magic DRC errors clear.
Check for KLayout DRC errors clear.
[INFO] Design is NOT manufacturable
"""
        check = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_server_id="test",
            docker_container_id="test-container",
            docker_exit_code=1,
            processing_logs=failure_logs,
        )

        mock_path = "wafer_space.projects.tasks_checks.docker.DockerClient"
        with patch(mock_path) as mock_docker:
            mock_client = MagicMock()
            mock_docker.return_value = mock_client

            mock_container = MagicMock()
            mock_container.id = "test-container"
            mock_client.containers.get.return_value = mock_container

            # Mock failed precheck output - DRC tools completed but found errors
            failure_log = b"""
Precheck Summary:
[ERROR] DRC violation at (100, 200)
[ERROR] Metal spacing violation
Check for Magic DRC errors clear.
Check for KLayout DRC errors clear.
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


@pytest.mark.django_db
class TestAnalyzingVersionStamping:
    """do_analyzing stamps versions from the image revision catalog (#315)."""

    DIGEST = "sha256:315bbb5678901234567890123456789012345678901234567890123456789012"

    def _logger(self) -> logging.Logger:
        return logging.getLogger("wafer_space.projects.tests")

    def test_resolve_check_versions_stamps_from_catalog(self) -> None:
        """Helper persists the catalog version and returns tool versions."""
        PrecheckImageRevision.objects.create(
            digest=self.DIGEST,
            precheck_version="1.7.2",
            tool_versions={"klayout": "0.29.1"},
        )
        check = ManufacturabilityCheckFactory(docker_image_digest=self.DIGEST)

        tool_versions = _resolve_check_versions(check, self._logger())

        check.refresh_from_db()
        assert check.precheck_version == "1.7.2"
        assert tool_versions == {"klayout": "0.29.1"}

    def test_resolve_check_versions_without_catalog_row(self) -> None:
        """No catalog row: nothing stamped, no tool versions."""
        check = ManufacturabilityCheckFactory(docker_image_digest=self.DIGEST)

        tool_versions = _resolve_check_versions(check, self._logger())

        check.refresh_from_db()
        assert check.precheck_version == ""
        assert tool_versions == {}

    def test_resolve_check_versions_keeps_existing_stamp(self) -> None:
        """An already-stamped check is not overwritten by the catalog."""
        PrecheckImageRevision.objects.create(
            digest=self.DIGEST,
            precheck_version="2.0.0",
        )
        check = ManufacturabilityCheckFactory(
            docker_image_digest=self.DIGEST,
            precheck_version="1.0.0",
        )

        _resolve_check_versions(check, self._logger())

        check.refresh_from_db()
        assert check.precheck_version == "1.0.0"

    def test_analyzing_stamps_versions_from_catalog(self, settings) -> None:
        """do_analyzing records real versions instead of 'unknown'."""
        settings.DOCKER_SERVERS = [
            {
                "id": "test",
                "url": "unix:///test.sock",
                "max_concurrent": 4,
                "priority": 1,
            },
        ]
        PrecheckImageRevision.objects.create(
            digest=self.DIGEST,
            precheck_version="1.7.2",
            tool_versions={"klayout": "0.29.1"},
        )
        project_file = ProjectFileFactory(
            processed_filename="test.gds",
            top_cell="TOP",
        )
        success_logs = """Check for Magic DRC errors clear.
Check for KLayout DRC errors clear.
Precheck successfully completed."""
        check = ManufacturabilityCheckFactory(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.ANALYZING,
            docker_server_id="test",
            docker_container_id="test-container",
            docker_exit_code=0,
            docker_image_digest=self.DIGEST,
            processing_logs=success_logs,
        )

        mock_path = "wafer_space.projects.tasks_checks.get_docker_client"
        with patch(mock_path) as mock_get_docker_client:
            mock_client = MagicMock()
            mock_get_docker_client.return_value = mock_client
            mock_container = MagicMock()
            mock_client.containers.get.return_value = mock_container
            mock_container.get_archive.return_value = (
                iter([b"tar content"]),
                {"name": "file.tar"},
            )

            result = do_analyzing(check.id)

        check.refresh_from_db()
        assert result["status"] == "success"
        assert check.precheck_version == "1.7.2"
        assert check.tool_versions == {"klayout": "0.29.1"}
