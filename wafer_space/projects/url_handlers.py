"""URL handler framework for processing downloads from various platforms.

This module provides a pluggable system for handling platform-specific URL
processing and content transformations. Each handler can:

1. Recognize URLs it can handle (via can_handle)
2. Pre-process URLs before download (via process_url)
3. Post-process downloaded content (via post_download)

Example:
    >>> registry = URLHandlerRegistry()
    >>> registry.register(GoogleSourceHandler())
    >>>
    >>> handler = registry.get_handler("https://example.googlesource.com/...")
    >>> if handler:
    ...     result = handler.process_url(url)
    ...     # Download from result["url"]
    ...     content = handler.post_download(downloaded_bytes, result["metadata"])
"""

import base64
from abc import ABC
from abc import abstractmethod
from typing import Any


class URLHandler(ABC):
    """Abstract base class for URL handlers.

    Each handler is responsible for a specific type of URL (e.g., Google Source,
    GitHub, GitLab) and can transform both the URL (before download) and the
    content (after download).
    """

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Check if this handler can process the given URL.

        Args:
            url: The URL to check

        Returns:
            bool: True if this handler can process the URL
        """

    @abstractmethod
    def process_url(self, url: str) -> dict[str, Any]:
        """Pre-process URL before download.

        This method can rewrite URLs, add query parameters, or perform other
        transformations needed before downloading the file.

        Args:
            url: The original URL

        Returns:
            dict: Contains:
                - url: The processed URL to download from
                - metadata: Handler-specific metadata to pass to post_download
        """

    @abstractmethod
    def post_download(self, content: bytes, metadata: dict[str, Any]) -> bytes:
        """Post-process downloaded content.

        This method can transform downloaded content (e.g., base64 decode,
        decompress, extract from archive).

        Args:
            content: The raw downloaded content
            metadata: Metadata from process_url

        Returns:
            bytes: The processed content
        """


class GoogleSourceHandler(URLHandler):
    """Handler for googlesource.com URLs.

    Google Source hosts Git repositories and serves file content as base64-encoded
    text when ?format=TEXT is appended to the URL. This handler:

    1. Detects *.googlesource.com URLs
    2. Adds ?format=TEXT parameter (if not present)
    3. Base64 decodes the downloaded content

    Example URLs:
        https://foss-eda-tools.googlesource.com/project/+/main/file.oas
        https://chromium.googlesource.com/chromium/src/+/refs/heads/main/DEPS
    """

    def can_handle(self, url: str) -> bool:
        """Check if URL is from googlesource.com.

        Args:
            url: URL to check

        Returns:
            bool: True if URL is from *.googlesource.com
        """
        return ".googlesource.com/" in url

    def process_url(self, url: str) -> dict[str, Any]:
        """Add ?format=TEXT parameter to URL if not already present.

        Args:
            url: Original googlesource.com URL

        Returns:
            dict: Contains processed URL and metadata
        """
        # Check if format=TEXT is already in the URL
        if "format=TEXT" in url:
            processed_url = url
        elif "?" in url:
            # URL already has query parameters, append with &
            processed_url = f"{url}&format=TEXT"
        else:
            # No query parameters, add with ?
            processed_url = f"{url}?format=TEXT"

        return {
            "url": processed_url,
            "metadata": {
                "handler": "GoogleSourceHandler",
                "base64_encoded": True,
            },
        }

    def post_download(self, content: bytes, metadata: dict[str, Any]) -> bytes:
        """Base64 decode the downloaded content.

        Google Source returns file content as base64-encoded text when
        format=TEXT is used. This method decodes it back to original bytes.

        Args:
            content: Base64-encoded content from Google Source
            metadata: Metadata from process_url (unused but required by interface)

        Returns:
            bytes: Decoded file content
        """
        return base64.b64decode(content)


class URLHandlerRegistry:
    """Registry for managing and selecting URL handlers.

    This class maintains a collection of URL handlers and selects the
    appropriate handler for a given URL based on the handler's can_handle method.

    Example:
        >>> registry = URLHandlerRegistry()
        >>> registry.register(GoogleSourceHandler())
        >>> handler = registry.get_handler("https://example.googlesource.com/file.oas")
        >>> if handler:
        ...     result = handler.process_url(url)
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._handlers: list[URLHandler] = []

    def register(self, handler: URLHandler) -> None:
        """Register a URL handler.

        Args:
            handler: The handler to register
        """
        self._handlers.append(handler)

    def get_handler(self, url: str) -> URLHandler | None:
        """Find the first handler that can process the given URL.

        Args:
            url: The URL to find a handler for

        Returns:
            URLHandler | None: The first matching handler, or None if no match
        """
        for handler in self._handlers:
            if handler.can_handle(url):
                return handler
        return None
