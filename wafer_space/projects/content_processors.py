"""Content processing framework for extracting/decompressing files."""

from __future__ import annotations

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
