"""Custom file storage for project files with correct group permissions.

This module provides a custom FileSystemStorage that creates directories with
775 permissions (owner+group write) to support the Celery worker's need to write
log files and archives alongside project files.

Background:
-----------
The Celery docker-persistent worker runs as celery-mfg:www-data and needs to write
manufacturability check logs and run archives to project directories. Django's
default FileSystemStorage creates directories with 755 permissions (owner write only),
which prevents the celery-mfg user from writing even though it's in the www-data group.

Problem:
--------
Django's FileSystemStorage passes directory_permissions_mode to os.makedirs(),
but os.makedirs() applies umask to the mode. With the typical umask of 022,
requested 775 becomes 755, stripping the group write bit.

Solution:
---------
This storage class overrides save() to explicitly chmod directories to 0o775
after creation, bypassing umask restrictions. This ensures all project directories
have the correct permissions regardless of the system umask.
"""

from __future__ import annotations

from pathlib import Path
from typing import IO
from typing import Any

from django.core.files.storage import FileSystemStorage


class ProjectFileStorage(FileSystemStorage):
    """File storage for project files with group-writable directory permissions.

    Creates directories with 0o775 (rwxrwxr-x) permissions to allow:
    - Owner (django:www-data) to read/write/execute
    - Group (www-data) to read/write/execute (enables celery-mfg writes)
    - Others to read/execute only

    This storage is used for ProjectFile.file and ManufacturabilityCheck log files.

    Note: We explicitly chmod directories after creation to bypass umask,
    which would otherwise strip the group write bit (775 -> 755).
    """

    def __init__(self, **kwargs):
        """Initialize storage with 775 directory permissions."""
        # Set directory permissions to 775 (owner+group write)
        kwargs.setdefault("directory_permissions_mode", 0o775)
        super().__init__(**kwargs)

    def save(
        self,
        name: str | None,
        content: IO[Any],
        max_length: int | None = None,
    ) -> str:
        """Save file and ensure directory has correct permissions.

        Overrides parent to explicitly chmod directories after creation,
        bypassing umask restrictions that would strip group write permission.
        """
        # Let parent handle the actual save (creates directory with makedirs)
        saved_name = super().save(name, content, max_length=max_length)

        # Get the full path to the saved file and its directory
        full_path = Path(self.path(saved_name))
        directory = full_path.parent

        # Explicitly set directory permissions to bypass umask
        # This ensures 775 even if umask would normally make it 755
        if self.directory_permissions_mode is not None:
            # Chmod all directories in the path up to the base location
            dir_path = directory
            base_path = Path(self.location)

            # Walk up from the file's directory to the base, setting permissions
            while dir_path != base_path and str(dir_path).startswith(str(base_path)):
                try:
                    current_mode = dir_path.stat().st_mode & 0o777
                    if current_mode != self.directory_permissions_mode:
                        dir_path.chmod(self.directory_permissions_mode)
                except OSError:
                    # Directory might have been removed or we lack permissions
                    pass
                dir_path = dir_path.parent

        return saved_name
