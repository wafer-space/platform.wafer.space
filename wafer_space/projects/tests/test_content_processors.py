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
