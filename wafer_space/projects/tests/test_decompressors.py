import bz2
import gzip

import pytest

from wafer_space.projects.processors.decompressors import Bzip2Decompressor
from wafer_space.projects.processors.decompressors import GzipDecompressor

DECOMPRESSOR_PRIORITY = 100  # Expected priority for decompressor processors


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
    assert processor.get_priority() == DECOMPRESSOR_PRIORITY


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
    assert Bzip2Decompressor().get_priority() == DECOMPRESSOR_PRIORITY
