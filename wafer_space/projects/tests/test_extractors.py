import zipfile

import pytest

from wafer_space.projects.processors.extractors import EXTRACTOR_PRIORITY
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
    assert ZipExtractor().get_priority() == EXTRACTOR_PRIORITY
