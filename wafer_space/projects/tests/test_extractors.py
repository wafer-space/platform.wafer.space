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


def test_zip_ignores_non_gds_files(temp_dir):
    """Test ZipExtractor ignores non-GDS/OASIS files in archive."""
    processor = ZipExtractor()
    zip_file = temp_dir / "archive.zip"
    output_file = temp_dir / "output.gds"

    gds_content = b"GDS binary data" * 50

    # Create ZIP with multiple files, only one valid
    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("README.md", "# Project Documentation\n")
        zf.writestr("LICENSE.txt", "MIT License\n")
        zf.writestr("design.gds", gds_content)

    result = processor.process(zip_file, output_file, max_size=10_000)

    # Verify only design.gds was extracted
    assert result.output_path == output_file
    assert result.filename == "design.gds"
    assert output_file.read_bytes() == gds_content
    # Total files includes README, LICENSE, and design.gds
    expected_file_count = 3
    assert result.metadata["total_files"] == expected_file_count


def test_zip_error_on_empty_archive(temp_dir):
    """Test ZipExtractor raises error for archive with no valid files."""
    processor = ZipExtractor()
    zip_file = temp_dir / "archive.zip"
    output_file = temp_dir / "output.gds"

    # Create ZIP with only non-GDS files
    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("README.md", "# Documentation\n")
        zf.writestr("LICENSE.txt", "MIT License\n")

    # Verify ValueError raised with correct message
    with pytest.raises(ValueError, match="Archive contains no GDS or OASIS files"):
        processor.process(zip_file, output_file, max_size=10_000)


def test_zip_error_on_multiple_valid_files(temp_dir):
    """Test ZipExtractor raises error for archive with multiple valid files."""
    processor = ZipExtractor()
    zip_file = temp_dir / "archive.zip"
    output_file = temp_dir / "output.gds"

    gds_content1 = b"GDS design 1" * 50
    gds_content2 = b"GDS design 2" * 50

    # Create ZIP with multiple GDS files
    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("design1.gds", gds_content1)
        zf.writestr("design2.gds", gds_content2)

    # Verify ValueError raised with correct message
    with pytest.raises(
        ValueError,
        match="Archive contains multiple GDS/OASIS files",
    ):
        processor.process(zip_file, output_file, max_size=10_000)


def test_zip_size_limit_enforcement(temp_dir):
    """Test ZipExtractor enforces size limits and cleans up on error."""
    processor = ZipExtractor()
    zip_file = temp_dir / "archive.zip"
    output_file = temp_dir / "output.gds"

    # Create ZIP with file larger than max_size
    large_content = b"X" * 20_000

    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("large.gds", large_content)

    # Verify ValueError raised with size limit message
    with pytest.raises(ValueError, match=r"exceeds maximum size.*20000.*10000"):
        processor.process(zip_file, output_file, max_size=10_000)

    # Verify output file was cleaned up (doesn't exist after error)
    assert not output_file.exists()
