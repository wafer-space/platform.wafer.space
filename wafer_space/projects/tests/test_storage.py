"""Tests for custom ProjectFileStorage with correct directory permissions.

These tests verify that project directories are created with 0o775 permissions
to allow the Celery worker (celery-mfg:www-data) to write log files alongside
project files uploaded by Django (django:www-data).
"""

from __future__ import annotations

import stat
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile

from wafer_space.projects.storage import ProjectFileStorage

# Permission constants for directory mode checks
GROUP_WRITABLE_PERMISSIONS = 0o775  # rwxrwxr-x - allows group write
OWNER_ONLY_WRITABLE_PERMISSIONS = 0o755  # rwxr-xr-x - owner write only


def test_project_file_storage_creates_directories_with_775_permissions():
    """Test that ProjectFileStorage creates directories with 0o775 permissions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create storage with temp directory
        storage = ProjectFileStorage(location=tmpdir)

        # Save a file in a nested directory structure
        test_content = ContentFile(b"test content")
        saved_path = storage.save("projects/test-uuid/test.gds", test_content)

        # Check that the directory was created with 775 permissions
        project_dir = Path(tmpdir) / "projects" / "test-uuid"
        assert project_dir.exists()

        # Get actual permissions (masking out file type bits)
        dir_stat = project_dir.stat()
        dir_mode = stat.S_IMODE(dir_stat.st_mode)

        # Should be 0o775 (rwxrwxr-x)
        assert dir_mode == GROUP_WRITABLE_PERMISSIONS, (
            f"Directory permissions are {oct(dir_mode)}, expected 0o775. "
            f"This means group write is not enabled, preventing celery-mfg "
            f"from writing log files."
        )

        # Clean up
        storage.delete(saved_path)


def test_project_file_storage_default_directory_permissions():
    """Test that ProjectFileStorage has correct default directory_permissions_mode."""
    storage = ProjectFileStorage()
    assert storage.directory_permissions_mode == GROUP_WRITABLE_PERMISSIONS


def test_project_file_storage_allows_override_directory_permissions():
    """Test that directory_permissions_mode can be overridden if needed."""
    storage = ProjectFileStorage(
        directory_permissions_mode=OWNER_ONLY_WRITABLE_PERMISSIONS
    )
    assert storage.directory_permissions_mode == OWNER_ONLY_WRITABLE_PERMISSIONS


def test_project_file_storage_creates_nested_directories():
    """Test that all intermediate directories get correct permissions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = ProjectFileStorage(location=tmpdir)

        # Create deeply nested path
        test_content = ContentFile(b"test content")
        saved_path = storage.save(
            "projects/uuid1/subdir1/subdir2/test.gds", test_content
        )

        # Check all directories have 775
        base_path = Path(tmpdir)
        for subdir in ["projects", "projects/uuid1", "projects/uuid1/subdir1"]:
            dir_path = base_path / subdir
            dir_mode = stat.S_IMODE(dir_path.stat().st_mode)
            assert dir_mode == GROUP_WRITABLE_PERMISSIONS, (
                f"Directory {subdir} has permissions {oct(dir_mode)}, expected 0o775"
            )

        # Clean up
        storage.delete(saved_path)
