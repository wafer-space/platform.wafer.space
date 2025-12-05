"""Tests for download and check verification functions."""

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase

from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.verification import _is_task_in_broker_queue
from wafer_space.projects.verification import is_check_task_actively_running
from wafer_space.projects.verification import is_check_task_queued
from wafer_space.projects.verification import is_download_task_actively_running
from wafer_space.projects.verification import is_download_task_queued

User = get_user_model()
TEST_PASSWORD = "testpass123"  # noqa: S105 - Test password constant


@pytest.mark.django_db
class BrokerQueueTests(TestCase):
    """Tests for _is_task_in_broker_queue() function."""

    def setUp(self):
        """Ensure kombu tables exist for testing."""
        with connection.cursor() as cursor:
            # Create kombu tables using database-agnostic SQL
            # SQLite uses AUTOINCREMENT, PostgreSQL uses SERIAL
            vendor = connection.vendor
            if vendor == "sqlite":
                id_type = "INTEGER PRIMARY KEY AUTOINCREMENT"
            else:
                # PostgreSQL and others
                id_type = "SERIAL PRIMARY KEY"

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS kombu_queue (
                    id {id_type},
                    name VARCHAR(200) UNIQUE
                )
            """)
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS kombu_message (
                    id {id_type},
                    visible BOOLEAN DEFAULT TRUE,
                    timestamp TIMESTAMP,
                    payload TEXT NOT NULL,
                    version SMALLINT NOT NULL DEFAULT 1,
                    queue_id INTEGER REFERENCES kombu_queue(id)
                )
            """)

    def tearDown(self):
        """Clean up test messages."""
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM kombu_message")
            cursor.execute("DELETE FROM kombu_queue")

    def test_task_found_in_broker_queue(self):
        """Test that task found in broker queue returns True."""
        task_id = "test-task-12345"
        payload = f'{{"headers": {{"id": "{task_id}"}}, "body": "..."}}'

        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO kombu_queue (name) VALUES (%s)",
                ["downloads"],
            )
            cursor.execute(
                """
                INSERT INTO kombu_message (visible, payload, version, queue_id)
                VALUES (1, %s, 1, 1)
                """,
                [payload],
            )

        result = _is_task_in_broker_queue(task_id)
        assert result is True

    def test_task_not_in_broker_queue(self):
        """Test that missing task returns False."""
        result = _is_task_in_broker_queue("nonexistent-task")
        assert result is False

    def test_invisible_task_not_found(self):
        """Test that invisible (processed) task returns False."""
        task_id = "invisible-task-123"
        payload = f'{{"headers": {{"id": "{task_id}"}}, "body": "..."}}'

        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO kombu_queue (name) VALUES (%s)",
                ["downloads"],
            )
            cursor.execute(
                """
                INSERT INTO kombu_message (visible, payload, version, queue_id)
                VALUES (0, %s, 1, 1)
                """,
                [payload],
            )

        result = _is_task_in_broker_queue(task_id)
        assert result is False

    def test_empty_task_id_returns_false(self):
        """Test that empty task_id returns False."""
        result = _is_task_in_broker_queue("")
        assert result is False

    def test_none_task_id_returns_false(self):
        """Test that None task_id returns False."""
        result = _is_task_in_broker_queue(None)
        assert result is False


@pytest.mark.django_db
class DownloadTaskQueuedVerificationTests(TestCase):
    """Tests for is_download_task_queued() function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test Description"
        )

    @patch("wafer_space.projects.verification._is_task_in_broker_queue")
    @patch("wafer_space.projects.verification.current_app")
    def test_task_in_reserved_queue(self, mock_app, mock_broker_check):
        """Test that task found in reserved queue returns True."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_task_id="task-123",
            is_active=False,
        )

        # Mock broker queue check to return False (not in broker)
        mock_broker_check.return_value = False

        # Mock Celery inspect to return task in reserved
        mock_inspect = Mock()
        mock_inspect.reserved.return_value = {
            "worker1": [
                {"id": "task-123", "name": "download_project_file"},
            ],
        }
        mock_inspect.active.return_value = {}
        mock_app.control.inspect.return_value = mock_inspect

        result = is_download_task_queued(project_file)

        assert result is True
        project_file.refresh_from_db()
        assert project_file.download_status == ProjectFile.DownloadStatus.QUEUED

    @patch("wafer_space.projects.verification._is_task_in_broker_queue")
    @patch("wafer_space.projects.verification.current_app")
    def test_task_in_active_auto_transitions(self, mock_app, mock_broker_check):
        """Test that task in active list returns True (still queued)."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_task_id="task-456",
            is_active=False,
            original_filename="test.gds",
        )

        # Mock broker queue check to return False (not in broker)
        mock_broker_check.return_value = False

        # Mock Celery inspect to return task in active
        mock_inspect = Mock()
        mock_inspect.reserved.return_value = {}
        mock_inspect.active.return_value = {
            "worker1": [
                {"id": "task-456", "name": "download_project_file"},
            ],
        }
        mock_app.control.inspect.return_value = mock_inspect

        result = is_download_task_queued(project_file)

        assert result is True
        project_file.refresh_from_db()
        # Status is QUEUED (has download_task_id but no DownloadAttempt)
        assert project_file.download_status == ProjectFile.DownloadStatus.QUEUED

    @patch("wafer_space.projects.verification._is_task_in_broker_queue")
    @patch("wafer_space.projects.verification.current_app")
    def test_task_not_found_returns_false(self, mock_app, mock_broker_check):
        """Test that missing task returns False."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_task_id="task-789",
            is_active=False,
        )

        # Mock broker queue check to return False (not in broker)
        mock_broker_check.return_value = False

        # Mock Celery inspect to return empty
        mock_inspect = Mock()
        mock_inspect.reserved.return_value = {}
        mock_inspect.active.return_value = {}
        mock_app.control.inspect.return_value = mock_inspect

        result = is_download_task_queued(project_file)

        assert result is False

    @patch("wafer_space.projects.verification.current_app")
    @patch("wafer_space.projects.verification._is_task_in_broker_queue")
    def test_task_in_broker_queue_returns_true(self, mock_broker_check, mock_app):
        """Test that task found in broker queue returns True."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_task_id="task-broker-123",
            is_active=False,
        )

        # Mock broker queue check to return True (found in broker)
        mock_broker_check.return_value = True

        result = is_download_task_queued(project_file)

        assert result is True
        # Should not even call inspect when broker check returns True
        mock_app.control.inspect.assert_not_called()


@pytest.mark.django_db
class DownloadTaskActivelyRunningTests(TestCase):
    """Tests for is_download_task_actively_running() function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test Description"
        )

    @patch("wafer_space.projects.verification.psutil")
    @patch("wafer_space.projects.verification.socket")
    @patch("wafer_space.projects.verification.current_app")
    def test_task_active_and_pid_exists(self, mock_app, mock_socket, mock_psutil):
        """Test task in active list with valid PID returns True."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_task_id="task-123",
            is_active=False,
            original_filename="test.gds",
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
            worker_pid=12345,
            worker_hostname="worker-01",
        )

        # Mock Celery inspect
        mock_inspect = Mock()
        mock_inspect.active.return_value = {
            "worker1": [{"id": "task-123"}],
        }
        mock_app.control.inspect.return_value = mock_inspect

        # Mock socket (same hostname)
        mock_socket.gethostname.return_value = "worker-01"

        # Mock psutil (PID exists, is Celery process)
        mock_psutil.pid_exists.return_value = True
        mock_proc = Mock()
        mock_proc.cmdline.return_value = ["python", "-m", "celery", "worker"]
        mock_psutil.Process.return_value = mock_proc

        result = is_download_task_actively_running(project_file)

        assert result is True

    @patch("wafer_space.projects.verification.psutil")
    @patch("wafer_space.projects.verification.socket")
    @patch("wafer_space.projects.verification.current_app")
    def test_task_active_but_pid_dead(self, mock_app, mock_socket, mock_psutil):
        """Test task in active but PID doesn't exist returns False."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_task_id="task-456",
            is_active=False,
            original_filename="test.gds",
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
            worker_pid=99999,
            worker_hostname="worker-01",
        )

        # Mock Celery inspect (task shows as active)
        mock_inspect = Mock()
        mock_inspect.active.return_value = {
            "worker1": [{"id": "task-456"}],
        }
        mock_app.control.inspect.return_value = mock_inspect

        # Mock socket (same hostname)
        mock_socket.gethostname.return_value = "worker-01"

        # Mock psutil (PID does NOT exist)
        mock_psutil.pid_exists.return_value = False

        result = is_download_task_actively_running(project_file)

        assert result is False

    @patch("wafer_space.projects.verification.current_app")
    def test_task_not_in_active(self, mock_app):
        """Test task not in active list returns False."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            download_task_id="task-789",
            is_active=False,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        # Mock Celery inspect (empty)
        mock_inspect = Mock()
        mock_inspect.active.return_value = {}
        mock_app.control.inspect.return_value = mock_inspect

        result = is_download_task_actively_running(project_file)

        assert result is False


@pytest.mark.django_db
class CheckTaskQueuedVerificationTests(TestCase):
    """Tests for is_check_task_queued() function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test Description"
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            original_filename="test.gds",
            is_active=True,
        )

    @patch("wafer_space.projects.verification._is_task_in_broker_queue")
    @patch("wafer_space.projects.verification.current_app")
    @pytest.mark.skip(reason="Obsolete - function always returns False")
    def test_check_task_in_reserved_queue(self, mock_app, mock_broker_check):
        """Test that check task found in reserved queue returns True."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHING,
        )

        # Mock broker queue check to return False (not in broker)
        mock_broker_check.return_value = False

        # Mock Celery inspect to return task in reserved
        mock_inspect = Mock()
        mock_inspect.reserved.return_value = {
            "worker1": [
                {"id": "check-task-123", "name": "do_starting"},
            ],
        }
        mock_inspect.active.return_value = {}
        mock_app.control.inspect.return_value = mock_inspect

        result = is_check_task_queued(check)

        assert result is True

    @patch("wafer_space.projects.verification._is_task_in_broker_queue")
    @patch("wafer_space.projects.verification.current_app")
    @pytest.mark.skip(reason="Obsolete - function always returns False")
    def test_check_task_in_active_returns_true(self, mock_app, mock_broker_check):
        """Test that check task in active list returns True."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHING,
        )

        # Mock broker queue check to return False (not in broker)
        mock_broker_check.return_value = False

        # Mock Celery inspect to return task in active
        mock_inspect = Mock()
        mock_inspect.reserved.return_value = {}
        mock_inspect.active.return_value = {
            "worker1": [
                {"id": "check-task-456", "name": "do_running"},
            ],
        }
        mock_app.control.inspect.return_value = mock_inspect

        result = is_check_task_queued(check)

        assert result is True

    @patch("wafer_space.projects.verification._is_task_in_broker_queue")
    @patch("wafer_space.projects.verification.current_app")
    def test_check_task_not_found_returns_false(self, mock_app, mock_broker_check):
        """Test that missing check task returns False."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHING,
        )

        # Mock broker queue check to return False (not in broker)
        mock_broker_check.return_value = False

        # Mock Celery inspect to return empty
        mock_inspect = Mock()
        mock_inspect.reserved.return_value = {}
        mock_inspect.active.return_value = {}
        mock_app.control.inspect.return_value = mock_inspect

        result = is_check_task_queued(check)

        assert result is False

    @patch("wafer_space.projects.verification.current_app")
    @patch("wafer_space.projects.verification._is_task_in_broker_queue")
    @pytest.mark.skip(reason="Obsolete - function always returns False")
    def test_check_task_in_broker_queue_returns_true(self, mock_broker_check, mock_app):
        """Test that check task found in broker queue returns True."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.DISPATCHING,
        )

        # Mock broker queue check to return True (found in broker)
        mock_broker_check.return_value = True

        result = is_check_task_queued(check)

        assert result is True
        # Should not even call inspect when broker check returns True
        mock_app.control.inspect.assert_not_called()

    def test_check_task_without_task_id_returns_false(self):
        """Test that check returns False (function is obsolete)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        result = is_check_task_queued(check)

        # Function is now obsolete and always returns False
        assert result is False


@pytest.mark.django_db
class CheckTaskActivelyRunningTests(TestCase):
    """Tests for is_check_task_actively_running() function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test Description"
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            source_url="http://example.com/test.gds",
            original_filename="test.gds",
            is_active=True,
        )

    @patch("wafer_space.projects.verification.psutil")
    @patch("wafer_space.projects.verification.socket")
    @patch("wafer_space.projects.verification.current_app")
    @pytest.mark.skip(reason="Obsolete - function always returns False")
    def test_check_task_active_and_pid_exists(self, mock_app, mock_socket, mock_psutil):
        """Test check task in active list with valid PID returns True."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        # Mock Celery inspect
        mock_inspect = Mock()
        mock_inspect.active.return_value = {
            "worker1": [{"id": "check-task-123"}],
        }
        mock_app.control.inspect.return_value = mock_inspect

        # Mock socket (same hostname)
        mock_socket.gethostname.return_value = "worker-01"

        # Mock psutil (PID exists, is Celery process)
        mock_psutil.pid_exists.return_value = True
        mock_proc = Mock()
        mock_proc.cmdline.return_value = ["python", "-m", "celery", "worker"]
        mock_psutil.Process.return_value = mock_proc

        result = is_check_task_actively_running(check)

        assert result is True

    @patch("wafer_space.projects.verification.psutil")
    @patch("wafer_space.projects.verification.socket")
    @patch("wafer_space.projects.verification.current_app")
    def test_check_task_active_but_pid_dead(self, mock_app, mock_socket, mock_psutil):
        """Test check task in active but PID doesn't exist returns False."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        # Mock Celery inspect (task shows as active)
        mock_inspect = Mock()
        mock_inspect.active.return_value = {
            "worker1": [{"id": "check-task-456"}],
        }
        mock_app.control.inspect.return_value = mock_inspect

        # Mock socket (same hostname)
        mock_socket.gethostname.return_value = "worker-01"

        # Mock psutil (PID does NOT exist)
        mock_psutil.pid_exists.return_value = False

        result = is_check_task_actively_running(check)

        assert result is False

    @patch("wafer_space.projects.verification.current_app")
    def test_check_task_not_in_active(self, mock_app):
        """Test check task not in active list returns False."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        # Mock Celery inspect (empty)
        mock_inspect = Mock()
        mock_inspect.active.return_value = {}
        mock_app.control.inspect.return_value = mock_inspect

        result = is_check_task_actively_running(check)

        assert result is False

    def test_check_task_without_task_id_returns_false(self):
        """Test that check returns False (function is obsolete)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        result = is_check_task_actively_running(check)

        # Function is now obsolete and always returns False
        assert result is False

    @pytest.mark.skip(reason="Obsolete - function always returns False")
    @patch("wafer_space.projects.verification.socket")
    @patch("wafer_space.projects.verification.current_app")
    def test_check_task_active_different_hostname_returns_true(
        self, mock_app, mock_socket
    ):
        """Test check task on different host returns True (can't verify remote)."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        # Mock Celery inspect
        mock_inspect = Mock()
        mock_inspect.active.return_value = {
            "worker1": [{"id": "check-task-remote"}],
        }
        mock_app.control.inspect.return_value = mock_inspect

        # Mock socket (different hostname)
        mock_socket.gethostname.return_value = "local-machine"

        result = is_check_task_actively_running(check)

        # Should return True because we can't verify remote processes
        assert result is True
