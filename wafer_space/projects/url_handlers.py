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
import re
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


class GitHubArtifactHandler(URLHandler):
    """Handler for GitHub Actions artifact URLs.

    GitHub Actions artifacts require authentication and URL transformation:

    1. Input URL format:
       https://github.com/{owner}/{repo}/actions/runs/{run_id}

    2. API URLs:
       - List artifacts: GET https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts
       - Download: GET https://api.github.com/repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip

    3. Authentication:
       - Requires GitHub PAT with 'actions:read' permission
       - Header: Authorization: Bearer {token}

    The handler:
    - Detects GitHub Actions URLs
    - Extracts owner/repo/run_id from URL
    - Stores this metadata for download task to use
    - Download task will call GitHub API to get artifact list
    - Then download the artifact ZIP

    Note: Artifact download URLs redirect to temporary signed URLs that
    expire after 60 seconds, so we don't pre-fetch them here.
    """

    # Pattern: https://github.com/{owner}/{repo}/actions/runs/{run_id}
    GITHUB_ACTIONS_URL_PATTERN = re.compile(
        r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/actions/runs/(?P<run_id>\d+)(?:/.*)?$"
    )

    def can_handle(self, url: str) -> bool:
        """Check if URL is a GitHub Actions run URL.

        Args:
            url: URL to check

        Returns:
            bool: True if URL matches GitHub Actions runs pattern
        """
        return bool(self.GITHUB_ACTIONS_URL_PATTERN.match(url))

    def process_url(self, url: str) -> dict[str, Any]:
        """Extract owner/repo/run_id from GitHub Actions URL.

        The URL is not transformed here because:
        - Artifact list requires API call with authentication
        - Artifact ID is not known until list is fetched
        - Download task will handle the GitHub API calls

        Args:
            url: Original GitHub Actions run URL

        Returns:
            dict: Contains original URL and metadata with owner/repo/run_id
        """
        match = self.GITHUB_ACTIONS_URL_PATTERN.match(url)
        if not match:
            msg = f"Invalid GitHub Actions URL format: {url}"
            raise ValueError(msg)

        return {
            "url": url,  # Keep original URL, download task will use API
            "metadata": {
                "handler": "GitHubArtifactHandler",
                "owner": match.group("owner"),
                "repo": match.group("repo"),
                "run_id": match.group("run_id"),
                "requires_github_auth": True,
            },
        }

    def post_download(self, content: bytes, metadata: dict[str, Any]) -> bytes:  # noqa: ARG002
        """Pass through artifact ZIP content without transformation.

        GitHub artifacts are downloaded as ZIP files and don't need
        any post-processing (unlike Google Source which needs base64 decode).

        Args:
            content: Downloaded artifact ZIP content
            metadata: Metadata from process_url (unused but required by interface)

        Returns:
            bytes: Unmodified ZIP content
        """
        return content


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
