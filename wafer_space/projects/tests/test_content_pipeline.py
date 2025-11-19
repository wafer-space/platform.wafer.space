"""Tests for ContentPipeline orchestration system."""

import gzip
import tarfile
import zipfile
from io import BytesIO
from unittest import mock

import pytest

from wafer_space.projects.content_pipeline import ContentPipeline
from wafer_space.projects.content_pipeline import cleanup_temp_dir
from wafer_space.projects.content_pipeline import get_temp_dir_for_file
from wafer_space.projects.content_processors import ContentProcessorRegistry
from wafer_space.projects.processors.decompressors import Bzip2Decompressor
from wafer_space.projects.processors.decompressors import GzipDecompressor
from wafer_space.projects.processors.decompressors import XzDecompressor
from wafer_space.projects.processors.extractors import TarExtractor
from wafer_space.projects.processors.extractors import ZipExtractor

# Expected stage counts for multi-stage tests
EXPECTED_NESTED_STAGES = 2
EXPECTED_RGLOB_COUNT = 4  # 1 subdir + 3 files


@pytest.fixture
def registry():
    """Create registry with all processors."""
    reg = ContentProcessorRegistry()
    # Register decompressors (priority 100)
    reg.register(GzipDecompressor())
    reg.register(Bzip2Decompressor())
    reg.register(XzDecompressor())
    # Register extractors (priority 50)
    reg.register(ZipExtractor())
    reg.register(TarExtractor())
    return reg


@pytest.fixture
def pipeline(registry):
    """Create pipeline instance."""
    return ContentPipeline(registry)


@pytest.fixture
def temp_dir(tmp_path):
    """Provide temporary directory."""
    return tmp_path


def test_pipeline_simple_decompression(pipeline, temp_dir):
    """Test pipeline handles simple .gds.gz -> .gds decompression."""
    # Create input file
    input_file = temp_dir / "design.gds.gz"
    gds_content = b"GDS binary data" * 100

    with gzip.open(input_file, "wb") as f:
        f.write(gds_content)

    # Process through pipeline
    result = pipeline.process_file(
        input_file,
        "design.gds.gz",
        temp_dir,
        max_size=10_000,
    )

    # Verify result
    assert result.filename == "design.gds"
    assert result.size_bytes == len(gds_content)
    assert result.output_path.read_bytes() == gds_content
    assert result.metadata["pipeline_stages"] == 1


def test_pipeline_zip_extraction(pipeline, temp_dir):
    """Test pipeline extracts .gds from .zip archive."""
    # Create ZIP with single GDS file
    zip_file = temp_dir / "archive.zip"
    gds_content = b"GDS design content" * 50

    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("design.gds", gds_content)

    # Process through pipeline
    result = pipeline.process_file(
        zip_file,
        "archive.zip",
        temp_dir,
        max_size=10_000,
    )

    # Verify result
    assert result.filename == "design.gds"
    assert result.size_bytes == len(gds_content)
    assert result.output_path.read_bytes() == gds_content
    assert result.metadata["pipeline_stages"] == 1


def test_pipeline_nested_compression(pipeline, temp_dir):
    """Test pipeline handles .zip with .gds.gz (three stages!)."""
    # Create compressed GDS file
    gds_content = b"GDS binary data" * 50
    gds_gz_bytes = BytesIO()
    with gzip.open(gds_gz_bytes, "wb") as f:
        f.write(gds_content)
    gds_gz_data = gds_gz_bytes.getvalue()

    # Create ZIP containing the compressed GDS
    zip_file = temp_dir / "archive.zip"
    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("design.gds.gz", gds_gz_data)

    # Process through pipeline
    result = pipeline.process_file(
        zip_file,
        "archive.zip",
        temp_dir,
        max_size=10_000,
    )

    # Verify result - should go through 2 stages:
    # Stage 1: Extract design.gds.gz from ZIP
    # Stage 2: Decompress design.gds.gz to design.gds
    assert result.filename == "design.gds"
    assert result.size_bytes == len(gds_content)
    assert result.output_path.read_bytes() == gds_content
    assert result.metadata["pipeline_stages"] == EXPECTED_NESTED_STAGES


def test_pipeline_tar_bz2_nested(pipeline, temp_dir):
    """Test pipeline handles .tar.bz2 with .gds inside."""
    # Create tar.bz2 archive with GDS file
    tar_file = temp_dir / "archive.tar.bz2"
    gds_content = b"GDS design data" * 50

    with tarfile.open(tar_file, "w:bz2") as tf:
        info = tarfile.TarInfo(name="design.gds")
        info.size = len(gds_content)
        tf.addfile(info, BytesIO(gds_content))

    # Process through pipeline with larger size limit (tar has overhead)
    result = pipeline.process_file(
        tar_file,
        "archive.tar.bz2",
        temp_dir,
        max_size=20_000,
    )

    # Verify result - pipeline goes through 2 stages:
    # Stage 1: Bzip2Decompressor decompresses .tar.bz2 to .tar
    # Stage 2: TarExtractor extracts .gds from .tar
    assert result.filename == "design.gds"
    assert result.size_bytes == len(gds_content)
    assert result.output_path.read_bytes() == gds_content
    assert result.metadata["pipeline_stages"] == EXPECTED_NESTED_STAGES


def test_pipeline_no_processing_needed(pipeline, temp_dir):
    """Test pipeline handles plain .gds file (pass-through)."""
    # Create plain GDS file
    gds_file = temp_dir / "design.gds"
    gds_content = b"GDS binary data" * 50
    gds_file.write_bytes(gds_content)

    # Process through pipeline
    result = pipeline.process_file(
        gds_file,
        "design.gds",
        temp_dir,
        max_size=10_000,
    )

    # Verify result - no processing, just return input
    assert result.filename == "design.gds"
    assert result.size_bytes == len(gds_content)
    assert result.output_path == gds_file  # Same file!
    assert result.metadata["pipeline_stages"] == 0


def test_pipeline_size_limit_enforcement(pipeline, temp_dir):
    """Test pipeline enforces size limits at each stage."""
    # Create large gzipped file
    input_file = temp_dir / "large.gds.gz"
    large_content = b"X" * 20_000

    with gzip.open(input_file, "wb") as f:
        f.write(large_content)

    # Try to process with small size limit
    with pytest.raises(ValueError, match="exceeds maximum size"):
        pipeline.process_file(
            input_file,
            "large.gds.gz",
            temp_dir,
            max_size=10_000,
        )


def test_temp_dir_creation(temp_dir):
    """Test temp directory structure is created correctly."""
    # Mock celery task and settings
    with (
        mock.patch("wafer_space.projects.content_pipeline.current_task") as mock_task,
        mock.patch("wafer_space.projects.content_pipeline.settings") as mock_settings,
    ):
        mock_task.request.id = "test-task-123"
        mock_settings.MEDIA_ROOT = str(temp_dir)

        # Get temp directory
        result_dir = get_temp_dir_for_file(project_file_id=42)

        # Verify directory structure
        expected_path = temp_dir / "temp" / "task_test-task-123" / "file_42"
        assert result_dir == expected_path
        assert result_dir.exists()
        assert result_dir.is_dir()


def test_temp_dir_creation_no_task(temp_dir):
    """Test temp directory creation when no celery task is active."""
    # Mock no active task and settings
    with (
        mock.patch("wafer_space.projects.content_pipeline.current_task", None),
        mock.patch("wafer_space.projects.content_pipeline.settings") as mock_settings,
    ):
        mock_settings.MEDIA_ROOT = str(temp_dir)

        # Get temp directory
        result_dir = get_temp_dir_for_file(project_file_id=99)

        # Verify directory uses "unknown" task ID
        expected_path = temp_dir / "temp" / "task_unknown" / "file_99"
        assert result_dir == expected_path
        assert result_dir.exists()


def test_temp_dir_cleanup(temp_dir):
    """Test cleanup_temp_dir removes all files."""
    # Create test directory structure
    test_dir = temp_dir / "test_cleanup"
    test_dir.mkdir()

    # Create some files
    (test_dir / "file1.txt").write_text("content1")
    (test_dir / "file2.txt").write_text("content2")

    # Create subdirectory with files
    sub_dir = test_dir / "subdir"
    sub_dir.mkdir()
    (sub_dir / "file3.txt").write_text("content3")

    # Verify directory exists
    assert test_dir.exists()
    assert len(list(test_dir.rglob("*"))) == EXPECTED_RGLOB_COUNT

    # Cleanup
    cleanup_temp_dir(test_dir)

    # Verify directory is gone
    assert not test_dir.exists()


def test_temp_dir_cleanup_nonexistent(temp_dir):
    """Test cleanup_temp_dir handles nonexistent directory gracefully."""
    # Try to cleanup directory that doesn't exist
    nonexistent_dir = temp_dir / "does_not_exist"

    # Should not raise exception
    cleanup_temp_dir(nonexistent_dir)

    # Directory still doesn't exist
    assert not nonexistent_dir.exists()


def test_pipeline_intermediate_files_created(pipeline, temp_dir):
    """Test that pipeline creates intermediate files with stage numbers."""
    # Create ZIP with compressed GDS (2-stage processing)
    gds_content = b"GDS data" * 50
    gds_gz_bytes = BytesIO()
    with gzip.open(gds_gz_bytes, "wb") as f:
        f.write(gds_content)
    gds_gz_data = gds_gz_bytes.getvalue()

    zip_file = temp_dir / "archive.zip"
    with zipfile.ZipFile(zip_file, "w") as zf:
        zf.writestr("design.gds.gz", gds_gz_data)

    # Process through pipeline
    result = pipeline.process_file(
        zip_file,
        "archive.zip",
        temp_dir,
        max_size=10_000,
    )

    # Verify intermediate files exist after renaming
    # Stage 1: ZipExtractor creates "stage_1_archive.zip"
    #          then renames to "design.gds.gz"
    # Stage 2: GzipDecompressor creates "stage_2_design.gds.gz"
    #          then renames to "design.gds"
    final_file = temp_dir / "design.gds"

    assert final_file.exists()  # Final decompressed file
    assert result.output_path == final_file


def test_pipeline_stops_when_no_processor_matches(pipeline, temp_dir):
    """Test pipeline stops processing when no processor can handle file."""
    # Create a plain GDS file
    gds_file = temp_dir / "design.gds"
    gds_content = b"GDS data"
    gds_file.write_bytes(gds_content)

    # Process through pipeline
    result = pipeline.process_file(
        gds_file,
        "design.gds",
        temp_dir,
        max_size=10_000,
    )

    # Should stop immediately (no processing needed)
    assert result.metadata["pipeline_stages"] == 0
    assert result.output_path == gds_file
