"""Content processing pipeline for extracting/decompressing files.

This module orchestrates the three-stage content processing pipeline:
1. Decompression (priority 100) - gzip, bzip2, xz
2. Archive extraction (priority 50) - zip, tar
3. Decompression again (for nested compression like .gds.gz inside .zip)
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from celery import current_task
from django.conf import settings

from wafer_space.projects.content_processors import ContentProcessorRegistry
from wafer_space.projects.content_processors import ProcessorResult

logger = logging.getLogger(__name__)


class ContentPipeline:
    """Three-stage pipeline for content extraction.

    Stage 1: Decompression (gzip/bzip2/xz)
    Stage 2: Archive extraction (zip/tar)
    Stage 3: Decompression (handle .gds.gz inside .zip)
    """

    def __init__(self, registry: ContentProcessorRegistry) -> None:
        """Initialize pipeline with processor registry.

        Args:
            registry: Registry containing all available processors
        """
        self.registry = registry

    def process_file(
        self,
        input_path: Path,
        filename: str,
        temp_dir: Path,
        *,
        max_size: int,
    ) -> ProcessorResult:
        """Process file through pipeline stages.

        Args:
            input_path: Path to input file
            filename: Original filename (for format detection)
            temp_dir: Temporary directory for intermediate files
            max_size: Maximum allowed output file size

        Returns:
            ProcessorResult with final output file

        Raises:
            ValueError: If no valid GDS/OASIS file found or size exceeded
        """
        current_path = input_path
        current_filename = filename
        stage_number = 0

        # Get all processors sorted by priority (high to low)
        processors = self.registry.get_processors()

        # Run up to 3 stages (decompression -> extraction -> decompression)
        for _ in range(3):
            # Find first processor that can handle current file
            processor_used = None
            for processor in processors:
                if processor.can_process(current_filename, current_path):
                    stage_number += 1

                    # Create output path for this stage
                    # Use current filename so processors can derive new filename from it
                    output_path = temp_dir / f"stage_{stage_number}_{current_filename}"

                    logger.info(
                        "Pipeline stage %d: Processing %s with %s",
                        stage_number,
                        current_filename,
                        processor.__class__.__name__,
                    )

                    # Process the file
                    result = processor.process(
                        current_path, output_path, max_size=max_size
                    )

                    # Rename output file to match the result filename
                    # This ensures next stage can correctly determine file type
                    final_output_path = result.output_path.parent / result.filename
                    if result.output_path != final_output_path:
                        result.output_path.rename(final_output_path)

                    # Update current path and filename for next stage
                    current_path = final_output_path
                    current_filename = result.filename

                    processor_used = processor
                    break

            # If no processor could handle the file, we're done
            if processor_used is None:
                break

        logger.info(
            "Pipeline complete after %d stages: final file is %s",
            stage_number,
            current_filename,
        )

        # Return final result
        return ProcessorResult(
            output_path=current_path,
            filename=current_filename,
            size_bytes=current_path.stat().st_size,
            metadata={
                "pipeline_stages": stage_number,
                "final_filename": current_filename,
            },
        )


def get_temp_dir_for_file(project_file_id: int) -> Path:
    """Get task-isolated temp directory for a file.

    Pattern: media/temp/task_{celery_task_id}/file_{project_file_id}/

    Args:
        project_file_id: Database ID of ProjectFile

    Returns:
        Path to temp directory (created if doesn't exist)
    """
    # Get celery task ID if available
    task_id = "unknown"
    if current_task and current_task.request and current_task.request.id:
        task_id = current_task.request.id

    # Build temp directory path
    media_root = Path(settings.MEDIA_ROOT)
    temp_dir = media_root / "temp" / f"task_{task_id}" / f"file_{project_file_id}"

    # Create directory if it doesn't exist
    temp_dir.mkdir(parents=True, exist_ok=True)

    logger.debug(
        "Created temp directory for file %d in task %s: %s",
        project_file_id,
        task_id,
        temp_dir,
    )

    return temp_dir


def cleanup_temp_dir(temp_dir: Path) -> None:
    """Recursively delete temp directory.

    Args:
        temp_dir: Directory to remove
    """
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
        logger.debug("Cleaned up temp directory: %s", temp_dir)
