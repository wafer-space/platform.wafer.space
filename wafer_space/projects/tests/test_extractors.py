import tarfile
import zipfile
from io import BytesIO

import pytest

from wafer_space.projects.processors.extractors import EXTRACTOR_PRIORITY
from wafer_space.projects.processors.extractors import TarExtractor
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


# ==================== TarExtractor Tests ====================


def test_tar_can_process_valid_tar(temp_dir):
    """Test TarExtractor recognizes uncompressed tar files."""
    processor = TarExtractor()
    tar_file = temp_dir / "archive.tar"

    # Create valid tar file
    with tarfile.open(tar_file, "w") as tf:
        info = tarfile.TarInfo(name="test.gds")
        info.size = 7
        tf.addfile(info, BytesIO(b"content"))

    assert processor.can_process("archive.tar", tar_file) is True


def test_tar_can_process_compressed(temp_dir):
    """Test TarExtractor recognizes compressed tar files."""
    processor = TarExtractor()

    # Test .tar.gz
    tar_gz_file = temp_dir / "archive.tar.gz"
    with tarfile.open(tar_gz_file, "w:gz") as tf:
        info = tarfile.TarInfo(name="test.gds")
        info.size = 0
        tf.addfile(info)

    assert processor.can_process("archive.tar.gz", tar_gz_file) is True

    # Test .tar.bz2
    tar_bz2_file = temp_dir / "archive.tar.bz2"
    with tarfile.open(tar_bz2_file, "w:bz2") as tf:
        info = tarfile.TarInfo(name="test.gds")
        info.size = 0
        tf.addfile(info)

    assert processor.can_process("archive.tar.bz2", tar_bz2_file) is True

    # Test .tar.xz
    tar_xz_file = temp_dir / "archive.tar.xz"
    with tarfile.open(tar_xz_file, "w:xz") as tf:
        info = tarfile.TarInfo(name="test.gds")
        info.size = 0
        tf.addfile(info)

    assert processor.can_process("archive.tar.xz", tar_xz_file) is True


def test_tar_cannot_process_invalid(temp_dir):
    """Test TarExtractor rejects non-tar files."""
    processor = TarExtractor()

    # Test non-tar file
    txt_file = temp_dir / "test.txt"
    txt_file.write_bytes(b"not a tar file")
    assert processor.can_process("test.txt", txt_file) is False

    # Test wrong extension
    fake_tar = temp_dir / "fake.tar"
    fake_tar.write_bytes(b"not a tar file")
    assert processor.can_process("fake.tar", fake_tar) is False


def test_tar_extract_single_file(temp_dir):
    """Test extracting single .gds file from tar."""
    processor = TarExtractor()
    tar_file = temp_dir / "archive.tar"
    output_file = temp_dir / "output.gds"

    gds_content = b"GDS binary data" * 100

    # Create tar with single GDS file
    with tarfile.open(tar_file, "w") as tf:
        info = tarfile.TarInfo(name="design.gds")
        info.size = len(gds_content)
        tf.addfile(info, BytesIO(gds_content))

    result = processor.process(tar_file, output_file, max_size=10_000)

    assert result.output_path == output_file
    assert result.filename == "design.gds"
    assert output_file.read_bytes() == gds_content
    assert result.metadata["processor"] == "TarExtractor"


def test_tar_priority():
    """Test TarExtractor has priority 50."""
    assert TarExtractor().get_priority() == EXTRACTOR_PRIORITY


def test_tar_ignores_non_gds_files(temp_dir):
    """Test TarExtractor ignores non-GDS/OASIS files in archive."""
    processor = TarExtractor()
    tar_file = temp_dir / "archive.tar"
    output_file = temp_dir / "output.gds"

    gds_content = b"GDS binary data" * 50
    readme_content = b"# Project Documentation\n"
    license_content = b"MIT License\n"

    # Create tar with multiple files, only one valid
    with tarfile.open(tar_file, "w") as tf:
        # Add README
        info = tarfile.TarInfo(name="README.md")
        info.size = len(readme_content)
        tf.addfile(info, BytesIO(readme_content))

        # Add LICENSE
        info = tarfile.TarInfo(name="LICENSE.txt")
        info.size = len(license_content)
        tf.addfile(info, BytesIO(license_content))

        # Add GDS file
        info = tarfile.TarInfo(name="design.gds")
        info.size = len(gds_content)
        tf.addfile(info, BytesIO(gds_content))

    result = processor.process(tar_file, output_file, max_size=10_000)

    # Verify only design.gds was extracted
    assert result.output_path == output_file
    assert result.filename == "design.gds"
    assert output_file.read_bytes() == gds_content
    # Total files includes README, LICENSE, and design.gds
    expected_file_count = 3
    assert result.metadata["total_files"] == expected_file_count


def test_tar_error_on_empty_archive(temp_dir):
    """Test TarExtractor raises error for archive with no valid files."""
    processor = TarExtractor()
    tar_file = temp_dir / "archive.tar"
    output_file = temp_dir / "output.gds"

    readme_content = b"# Documentation\n"
    license_content = b"MIT License\n"

    # Create tar with only non-GDS files
    with tarfile.open(tar_file, "w") as tf:
        info = tarfile.TarInfo(name="README.md")
        info.size = len(readme_content)
        tf.addfile(info, BytesIO(readme_content))

        info = tarfile.TarInfo(name="LICENSE.txt")
        info.size = len(license_content)
        tf.addfile(info, BytesIO(license_content))

    # Verify ValueError raised with correct message
    with pytest.raises(ValueError, match="Archive contains no GDS or OASIS files"):
        processor.process(tar_file, output_file, max_size=10_000)


def test_tar_error_on_multiple_valid_files(temp_dir):
    """Test TarExtractor raises error for archive with multiple valid files."""
    processor = TarExtractor()
    tar_file = temp_dir / "archive.tar"
    output_file = temp_dir / "output.gds"

    gds_content1 = b"GDS design 1" * 50
    gds_content2 = b"GDS design 2" * 50

    # Create tar with multiple GDS files
    with tarfile.open(tar_file, "w") as tf:
        info = tarfile.TarInfo(name="design1.gds")
        info.size = len(gds_content1)
        tf.addfile(info, BytesIO(gds_content1))

        info = tarfile.TarInfo(name="design2.gds")
        info.size = len(gds_content2)
        tf.addfile(info, BytesIO(gds_content2))

    # Verify ValueError raised with correct message
    with pytest.raises(
        ValueError,
        match="Archive contains multiple GDS/OASIS files",
    ):
        processor.process(tar_file, output_file, max_size=10_000)


def test_tar_size_limit_enforcement(temp_dir):
    """Test TarExtractor enforces size limits and cleans up on error."""
    processor = TarExtractor()
    tar_file = temp_dir / "archive.tar"
    output_file = temp_dir / "output.gds"

    # Create tar with file larger than max_size
    large_content = b"X" * 20_000

    with tarfile.open(tar_file, "w") as tf:
        info = tarfile.TarInfo(name="large.gds")
        info.size = len(large_content)
        tf.addfile(info, BytesIO(large_content))

    # Verify ValueError raised with size limit message
    with pytest.raises(ValueError, match=r"exceeds maximum size.*20000.*10000"):
        processor.process(tar_file, output_file, max_size=10_000)

    # Verify output file was cleaned up (doesn't exist after error)
    assert not output_file.exists()
