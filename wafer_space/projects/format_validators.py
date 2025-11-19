"""Format validators for GDS and OASIS files.

This module provides validators that check magic byte signatures
to verify file formats after extraction/decompression.
"""

from abc import ABC
from abc import abstractmethod
from pathlib import Path


class FormatValidator(ABC):
    """Abstract base class for format validators."""

    @abstractmethod
    def is_valid(self, file_path: Path) -> bool:
        """Check if file is valid format.

        Args:
            file_path: Path to file to validate

        Returns:
            True if file matches expected format
        """

    @abstractmethod
    def get_format_name(self) -> str:
        """Return human-readable format name."""


class GDSValidator(FormatValidator):
    """Validator for GDSII files.

    GDSII files start with a 4-byte header:
    - Bytes 0-1: Record length (0x0006 in big-endian)
    - Byte 2: Record type (0x00 for HEADER)
    - Byte 3: Data type (0x02 for 2-byte integer)

    Common signature: 00 06 00 02

    Reference: GDSII Stream Format Manual, Calma/Cadence
    """

    MAGIC_BYTES = b"\x00\x06\x00\x02"
    MIN_FILE_SIZE = 4

    def is_valid(self, file_path: Path) -> bool:
        """Check if file is valid GDSII format.

        Args:
            file_path: Path to file to validate

        Returns:
            True if file starts with GDSII magic bytes
        """
        try:
            # Check file exists and is readable
            if not file_path.exists():
                return False

            # Check file size is sufficient
            if file_path.stat().st_size < self.MIN_FILE_SIZE:
                return False

            # Read first 4 bytes and compare
            with file_path.open("rb") as f:
                header = f.read(self.MIN_FILE_SIZE)
                return header == self.MAGIC_BYTES

        except (OSError, PermissionError):
            # File is not accessible
            return False

    def get_format_name(self) -> str:
        """Return human-readable format name."""
        return "GDSII"


class OASISValidator(FormatValidator):
    """Validator for OASIS files.

    OASIS files start with magic string:
    - Bytes 0-12: "%SEMI-OASIS\r\n" (13 bytes)

    The magic signature is: 25 53 45 4D 49 2D 4F 41 53 49 53 0D 0A

    See OASIS spec: http://www.artwork.com/oasis/spec/
    """

    MAGIC_BYTES = b"%SEMI-OASIS\r\n"
    MIN_FILE_SIZE = 13

    def is_valid(self, file_path: Path) -> bool:
        """Check if file is valid OASIS format.

        Args:
            file_path: Path to file to validate

        Returns:
            True if file starts with OASIS magic string
        """
        try:
            # Check file exists and is readable
            if not file_path.exists():
                return False

            # Check file size is sufficient
            if file_path.stat().st_size < self.MIN_FILE_SIZE:
                return False

            # Read first 13 bytes and compare
            with file_path.open("rb") as f:
                header = f.read(self.MIN_FILE_SIZE)
                return header == self.MAGIC_BYTES

        except (OSError, PermissionError):
            # File is not accessible
            return False

    def get_format_name(self) -> str:
        """Return human-readable format name."""
        return "OASIS"


def validate_output_format(file_path: Path) -> str:
    """Validate file format and return format name.

    Args:
        file_path: Path to file to validate

    Returns:
        Format name ("GDSII" or "OASIS")

    Raises:
        ValueError: If file is not a valid GDS or OASIS file
    """
    validators = [GDSValidator(), OASISValidator()]

    for validator in validators:
        if validator.is_valid(file_path):
            return validator.get_format_name()

    msg = (
        f"File {file_path.name} is not a valid GDS or OASIS file. "
        "Expected GDSII format (00 06 00 02) or OASIS format (%SEMI-OASIS)."
    )
    raise ValueError(msg)
