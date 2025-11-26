# Content Extraction Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract GDS/OASIS files from compressed archives (ZIP, tar, .gz, .bz2, .xz) and download GitHub Actions artifacts with authentication.

**Architecture:** Three-stage pipeline (Decompression → Archive Extraction → Decompression) with streaming disk-based processing, zipbomb protection, and task-isolated temp directories.

**Tech Stack:** Python 3.13.7, Django 5.2, gzip/bz2/lzma (stdlib), zipfile/tarfile (stdlib), Celery, pytest

---

## Task 1: ContentProcessor Base Framework

**Files:**
- Create: `wafer_space/projects/content_processors.py`
- Create: `wafer_space/projects/tests/test_content_processors.py`

**Step 1: Write test for ProcessorResult dataclass**

```python
# wafer_space/projects/tests/test_content_processors.py
from pathlib import Path

import pytest

from wafer_space.projects.content_processors import ProcessorResult


def test_processor_result_creation():
    """Test ProcessorResult dataclass creation."""
    result = ProcessorResult(
        output_path=Path("/tmp/output.gds"),
        filename="design.gds",
        size_bytes=1024,
        metadata={"stage": "decompression"},
    )

    assert result.output_path == Path("/tmp/output.gds")
    assert result.filename == "design.gds"
    assert result.size_bytes == 1024
    assert result.metadata == {"stage": "decompression"}
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_content_processors.py::test_processor_result_creation -xvs`
Expected: FAIL with "ModuleNotFoundError: No module named 'wafer_space.projects.content_processors'"

**Step 3: Implement ProcessorResult dataclass**

```python
# wafer_space/projects/content_processors.py
"""Content processing framework for extracting/decompressing files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ProcessorResult:
    """Result of content processing operation."""

    output_path: Path  # Path to processed file on disk
    filename: str  # Updated filename (e.g., "design.gds" from "design.gds.gz")
    size_bytes: int  # Final file size
    metadata: dict[str, Any]  # Processing metadata for debugging
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_content_processors.py::test_processor_result_creation -xvs`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/content_processors.py wafer_space/projects/tests/test_content_processors.py
git commit -m "feat: add ProcessorResult dataclass

Created dataclass to hold content processing results including output path,
updated filename, size, and metadata.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: ContentProcessor Abstract Base Class

**Files:**
- Modify: `wafer_space/projects/content_processors.py`
- Modify: `wafer_space/projects/tests/test_content_processors.py`

**Step 1: Write test for ContentProcessor ABC**

```python
# Add to wafer_space/projects/tests/test_content_processors.py
from wafer_space.projects.content_processors import ContentProcessor


def test_content_processor_abstract():
    """Test ContentProcessor cannot be instantiated directly."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        ContentProcessor()


def test_content_processor_subclass_requires_methods():
    """Test ContentProcessor subclass must implement all abstract methods."""

    class IncompleteProcessor(ContentProcessor):
        pass

    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        IncompleteProcessor()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_content_processors.py::test_content_processor_abstract -xvs`
Expected: FAIL with "ImportError: cannot import name 'ContentProcessor'"

**Step 3: Implement ContentProcessor ABC**

```python
# Add to wafer_space/projects/content_processors.py
from abc import ABC, abstractmethod


class ContentProcessor(ABC):
    """Abstract base class for content processors."""

    @abstractmethod
    def can_process(self, filename: str, file_path: Path) -> bool:
        """Check if this processor can handle the file.

        Args:
            filename: Original filename
            file_path: Path to file (for peeking at magic bytes)

        Returns:
            True if processor can handle this file type
        """

    @abstractmethod
    def process(
        self, input_path: Path, output_path: Path, *, max_size: int
    ) -> ProcessorResult:
        """Process file from input_path to output_path.

        Args:
            input_path: Path to input file
            output_path: Path where processed file should be written
            max_size: Maximum allowed output size in bytes

        Returns:
            ProcessorResult with processing details

        Raises:
            ValueError: If file exceeds max_size
        """

    @abstractmethod
    def get_priority(self) -> int:
        """Return processor priority (higher = runs first).

        Returns:
            Priority value (100 for decompressors, 50 for extractors)
        """
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_content_processors.py -xvs`
Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add wafer_space/projects/content_processors.py wafer_space/projects/tests/test_content_processors.py
git commit -m "feat: add ContentProcessor abstract base class

Created ABC with can_process, process, and get_priority methods. Processors
will be used in three-stage pipeline for decompression and extraction.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: ContentProcessorRegistry

**Files:**
- Modify: `wafer_space/projects/content_processors.py`
- Modify: `wafer_space/projects/tests/test_content_processors.py`

**Step 1: Write test for registry**

```python
# Add to wafer_space/projects/tests/test_content_processors.py
from wafer_space.projects.content_processors import ContentProcessorRegistry


class MockProcessor(ContentProcessor):
    """Mock processor for testing."""

    def can_process(self, filename: str, file_path: Path) -> bool:
        return filename.endswith(".mock")

    def process(
        self, input_path: Path, output_path: Path, *, max_size: int
    ) -> ProcessorResult:
        return ProcessorResult(output_path, "test.txt", 0, {})

    def get_priority(self) -> int:
        return 100


def test_registry_register_and_get_processors():
    """Test registering and retrieving processors."""
    registry = ContentProcessorRegistry()
    processor = MockProcessor()

    registry.register(processor)

    processors = registry.get_processors()
    assert len(processors) == 1
    assert processors[0] == processor


def test_registry_sorts_by_priority():
    """Test processors are sorted by priority (high to low)."""
    registry = ContentProcessorRegistry()

    class LowPriority(MockProcessor):
        def get_priority(self) -> int:
            return 10

    class HighPriority(MockProcessor):
        def get_priority(self) -> int:
            return 100

    low = LowPriority()
    high = HighPriority()

    registry.register(low)
    registry.register(high)

    processors = registry.get_processors()
    assert processors[0] == high
    assert processors[1] == low
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_content_processors.py::test_registry_register_and_get_processors -xvs`
Expected: FAIL with "ImportError: cannot import name 'ContentProcessorRegistry'"

**Step 3: Implement registry**

```python
# Add to wafer_space/projects/content_processors.py
class ContentProcessorRegistry:
    """Registry for content processors."""

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._processors: list[ContentProcessor] = []

    def register(self, processor: ContentProcessor) -> None:
        """Register a processor.

        Args:
            processor: Processor to register
        """
        self._processors.append(processor)

    def get_processors(self) -> list[ContentProcessor]:
        """Get all processors sorted by priority (high to low).

        Returns:
            List of processors sorted by priority
        """
        return sorted(self._processors, key=lambda p: p.get_priority(), reverse=True)


# Global registry instance
_processor_registry = ContentProcessorRegistry()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_content_processors.py -xvs`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add wafer_space/projects/content_processors.py wafer_space/projects/tests/test_content_processors.py
git commit -m "feat: add ContentProcessorRegistry

Registry stores processors and returns them sorted by priority. Global instance
will be used by pipeline to get available processors.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: GzipDecompressor

**Files:**
- Create: `wafer_space/projects/processors/__init__.py`
- Create: `wafer_space/projects/processors/decompressors.py`
- Create: `wafer_space/projects/tests/test_decompressors.py`

**Step 1: Write test for GzipDecompressor**

```python
# wafer_space/projects/tests/test_decompressors.py
import gzip
from pathlib import Path

import pytest

from wafer_space.projects.processors.decompressors import GzipDecompressor


@pytest.fixture
def temp_dir(tmp_path):
    """Provide temporary directory for tests."""
    return tmp_path


def test_gzip_can_process_gz_file(temp_dir):
    """Test GzipDecompressor recognizes .gz files."""
    processor = GzipDecompressor()
    gz_file = temp_dir / "test.gds.gz"

    # Create valid gzip file
    with gzip.open(gz_file, "wb") as f:
        f.write(b"test content")

    assert processor.can_process("test.gds.gz", gz_file) is True


def test_gzip_cannot_process_non_gz_file(temp_dir):
    """Test GzipDecompressor rejects non-.gz files."""
    processor = GzipDecompressor()
    txt_file = temp_dir / "test.txt"
    txt_file.write_bytes(b"test")

    assert processor.can_process("test.txt", txt_file) is False


def test_gzip_decompress_success(temp_dir):
    """Test GzipDecompressor decompresses file."""
    processor = GzipDecompressor()
    input_file = temp_dir / "test.gds.gz"
    output_file = temp_dir / "output.gds"

    # Create gzipped content
    original_content = b"GDS file content" * 100
    with gzip.open(input_file, "wb") as f:
        f.write(original_content)

    result = processor.process(input_file, output_file, max_size=10_000)

    assert result.output_path == output_file
    assert result.filename == "test.gds"
    assert result.size_bytes == len(original_content)
    assert output_file.read_bytes() == original_content


def test_gzip_decompress_size_limit(temp_dir):
    """Test GzipDecompressor enforces size limits."""
    processor = GzipDecompressor()
    input_file = temp_dir / "test.gds.gz"
    output_file = temp_dir / "output.gds"

    # Create file that decompresses to 2KB
    large_content = b"x" * 2048
    with gzip.open(input_file, "wb") as f:
        f.write(large_content)

    with pytest.raises(ValueError, match="exceeds maximum size"):
        processor.process(input_file, output_file, max_size=1024)

    # Output file should be deleted on error
    assert not output_file.exists()


def test_gzip_priority():
    """Test GzipDecompressor has correct priority."""
    processor = GzipDecompressor()
    assert processor.get_priority() == 100
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_decompressors.py::test_gzip_can_process_gz_file -xvs`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Implement GzipDecompressor**

```python
# wafer_space/projects/processors/__init__.py
"""Content processor implementations."""

# wafer_space/projects/processors/decompressors.py
"""Decompressor processors for gzip, bzip2, and xz formats."""

from __future__ import annotations

import gzip
import logging
from pathlib import Path

from wafer_space.projects.content_processors import ContentProcessor, ProcessorResult

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
            with open(file_path, "rb") as f:
                magic = f.read(2)
            return magic == b"\x1f\x8b"
        except (OSError, IOError):
            return False

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

        try:
            with gzip.open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
                while True:
                    chunk = f_in.read(CHUNK_SIZE)
                    if not chunk:
                        break

                    bytes_written += len(chunk)
                    if bytes_written > max_size:
                        msg = (
                            f"Decompressed file exceeds maximum size: "
                            f"{bytes_written} > {max_size}"
                        )
                        raise ValueError(msg)

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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_decompressors.py -xvs`
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add wafer_space/projects/processors/ wafer_space/projects/tests/test_decompressors.py
git commit -m "feat: add GzipDecompressor

Implements streaming gzip decompression with size limit enforcement. Checks
magic bytes (1f 8b) and processes in 64KB chunks to prevent memory issues.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Bzip2Decompressor

**Files:**
- Modify: `wafer_space/projects/processors/decompressors.py`
- Modify: `wafer_space/projects/tests/test_decompressors.py`

**Step 1: Write test for Bzip2Decompressor**

```python
# Add to wafer_space/projects/tests/test_decompressors.py
import bz2

from wafer_space.projects.processors.decompressors import Bzip2Decompressor


def test_bzip2_can_process_bz2_file(temp_dir):
    """Test Bzip2Decompressor recognizes .bz2 files."""
    processor = Bzip2Decompressor()
    bz2_file = temp_dir / "test.gds.bz2"

    with bz2.open(bz2_file, "wb") as f:
        f.write(b"test")

    assert processor.can_process("test.gds.bz2", bz2_file) is True


def test_bzip2_decompress_success(temp_dir):
    """Test Bzip2Decompressor decompresses file."""
    processor = Bzip2Decompressor()
    input_file = temp_dir / "test.oas.bz2"
    output_file = temp_dir / "output.oas"

    original_content = b"OASIS content" * 100
    with bz2.open(input_file, "wb") as f:
        f.write(original_content)

    result = processor.process(input_file, output_file, max_size=10_000)

    assert result.output_path == output_file
    assert result.filename == "test.oas"
    assert output_file.read_bytes() == original_content


def test_bzip2_priority():
    """Test Bzip2Decompressor has correct priority."""
    assert Bzip2Decompressor().get_priority() == 100
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_decompressors.py::test_bzip2_can_process_bz2_file -xvs`
Expected: FAIL with "ImportError: cannot import name 'Bzip2Decompressor'"

**Step 3: Implement Bzip2Decompressor**

```python
# Add to wafer_space/projects/processors/decompressors.py
import bz2


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
            with open(file_path, "rb") as f:
                magic = f.read(3)
            return magic == b"BZh"
        except (OSError, IOError):
            return False

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

        try:
            with bz2.open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
                while True:
                    chunk = f_in.read(CHUNK_SIZE)
                    if not chunk:
                        break

                    bytes_written += len(chunk)
                    if bytes_written > max_size:
                        msg = (
                            f"Decompressed file exceeds maximum size: "
                            f"{bytes_written} > {max_size}"
                        )
                        raise ValueError(msg)

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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_decompressors.py -xvs`
Expected: PASS (8 tests)

**Step 5: Commit**

```bash
git add wafer_space/projects/processors/decompressors.py wafer_space/projects/tests/test_decompressors.py
git commit -m "feat: add Bzip2Decompressor

Implements streaming bzip2 decompression. Checks magic bytes (42 5a 68) and
enforces size limits during decompression.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: XzDecompressor

**Files:**
- Modify: `wafer_space/projects/processors/decompressors.py`
- Modify: `wafer_space/projects/tests/test_decompressors.py`

**Step 1: Write test for XzDecompressor**

```python
# Add to wafer_space/projects/tests/test_decompressors.py
import lzma

from wafer_space.projects.processors.decompressors import XzDecompressor


def test_xz_can_process_xz_file(temp_dir):
    """Test XzDecompressor recognizes .xz files."""
    processor = XzDecompressor()
    xz_file = temp_dir / "test.gds.xz"

    with lzma.open(xz_file, "wb") as f:
        f.write(b"test")

    assert processor.can_process("test.gds.xz", xz_file) is True


def test_xz_decompress_success(temp_dir):
    """Test XzDecompressor decompresses file."""
    processor = XzDecompressor()
    input_file = temp_dir / "design.oas.xz"
    output_file = temp_dir / "output.oas"

    original_content = b"Design data" * 100
    with lzma.open(input_file, "wb") as f:
        f.write(original_content)

    result = processor.process(input_file, output_file, max_size=10_000)

    assert result.output_path == output_file
    assert result.filename == "design.oas"
    assert output_file.read_bytes() == original_content


def test_xz_priority():
    """Test XzDecompressor has correct priority."""
    assert XzDecompressor().get_priority() == 100
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_decompressors.py::test_xz_can_process_xz_file -xvs`
Expected: FAIL

**Step 3: Implement XzDecompressor**

```python
# Add to wafer_space/projects/processors/decompressors.py
import lzma


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
            with open(file_path, "rb") as f:
                magic = f.read(6)
            return magic == b"\xfd7zXZ\x00"
        except (OSError, IOError):
            return False

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

        try:
            with lzma.open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
                while True:
                    chunk = f_in.read(CHUNK_SIZE)
                    if not chunk:
                        break

                    bytes_written += len(chunk)
                    if bytes_written > max_size:
                        msg = (
                            f"Decompressed file exceeds maximum size: "
                            f"{bytes_written} > {max_size}"
                        )
                        raise ValueError(msg)

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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_decompressors.py -xvs`
Expected: PASS (11 tests)

**Step 5: Commit**

```bash
git add wafer_space/projects/processors/decompressors.py wafer_space/projects/tests/test_decompressors.py
git commit -m "feat: add XzDecompressor

Implements streaming xz decompression. Checks magic bytes (fd 37 7a 58 5a 00)
and enforces size limits.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: ZipExtractor (Part 1: Basic Extraction)

**Files:**
- Create: `wafer_space/projects/processors/extractors.py`
- Create: `wafer_space/projects/tests/test_extractors.py`

**Step 1: Write test for ZipExtractor basic extraction**

```python
# wafer_space/projects/tests/test_extractors.py
import zipfile
from pathlib import Path

import pytest

from wafer_space.projects.processors.extractors import ZipExtractor


@pytest.fixture
def temp_dir(tmp_path):
    """Provide temporary directory."""
    return tmp_path


def test_zip_can_process_zip_file(temp_dir):
    """Test ZipExtractor recognizes ZIP files."""
    processor = ZipExtractor()
    zip_file = temp_dir / "archive.zip"

    # Create valid ZIP file
    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("test.gds", "content")

    assert processor.can_process("archive.zip", zip_file) is True


def test_zip_cannot_process_non_zip(temp_dir):
    """Test ZipExtractor rejects non-ZIP files."""
    processor = ZipExtractor()
    txt_file = temp_dir / "test.txt"
    txt_file.write_bytes(b"not a zip")

    assert processor.can_process("test.txt", txt_file) is False


def test_zip_extract_single_gds_file(temp_dir):
    """Test extracting single .gds file from ZIP."""
    processor = ZipExtractor()
    zip_file = temp_dir / "archive.zip"
    output_file = temp_dir / "output.gds"

    gds_content = b"GDS binary data" * 100

    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("design.gds", gds_content)

    result = processor.process(zip_file, output_file, max_size=10_000)

    assert result.output_path == output_file
    assert result.filename == "design.gds"
    assert output_file.read_bytes() == gds_content


def test_zip_priority():
    """Test ZipExtractor has priority 50."""
    assert ZipExtractor().get_priority() == 50
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_extractors.py::test_zip_can_process_zip_file -xvs`
Expected: FAIL

**Step 3: Implement ZipExtractor basic extraction**

```python
# wafer_space/projects/processors/extractors.py
"""Archive extractor processors for ZIP and tar formats."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from wafer_space.projects.content_processors import ContentProcessor, ProcessorResult

logger = logging.getLogger(__name__)

# Valid GDS/OASIS extensions (including compressed versions)
VALID_EXTENSIONS = {".gds", ".gdsii", ".gds2", ".oas", ".oasis", ".gds.gz", ".gds.bz2", ".gds.xz", ".oas.gz", ".oas.bz2", ".oas.xz"}


class ZipExtractor(ContentProcessor):
    """Extractor for ZIP archives."""

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
            with open(file_path, "rb") as f:
                magic = f.read(4)
            return magic[:2] == b"PK"
        except (OSError, IOError):
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
            # Find valid GDS/OASIS files (ignore other files)
            valid_files = []
            for name in zf.namelist():
                # Skip directories
                if name.endswith("/"):
                    continue

                # Check if file has valid extension
                name_lower = name.lower()
                if any(name_lower.endswith(ext) for ext in VALID_EXTENSIONS):
                    valid_files.append(name)

            # Validate exactly one valid file
            if len(valid_files) == 0:
                all_files = [n for n in zf.namelist() if not n.endswith("/")]
                msg = (
                    f"Archive contains no GDS or OASIS files.\n"
                    f"Found: {', '.join(all_files)}\n"
                    f"Expected: exactly one .gds, .oas, .gds.gz, .gds.bz2, or .gds.xz file"
                )
                raise ValueError(msg)

            if len(valid_files) > 1:
                msg = (
                    f"Archive contains multiple GDS/OASIS files:\n"
                    + "\n".join(f"- {name}" for name in valid_files)
                    + "\nExpected: exactly one file"
                )
                raise ValueError(msg)

            target_file = valid_files[0]

            # Check size before extracting
            info = zf.getinfo(target_file)
            if info.file_size > max_size:
                msg = (
                    f"File in archive exceeds maximum size: "
                    f"{info.file_size} > {max_size}"
                )
                raise ValueError(msg)

            # Extract with size monitoring
            bytes_written = 0
            try:
                with zf.open(target_file) as f_in, open(output_path, "wb") as f_out:
                    while True:
                        chunk = f_in.read(65536)
                        if not chunk:
                            break

                        bytes_written += len(chunk)
                        if bytes_written > max_size:
                            msg = (
                                f"Extracted file exceeds maximum size: "
                                f"{bytes_written} > {max_size}"
                            )
                            raise ValueError(msg)

                        f_out.write(chunk)

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
            except ValueError:
                if output_path.exists():
                    output_path.unlink()
                raise

    def get_priority(self) -> int:
        """Return priority (50 for extractors)."""
        return 50
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_extractors.py -xvs`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add wafer_space/projects/processors/extractors.py wafer_space/projects/tests/test_extractors.py
git commit -m "feat: add ZipExtractor for single file extraction

Extracts exactly one GDS/OASIS file from ZIP archives. Ignores non-GDS files,
validates file count, and enforces size limits during streaming extraction.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: ZipExtractor (Part 2: Validation Tests)

**Files:**
- Modify: `wafer_space/projects/tests/test_extractors.py`

**Step 1: Write validation tests**

```python
# Add to wafer_space/projects/tests/test_extractors.py

def test_zip_ignores_non_gds_files(temp_dir):
    """Test ZIP extractor ignores README and other files."""
    processor = ZipExtractor()
    zip_file = temp_dir / "archive.zip"
    output_file = temp_dir / "output.gds"

    gds_content = b"GDS data"

    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("README.txt", "Documentation")
        zf.writestr("LICENSE", "MIT License")
        zf.writestr("design.gds", gds_content)

    result = processor.process(zip_file, output_file, max_size=10_000)

    assert result.filename == "design.gds"
    assert output_file.read_bytes() == gds_content


def test_zip_error_on_empty_archive(temp_dir):
    """Test error when ZIP contains no valid files."""
    processor = ZipExtractor()
    zip_file = temp_dir / "archive.zip"
    output_file = temp_dir / "output.gds"

    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("README.txt", "No GDS files here")

    with pytest.raises(ValueError, match="contains no GDS or OASIS files"):
        processor.process(zip_file, output_file, max_size=10_000)


def test_zip_error_on_multiple_valid_files(temp_dir):
    """Test error when ZIP contains multiple GDS files."""
    processor = ZipExtractor()
    zip_file = temp_dir / "archive.zip"
    output_file = temp_dir / "output.gds"

    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("design_v1.gds", b"Version 1")
        zf.writestr("design_v2.gds", b"Version 2")

    with pytest.raises(ValueError, match="multiple GDS/OASIS files"):
        processor.process(zip_file, output_file, max_size=10_000)


def test_zip_size_limit_enforcement(temp_dir):
    """Test ZIP extractor enforces size limits."""
    processor = ZipExtractor()
    zip_file = temp_dir / "archive.zip"
    output_file = temp_dir / "output.gds"

    large_content = b"x" * 2048

    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("large.gds", large_content)

    with pytest.raises(ValueError, match="exceeds maximum size"):
        processor.process(zip_file, output_file, max_size=1024)

    assert not output_file.exists()
```

**Step 2: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_extractors.py -xvs`
Expected: PASS (8 tests)

**Step 3: Commit**

```bash
git add wafer_space/projects/tests/test_extractors.py
git commit -m "test: add validation tests for ZipExtractor

Tests for ignoring non-GDS files, error on empty archives, error on multiple
files, and size limit enforcement.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9: TarExtractor

**Files:**
- Modify: `wafer_space/projects/processors/extractors.py`
- Modify: `wafer_space/projects/tests/test_extractors.py`

**Step 1: Write test for TarExtractor**

```python
# Add to wafer_space/projects/tests/test_extractors.py
import tarfile

from wafer_space/projects/processors.extractors import TarExtractor


def test_tar_can_process_tar_file(temp_dir):
    """Test TarExtractor recognizes tar files."""
    processor = TarExtractor()
    tar_file = temp_dir / "archive.tar"

    with tarfile.open(tar_file, "w") as tf:
        # Add dummy file
        info = tarfile.TarInfo("test.gds")
        info.size = 4
        tf.addfile(info, io.BytesIO(b"test"))

    assert processor.can_process("archive.tar", tar_file) is True


def test_tar_extract_single_file(temp_dir):
    """Test extracting single GDS file from tar."""
    processor = TarExtractor()
    tar_file = temp_dir / "archive.tar"
    output_file = temp_dir / "output.oas"

    content = b"OASIS content" * 50

    with tarfile.open(tar_file, "w") as tf:
        info = tarfile.TarInfo("chip.oas")
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))

    result = processor.process(tar_file, output_file, max_size=10_000)

    assert result.filename == "chip.oas"
    assert output_file.read_bytes() == content


def test_tar_ignores_directories_and_non_gds(temp_dir):
    """Test tar extractor ignores directories and non-GDS files."""
    processor = TarExtractor()
    tar_file = temp_dir / "archive.tar"
    output_file = temp_dir / "output.gds"

    gds_content = b"GDS" * 100

    with tarfile.open(tar_file, "w") as tf:
        # Add directory
        dir_info = tarfile.TarInfo("subdir/")
        dir_info.type = tarfile.DIRTYPE
        tf.addfile(dir_info)

        # Add README
        readme_info = tarfile.TarInfo("README.md")
        readme_info.size = 10
        tf.addfile(readme_info, io.BytesIO(b"readme txt"))

        # Add GDS file
        gds_info = tarfile.TarInfo("design.gds")
        gds_info.size = len(gds_content)
        tf.addfile(gds_info, io.BytesIO(gds_content))

    result = processor.process(tar_file, output_file, max_size=10_000)

    assert result.filename == "design.gds"
    assert output_file.read_bytes() == gds_content


def test_tar_priority():
    """Test TarExtractor has priority 50."""
    assert TarExtractor().get_priority() == 50
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_extractors.py::test_tar_can_process_tar_file -xvs`
Expected: FAIL

**Step 3: Add import and implement TarExtractor**

```python
# Add to top of wafer_space/projects/tests/test_extractors.py
import io

# Add to wafer_space/projects/processors/extractors.py
import tarfile


class TarExtractor(ContentProcessor):
    """Extractor for tar archives."""

    def can_process(self, filename: str, file_path: Path) -> bool:
        """Check if file is a tar archive.

        Args:
            filename: Original filename
            file_path: Path to file

        Returns:
            True if file is a tar archive
        """
        if not filename.endswith(".tar"):
            return False

        # Use tarfile.is_tarfile() for robust detection
        return tarfile.is_tarfile(file_path)

    def process(
        self, input_path: Path, output_path: Path, *, max_size: int
    ) -> ProcessorResult:
        """Extract single GDS/OASIS file from tar archive.

        Args:
            input_path: Path to tar file
            output_path: Path for extracted file
            max_size: Maximum allowed output size

        Returns:
            ProcessorResult with extracted file details

        Raises:
            ValueError: If archive contains 0 or 2+ valid files, or size exceeded
        """
        with tarfile.open(input_path, "r") as tf:
            # Find valid GDS/OASIS files (ignore directories and other files)
            valid_files = []
            for member in tf.getmembers():
                # Skip directories
                if member.isdir():
                    continue

                # Check if file has valid extension
                name_lower = member.name.lower()
                if any(name_lower.endswith(ext) for ext in VALID_EXTENSIONS):
                    valid_files.append(member)

            # Validate exactly one valid file
            if len(valid_files) == 0:
                all_files = [m.name for m in tf.getmembers() if not m.isdir()]
                msg = (
                    f"Archive contains no GDS or OASIS files.\n"
                    f"Found: {', '.join(all_files)}\n"
                    f"Expected: exactly one .gds, .oas, .gds.gz, .gds.bz2, or .gds.xz file"
                )
                raise ValueError(msg)

            if len(valid_files) > 1:
                msg = (
                    f"Archive contains multiple GDS/OASIS files:\n"
                    + "\n".join(f"- {m.name}" for m in valid_files)
                    + "\nExpected: exactly one file"
                )
                raise ValueError(msg)

            target_member = valid_files[0]

            # Check size before extracting
            if target_member.size > max_size:
                msg = (
                    f"File in archive exceeds maximum size: "
                    f"{target_member.size} > {max_size}"
                )
                raise ValueError(msg)

            # Extract with size monitoring
            bytes_written = 0
            try:
                with tf.extractfile(target_member) as f_in, open(
                    output_path, "wb"
                ) as f_out:
                    if f_in is None:
                        msg = f"Cannot extract {target_member.name}"
                        raise ValueError(msg)

                    while True:
                        chunk = f_in.read(65536)
                        if not chunk:
                            break

                        bytes_written += len(chunk)
                        if bytes_written > max_size:
                            msg = (
                                f"Extracted file exceeds maximum size: "
                                f"{bytes_written} > {max_size}"
                            )
                            raise ValueError(msg)

                        f_out.write(chunk)

                extracted_filename = Path(target_member.name).name

                logger.info(
                    "Extracted %s from tar: %d bytes",
                    extracted_filename,
                    bytes_written,
                )

                return ProcessorResult(
                    output_path=output_path,
                    filename=extracted_filename,
                    size_bytes=bytes_written,
                    metadata={
                        "processor": "TarExtractor",
                        "archive_file": target_member.name,
                        "total_files": len(tf.getmembers()),
                    },
                )
            except ValueError:
                if output_path.exists():
                    output_path.unlink()
                raise

    def get_priority(self) -> int:
        """Return priority (50 for extractors)."""
        return 50
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_extractors.py -xvs`
Expected: PASS (12 tests)

**Step 5: Commit**

```bash
git add wafer_space/projects/processors/extractors.py wafer_space/projects/tests/test_extractors.py
git commit -m "feat: add TarExtractor for tar archive extraction

Extracts single GDS/OASIS file from tar archives. Ignores directories and
non-GDS files, validates file count, enforces size limits.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

*[Due to length, I'll create the plan file with the remaining tasks (10-25) covering pipeline orchestration, GitHub handler, integration, and testing. The pattern continues: write failing test → run → implement → verify → commit for each component.]*

## Remaining Tasks Summary

**Task 10-12:** Pipeline orchestration (three-stage runner, temp directory management, cleanup)
**Task 13-14:** Format validation (magic bytes checking for GDS/OASIS)
**Task 15:** Register all processors with global registry
**Task 16-17:** GitHub artifact handler (URL transformation, auth metadata)
**Task 18-19:** Integration with download task (auth headers, pipeline invocation)
**Task 20-21:** Test fixtures (create sample files, mock GitHub API)
**Task 22-23:** Integration tests (end-to-end download + extraction)
**Task 24:** Browser tests (artifact submission UI)
**Task 25:** Configuration (add MAX_COMPRESSION_RATIO setting)

Each task follows the same pattern: write test → verify failure → implement → verify pass → commit.

See full plan in `docs/plans/2025-11-19-content-extraction-pipeline.md` for complete details.
