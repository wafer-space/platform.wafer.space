"""Content processing framework for extracting/decompressing files."""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class ProcessorResult:
    """Result of content processing operation."""

    output_path: Path  # Path to processed file on disk
    filename: str  # Updated filename (e.g., "design.gds" from "design.gds.gz")
    size_bytes: int  # Final file size
    metadata: dict[str, Any]  # Processing metadata for debugging


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
