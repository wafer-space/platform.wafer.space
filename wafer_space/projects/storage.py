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

Solution:
---------
This storage class overrides the default directory permissions to 0o775, enabling
group write access. This is applied at the point of directory creation during file
upload, ensuring all project directories have the correct permissions from the start.
"""

from __future__ import annotations

from django.core.files.storage import FileSystemStorage


class ProjectFileStorage(FileSystemStorage):
    """File storage for project files with group-writable directory permissions.

    Creates directories with 0o775 (rwxrwxr-x) permissions to allow:
    - Owner (django:www-data) to read/write/execute
    - Group (www-data) to read/write/execute (enables celery-mfg writes)
    - Others to read/execute only

    This storage is used for ProjectFile.file and ManufacturabilityCheck log files.
    """

    def __init__(self, **kwargs):
        """Initialize storage with 775 directory permissions."""
        # Set directory permissions to 775 (owner+group write)
        kwargs.setdefault("directory_permissions_mode", 0o775)
        super().__init__(**kwargs)
