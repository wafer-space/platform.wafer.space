from pathlib import Path

import pytest

from wafer_space.projects.content_processors import ContentProcessor
from wafer_space.projects.content_processors import ContentProcessorRegistry
from wafer_space.projects.content_processors import ProcessorResult

# Test constants
TEST_SIZE_BYTES = 1024


def test_processor_result_creation(tmp_path):
    """Test ProcessorResult dataclass creation."""
    output_file = tmp_path / "output.gds"

    result = ProcessorResult(
        output_path=output_file,
        filename="design.gds",
        size_bytes=TEST_SIZE_BYTES,
        metadata={"stage": "decompression"},
    )

    assert result.output_path == output_file
    assert result.filename == "design.gds"
    assert result.size_bytes == TEST_SIZE_BYTES
    assert result.metadata == {"stage": "decompression"}


def test_content_processor_abstract():
    """Test ContentProcessor cannot be instantiated directly."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        ContentProcessor()  # type: ignore[abstract]


def test_content_processor_subclass_requires_methods():
    """Test ContentProcessor subclass must implement all abstract methods."""

    class IncompleteProcessor(ContentProcessor):
        pass

    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        IncompleteProcessor()  # type: ignore[abstract]


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
