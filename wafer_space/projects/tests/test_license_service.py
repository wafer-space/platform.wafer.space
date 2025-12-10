"""Tests for license validation service."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import requests

from wafer_space.projects.services.license_service import LicenseValidationError
from wafer_space.projects.services.license_service import cache_proprietary_terms
from wafer_space.projects.services.license_service import fetch_url_content
from wafer_space.projects.services.license_service import validate_spdx_id


class TestValidateSpdxId:
    """Tests for validate_spdx_id function."""

    def test_valid_spdx_id_succeeds(self):
        """Valid SPDX ID does not raise an error."""
        patch_path = "wafer_space.projects.services.license_service.requests.head"
        with patch(patch_path) as mock_head:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_head.return_value = mock_response

            # Should not raise
            validate_spdx_id("MIT")

    def test_invalid_spdx_id_raises_error(self):
        """Invalid SPDX ID raises LicenseValidationError."""
        patch_path = "wafer_space.projects.services.license_service.requests.head"
        with patch(patch_path) as mock_head:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_head.return_value = mock_response

            with pytest.raises(LicenseValidationError, match="Invalid SPDX identifier"):
                validate_spdx_id("NOT-A-REAL-LICENSE")

    def test_timeout_raises_error(self):
        """Timeout raises LicenseValidationError."""
        patch_path = "wafer_space.projects.services.license_service.requests.head"
        with patch(patch_path) as mock_head:
            mock_head.side_effect = requests.Timeout("timeout")

            with pytest.raises(LicenseValidationError, match="Timeout"):
                validate_spdx_id("MIT")


class TestFetchUrlContent:
    """Tests for fetch_url_content function."""

    def test_successful_fetch_returns_content(self):
        """Successful fetch returns content."""
        patch_path = "wafer_space.projects.services.license_service.requests.get"
        with patch(patch_path) as mock_get:
            mock_response = MagicMock()
            mock_response.headers = {"content-length": "20"}
            mock_response.iter_content.return_value = [b"License text content"]
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = fetch_url_content("https://example.com/license.txt")
            assert result == "License text content"

    def test_http_error_raises_validation_error(self):
        """HTTP error raises LicenseValidationError."""
        patch_path = "wafer_space.projects.services.license_service.requests.get"
        with patch(patch_path) as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 404
            error = requests.HTTPError("Not found")
            error.response = mock_response
            mock_response.raise_for_status.side_effect = error
            mock_get.return_value = mock_response

            with pytest.raises(LicenseValidationError, match="Error fetching URL"):
                fetch_url_content("https://example.com/nonexistent.txt")

    def test_timeout_raises_validation_error(self):
        """Timeout raises LicenseValidationError."""
        patch_path = "wafer_space.projects.services.license_service.requests.get"
        with patch(patch_path) as mock_get:
            mock_get.side_effect = requests.Timeout("timeout")

            with pytest.raises(LicenseValidationError, match="Timeout"):
                fetch_url_content("https://example.com/slow.txt")


class TestCacheProprietaryTerms:
    """Tests for cache_proprietary_terms function."""

    def test_caches_content_and_timestamp(self):
        """Caches content and sets timestamp."""
        patch_path = "wafer_space.projects.services.license_service.fetch_url_content"
        with patch(patch_path) as mock_fetch:
            mock_fetch.return_value = "Proprietary license terms..."

            mock_project = MagicMock()
            mock_project.proprietary_terms_cached = ""
            mock_project.proprietary_terms_cached_at = None

            cache_proprietary_terms(mock_project, "https://example.com/terms.txt")

            expected_content = "Proprietary license terms..."
            assert mock_project.proprietary_terms_cached == expected_content
            assert mock_project.proprietary_terms_cached_at is not None

    def test_fetch_failure_propagates_error(self):
        """Fetch failure propagates LicenseValidationError."""
        patch_path = "wafer_space.projects.services.license_service.fetch_url_content"
        with patch(patch_path) as mock_fetch:
            mock_fetch.side_effect = LicenseValidationError("Could not fetch")

            mock_project = MagicMock()

            with pytest.raises(LicenseValidationError):
                cache_proprietary_terms(mock_project, "https://example.com/bad.txt")
