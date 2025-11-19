"""Decompressor processors for gzip, bzip2, and xz formats."""

from __future__ import annotations

import bz2
import gzip
import logging
import lzma
from typing import TYPE_CHECKING

from wafer_space.projects.content_processors import ContentProcessor
from wafer_space.projects.content_processors import ProcessorResult

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

CHUNK_SIZE = 65536  # 64KB chunks for streaming


class GzipDecompressor(ContentProcessor):
    """Decompressor for gzip (.gz) files."""

    def can_process(self, filename: str, file_path: Path) -> bool:
        """Check if file is gzipped.

        Args:
            filename: Original filename
            file_path: Path to file

        Returns:
            True if filename ends with .gz and file has gzip magic bytes
        """
        if not filename.endswith(".gz"):
            return False

        # Check gzip magic bytes: 1f 8b
        try:
            with file_path.open("rb") as f:
                magic = f.read(2)
        except OSError:
            return False
        else:
            return magic == b"\x1f\x8b"

    def process(
        self, input_path: Path, output_path: Path, *, max_size: int
    ) -> ProcessorResult:
        """Decompress gzip file.

        Args:
            input_path: Path to .gz file
            output_path: Path for decompressed output
            max_size: Maximum allowed output size

        Returns:
            ProcessorResult with decompressed file details

        Raises:
            ValueError: If decompressed size exceeds max_size
        """
        bytes_written = 0

        def _raise_size_error() -> None:
            msg = (
                f"Decompressed file exceeds maximum size: {bytes_written} > {max_size}"
            )
            raise ValueError(msg)

        try:
            with gzip.open(input_path, "rb") as f_in, output_path.open("wb") as f_out:
                while True:
                    chunk = f_in.read(CHUNK_SIZE)
                    if not chunk:
                        break

                    bytes_written += len(chunk)
                    if bytes_written > max_size:
                        _raise_size_error()

                    f_out.write(chunk)

            # Update filename: remove .gz extension
            original_filename = input_path.name
            new_filename = original_filename.removesuffix(".gz")

            logger.info(
                "Decompressed %s: %d bytes → %d bytes",
                input_path.name,
                input_path.stat().st_size,
                bytes_written,
            )

            return ProcessorResult(
                output_path=output_path,
                filename=new_filename,
                size_bytes=bytes_written,
                metadata={
                    "processor": "GzipDecompressor",
                    "compressed_size": input_path.stat().st_size,
                    "decompressed_size": bytes_written,
                },
            )
        except ValueError:
            # Size limit exceeded - cleanup and re-raise
            if output_path.exists():
                output_path.unlink()
            raise

    def get_priority(self) -> int:
        """Return priority (100 for decompressors).

        Returns:
            Priority value 100
        """
        return 100


class Bzip2Decompressor(ContentProcessor):
    """Decompressor for bzip2 (.bz2) files."""

    def can_process(self, filename: str, file_path: Path) -> bool:
        """Check if file is bzip2 compressed.

        Args:
            filename: Original filename
            file_path: Path to file

        Returns:
            True if filename ends with .bz2 and file has bzip2 magic bytes
        """
        if not filename.endswith(".bz2"):
            return False

        # Check bzip2 magic bytes: 42 5a 68 (BZh)
        try:
            with file_path.open("rb") as f:
                magic = f.read(3)
        except OSError:
            return False
        else:
            return magic == b"BZh"

    def process(
        self, input_path: Path, output_path: Path, *, max_size: int
    ) -> ProcessorResult:
        """Decompress bzip2 file.

        Args:
            input_path: Path to .bz2 file
            output_path: Path for decompressed output
            max_size: Maximum allowed output size

        Returns:
            ProcessorResult with decompressed file details

        Raises:
            ValueError: If decompressed size exceeds max_size
        """
        bytes_written = 0

        def _raise_size_error() -> None:
            msg = (
                f"Decompressed file exceeds maximum size: {bytes_written} > {max_size}"
            )
            raise ValueError(msg)

        try:
            with bz2.open(input_path, "rb") as f_in, output_path.open("wb") as f_out:
                while True:
                    chunk = f_in.read(CHUNK_SIZE)
                    if not chunk:
                        break

                    bytes_written += len(chunk)
                    if bytes_written > max_size:
                        _raise_size_error()

                    f_out.write(chunk)

            new_filename = input_path.name.removesuffix(".bz2")

            logger.info(
                "Decompressed %s: %d bytes → %d bytes",
                input_path.name,
                input_path.stat().st_size,
                bytes_written,
            )

            return ProcessorResult(
                output_path=output_path,
                filename=new_filename,
                size_bytes=bytes_written,
                metadata={
                    "processor": "Bzip2Decompressor",
                    "compressed_size": input_path.stat().st_size,
                    "decompressed_size": bytes_written,
                },
            )
        except ValueError:
            if output_path.exists():
                output_path.unlink()
            raise

    def get_priority(self) -> int:
        """Return priority (100 for decompressors)."""
        return 100


class XzDecompressor(ContentProcessor):
    """Decompressor for xz (.xz) files."""

    def can_process(self, filename: str, file_path: Path) -> bool:
        """Check if file is xz compressed.

        Args:
            filename: Original filename
            file_path: Path to file

        Returns:
            True if filename ends with .xz and file has xz magic bytes
        """
        if not filename.endswith(".xz"):
            return False

        # Check xz magic bytes: fd 37 7a 58 5a 00
        try:
            with file_path.open("rb") as f:
                magic = f.read(6)
        except OSError:
            return False
        else:
            return magic == b"\xfd7zXZ\x00"

    def process(
        self, input_path: Path, output_path: Path, *, max_size: int
    ) -> ProcessorResult:
        """Decompress xz file.

        Args:
            input_path: Path to .xz file
            output_path: Path for decompressed output
            max_size: Maximum allowed output size

        Returns:
            ProcessorResult with decompressed file details

        Raises:
            ValueError: If decompressed size exceeds max_size
        """
        bytes_written = 0

        def _raise_size_error() -> None:
            msg = (
                f"Decompressed file exceeds maximum size: {bytes_written} > {max_size}"
            )
            raise ValueError(msg)

        try:
            with lzma.open(input_path, "rb") as f_in, output_path.open("wb") as f_out:
                while True:
                    chunk = f_in.read(CHUNK_SIZE)
                    if not chunk:
                        break

                    bytes_written += len(chunk)
                    if bytes_written > max_size:
                        _raise_size_error()

                    f_out.write(chunk)

            new_filename = input_path.name.removesuffix(".xz")

            logger.info(
                "Decompressed %s: %d bytes → %d bytes",
                input_path.name,
                input_path.stat().st_size,
                bytes_written,
            )

            return ProcessorResult(
                output_path=output_path,
                filename=new_filename,
                size_bytes=bytes_written,
                metadata={
                    "processor": "XzDecompressor",
                    "compressed_size": input_path.stat().st_size,
                    "decompressed_size": bytes_written,
                },
            )
        except ValueError:
            if output_path.exists():
                output_path.unlink()
            raise

    def get_priority(self) -> int:
        """Return priority (100 for decompressors)."""
        return 100


# Register all decompressors with global registry
from wafer_space.projects.content_processors import _processor_registry

_processor_registry.register(GzipDecompressor())
_processor_registry.register(Bzip2Decompressor())
_processor_registry.register(XzDecompressor())
