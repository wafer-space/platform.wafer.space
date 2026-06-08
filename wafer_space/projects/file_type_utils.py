"""Utility functions for file type detection.

This module is separate from services to avoid circular imports.
Both services.py and tasks.py can import from this module.
"""

import magic

# GDSII files begin with a HEADER record: 2-byte length (0x0006), 1-byte record
# type (0x00 = HEADER), 1-byte data type (0x02 = two-byte integer).
GDS_SIGNATURE = b"\x00\x06\x00\x02"

# OASIS files begin with the magic string defined by SEMI P39/P44.
OASIS_SIGNATURE = b"%SEMI-OASIS\r\n"

# Zip local-file-header / empty-archive / spanned-archive signatures. Detected
# explicitly because libmagic identifies a zip via the End-Of-Central-Directory
# record at the *end* of the archive, which ``magic.from_buffer`` cannot seek to
# (and which is absent when only the first chunk of a large upload is passed).
# Recent libmagic (file 5.46) therefore reports a real zip as
# ``application/octet-stream`` in buffer mode.
ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

# Compressed wrappers libmagic reliably identifies from their leading bytes.
_COMPRESSED_MIME_TO_EXTENSION = {
    "application/gzip": ".gds.gz",
    "application/x-gzip": ".gds.gz",
    "application/x-bzip2": ".gds.bz2",
    "application/x-xz": ".gds.xz",
}


def detect_file_type_from_data(data: bytes) -> tuple[str, str]:
    """Detect file type from actual file data.

    GDS and OASIS files are identified by their own format signatures rather
    than assuming any generic binary (``application/octet-stream``) is GDS.
    Compressed archives (gzip/bzip2/xz/zip) wrapping a GDS/OASIS file are also
    recognised. Anything else is rejected.

    Args:
        data: File data bytes (at least first 1MB recommended)

    Returns:
        tuple: (mime_type, file_extension)
            - mime_type: Detected MIME type (e.g., "application/x-gds")
            - file_extension: Appropriate file extension (e.g., ".gds")

    Raises:
        ValueError: If the file is not a GDS/OASIS file or a supported archive.
    """
    # Detect GDS/OASIS/zip by their leading signatures, independent of libmagic.
    if data[:4] == GDS_SIGNATURE:
        return "application/x-gds", ".gds"
    if data.startswith(OASIS_SIGNATURE):
        return "application/x-oasis", ".oas"
    if data[:4] in ZIP_SIGNATURES:
        return "application/zip", ".gds.zip"

    # Fall back to libmagic for compressed wrappers.
    mime_detector = magic.Magic(mime=True)
    mime_type = mime_detector.from_buffer(data)

    extension = _COMPRESSED_MIME_TO_EXTENSION.get(mime_type)
    if extension is None:
        msg = (
            f"Unsupported file type: {mime_type}. Only GDS, OASIS, or "
            f"gzip/bzip2/xz/zip-compressed GDS/OASIS files are accepted."
        )
        raise ValueError(msg)

    return mime_type, extension
