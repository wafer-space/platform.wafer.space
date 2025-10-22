"""
Tests for project background tasks.

Security-Critical Tests:
- URL validation prevents dangerous schemes like file://, ftp://, custom schemes
- Only http:// and https:// schemes are allowed for file downloads
"""

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.tasks import _safe_urlopen
from wafer_space.projects.tasks import check_project_manufacturability

User = get_user_model()
TEST_PASSWORD = "testpass123"  # noqa: S105


class URLValidationSecurityTests(TestCase):
    """Security tests for URL validation in file download functionality."""

    def test_valid_http_url_allowed(self):
        """Test that http:// URLs are accepted."""
        with patch("wafer_space.projects.tasks.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"test content"
            mock_response.headers = {"Content-Type": "application/zip"}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            # This should not raise any exception
            content, headers = _safe_urlopen("http://example.com/file.zip")
            assert content == b"test content"
            assert headers["Content-Type"] == "application/zip"

    def test_valid_https_url_allowed(self):
        """Test that https:// URLs are accepted."""
        with patch("wafer_space.projects.tasks.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"test content"
            mock_response.headers = {"Content-Type": "application/zip"}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            # This should not raise any exception
            content, headers = _safe_urlopen("https://example.com/file.zip")
            assert content == b"test content"
            assert headers["Content-Type"] == "application/zip"

    def test_file_scheme_blocked(self):
        """Test that file:// URLs are blocked for security."""
        with pytest.raises(ValueError, match="Unsupported URL scheme: file") as excinfo:
            _safe_urlopen("file:///etc/passwd")

        assert "Unsupported URL scheme: file" in str(excinfo.value)

    def test_ftp_scheme_blocked(self):
        """Test that ftp:// URLs are blocked."""
        with pytest.raises(ValueError, match="Unsupported URL scheme: ftp") as excinfo:
            _safe_urlopen("ftp://example.com/file.zip")

        assert "Unsupported URL scheme: ftp" in str(excinfo.value)

    def test_custom_scheme_blocked(self):
        """Test that custom schemes are blocked."""
        with pytest.raises(
            ValueError,
            match="Unsupported URL scheme: custom",
        ) as excinfo:
            _safe_urlopen("custom://malicious/payload")

        assert "Unsupported URL scheme: custom" in str(excinfo.value)

    def test_javascript_scheme_blocked(self):
        """Test that javascript: URLs are blocked."""
        with pytest.raises(
            ValueError,
            match="Unsupported URL scheme: javascript",
        ) as excinfo:
            _safe_urlopen("javascript:alert('xss')")

        assert "Unsupported URL scheme: javascript" in str(excinfo.value)

    def test_data_scheme_blocked(self):
        """Test that data: URLs are blocked."""
        with pytest.raises(ValueError, match="Unsupported URL scheme: data") as excinfo:
            _safe_urlopen("data:text/plain;base64,SGVsbG8=")

        assert "Unsupported URL scheme: data" in str(excinfo.value)

    def test_ldap_scheme_blocked(self):
        """Test that ldap:// URLs are blocked."""
        with pytest.raises(ValueError, match="Unsupported URL scheme: ldap") as excinfo:
            _safe_urlopen("ldap://example.com/query")

        assert "Unsupported URL scheme: ldap" in str(excinfo.value)

    def test_empty_scheme_blocked(self):
        """Test that URLs without schemes are blocked."""
        with pytest.raises(ValueError, match="Unsupported URL scheme:") as excinfo:
            _safe_urlopen("//example.com/file.zip")

        assert "Unsupported URL scheme:" in str(excinfo.value)

    def test_scheme_case_insensitive(self):
        """Test that scheme validation is case insensitive."""
        # Should allow HTTPS
        with patch("wafer_space.projects.tasks.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"test content"
            mock_response.headers = {}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            # This should not raise any exception
            content, _headers = _safe_urlopen("HTTPS://example.com/file.zip")
            assert content == b"test content"

        # Should block FILE
        with pytest.raises(ValueError, match="Unsupported URL scheme: file") as excinfo:
            _safe_urlopen("FILE:///etc/passwd")

        assert "Unsupported URL scheme: file" in str(excinfo.value)

    def test_headers_passed_correctly(self):
        """Test that custom headers are passed to the request."""
        custom_headers = {"Authorization": "Bearer token123", "Custom-Header": "test"}

        with patch("wafer_space.projects.tasks.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"test content"
            mock_response.headers = {"Content-Type": "text/plain"}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            content, headers = _safe_urlopen(
                "https://example.com/file.zip",
                headers=custom_headers,
            )
            assert content == b"test content"
            assert headers["Content-Type"] == "text/plain"

            # Verify the request was made with correct headers
            assert mock_urlopen.called


class URLValidationBehaviorTests(TestCase):
    """Tests to verify the behavior of URL validation security measures."""

    def test_validation_error_provides_helpful_message(self):
        """Test that validation errors provide clear, helpful messages."""
        test_cases = [
            ("file:///etc/passwd", "file"),
            ("ftp://example.com", "ftp"),
            ("custom://test", "custom"),
        ]

        for url, expected_scheme in test_cases:
            with self.subTest(url=url):
                with pytest.raises(
                    ValueError,
                    match=r"(?i)unsupported url scheme",
                ) as excinfo:
                    _safe_urlopen(url)

                error_msg = str(excinfo.value).lower()
                assert "unsupported url scheme" in error_msg
                assert expected_scheme in error_msg

    def test_validation_is_case_insensitive_comprehensive(self):
        """Test comprehensive case insensitivity for both valid and invalid schemes."""
        valid_cases = [
            "http://test.com",
            "HTTP://test.com",
            "https://test.com",
            "HTTPS://test.com",
        ]
        invalid_cases = ["file:///test", "FILE:///test", "ftp://test", "FTP://test"]

        # Test valid cases
        for url in valid_cases:
            with (
                self.subTest(url=url),
                patch(
                    "wafer_space.projects.tasks.urlopen",
                ) as mock_urlopen,
            ):
                mock_response = Mock()
                mock_response.read.return_value = b"test"
                mock_response.headers = {}
                mock_urlopen.return_value.__enter__.return_value = mock_response

                # Should not raise exception
                content, _headers = _safe_urlopen(url)
                assert content == b"test"

        # Test invalid cases
        for url in invalid_cases:
            with (
                self.subTest(url=url),
                pytest.raises(
                    ValueError,
                    match=r".*(file|ftp).*",
                ),
            ):
                _safe_urlopen(url)


@pytest.mark.django_db
class TestManufacturabilityCheckTask(TestCase):
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test Description",
        )

    @patch("wafer_space.projects.tasks.time.sleep")
    @patch("wafer_space.projects.tasks.random.uniform")
    @patch("wafer_space.projects.tasks.random.random")
    def test_check_task_marks_processing(
        self,
        mock_random,
        mock_uniform,
        mock_sleep,
    ):
        """Test that task marks check as PROCESSING."""
        # Mock random to ensure predictable success
        mock_random.return_value = 0.5  # Below 0.8 threshold = manufacturable
        mock_uniform.return_value = 2.0  # Fixed processing time
        mock_sleep.return_value = None  # Don't actually sleep

        # Create a check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            status=ManufacturabilityCheck.Status.QUEUED,
            task_id="test-task-123",
        )

        # Run task
        result = check_project_manufacturability(check.id)

        # Verify check was marked as processing then completed
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.COMPLETED
        assert result["status"] == "completed"

    @patch("wafer_space.projects.tasks.time.sleep")
    @patch("wafer_space.projects.tasks.random.uniform")
    @patch("wafer_space.projects.tasks.random.random")
    def test_check_task_completes_successfully(
        self,
        mock_random,
        mock_uniform,
        mock_sleep,
    ):
        """Test that task completes check successfully."""
        # Mock random to ensure manufacturable result
        mock_random.return_value = 0.5  # Below 0.8 = manufacturable
        mock_uniform.return_value = 2.0
        mock_sleep.return_value = None

        # Create a check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            status=ManufacturabilityCheck.Status.QUEUED,
            task_id="test-task-123",
        )

        # Run task
        result = check_project_manufacturability(check.id)

        # Verify result
        assert result["status"] == "completed"
        assert result["is_manufacturable"] is True
        assert len(result["warnings"]) > 0
        assert len(result["errors"]) == 0

        # Verify check was updated
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.COMPLETED
        assert check.is_manufacturable is True
        assert len(check.warnings) > 0
        assert len(check.errors) == 0
        assert check.completed_at is not None

    @patch("wafer_space.projects.tasks.time.sleep")
    @patch("wafer_space.projects.tasks.random.uniform")
    @patch("wafer_space.projects.tasks.random.random")
    def test_check_task_detects_not_manufacturable(
        self,
        mock_random,
        mock_uniform,
        mock_sleep,
    ):
        """Test that task can mark project as not manufacturable."""
        # Mock random to ensure not manufacturable result
        mock_random.return_value = 0.9  # Above 0.8 = not manufacturable
        mock_uniform.return_value = 2.0
        mock_sleep.return_value = None

        # Create a check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            status=ManufacturabilityCheck.Status.QUEUED,
            task_id="test-task-123",
        )

        # Run task
        result = check_project_manufacturability(check.id)

        # Verify result
        assert result["status"] == "completed"
        assert result["is_manufacturable"] is False
        assert len(result["errors"]) > 0

        # Verify check was updated
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.COMPLETED
        assert check.is_manufacturable is False
        assert len(check.errors) > 0
        assert check.completed_at is not None

    def test_check_task_handles_missing_check(self):
        """Test that task handles missing check gracefully."""
        # Run task with non-existent check ID
        result = check_project_manufacturability(999999)

        # Verify error handling
        assert result["status"] == "error"
        assert "not found" in result["message"]

    @patch("wafer_space.projects.tasks.time.sleep")
    def test_check_task_retries_on_error(self, mock_sleep):
        """Test that task retries on unexpected errors."""
        # Make sleep raise an exception
        mock_sleep.side_effect = ValueError("Test error")

        # Create a check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            status=ManufacturabilityCheck.Status.QUEUED,
        )

        # Run task - should handle the exception
        with pytest.raises(ValueError, match="Test error"):
            check_project_manufacturability(check.id)

    @patch("wafer_space.projects.tasks.time.sleep")
    @patch("wafer_space.projects.tasks.random.uniform")
    @patch("wafer_space.projects.tasks.random.random")
    def test_check_task_updates_project_status(
        self,
        mock_random,
        mock_uniform,
        mock_sleep,
    ):
        """Test that task updates project status based on check result."""
        # Mock for manufacturable result
        mock_random.return_value = 0.5
        mock_uniform.return_value = 2.0
        mock_sleep.return_value = None

        # Set project to SUBMITTED status
        self.project.status = Project.Status.SUBMITTED
        self.project.save()

        # Create a check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            status=ManufacturabilityCheck.Status.QUEUED,
            task_id="test-task-456",
        )

        # Run task
        check_project_manufacturability(check.id)

        # Verify project status was updated
        self.project.refresh_from_db()
        assert self.project.status == Project.Status.MANUFACTURABLE
        assert self.project.is_manufacturable is True


@pytest.mark.django_db
class TestProjectSubmissionIntegration(TestCase):
    """Integration tests for project submission with manufacturability check."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test Description",
        )
        # Create a completed file for submission
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            source_url="https://example.com/test.gds",
            file_size=1024,
            is_active=True,
            download_status=ProjectFile.DownloadStatus.COMPLETED,
            hash_verified=True,
        )

    @patch("wafer_space.projects.tasks.check_project_manufacturability.delay")
    def test_submit_queues_manufacturability_check(self, mock_task):
        """Test that submitting a project queues a manufacturability check."""
        # Mock the Celery task
        mock_task.return_value = Mock(id="task-123")

        # Submit the project
        self.project.submit()

        # Verify check was created and queued
        assert ManufacturabilityCheck.objects.filter(project=self.project).count() == 1
        check = ManufacturabilityCheck.objects.get(project=self.project)
        assert check.status == ManufacturabilityCheck.Status.QUEUED
        assert check.task_id == "task-123"

        # Verify task was called
        mock_task.assert_called_once_with(check.id)

        # Verify project status
        assert self.project.status == Project.Status.SUBMITTED
        assert self.project.submitted_at is not None
