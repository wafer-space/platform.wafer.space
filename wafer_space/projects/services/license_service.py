"""Service for license validation and caching."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import requests
from django.utils import timezone

if TYPE_CHECKING:
    from wafer_space.projects.models import Project

logger = logging.getLogger(__name__)

# Timeout for HTTP requests (seconds)
HTTP_TIMEOUT = 10.0

# HTTP status code for success
HTTP_OK = 200

# Maximum content size for fetched license terms (1 MB)
MAX_CONTENT_SIZE = 1024 * 1024

# SPDX license text base URL
SPDX_LICENSE_TEXT_URL = (
    "https://raw.githubusercontent.com/spdx/license-list-data/main/text/{spdx_id}.txt"
)


class LicenseValidationError(Exception):
    """Raised when license validation fails."""


def validate_spdx_id(spdx_id: str) -> None:
    """Validate that an SPDX identifier exists.

    Args:
        spdx_id: The SPDX license identifier to validate.

    Raises:
        LicenseValidationError: If the SPDX ID is invalid or unreachable.
    """
    url = SPDX_LICENSE_TEXT_URL.format(spdx_id=spdx_id)
    try:
        response = requests.head(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
        if response.status_code != HTTP_OK:
            msg = f"Invalid SPDX identifier: {spdx_id}"
            raise LicenseValidationError(msg)
    except requests.Timeout as e:
        msg = f"Timeout validating SPDX identifier: {spdx_id}"
        raise LicenseValidationError(msg) from e
    except requests.ConnectionError as e:
        msg = f"Connection error validating SPDX identifier: {spdx_id}"
        raise LicenseValidationError(msg) from e
    except requests.RequestException as e:
        msg = f"Error validating SPDX identifier: {spdx_id}"
        raise LicenseValidationError(msg) from e


def fetch_url_content(url: str) -> str:
    """Fetch content from a URL with size limits.

    Args:
        url: The URL to fetch.

    Returns:
        The content as a string (max 1 MB).

    Raises:
        LicenseValidationError: If the URL is unreachable, returns an error,
            or content exceeds size limit.
    """
    try:
        response = requests.get(
            url, timeout=HTTP_TIMEOUT, allow_redirects=True, stream=True
        )
        response.raise_for_status()

        # Check Content-Length header if available
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > MAX_CONTENT_SIZE:
            msg = f"Content too large (max {MAX_CONTENT_SIZE} bytes): {url}"
            raise LicenseValidationError(msg)

        # Read content with size limit
        content = b""
        for chunk in response.iter_content(chunk_size=8192):
            content += chunk
            if len(content) > MAX_CONTENT_SIZE:
                msg = (
                    f"Content exceeds size limit (max {MAX_CONTENT_SIZE} bytes): {url}"
                )
                raise LicenseValidationError(msg)

        return content.decode("utf-8")
    except requests.Timeout as e:
        msg = f"Timeout fetching URL: {url}"
        raise LicenseValidationError(msg) from e
    except requests.ConnectionError as e:
        msg = f"Connection error fetching URL: {url}"
        raise LicenseValidationError(msg) from e
    except requests.HTTPError as e:
        msg = f"Error fetching URL ({e.response.status_code}): {url}"
        raise LicenseValidationError(msg) from e
    except requests.RequestException as e:
        msg = f"Error fetching URL: {url}"
        raise LicenseValidationError(msg) from e
    except UnicodeDecodeError as e:
        msg = f"Content is not valid UTF-8 text: {url}"
        raise LicenseValidationError(msg) from e


def cache_proprietary_terms(project: Project, terms_url: str) -> None:
    """Fetch and cache proprietary license terms.

    Args:
        project: The project to update.
        terms_url: The URL to fetch terms from.

    Raises:
        LicenseValidationError: If the URL cannot be fetched.
    """
    content = fetch_url_content(terms_url)
    project.proprietary_terms_cached = content
    project.proprietary_terms_cached_at = timezone.now()
