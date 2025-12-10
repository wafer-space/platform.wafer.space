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

# SPDX license text base URL
SPDX_LICENSE_TEXT_URL = (
    "https://raw.githubusercontent.com/spdx/license-list-data/main/text/{spdx_id}.txt"
)


class LicenseValidationError(Exception):
    """Raised when license validation fails."""


def validate_spdx_id(spdx_id: str) -> bool:
    """Validate that an SPDX identifier exists.

    Args:
        spdx_id: The SPDX license identifier to validate.

    Returns:
        True if valid, False otherwise.

    Raises:
        LicenseValidationError: If the SPDX ID is invalid or unreachable.
    """
    url = SPDX_LICENSE_TEXT_URL.format(spdx_id=spdx_id)
    try:
        response = requests.head(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
        if response.status_code == HTTP_OK:
            return True
        msg = f"Invalid SPDX identifier: {spdx_id}"
        raise LicenseValidationError(msg)
    except requests.Timeout as e:
        msg = f"Timeout validating SPDX identifier: {spdx_id}"
        raise LicenseValidationError(msg) from e
    except requests.RequestException as e:
        msg = f"Error validating SPDX identifier: {spdx_id}"
        raise LicenseValidationError(msg) from e


def fetch_url_content(url: str) -> str:
    """Fetch content from a URL.

    Args:
        url: The URL to fetch.

    Returns:
        The content as a string.

    Raises:
        LicenseValidationError: If the URL is unreachable or returns an error.
    """
    try:
        response = requests.get(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
    except requests.Timeout as e:
        msg = f"Timeout fetching URL: {url}"
        raise LicenseValidationError(msg) from e
    except requests.HTTPError as e:
        msg = f"Error fetching URL ({e.response.status_code}): {url}"
        raise LicenseValidationError(msg) from e
    except requests.RequestException as e:
        msg = f"Error fetching URL: {url}"
        raise LicenseValidationError(msg) from e
    else:
        return response.text


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
