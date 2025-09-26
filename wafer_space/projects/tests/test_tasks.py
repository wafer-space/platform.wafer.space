"""
Tests for project background tasks.

Security-Critical Tests:
- URL validation prevents dangerous schemes like file://, ftp://, custom schemes
- Only http:// and https:// schemes are allowed for file downloads
"""

from unittest.mock import Mock
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.tasks import _download_file_content

User = get_user_model()


class URLValidationSecurityTests(TestCase):
    """Security tests for URL validation in file download functionality."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project for URL validation",
        )

    def create_project_file(self, source_url):
        """Helper to create ProjectFile with given URL."""
        return ProjectFile.objects.create(
            project=self.project,
            source_url=source_url,
            original_filename="test_file.zip",
            file_type=ProjectFile.FileType.DESIGN,
        )

    def test_valid_http_url_allowed(self):
        """Test that http:// URLs are accepted."""
        project_file = self.create_project_file("http://example.com/file.zip")

        with patch("wafer_space.projects.tasks.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"test content"
            mock_response.headers = {"Content-Type": "application/zip"}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            # This should not raise any exception
            content = _download_file_content(project_file)
            self.assertEqual(content, b"test content")

    def test_valid_https_url_allowed(self):
        """Test that https:// URLs are accepted."""
        project_file = self.create_project_file("https://example.com/file.zip")

        with patch("wafer_space.projects.tasks.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"test content"
            mock_response.headers = {"Content-Type": "application/zip"}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            # This should not raise any exception
            content = _download_file_content(project_file)
            self.assertEqual(content, b"test content")

    def test_file_scheme_blocked(self):
        """Test that file:// URLs are blocked for security."""
        project_file = self.create_project_file("file:///etc/passwd")

        with self.assertRaises(ValueError) as context:
            _download_file_content(project_file)

        self.assertIn("Unsupported URL scheme: file", str(context.exception))

    def test_ftp_scheme_blocked(self):
        """Test that ftp:// URLs are blocked."""
        project_file = self.create_project_file("ftp://example.com/file.zip")

        with self.assertRaises(ValueError) as context:
            _download_file_content(project_file)

        self.assertIn("Unsupported URL scheme: ftp", str(context.exception))

    def test_custom_scheme_blocked(self):
        """Test that custom schemes are blocked."""
        project_file = self.create_project_file("custom://malicious/payload")

        with self.assertRaises(ValueError) as context:
            _download_file_content(project_file)

        self.assertIn("Unsupported URL scheme: custom", str(context.exception))

    def test_javascript_scheme_blocked(self):
        """Test that javascript: URLs are blocked."""
        project_file = self.create_project_file("javascript:alert('xss')")

        with self.assertRaises(ValueError) as context:
            _download_file_content(project_file)

        self.assertIn("Unsupported URL scheme: javascript", str(context.exception))

    def test_data_scheme_blocked(self):
        """Test that data: URLs are blocked."""
        project_file = self.create_project_file("data:text/plain;base64,SGVsbG8=")

        with self.assertRaises(ValueError) as context:
            _download_file_content(project_file)

        self.assertIn("Unsupported URL scheme: data", str(context.exception))

    def test_ldap_scheme_blocked(self):
        """Test that ldap:// URLs are blocked."""
        project_file = self.create_project_file("ldap://example.com/query")

        with self.assertRaises(ValueError) as context:
            _download_file_content(project_file)

        self.assertIn("Unsupported URL scheme: ldap", str(context.exception))

    def test_empty_scheme_blocked(self):
        """Test that URLs without schemes are blocked."""
        project_file = self.create_project_file("//example.com/file.zip")

        with self.assertRaises(ValueError) as context:
            _download_file_content(project_file)

        self.assertIn("Unsupported URL scheme:", str(context.exception))

    def test_scheme_case_insensitive(self):
        """Test that scheme validation is case insensitive."""
        # Should allow HTTPS
        project_file_https = self.create_project_file("HTTPS://example.com/file.zip")

        with patch("wafer_space.projects.tasks.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"test content"
            mock_response.headers = {}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            # This should not raise any exception
            content = _download_file_content(project_file_https)
            self.assertEqual(content, b"test content")

        # Should block FILE
        project_file_file = self.create_project_file("FILE:///etc/passwd")

        with self.assertRaises(ValueError) as context:
            _download_file_content(project_file_file)

        self.assertIn("Unsupported URL scheme: file", str(context.exception))


class URLValidationDocumentationTests(TestCase):
    """Tests to ensure URL validation security measures are properly documented."""

    def test_security_validation_documented_in_function(self):
        """Test that the security validation is documented in the function."""
        import inspect

        from wafer_space.projects.tasks import _download_file_content

        source = inspect.getsource(_download_file_content)

        # Check that security validation is documented
        self.assertIn("Validate URL scheme for security", source)
        self.assertIn('("http", "https")', source)
        self.assertIn("Unsupported URL scheme", source)

    def test_security_validation_happens_before_request(self):
        """Test that URL validation happens before Request object creation."""
        import inspect

        from wafer_space.projects.tasks import _download_file_content

        source_lines = inspect.getsource(_download_file_content).split("\n")

        validation_line = None
        request_line = None

        for i, line in enumerate(source_lines):
            if "parsed_url.scheme.lower() not in" in line:
                validation_line = i
            elif "Request(" in line:
                request_line = i

        # Validation must happen before Request creation
        self.assertIsNotNone(validation_line, "URL scheme validation not found")
        self.assertIsNotNone(request_line, "Request creation not found")
        self.assertLess(validation_line, request_line,
                       "URL validation must happen before Request creation")
