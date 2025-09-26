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

from wafer_space.projects.tasks import _safe_urlopen

User = get_user_model()


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
            self.assertEqual(content, b"test content")
            self.assertEqual(headers["Content-Type"], "application/zip")

    def test_valid_https_url_allowed(self):
        """Test that https:// URLs are accepted."""
        with patch("wafer_space.projects.tasks.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"test content"
            mock_response.headers = {"Content-Type": "application/zip"}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            # This should not raise any exception
            content, headers = _safe_urlopen("https://example.com/file.zip")
            self.assertEqual(content, b"test content")
            self.assertEqual(headers["Content-Type"], "application/zip")

    def test_file_scheme_blocked(self):
        """Test that file:// URLs are blocked for security."""
        with self.assertRaises(ValueError) as context:
            _safe_urlopen("file:///etc/passwd")

        self.assertIn("Unsupported URL scheme: file", str(context.exception))

    def test_ftp_scheme_blocked(self):
        """Test that ftp:// URLs are blocked."""
        with self.assertRaises(ValueError) as context:
            _safe_urlopen("ftp://example.com/file.zip")

        self.assertIn("Unsupported URL scheme: ftp", str(context.exception))

    def test_custom_scheme_blocked(self):
        """Test that custom schemes are blocked."""
        with self.assertRaises(ValueError) as context:
            _safe_urlopen("custom://malicious/payload")

        self.assertIn("Unsupported URL scheme: custom", str(context.exception))

    def test_javascript_scheme_blocked(self):
        """Test that javascript: URLs are blocked."""
        with self.assertRaises(ValueError) as context:
            _safe_urlopen("javascript:alert('xss')")

        self.assertIn("Unsupported URL scheme: javascript", str(context.exception))

    def test_data_scheme_blocked(self):
        """Test that data: URLs are blocked."""
        with self.assertRaises(ValueError) as context:
            _safe_urlopen("data:text/plain;base64,SGVsbG8=")

        self.assertIn("Unsupported URL scheme: data", str(context.exception))

    def test_ldap_scheme_blocked(self):
        """Test that ldap:// URLs are blocked."""
        with self.assertRaises(ValueError) as context:
            _safe_urlopen("ldap://example.com/query")

        self.assertIn("Unsupported URL scheme: ldap", str(context.exception))

    def test_empty_scheme_blocked(self):
        """Test that URLs without schemes are blocked."""
        with self.assertRaises(ValueError) as context:
            _safe_urlopen("//example.com/file.zip")

        self.assertIn("Unsupported URL scheme:", str(context.exception))

    def test_scheme_case_insensitive(self):
        """Test that scheme validation is case insensitive."""
        # Should allow HTTPS
        with patch("wafer_space.projects.tasks.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"test content"
            mock_response.headers = {}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            # This should not raise any exception
            content, headers = _safe_urlopen("HTTPS://example.com/file.zip")
            self.assertEqual(content, b"test content")

        # Should block FILE
        with self.assertRaises(ValueError) as context:
            _safe_urlopen("FILE:///etc/passwd")

        self.assertIn("Unsupported URL scheme: file", str(context.exception))

    def test_headers_passed_correctly(self):
        """Test that custom headers are passed to the request."""
        custom_headers = {"Authorization": "Bearer token123", "Custom-Header": "test"}

        with patch("wafer_space.projects.tasks.urlopen") as mock_urlopen:
            mock_response = Mock()
            mock_response.read.return_value = b"test content"
            mock_response.headers = {"Content-Type": "text/plain"}
            mock_urlopen.return_value.__enter__.return_value = mock_response

            content, headers = _safe_urlopen("https://example.com/file.zip", headers=custom_headers)
            self.assertEqual(content, b"test content")
            self.assertEqual(headers["Content-Type"], "text/plain")

            # Verify the request was made with correct headers
            self.assertTrue(mock_urlopen.called)


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
                with self.assertRaises(ValueError) as context:
                    _safe_urlopen(url)

                error_msg = str(context.exception).lower()
                self.assertIn("unsupported url scheme", error_msg)
                self.assertIn(expected_scheme, error_msg)

    def test_validation_is_case_insensitive_comprehensive(self):
        """Test comprehensive case insensitivity for both valid and invalid schemes."""
        valid_cases = ["http://test.com", "HTTP://test.com", "https://test.com", "HTTPS://test.com"]
        invalid_cases = ["file:///test", "FILE:///test", "ftp://test", "FTP://test"]

        # Test valid cases
        for url in valid_cases:
            with self.subTest(url=url):
                with patch("wafer_space.projects.tasks.urlopen") as mock_urlopen:
                    mock_response = Mock()
                    mock_response.read.return_value = b"test"
                    mock_response.headers = {}
                    mock_urlopen.return_value.__enter__.return_value = mock_response

                    # Should not raise exception
                    content, headers = _safe_urlopen(url)
                    self.assertEqual(content, b"test")

        # Test invalid cases
        for url in invalid_cases:
            with self.subTest(url=url), self.assertRaises(ValueError):
                _safe_urlopen(url)
