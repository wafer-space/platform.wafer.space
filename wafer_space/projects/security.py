"""Security validation for file downloads and URL handling.

Prevents SSRF (Server-Side Request Forgery) attacks and validates file downloads:
- Blocks private IP addresses (RFC 1918, RFC 4193, RFC 3927)
- Validates URL schemes (only http/https)
- Checks file sizes against limits
- Validates response headers and content types
"""

import ipaddress
import socket
from collections.abc import Mapping
from urllib.parse import urlparse

import requests


class SecurityValidationError(Exception):
    """Raised when security validation fails."""


class URLValidator:
    """Validates URLs for security issues before downloading."""

    # Maximum file size: 100GB
    MAX_FILE_SIZE = 100 * 1024 * 1024 * 1024  # 100GB in bytes

    # Allowed URL schemes
    ALLOWED_SCHEMES = {"http", "https"}

    # Private IP ranges (RFC 1918, RFC 4193, RFC 3927)
    PRIVATE_IP_RANGES = [
        ipaddress.ip_network("10.0.0.0/8"),  # RFC 1918
        ipaddress.ip_network("172.16.0.0/12"),  # RFC 1918
        ipaddress.ip_network("192.168.0.0/16"),  # RFC 1918
        ipaddress.ip_network("169.254.0.0/16"),  # RFC 3927 (link-local)
        ipaddress.ip_network("fc00::/7"),  # RFC 4193 (unique local)
        ipaddress.ip_network("fe80::/10"),  # RFC 4291 (link-local)
        ipaddress.ip_network("127.0.0.0/8"),  # Loopback
        ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ]

    @classmethod
    def validate_url_scheme(cls, url: str) -> None:
        """Validate URL scheme is allowed.

        Args:
            url: The URL to validate

        Raises:
            SecurityValidationError: If URL scheme is not allowed
        """
        parsed = urlparse(url)

        if not parsed.scheme:
            msg = "URL must include a scheme (http:// or https://)"
            raise SecurityValidationError(msg)

        if parsed.scheme.lower() not in cls.ALLOWED_SCHEMES:
            msg = (
                f"URL scheme '{parsed.scheme}' is not allowed. Use http:// or https://"
            )
            raise SecurityValidationError(msg)

    @classmethod
    def validate_hostname(cls, url: str) -> None:
        """Validate hostname is not a private IP address.

        Args:
            url: The URL to validate

        Raises:
            SecurityValidationError: If hostname resolves to a private IP
        """
        parsed = urlparse(url)
        hostname = parsed.hostname

        if not hostname:
            msg = "URL must include a hostname"
            raise SecurityValidationError(msg)

        # Check for localhost
        if hostname.lower() in ("localhost", "127.0.0.1", "::1"):
            msg = "Cannot download from localhost"
            raise SecurityValidationError(msg)

        # Try to resolve hostname to IP address
        try:
            # Get the IP address from the socket
            if parsed.hostname is None:
                msg = f"URL has no hostname: {url}"
                raise ValueError(msg)
            ip_address = socket.gethostbyname(parsed.hostname)
            ip_obj = ipaddress.ip_address(ip_address)

            # Check if IP is in private ranges
            for private_range in cls.PRIVATE_IP_RANGES:
                if ip_obj in private_range:
                    msg = f"Cannot download from private IP address: {ip_address}"
                    raise SecurityValidationError(msg)
        except (socket.gaierror, socket.herror) as e:
            msg = f"Cannot resolve hostname: {hostname}"
            raise SecurityValidationError(msg) from e
        except requests.RequestException as e:
            msg = f"Cannot connect to URL: {e}"
            raise SecurityValidationError(msg) from e

    @classmethod
    def _parse_content_length(cls, headers: Mapping[str, str]) -> int | None:
        """Parse the Content-Length header into a usable file size.

        Args:
            headers: Response headers to read Content-Length from

        Returns:
            int: The advertised file size in bytes, or None when the header
                is missing or zero. Some hosts answer HEAD requests with
                Content-Length: 0 (e.g. Google Drive) or omit the header
                entirely when using chunked transfer encoding (e.g. Dropbox),
                even though a GET serves the real file - so both cases mean
                "size unknown", not "empty file".

        Raises:
            SecurityValidationError: If the header is malformed, negative,
                or exceeds the maximum allowed size
        """
        content_length = headers.get("Content-Length")
        if not content_length:
            return None

        try:
            file_size = int(content_length)
        except ValueError as e:
            msg = f"Invalid Content-Length header: {e}"
            raise SecurityValidationError(msg) from e

        if file_size < 0:
            msg = f"Invalid file size: {file_size} bytes"
            raise SecurityValidationError(msg)

        if file_size == 0:
            return None

        if file_size > cls.MAX_FILE_SIZE:
            # File size exceeds maximum - convert to GB for error message
            size_gb = file_size / (1024 * 1024 * 1024)
            max_gb = cls.MAX_FILE_SIZE / (1024 * 1024 * 1024)
            msg = (
                f"File size {size_gb:.2f}GB exceeds maximum "
                f"allowed size of {max_gb:.0f}GB"
            )
            raise SecurityValidationError(msg)

        return file_size

    @classmethod
    def _fetch_metadata(cls, url: str) -> tuple[int, Mapping[str, str]]:
        """Fetch file size and response headers for a URL.

        Tries a HEAD request first. When that doesn't yield a usable
        Content-Length (missing, zero, or the server rejects HEAD), falls
        back to a streaming GET and reads only the response headers.

        A size of 0 means the server did not report one; the download task
        enforces the size limit on actual received bytes, so unknown sizes
        are safe to accept here.

        Args:
            url: The URL to check

        Returns:
            tuple: (file size in bytes or 0 if unknown, response headers)

        Raises:
            SecurityValidationError: If the URL is unreachable or advertises
                an invalid or oversized Content-Length
        """
        try:
            try:
                response = requests.head(url, allow_redirects=True, timeout=10)
                response.raise_for_status()
                file_size = cls._parse_content_length(response.headers)
                headers: Mapping[str, str] = response.headers
            except requests.RequestException:
                # Some servers reject HEAD requests - retry as GET below
                file_size = None
                headers = {}

            if file_size is None:
                # HEAD gave no usable size - a streaming GET reads only the
                # response headers without consuming the body
                get_response = requests.get(
                    url,
                    allow_redirects=True,
                    timeout=10,
                    stream=True,
                )
                try:
                    get_response.raise_for_status()
                    file_size = cls._parse_content_length(get_response.headers)
                    headers = get_response.headers
                finally:
                    get_response.close()
        except requests.RequestException as e:
            msg = f"Failed to check file size: {e}"
            raise SecurityValidationError(msg) from e

        return file_size or 0, headers

    @classmethod
    def validate_file_size(cls, url: str) -> int:
        """Validate file size is within allowed limits.

        Args:
            url: The URL to check

        Returns:
            int: The file size in bytes, or 0 when the server does not
                report one (the download task enforces the limit on actual
                received bytes)

        Raises:
            SecurityValidationError: If the URL is unreachable or advertises
                an invalid or oversized Content-Length
        """
        file_size, _headers = cls._fetch_metadata(url)
        return file_size

    @classmethod
    def validate_url(cls, url: str) -> dict[str, int | str | None]:
        """Perform complete URL validation.

        Args:
            url: The URL to validate

        Returns:
            dict: Validation results containing:
                - file_size: File size in bytes (0 if the server does not
                    report one)
                - content_type: Content type from server
                - content_disposition: Content-Disposition header if available
                - etag: ETag header if available
                - supports_range: Whether server supports range requests

        Raises:
            SecurityValidationError: If any validation check fails
        """
        # Validate URL scheme
        cls.validate_url_scheme(url)

        # Validate hostname is not private
        cls.validate_hostname(url)

        # Validate file size and gather response metadata in one pass
        file_size, headers = cls._fetch_metadata(url)

        return {
            "file_size": file_size,
            "content_type": headers.get("Content-Type"),
            "content_disposition": headers.get("Content-Disposition"),
            "etag": headers.get("ETag"),
            "supports_range": headers.get("Accept-Ranges") == "bytes",
        }
