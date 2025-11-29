"""Utility functions for file type detection.

This module is separate from services to avoid circular imports.
Both services.py and tasks.py can import from this module.
"""

import magic


def detect_file_type_from_data(data: bytes) -> tuple[str, str]:
    """Detect file type from actual file data using MIME type detection.

    Args:
        data: File data bytes (at least first 1MB recommended)

    Returns:
        tuple: (mime_type, file_extension)
            - mime_type: Detected MIME type (e.g., "application/gzip")
            - file_extension: Appropriate file extension (e.g., ".gds.gz")

    Raises:
        ValueError: If file type is not a valid GDS/OASIS file
    """
    # Detect MIME type from data
    mime_detector = magic.Magic(mime=True)
    mime_type = mime_detector.from_buffer(data)

    # Map MIME types to file extensions
    # GDS/OASIS files are binary formats, often detected as generic binary
    mime_to_extension = {
        # Compressed formats
        "application/gzip": ".gds.gz",  # Assume GDS compressed with gzip
        "application/x-gzip": ".gds.gz",
        "application/zip": ".gds.zip",
        "application/x-zip-compressed": ".gds.zip",
        "application/x-bzip2": ".gds.bz2",
        "application/x-xz": ".gds.xz",
        # Uncompressed - these are tricky as GDS/OASIS have no standard MIME type
        "application/octet-stream": ".gds",  # Generic binary, assume GDS
        "application/x-gds": ".gds",  # Non-standard but sometimes used
        "application/x-oasis": ".oas",
    }

    if mime_type not in mime_to_extension:
        msg = (
            f"Unsupported file type: {mime_type}. "
            f"Only GDS/OASIS files are accepted. "
            f"Supported MIME types: {', '.join(sorted(mime_to_extension.keys()))}"
        )
        raise ValueError(msg)

    extension = mime_to_extension[mime_type]
    return mime_type, extension
