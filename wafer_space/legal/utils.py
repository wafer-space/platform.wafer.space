"""Utility functions for the legal app."""

from pathlib import Path


def get_tos_versions_directory() -> Path:
    """Get the directory where TOS version files are stored.

    Returns:
        Path to the tos_versions directory.
    """
    return Path(__file__).parent / "tos_versions"
