"""URL handler framework for processing downloads from various platforms.

This module provides a pluggable system for handling platform-specific URL
processing and content transformations. Each handler can:

1. Recognize URLs it can handle (via can_handle)
2. Pre-process URLs before download (via process_url)
3. Post-process the downloaded file on disk (via post_download_file)

Example:
    >>> registry = URLHandlerRegistry()
    >>> registry.register(GoogleSourceHandler())
    >>>
    >>> handler = registry.get_handler("https://example.googlesource.com/...")
    >>> if handler:
    ...     result = handler.process_url(url)
    ...     # Download from result["url"]
    ...     content_path = handler.post_download_file(downloaded_path, meta)
"""

import base64
import binascii
import os
import re
from abc import ABC
from abc import abstractmethod
from pathlib import Path
from typing import IO
from typing import Any

# Read size for streaming post-download transforms (issue #139).
DECODE_CHUNK_SIZE = 1024 * 1024
_B64_ALPHABET = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
)
# Bytes base64.b64decode(validate=False) would skip (googlesource's line breaks).
_NON_B64 = bytes(b for b in range(256) if b not in _B64_ALPHABET)


def _stream_b64decode(src: IO[bytes], dst: IO[bytes]) -> None:
    """Decode base64 from src to dst in DECODE_CHUNK_SIZE reads.

    Non-alphabet bytes are dropped, as base64.b64decode(validate=False)
    does. Padding ('=') may only end the stream: b64decode(validate=True)
    rejects it within a block, and seen_padding rejects data after a block
    that ended in padding.
    """
    carry = b""
    seen_padding = False
    while chunk := src.read(DECODE_CHUNK_SIZE):
        data = carry + chunk.translate(None, _NON_B64)
        if seen_padding and data:
            msg = "Invalid base64 in googlesource download: data after padding"
            raise ValueError(msg)
        usable = len(data) - len(data) % 4
        block = data[:usable]
        dst.write(_b64decode_strict(block))
        if block:
            seen_padding = block.endswith(b"=")
        carry = data[usable:]
    if carry:
        msg = "Invalid base64 in googlesource download: truncated final group"
        raise ValueError(msg)


def _b64decode_strict(data: bytes) -> bytes:
    """Decode whole 4-byte groups, rejecting padding before their end."""
    try:
        return base64.b64decode(data, validate=True)
    except binascii.Error as exc:
        msg = f"Invalid base64 in googlesource download: {exc}"
        raise ValueError(msg) from exc


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
                - metadata: Handler-specific metadata to pass to post_download_file
        """

    def post_download_file(self, path: Path, metadata: dict[str, Any]) -> Path:
        """Return the file holding the content to process, without reading it whole.

        The default returns ``path`` itself. Handlers that transform content
        (e.g. base64 decode) write a new sibling file in bounded chunks and
        return it, leaving the download byte-exact: a retry resumes the
        download with an HTTP Range request against the original stream, so
        the download must never be rewritten in place (issue #139).

        Args:
            path: The downloaded file on disk (not modified)
            metadata: Metadata from process_url

        Returns:
            Path: The file the content pipeline should process
        """
        return path


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

    def post_download_file(self, path: Path, metadata: dict[str, Any]) -> Path:
        """Base64 decode the download into a sibling file, in bounded chunks.

        Google Source returns file content as base64-encoded text when
        format=TEXT is used. The decoded bytes go to ``<path>.decoded``; the
        download itself stays byte-exact so a retry can resume it.

        Args:
            path: Base64-encoded download from Google Source (not modified)
            metadata: Metadata from process_url (unused but required by interface)

        Returns:
            Path: The decoded file

        Raises:
            ValueError: If the content is not valid base64
            OSError: If the decoded file cannot be written
        """
        decoded_path = Path(os.fspath(path) + ".decoded")
        try:
            with path.open("rb") as src, decoded_path.open("wb") as dst:
                _stream_b64decode(src, dst)
        except (ValueError, OSError):
            decoded_path.unlink(missing_ok=True)
            raise
        return decoded_path


class GitHubArtifactHandler(URLHandler):
    """Handler for GitHub Actions artifact URLs.

    GitHub Actions artifacts require authentication and URL transformation:

    1. Input URL formats:
       - Run URL (selects first artifact):
         https://github.com/{owner}/{repo}/actions/runs/{run_id}
       - Specific artifact URL:
         https://github.com/{owner}/{repo}/actions/runs/{run_id}/artifacts/{artifact_id}

    2. API URLs:
       - List artifacts: GET https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts
       - Download: GET https://api.github.com/repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip

    3. Authentication:
       - Requires GitHub PAT with 'actions:read' permission
       - Header: Authorization: Bearer {token}

    The handler:
    - Detects GitHub Actions URLs
    - Extracts owner/repo/run_id and optionally artifact_id from URL
    - Stores this metadata for download task to use
    - Download task will call GitHub API to get artifact list
    - If artifact_id provided, downloads that specific artifact
    - Otherwise downloads the first artifact from the run

    Note: Artifact download URLs redirect to temporary signed URLs that
    expire after 60 seconds, so we don't pre-fetch them here.
    """

    # Pattern: https://github.com/{owner}/{repo}/actions/runs/{run_id}[/artifacts/{artifact_id}]
    # Also supports query strings like ?check_suite_focus=true
    GITHUB_ACTIONS_URL_PATTERN = re.compile(
        r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/actions/runs/"
        r"(?P<run_id>\d+)(?:/artifacts/(?P<artifact_id>\d+))?(?:[/?].*)?$"
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
        """Extract owner/repo/run_id and optional artifact_id from GitHub Actions URL.

        The URL is not transformed here because:
        - Artifact download requires API call with authentication
        - Download task will handle the GitHub API calls
        - If artifact_id is provided, it downloads that specific artifact
        - Otherwise it lists artifacts and downloads the first one

        Args:
            url: Original GitHub Actions run URL (optionally with artifact ID)

        Returns:
            dict: Contains original URL and metadata with owner/repo/run_id
                  and optionally artifact_id
        """
        match = self.GITHUB_ACTIONS_URL_PATTERN.match(url)
        if not match:
            msg = f"Invalid GitHub Actions URL format: {url}"
            raise ValueError(msg)

        metadata = {
            "handler": "GitHubArtifactHandler",
            "owner": match.group("owner"),
            "repo": match.group("repo"),
            "run_id": match.group("run_id"),
            "requires_github_auth": True,
        }

        # Include artifact_id if specified in URL
        artifact_id = match.group("artifact_id")
        if artifact_id:
            metadata["artifact_id"] = artifact_id

        return {
            "url": url,  # Keep original URL, download task will use API
            "metadata": metadata,
        }


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
