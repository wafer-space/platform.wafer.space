"""Archive extractor processors for ZIP and tar formats."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from wafer_space.projects.content_processors import ContentProcessor
from wafer_space.projects.content_processors import ProcessorResult

logger = logging.getLogger(__name__)

# Valid GDS/OASIS extensions (including compressed versions)
VALID_EXTENSIONS = {
    ".gds",
    ".gdsii",
    ".gds2",
    ".oas",
    ".oasis",
    ".gds.gz",
    ".gds.bz2",
    ".gds.xz",
    ".oas.gz",
    ".oas.bz2",
    ".oas.xz",
}

# Priority for extractors (lower than decompressors)
EXTRACTOR_PRIORITY = 50


class ZipExtractor(ContentProcessor):
    """Extractor for ZIP archives."""

    def _find_valid_files(self, zf: zipfile.ZipFile) -> list[str]:
        """Find valid GDS/OASIS files in ZIP archive.

        Args:
            zf: ZipFile object

        Returns:
            List of valid file names
        """
        valid_files = []
        for name in zf.namelist():
            # Skip directories
            if name.endswith("/"):
                continue

            # Check if file has valid extension
            name_lower = name.lower()
            if any(name_lower.endswith(ext) for ext in VALID_EXTENSIONS):
                valid_files.append(name)
        return valid_files

    def _validate_file_count(self, valid_files: list[str], zf: zipfile.ZipFile) -> str:
        """Validate that exactly one valid file exists.

        Args:
            valid_files: List of valid file names
            zf: ZipFile object for error messages

        Returns:
            The single valid file name

        Raises:
            ValueError: If there are 0 or 2+ valid files
        """
        if len(valid_files) == 0:
            all_files = [n for n in zf.namelist() if not n.endswith("/")]
            msg = (
                "Archive contains no GDS or OASIS files.\n"
                f"Found: {', '.join(all_files)}\n"
                "Expected: exactly one .gds, .oas, .gds.gz, .gds.bz2, "
                "or .gds.xz file"
            )
            raise ValueError(msg)

        if len(valid_files) > 1:
            msg = (
                "Archive contains multiple GDS/OASIS files:\n"
                + "\n".join(f"- {name}" for name in valid_files)
                + "\nExpected: exactly one file"
            )
            raise ValueError(msg)

        return valid_files[0]

    def _check_size_limit(self, bytes_written: int, max_size: int) -> None:
        """Check if size limit is exceeded.

        Args:
            bytes_written: Current bytes written
            max_size: Maximum allowed size

        Raises:
            ValueError: If size limit exceeded
        """
        if bytes_written > max_size:
            msg = f"Extracted file exceeds maximum size: {bytes_written} > {max_size}"
            raise ValueError(msg)

    def _extract_file(
        self,
        zf: zipfile.ZipFile,
        target_file: str,
        output_path: Path,
        max_size: int,
    ) -> int:
        """Extract file with size monitoring.

        Args:
            zf: ZipFile object
            target_file: Name of file to extract
            output_path: Path for extracted file
            max_size: Maximum allowed size

        Returns:
            Number of bytes written

        Raises:
            ValueError: If size limit exceeded
        """
        bytes_written = 0
        try:
            with zf.open(target_file) as f_in, output_path.open("wb") as f_out:
                while True:
                    chunk = f_in.read(65536)
                    if not chunk:
                        break

                    bytes_written += len(chunk)
                    self._check_size_limit(bytes_written, max_size)
                    f_out.write(chunk)
        except ValueError:
            if output_path.exists():
                output_path.unlink()
            raise

        return bytes_written

    def can_process(self, filename: str, file_path: Path) -> bool:
        """Check if file is a ZIP archive.

        Args:
            filename: Original filename
            file_path: Path to file

        Returns:
            True if file is a ZIP archive
        """
        if not filename.endswith(".zip"):
            return False

        # Check ZIP magic bytes: 50 4b 03 04 or 50 4b 05 06 (empty zip)
        try:
            with file_path.open("rb") as f:
                magic = f.read(4)
            return magic[:2] == b"PK"
        except OSError:
            return False

    def process(
        self, input_path: Path, output_path: Path, *, max_size: int
    ) -> ProcessorResult:
        """Extract single GDS/OASIS file from ZIP archive.

        Args:
            input_path: Path to ZIP file
            output_path: Path for extracted file
            max_size: Maximum allowed output size

        Returns:
            ProcessorResult with extracted file details

        Raises:
            ValueError: If archive contains 0 or 2+ valid files, or size exceeded
        """
        with zipfile.ZipFile(input_path, "r") as zf:
            # Find and validate exactly one valid file
            valid_files = self._find_valid_files(zf)
            target_file = self._validate_file_count(valid_files, zf)

            # Check size before extracting
            info = zf.getinfo(target_file)
            if info.file_size > max_size:
                msg = (
                    f"File in archive exceeds maximum size: "
                    f"{info.file_size} > {max_size}"
                )
                raise ValueError(msg)

            # Extract with size monitoring
            bytes_written = self._extract_file(zf, target_file, output_path, max_size)

            # Extract just the filename (no directory path)
            extracted_filename = Path(target_file).name

            logger.info(
                "Extracted %s from ZIP: %d bytes",
                extracted_filename,
                bytes_written,
            )

            return ProcessorResult(
                output_path=output_path,
                filename=extracted_filename,
                size_bytes=bytes_written,
                metadata={
                    "processor": "ZipExtractor",
                    "archive_file": target_file,
                    "total_files": len(zf.namelist()),
                },
            )

    def get_priority(self) -> int:
        """Return priority (50 for extractors)."""
        return EXTRACTOR_PRIORITY
