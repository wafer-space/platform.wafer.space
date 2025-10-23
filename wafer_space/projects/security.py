"""Security validation for file downloads and URL handling.

Prevents SSRF (Server-Side Request Forgery) attacks and validates file downloads:
- Blocks private IP addresses (RFC 1918, RFC 4193, RFC 3927)
- Validates URL schemes (only http/https)
- Checks file sizes against limits
- Validates response headers and content types
"""

import ipaddress
import socket
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
    def validate_file_size(
        cls,
        url: str,
        *,
        allow_missing_content_length: bool = False,
    ) -> int:
        """Validate file size is within allowed limits.

        Args:
            url: The URL to check
            allow_missing_content_length: If True, return 0 when Content-Length
                is missing (useful for URLs with special handlers that transform
                content, like Google Source base64-encoded responses)

        Returns:
            int: The file size in bytes (or 0 if Content-Length missing and
                allowed)

        Raises:
            SecurityValidationError: If file size exceeds limits or cannot be determined
        """
        try:
            response = requests.head(url, allow_redirects=True, timeout=10)
            response.raise_for_status()

            content_length = response.headers.get("Content-Length")
            if not content_length:
                if allow_missing_content_length:
                    # Content-Length not provided, but allowed for this URL
                    # (e.g., Google Source base64-encoded responses)
                    return 0
                msg = (
                    "Server did not provide Content-Length header. "
                    "Cannot validate file size."
                )
                raise SecurityValidationError(msg)

            file_size = int(content_length)

            if file_size <= 0:
                msg = f"Invalid file size: {file_size} bytes"
                raise SecurityValidationError(msg)

            # Check if file size is within acceptable limits
            if file_size <= cls.MAX_FILE_SIZE:
                return file_size

            # File size exceeds maximum - convert to GB for error message
            size_gb = file_size / (1024 * 1024 * 1024)
            max_gb = cls.MAX_FILE_SIZE / (1024 * 1024 * 1024)
            msg = (
                f"File size {size_gb:.2f}GB exceeds maximum "
                f"allowed size of {max_gb:.0f}GB"
            )
            raise SecurityValidationError(msg)
        except requests.RequestException as e:
            msg = f"Failed to check file size: {e}"
            raise SecurityValidationError(msg) from e
        except ValueError as e:
            msg = f"Invalid Content-Length header: {e}"
            raise SecurityValidationError(msg) from e

    @classmethod
    def validate_url(
        cls,
        url: str,
        *,
        allow_missing_content_length: bool = False,
    ) -> dict[str, int | str | None]:
        """Perform complete URL validation.

        Args:
            url: The URL to validate
            allow_missing_content_length: If True, allow missing Content-Length header
                                         (useful for URLs with special handlers)

        Returns:
            dict: Validation results containing:
                - file_size: File size in bytes (0 if Content-Length missing
                    and allowed)
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

        # Validate file size
        file_size = cls.validate_file_size(
            url,
            allow_missing_content_length=allow_missing_content_length,
        )

        # Get additional metadata from HEAD request
        try:
            response = requests.head(url, allow_redirects=True, timeout=10)
            response.raise_for_status()

            return {
                "file_size": file_size,
                "content_type": response.headers.get("Content-Type"),
                "content_disposition": response.headers.get("Content-Disposition"),
                "etag": response.headers.get("ETag"),
                "supports_range": response.headers.get("Accept-Ranges") == "bytes",
            }
        except requests.RequestException as e:
            msg = f"Failed to retrieve file metadata: {e}"
            raise SecurityValidationError(msg) from e
