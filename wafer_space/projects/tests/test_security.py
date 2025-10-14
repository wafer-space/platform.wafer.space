"""Tests for security validation module."""

import socket
from unittest.mock import Mock
from unittest.mock import patch

import pytest
import requests

from wafer_space.projects.security import SecurityValidationError
from wafer_space.projects.security import URLValidator

from .constants import EXPECTED_IP_RANGE_COUNT
from .constants import ONE_MB


class TestURLValidator:
    """Test URLValidator class for security validation."""

    def test_validate_url_scheme_http_allowed(self):
        """Test that HTTP URLs are allowed."""
        url = "http://example.com/file.gds"
        # Should not raise exception
        URLValidator.validate_url_scheme(url)

    def test_validate_url_scheme_https_allowed(self):
        """Test that HTTPS URLs are allowed."""
        url = "https://example.com/file.gds"
        # Should not raise exception
        URLValidator.validate_url_scheme(url)

    def test_validate_url_scheme_missing(self):
        """Test that URLs without scheme are rejected."""
        url = "example.com/file.gds"

        with pytest.raises(SecurityValidationError, match="must include a scheme"):
            URLValidator.validate_url_scheme(url)

    def test_validate_url_scheme_ftp_rejected(self):
        """Test that FTP URLs are rejected."""
        url = "ftp://example.com/file.gds"

        with pytest.raises(SecurityValidationError, match="not allowed"):
            URLValidator.validate_url_scheme(url)

    def test_validate_url_scheme_file_rejected(self):
        """Test that file:// URLs are rejected."""
        url = "file:///local/path/file.gds"

        with pytest.raises(SecurityValidationError, match="not allowed"):
            URLValidator.validate_url_scheme(url)

    def test_validate_hostname_localhost_rejected(self):
        """Test that localhost hostnames are rejected."""
        test_cases = [
            "http://localhost/file.gds",
            "http://127.0.0.1/file.gds",
            "http://[::1]/file.gds",
        ]

        for url in test_cases:
            match_str = "Cannot download from localhost"
            with pytest.raises(SecurityValidationError, match=match_str):
                URLValidator.validate_hostname(url)

    def test_validate_hostname_missing(self):
        """Test that URLs without hostname are rejected."""
        url = "http:///file.gds"

        with pytest.raises(SecurityValidationError, match="must include a hostname"):
            URLValidator.validate_hostname(url)

    @patch("socket.gethostbyname")
    @patch("requests.head")
    def test_validate_hostname_private_ip_rejected(self, mock_head, mock_gethostbyname):
        """Test that private IP addresses are rejected."""
        # Mock DNS resolution to return private IP
        mock_gethostbyname.return_value = "192.168.1.1"
        mock_head.return_value = Mock(status_code=200)

        url = "http://internal.example.com/file.gds"

        with pytest.raises(SecurityValidationError, match="private IP address"):
            URLValidator.validate_hostname(url)

    @patch("socket.gethostbyname")
    @patch("requests.head")
    def test_validate_hostname_rfc1918_ranges_rejected(
        self,
        mock_head,
        mock_gethostbyname,
    ):
        """Test that all RFC 1918 private IP ranges are rejected."""
        mock_head.return_value = Mock(status_code=200)

        test_cases = [
            ("10.0.0.1", "10.0.0.0/8"),
            ("172.16.0.1", "172.16.0.0/12"),
            ("192.168.0.1", "192.168.0.0/16"),
            ("169.254.0.1", "169.254.0.0/16"),  # Link-local
        ]

        for ip, _description in test_cases:
            mock_gethostbyname.return_value = ip
            url = f"http://host-{ip.replace('.', '-')}.example.com/file.gds"

            with pytest.raises(SecurityValidationError, match="private IP address"):
                URLValidator.validate_hostname(url)

    @patch("socket.gethostbyname")
    @patch("requests.head")
    def test_validate_hostname_unresolvable_rejected(
        self,
        mock_head,
        mock_gethostbyname,
    ):
        """Test that unresolvable hostnames are rejected."""
        # Mock requests.head to succeed (so it doesn't fail first)
        mock_head.return_value = Mock(status_code=200)

        # Mock socket.gethostbyname to raise error
        mock_gethostbyname.side_effect = socket.gaierror("Name or service not known")

        url = "http://nonexistent.example.com/file.gds"

        with pytest.raises(SecurityValidationError, match="Cannot resolve hostname"):
            URLValidator.validate_hostname(url)

    @patch("requests.head")
    def test_validate_file_size_success(self, mock_head):
        """Test successful file size validation."""
        # Mock response with Content-Length header
        mock_response = Mock()
        mock_response.headers = {"Content-Length": str(ONE_MB)}  # 1 MB
        mock_response.raise_for_status = Mock()
        mock_head.return_value = mock_response

        url = "http://example.com/file.gds"
        file_size = URLValidator.validate_file_size(url)

        assert file_size == ONE_MB
        mock_head.assert_called_once()

    @patch("requests.head")
    def test_validate_file_size_missing_content_length(self, mock_head):
        """Test that missing Content-Length header is rejected."""
        # Mock response without Content-Length header
        mock_response = Mock()
        mock_response.headers = {}
        mock_response.raise_for_status = Mock()
        mock_head.return_value = mock_response

        url = "http://example.com/file.gds"

        match_str = "did not provide Content-Length"
        with pytest.raises(SecurityValidationError, match=match_str):
            URLValidator.validate_file_size(url)

    @patch("requests.head")
    def test_validate_file_size_exceeds_limit(self, mock_head):
        """Test that files exceeding 100GB limit are rejected."""
        # Mock response with size > 100GB
        mock_response = Mock()
        size_101gb = 101 * 1024 * 1024 * 1024
        mock_response.headers = {"Content-Length": str(size_101gb)}
        mock_response.raise_for_status = Mock()
        mock_head.return_value = mock_response

        url = "http://example.com/huge_file.gds"

        match_str = "exceeds maximum allowed size"
        with pytest.raises(SecurityValidationError, match=match_str):
            URLValidator.validate_file_size(url)

    @patch("requests.head")
    def test_validate_file_size_zero_rejected(self, mock_head):
        """Test that zero-byte files are rejected."""
        # Mock response with zero size
        mock_response = Mock()
        mock_response.headers = {"Content-Length": "0"}
        mock_response.raise_for_status = Mock()
        mock_head.return_value = mock_response

        url = "http://example.com/empty_file.gds"

        with pytest.raises(SecurityValidationError, match="Invalid file size"):
            URLValidator.validate_file_size(url)

    @patch("requests.head")
    def test_validate_file_size_negative_rejected(self, mock_head):
        """Test that negative file sizes are rejected."""
        # Mock response with negative size
        mock_response = Mock()
        mock_response.headers = {"Content-Length": "-100"}
        mock_response.raise_for_status = Mock()
        mock_head.return_value = mock_response

        url = "http://example.com/file.gds"

        with pytest.raises(SecurityValidationError, match="Invalid file size"):
            URLValidator.validate_file_size(url)

    @patch("requests.head")
    def test_validate_file_size_invalid_content_length(self, mock_head):
        """Test that invalid Content-Length values are rejected."""
        # Mock response with non-numeric Content-Length
        mock_response = Mock()
        mock_response.headers = {"Content-Length": "not-a-number"}
        mock_response.raise_for_status = Mock()
        mock_head.return_value = mock_response

        url = "http://example.com/file.gds"

        with pytest.raises(SecurityValidationError, match="Invalid Content-Length"):
            URLValidator.validate_file_size(url)

    @patch("requests.head")
    def test_validate_file_size_request_error(self, mock_head):
        """Test that network errors are caught."""
        # Mock request exception
        mock_head.side_effect = requests.RequestException("Connection timeout")

        url = "http://example.com/file.gds"

        with pytest.raises(SecurityValidationError, match="Failed to check file size"):
            URLValidator.validate_file_size(url)

    @patch("requests.head")
    def test_validate_file_size_http_error(self, mock_head):
        """Test that HTTP errors are caught."""
        # Mock HTTP error response
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        mock_head.return_value = mock_response

        url = "http://example.com/file.gds"

        with pytest.raises(SecurityValidationError, match="Failed to check file size"):
            URLValidator.validate_file_size(url)

    @patch("socket.gethostbyname")
    @patch("requests.head")
    def test_validate_url_complete_success(self, mock_head, mock_gethostbyname):
        """Test complete URL validation with all checks passing."""
        # Mock DNS resolution to public IP
        mock_gethostbyname.return_value = "93.184.216.34"  # example.com

        # Mock HEAD request response
        mock_response = Mock()
        mock_response.headers = {
            "Content-Length": str(ONE_MB),  # 1 MB
            "Content-Type": "application/octet-stream",
            "ETag": '"abc123"',
            "Accept-Ranges": "bytes",
        }
        mock_response.raise_for_status = Mock()
        mock_head.return_value = mock_response

        url = "https://example.com/file.gds"
        result = URLValidator.validate_url(url)

        assert result["file_size"] == ONE_MB
        assert result["content_type"] == "application/octet-stream"
        assert result["etag"] == '"abc123"'
        assert result["supports_range"] is True

    @patch("socket.gethostbyname")
    @patch("requests.head")
    def test_validate_url_no_range_support(self, mock_head, mock_gethostbyname):
        """Test URL validation when server doesn't support Range requests."""
        # Mock DNS resolution
        mock_gethostbyname.return_value = "93.184.216.34"

        # Mock HEAD request without Range support
        mock_response = Mock()
        mock_response.headers = {
            "Content-Length": str(ONE_MB),
            "Content-Type": "application/octet-stream",
        }
        mock_response.raise_for_status = Mock()
        mock_head.return_value = mock_response

        url = "https://example.com/file.gds"
        result = URLValidator.validate_url(url)

        assert result["file_size"] == ONE_MB
        assert result["supports_range"] is False
        assert result["etag"] is None

    def test_validate_url_invalid_scheme(self):
        """Test that validate_url rejects invalid schemes."""
        url = "ftp://example.com/file.gds"

        with pytest.raises(SecurityValidationError, match="not allowed"):
            URLValidator.validate_url(url)

    @patch("requests.head")
    def test_validate_url_localhost(self, mock_head):
        """Test that validate_url rejects localhost."""
        url = "http://localhost/file.gds"

        with pytest.raises(SecurityValidationError, match="localhost"):
            URLValidator.validate_url(url)

    @patch("socket.gethostbyname")
    @patch("requests.head")
    def test_validate_url_private_ip(self, mock_head, mock_gethostbyname):
        """Test that validate_url rejects private IPs."""
        mock_gethostbyname.return_value = "10.0.0.1"
        mock_head.return_value = Mock(status_code=200)

        url = "http://internal.example.com/file.gds"

        with pytest.raises(SecurityValidationError, match="private IP"):
            URLValidator.validate_url(url)

    @patch("socket.gethostbyname")
    @patch("requests.head")
    def test_validate_url_file_too_large(self, mock_head, mock_gethostbyname):
        """Test that validate_url rejects files > 100GB."""
        mock_gethostbyname.return_value = "93.184.216.34"

        # Mock response with size > 100GB
        mock_response = Mock()
        size_101gb = 101 * 1024 * 1024 * 1024
        mock_response.headers = {"Content-Length": str(size_101gb)}
        mock_response.raise_for_status = Mock()
        mock_head.return_value = mock_response

        url = "https://example.com/huge_file.gds"

        with pytest.raises(SecurityValidationError, match="exceeds maximum"):
            URLValidator.validate_url(url)

    def test_max_file_size_constant(self):
        """Test that MAX_FILE_SIZE is 100GB."""
        assert URLValidator.MAX_FILE_SIZE == 100 * 1024 * 1024 * 1024

    def test_allowed_schemes_constant(self):
        """Test that only http and https are allowed."""
        assert {"http", "https"} == URLValidator.ALLOWED_SCHEMES

    def test_private_ip_ranges_defined(self):
        """Test that private IP ranges are properly defined."""
        # Should include RFC 1918, RFC 4193, RFC 3927, and loopback
        assert len(URLValidator.PRIVATE_IP_RANGES) >= EXPECTED_IP_RANGE_COUNT

        # Check for some key ranges
        range_strings = [str(r) for r in URLValidator.PRIVATE_IP_RANGES]
        assert "10.0.0.0/8" in range_strings
        assert "172.16.0.0/12" in range_strings
        assert "192.168.0.0/16" in range_strings
        assert "127.0.0.0/8" in range_strings
