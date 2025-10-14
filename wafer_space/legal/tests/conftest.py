"""Pytest configuration and fixtures for legal app tests."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def mock_tos_directory(monkeypatch):
    """Mock the TOS directory to use a temporary directory during tests.

    This prevents tests from creating files in the real tos_versions directory.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_tos_dir = Path(temp_dir) / "tos_versions"
        temp_tos_dir.mkdir()

        # Mock the function that returns the TOS directory
        monkeypatch.setattr(
            "wafer_space.legal.utils.get_tos_versions_directory", lambda: temp_tos_dir
        )

        # Also mock it in the models module (already imported)
        monkeypatch.setattr(
            "wafer_space.legal.models.get_tos_versions_directory", lambda: temp_tos_dir
        )

        # And in the factories module
        monkeypatch.setattr(
            "wafer_space.legal.tests.factories.get_tos_versions_directory",
            lambda: temp_tos_dir,
        )

        yield temp_tos_dir
