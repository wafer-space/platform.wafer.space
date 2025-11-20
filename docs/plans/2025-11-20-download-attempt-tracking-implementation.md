# Download Attempt Tracking Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Track download attempts separately with their own checkpoints and errors to eliminate duplicates and enable retry history.

**Architecture:** Introduce `DownloadAttempt` model between `ProjectFile` and checkpoints/errors. Move download state from ProjectFile to DownloadAttempt. Clean slate migration drops existing data.

**Tech Stack:** Django 5.2, PostgreSQL 17, pytest-django

**Design Document:** `docs/plans/2025-11-20-download-attempt-tracking-design.md`

---

## Task 1: Create DownloadAttempt Model

**Files:**
- Modify: `wafer_space/projects/models.py` (add after FileProcessingError class ~line 590)

**Step 1: Add DownloadAttempt model to models.py**

Add after the `FileProcessingError` class (~line 590):

```python
class DownloadAttempt(models.Model):
    """Track a single download attempt for a ProjectFile.

    Created at the start of each download task execution. Tracks the full
    lifecycle of that execution including progress, checkpoints, and errors.

    Each ProjectFile can have multiple attempts (retries). Each attempt has
    its own set of checkpoints and errors, preventing duplicates.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DOWNLOADING = "downloading", "Downloading"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    # Foreign Keys
    project_file = models.ForeignKey(
        ProjectFile,
        on_delete=models.CASCADE,
        related_name="download_attempts",
        help_text="The file this download attempt belongs to",
    )

    # Attempt tracking
    attempt_number = models.IntegerField(
        help_text="Sequential attempt number (1, 2, 3...)",
    )
    started_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this attempt was created",
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this attempt finished (success or failure)",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        help_text="Current status of this download attempt",
    )

    # Download details (moved from ProjectFile)
    download_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When download actually started (after task setup)",
    )
    download_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When download finished (success or failure)",
    )
    download_error = models.TextField(
        blank=True,
        help_text="Error message if download failed",
    )
    download_duration_seconds = models.FloatField(
        null=True,
        blank=True,
        help_text="Total download duration in seconds",
    )
    bytes_downloaded = models.BigIntegerField(
        default=0,
        help_text="Total bytes downloaded in this attempt",
    )

    # Metadata
    last_activity = models.DateTimeField(
        auto_now=True,
        help_text="Last update to this attempt (for staleness detection)",
    )

    class Meta:
        ordering = ["-attempt_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["project_file", "attempt_number"],
                name="unique_attempt_per_file",
            ),
        ]
        indexes = [
            models.Index(fields=["project_file", "-attempt_number"]),
            models.Index(fields=["status"]),
            models.Index(fields=["last_activity"]),
        ]

    def __str__(self):
        return f"{self.project_file.original_filename} - Attempt #{self.attempt_number} ({self.get_status_display()})"

    @property
    def download_progress(self) -> int:
        """Calculate download progress percentage.

        Returns:
            int: Progress percentage (0-100)
        """
        if not self.project_file.file_size or self.project_file.file_size == 0:
            return 0
        progress = (self.bytes_downloaded / self.project_file.file_size) * 100
        return min(int(progress), 100)

    @property
    def download_speed_formatted(self) -> str:
        """Get formatted download speed.

        Returns:
            str: Speed like "1.2 MB/s" or empty string
        """
        if not self.download_duration_seconds or self.download_duration_seconds <= 0:
            return ""

        speed_bytes_per_sec = self.bytes_downloaded / self.download_duration_seconds

        # Format speed
        for unit in ["B/s", "KB/s", "MB/s", "GB/s"]:
            if speed_bytes_per_sec < 1024:
                return f"{speed_bytes_per_sec:.1f} {unit}"
            speed_bytes_per_sec /= 1024
        return f"{speed_bytes_per_sec:.1f} TB/s"
```

**Step 2: Run linting**

Run: `make lint-fix && make lint`
Expected: All checks passed

**Step 3: Commit model creation**

```bash
git add wafer_space/projects/models.py
git commit -m "Add DownloadAttempt model for tracking download retries

Created DownloadAttempt model to track individual download executions.
Each attempt has its own status, timestamps, and download metrics.

- Unique constraint on (project_file, attempt_number)
- Status choices: PENDING, DOWNLOADING, COMPLETED, FAILED
- Properties for download_progress and download_speed_formatted

Related to: docs/plans/2025-11-20-download-attempt-tracking-design.md"
```

---

## Task 2: Update ProjectFileChunk Foreign Key

**Files:**
- Modify: `wafer_space/projects/models.py` (ProjectFileChunk class ~line 592-655)

**Step 1: Update ProjectFileChunk model**

Find the `ProjectFileChunk` class (~line 592) and change the foreign key:

```python
class ProjectFileChunk(models.Model):
    """Track individual chunk downloads for performance analysis and resume capability.

    Records are created periodically during download (e.g., every 5MB) rather than
    for every single chunk, to balance granularity with database overhead.

    Each chunk belongs to a specific DownloadAttempt, not directly to ProjectFile.
    This prevents duplicate checkpoints when downloads are retried.
    """

    download_attempt = models.ForeignKey(  # CHANGED from project_file
        "DownloadAttempt",  # Use string to avoid ordering issues
        on_delete=models.CASCADE,
        related_name="chunks",
        help_text="The download attempt this checkpoint belongs to",
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        help_text="When this checkpoint was recorded",
    )
    bytes_downloaded = models.BigIntegerField(
        help_text="Cumulative bytes downloaded at this checkpoint",
    )
    chunk_number = models.IntegerField(
        help_text="Sequential chunk number for ordering",
    )

    class Meta:
        ordering = ["chunk_number"]
        indexes = [
            models.Index(fields=["download_attempt", "chunk_number"]),
            models.Index(fields=["download_attempt", "timestamp"]),
        ]

    def __str__(self):
        return (
            f"{self.download_attempt.project_file.original_filename} - "
            f"Attempt #{self.download_attempt.attempt_number} - "
            f"Chunk {self.chunk_number} ({self.bytes_downloaded:,} bytes)"
        )

    @property
    def speed_since_previous(self) -> float | None:
        """Calculate download speed since the previous chunk.

        Returns:
            float: Speed in bytes/sec, or None if this is the first chunk
        """
        # Get previous chunk FOR THIS ATTEMPT
        previous = (
            ProjectFileChunk.objects.filter(
                download_attempt=self.download_attempt,  # CHANGED from project_file
                chunk_number__lt=self.chunk_number,
            )
            .order_by("-chunk_number")
            .first()
        )

        if not previous:
            # This is the first chunk, calculate from download start
            if not self.download_attempt.download_started_at:  # CHANGED
                return None

            time_diff = self.timestamp - self.download_attempt.download_started_at  # CHANGED
            duration = time_diff.total_seconds()
            if duration <= 0:
                return None

            return self.bytes_downloaded / duration

        # Calculate speed since previous chunk
        time_diff = self.timestamp - previous.timestamp
        duration = time_diff.total_seconds()
        if duration <= 0:
            return None

        bytes_diff = self.bytes_downloaded - previous.bytes_downloaded
        return bytes_diff / duration
```

**Step 2: Run linting**

Run: `make lint-fix && make lint`
Expected: All checks passed

**Step 3: Commit chunk FK update**

```bash
git add wafer_space/projects/models.py
git commit -m "Update ProjectFileChunk to link to DownloadAttempt

Changed foreign key from ProjectFile to DownloadAttempt to prevent
duplicate checkpoints when downloads are retried.

- FK: project_file → download_attempt
- Updated speed_since_previous to filter by attempt
- Updated __str__ to show attempt number"
```

---

## Task 3: Update FileProcessingError Foreign Key

**Files:**
- Modify: `wafer_space/projects/models.py` (FileProcessingError class ~line 554-590)

**Step 1: Update FileProcessingError model**

Find the `FileProcessingError` class (~line 554) and change the foreign key:

```python
class FileProcessingError(models.Model):
    """Log of errors that occurred during file processing.

    Each error belongs to a specific DownloadAttempt, not directly to ProjectFile.
    This allows tracking which errors occurred in which retry attempt.
    """

    class ErrorType(models.TextChoices):
        DOWNLOAD = "download", "Download Error"
        EXTRACTION = "extraction", "Extraction Error"
        VALIDATION = "validation", "Validation Error"
        PIPELINE = "pipeline", "Pipeline Error"

    download_attempt = models.ForeignKey(  # CHANGED from project_file
        "DownloadAttempt",  # Use string to avoid ordering issues
        on_delete=models.CASCADE,
        related_name="errors",
        help_text="The download attempt this error belongs to",
    )
    error_type = models.CharField(max_length=20, choices=ErrorType.choices)
    error_message = models.TextField(help_text="User-friendly error message")
    error_detail = models.JSONField(
        default=dict,
        blank=True,
        help_text="Technical details: stack trace, context, etc. (superuser only)",
    )
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["download_attempt", "-occurred_at"]),  # CHANGED
            models.Index(fields=["error_type", "-occurred_at"]),
        ]

    def __str__(self):
        return f"Attempt #{self.download_attempt.attempt_number} - {self.get_error_type_display()}: {self.error_message[:50]}"
```

**Step 2: Run linting**

Run: `make lint-fix && make lint`
Expected: All checks passed

**Step 3: Commit error FK update**

```bash
git add wafer_space/projects/models.py
git commit -m "Update FileProcessingError to link to DownloadAttempt

Changed foreign key from ProjectFile to DownloadAttempt to track
errors per retry attempt.

- FK: project_file → download_attempt
- Updated indexes to use download_attempt
- Updated __str__ to show attempt number"
```

---

## Task 4: Add Helper Properties to ProjectFile

**Files:**
- Modify: `wafer_space/projects/models.py` (ProjectFile class ~line 200-500)

**Step 1: Add helper properties after existing properties**

Add these properties to the `ProjectFile` class (after existing properties, before methods):

```python
    # ==================== Download Attempt Helpers ====================

    @property
    def latest_attempt(self) -> "DownloadAttempt | None":
        """Get the most recent download attempt.

        Returns:
            DownloadAttempt | None: Latest attempt or None if no attempts yet
        """
        return self.download_attempts.first()  # Already ordered by -attempt_number

    @property
    def current_status(self) -> str:
        """Get current download status from latest attempt.

        Returns:
            str: Status from DownloadAttempt.Status choices, or PENDING if no attempts
        """
        from wafer_space.projects.models import DownloadAttempt  # Avoid circular import

        attempt = self.latest_attempt
        return attempt.status if attempt else DownloadAttempt.Status.PENDING

    @property
    def retry_count(self) -> int:
        """Get number of download attempts (including current).

        Returns:
            int: Number of attempts (0 if never tried)
        """
        return self.download_attempts.count()

    @property
    def download_progress(self) -> int:
        """Get current download progress percentage from latest attempt.

        Returns:
            int: Progress 0-100, or 0 if no active attempt
        """
        attempt = self.latest_attempt
        return attempt.download_progress if attempt else 0

    @property
    def download_status(self) -> str:
        """Backward compatibility property - maps to current_status.

        DEPRECATED: Use current_status instead.

        Returns:
            str: Status from latest attempt
        """
        return self.current_status
```

**Step 2: Run linting**

Run: `make lint-fix && make lint`
Expected: All checks passed

**Step 3: Commit helper properties**

```bash
git add wafer_space/projects/models.py
git commit -m "Add helper properties to ProjectFile for DownloadAttempt access

Added convenience properties to access latest attempt data:
- latest_attempt: Get most recent DownloadAttempt
- current_status: Get status from latest attempt
- retry_count: Count of all attempts
- download_progress: Progress from latest attempt
- download_status: Deprecated backward compat property

These provide clean API for views/templates without direct field access."
```

---

## Task 5: Create Migration

**Files:**
- Create: `wafer_space/projects/migrations/0014_downloadattempt_restructure.py`

**Step 1: Create migration**

Run: `make makemigrations`
Expected: Creates migration file

**Step 2: Review and edit migration**

The auto-generated migration will try to preserve data. We want to drop it instead.
Edit the migration file to this structure:

```python
# Generated by Django 5.2.6 on 2025-11-20

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0013_projectfile_processed_filename_and_more"),
    ]

    operations = [
        # Step 1: Drop old tables completely (loses data)
        migrations.DeleteModel(
            name="ProjectFileChunk",
        ),
        migrations.DeleteModel(
            name="FileProcessingError",
        ),

        # Step 2: Remove download fields from ProjectFile
        migrations.RemoveField(
            model_name="projectfile",
            name="download_status",
        ),
        migrations.RemoveField(
            model_name="projectfile",
            name="download_started_at",
        ),
        migrations.RemoveField(
            model_name="projectfile",
            name="download_completed_at",
        ),
        migrations.RemoveField(
            model_name="projectfile",
            name="download_error",
        ),
        migrations.RemoveField(
            model_name="projectfile",
            name="download_duration_seconds",
        ),
        migrations.RemoveField(
            model_name="projectfile",
            name="retry_count",
        ),
        migrations.RemoveField(
            model_name="projectfile",
            name="next_retry_at",
        ),
        migrations.RemoveField(
            model_name="projectfile",
            name="auto_retry_enabled",
        ),
        migrations.RemoveField(
            model_name="projectfile",
            name="max_retries",
        ),
        migrations.RemoveField(
            model_name="projectfile",
            name="last_activity",
        ),

        # Step 3: Create DownloadAttempt model
        migrations.CreateModel(
            name="DownloadAttempt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "attempt_number",
                    models.IntegerField(
                        help_text="Sequential attempt number (1, 2, 3...)"
                    ),
                ),
                (
                    "started_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="When this attempt was created",
                    ),
                ),
                (
                    "completed_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When this attempt finished (success or failure)",
                        null=True,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("downloading", "Downloading"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        help_text="Current status of this download attempt",
                        max_length=20,
                    ),
                ),
                (
                    "download_started_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When download actually started (after task setup)",
                        null=True,
                    ),
                ),
                (
                    "download_completed_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When download finished (success or failure)",
                        null=True,
                    ),
                ),
                (
                    "download_error",
                    models.TextField(
                        blank=True,
                        help_text="Error message if download failed",
                    ),
                ),
                (
                    "download_duration_seconds",
                    models.FloatField(
                        blank=True,
                        help_text="Total download duration in seconds",
                        null=True,
                    ),
                ),
                (
                    "bytes_downloaded",
                    models.BigIntegerField(
                        default=0,
                        help_text="Total bytes downloaded in this attempt",
                    ),
                ),
                (
                    "last_activity",
                    models.DateTimeField(
                        auto_now=True,
                        help_text="Last update to this attempt (for staleness detection)",
                    ),
                ),
                (
                    "project_file",
                    models.ForeignKey(
                        help_text="The file this download attempt belongs to",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="download_attempts",
                        to="projects.projectfile",
                    ),
                ),
            ],
            options={
                "ordering": ["-attempt_number"],
                "indexes": [
                    models.Index(
                        fields=["project_file", "-attempt_number"],
                        name="projects_do_project_abc123_idx",
                    ),
                    models.Index(
                        fields=["status"],
                        name="projects_do_status_def456_idx",
                    ),
                    models.Index(
                        fields=["last_activity"],
                        name="projects_do_last_ac_ghi789_idx",
                    ),
                ],
            },
        ),
        migrations.AddConstraint(
            model_name="downloadattempt",
            constraint=models.UniqueConstraint(
                fields=("project_file", "attempt_number"),
                name="unique_attempt_per_file",
            ),
        ),

        # Step 4: Recreate ProjectFileChunk with new FK
        migrations.CreateModel(
            name="ProjectFileChunk",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "timestamp",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="When this checkpoint was recorded",
                    ),
                ),
                (
                    "bytes_downloaded",
                    models.BigIntegerField(
                        help_text="Cumulative bytes downloaded at this checkpoint"
                    ),
                ),
                (
                    "chunk_number",
                    models.IntegerField(
                        help_text="Sequential chunk number for ordering"
                    ),
                ),
                (
                    "download_attempt",
                    models.ForeignKey(
                        help_text="The download attempt this checkpoint belongs to",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunks",
                        to="projects.downloadattempt",
                    ),
                ),
            ],
            options={
                "ordering": ["chunk_number"],
                "indexes": [
                    models.Index(
                        fields=["download_attempt", "chunk_number"],
                        name="projects_pr_downloa_jkl012_idx",
                    ),
                    models.Index(
                        fields=["download_attempt", "timestamp"],
                        name="projects_pr_downloa_mno345_idx",
                    ),
                ],
            },
        ),

        # Step 5: Recreate FileProcessingError with new FK
        migrations.CreateModel(
            name="FileProcessingError",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "error_type",
                    models.CharField(
                        choices=[
                            ("download", "Download Error"),
                            ("extraction", "Extraction Error"),
                            ("validation", "Validation Error"),
                            ("pipeline", "Pipeline Error"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "error_message",
                    models.TextField(help_text="User-friendly error message"),
                ),
                (
                    "error_detail",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Technical details: stack trace, context, etc. (superuser only)",
                    ),
                ),
                ("occurred_at", models.DateTimeField(auto_now_add=True)),
                (
                    "download_attempt",
                    models.ForeignKey(
                        help_text="The download attempt this error belongs to",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="errors",
                        to="projects.downloadattempt",
                    ),
                ),
            ],
            options={
                "ordering": ["-occurred_at"],
                "indexes": [
                    models.Index(
                        fields=["download_attempt", "-occurred_at"],
                        name="projects_fi_downloa_pqr678_idx",
                    ),
                    models.Index(
                        fields=["error_type", "-occurred_at"],
                        name="projects_fi_error_t_stu901_idx",
                    ),
                ],
            },
        ),
    ]
```

**Step 3: Run migration**

Run: `make migrate`
Expected: Migration applies successfully, data is dropped

**Step 4: Commit migration**

```bash
git add wafer_space/projects/migrations/0014_downloadattempt_restructure.py
git commit -m "Add migration for DownloadAttempt restructure (BREAKS DATA)

Clean slate migration that drops and recreates checkpoint/error tables:
1. Drop ProjectFileChunk table
2. Drop FileProcessingError table
3. Remove download fields from ProjectFile
4. Create DownloadAttempt model
5. Recreate ProjectFileChunk with FK to DownloadAttempt
6. Recreate FileProcessingError with FK to DownloadAttempt

WARNING: This migration DELETES ALL:
- Existing checkpoints
- Existing error logs
- In-progress download state

This is intentional and acceptable during active development."
```

---

## Task 6: Update download_file Task - Attempt Creation

**Files:**
- Modify: `wafer_space/projects/tasks.py` (download_file function ~line 880)

**Step 1: Import DownloadAttempt**

Add import at top of file with other model imports (~line 30):

```python
from .models import (
    DownloadAttempt,  # ADD THIS
    FileProcessingError,
    Project,
    ProjectFile,
    ProjectFileChunk,
)
```

**Step 2: Create attempt at start of download_file**

Find the `download_file` function (~line 880) and add attempt creation right after getting the project_file:

```python
@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def download_file(self, project_file_id: int) -> dict[str, Any]:
    """Download a file from a URL with progress tracking.

    Args:
        project_file_id: ID of ProjectFile to download

    Returns:
        dict: Download result with status and metadata
    """
    logger.info("Starting download task for ProjectFile ID: %d", project_file_id)

    # Get the project file
    try:
        project_file = ProjectFile.objects.select_related("project").get(
            id=project_file_id
        )
    except ProjectFile.DoesNotExist:
        msg = f"ProjectFile with ID {project_file_id} not found"
        logger.error(msg)
        raise

    # Create new download attempt
    attempt = DownloadAttempt.objects.create(
        project_file=project_file,
        attempt_number=project_file.download_attempts.count() + 1,
        status=DownloadAttempt.Status.DOWNLOADING,
    )
    logger.info(
        "Created DownloadAttempt #%d for file: %s",
        attempt.attempt_number,
        project_file.original_filename,
    )

    # Rest of function continues...
```

**Step 3: Run linting**

Run: `make lint-fix && make lint`
Expected: All checks passed

**Step 4: Commit attempt creation**

```bash
git add wafer_space/projects/tasks.py
git commit -m "Create DownloadAttempt at start of download_file task

Added attempt creation logic:
- Import DownloadAttempt model
- Create attempt with auto-incremented attempt_number
- Set initial status to DOWNLOADING
- Log attempt creation

Each task execution now creates a separate attempt record."
```

---

## Task 7: Update download_file Task - Progress Updates

**Files:**
- Modify: `wafer_space/projects/tasks.py` (multiple locations in download_file)

**Step 1: Update last_activity saves**

Find all occurrences of `project_file.last_activity = timezone.now()` and change to use `attempt`:

```python
# OLD (~line 786):
project_file.last_activity = timezone.now()
project_file.save(update_fields=["last_activity"])

# NEW:
attempt.last_activity = timezone.now()
attempt.save(update_fields=["last_activity"])
```

**Step 2: Update checkpoint creation**

Find `ProjectFileChunk.objects.create(` (~line 791) and change to use attempt:

```python
# OLD:
ProjectFileChunk.objects.create(
    project_file=state.project_file,
    bytes_downloaded=last_db_update_bytes,
    chunk_number=chunk_count,
)

# NEW:
ProjectFileChunk.objects.create(
    download_attempt=attempt,
    bytes_downloaded=last_db_update_bytes,
    chunk_number=chunk_count,
)
```

**Step 3: Update status fields on completion**

Find where download completes successfully and update:

```python
# Find code that sets download_status = COMPLETED
# Change from:
project_file.download_status = ProjectFile.DownloadStatus.COMPLETED
project_file.download_completed_at = timezone.now()
project_file.save(...)

# To:
attempt.status = DownloadAttempt.Status.COMPLETED
attempt.download_completed_at = timezone.now()
attempt.completed_at = timezone.now()
attempt.save(update_fields=["status", "download_completed_at", "completed_at"])
```

**Step 4: Run linting**

Run: `make lint-fix && make lint`
Expected: All checks passed

**Step 5: Commit progress updates**

```bash
git add wafer_space/projects/tasks.py
git commit -m "Update download progress to use DownloadAttempt

Changed all progress tracking to use attempt instead of project_file:
- last_activity updates → attempt.last_activity
- Checkpoint creation → download_attempt FK
- Status updates → attempt.status
- Completion timestamps → attempt.completed_at

Download state now properly tracked per attempt."
```

---

## Task 8: Update download_file Task - Error Handling

**Files:**
- Modify: `wafer_space/projects/tasks.py` (error handling sections)

**Step 1: Update FileProcessingError creation**

Find all `FileProcessingError.objects.create(` calls (~lines 1145, 1427) and update:

```python
# OLD:
FileProcessingError.objects.create(
    project_file=project_file,
    error_type=FileProcessingError.ErrorType.PIPELINE,
    error_message=str(e),
    error_detail={...}
)

# NEW:
FileProcessingError.objects.create(
    download_attempt=attempt,
    error_type=FileProcessingError.ErrorType.PIPELINE,
    error_message=str(e),
    error_detail={...}
)
```

**Step 2: Update failure status setting**

Find code that sets status to FAILED and update:

```python
# OLD:
project_file.download_status = ProjectFile.DownloadStatus.FAILED
project_file.download_error = f"Pipeline error: {e}"
project_file.save(update_fields=["download_status", "download_error"])

# NEW:
attempt.status = DownloadAttempt.Status.FAILED
attempt.download_error = f"Pipeline error: {e}"
attempt.completed_at = timezone.now()
attempt.save(update_fields=["status", "download_error", "completed_at"])
```

**Step 3: Run linting**

Run: `make lint-fix && make lint`
Expected: All checks passed

**Step 4: Commit error handling**

```bash
git add wafer_space/projects/tasks.py
git commit -m "Update error handling to use DownloadAttempt

Changed error logging to use attempt:
- FileProcessingError creation → download_attempt FK
- Failure status → attempt.status = FAILED
- Error messages → attempt.download_error
- Set attempt.completed_at on failure

Errors now properly associated with specific attempts."
```

---

## Task 9: Update ProjectDetailView

**Files:**
- Modify: `wafer_space/projects/views.py` (ProjectDetailView class ~line 100)

**Step 1: Update get_context_data method**

Find `ProjectDetailView.get_context_data` and update to use latest_attempt:

```python
def get_context_data(self, **kwargs):
    """Add file information and download progress to context."""
    context = super().get_context_data(**kwargs)
    project = self.get_object()

    # Get in-progress and submitted files
    in_progress_file = project.files.filter(is_active=True).first()
    submitted_file = project.submitted_file

    # Get latest download attempt for in-progress file
    latest_attempt = None
    if in_progress_file:
        latest_attempt = in_progress_file.latest_attempt

    context.update(
        {
            "in_progress_file": in_progress_file,
            "submitted_file": submitted_file,
            "latest_attempt": latest_attempt,  # NEW: Pass attempt to template
            "history_files": project.files.filter(is_active=False).order_by(
                "-uploaded_at"
            )[:10],
        }
    )

    # Download progress from latest attempt
    if latest_attempt and latest_attempt.status == DownloadAttempt.Status.DOWNLOADING:
        context["show_progress"] = True
        context["progress"] = {
            "progress": latest_attempt.download_progress,
            "message": f"Downloaded {latest_attempt.bytes_downloaded:,} bytes",
        }

    # Error display
    if (
        latest_attempt
        and latest_attempt.status == DownloadAttempt.Status.FAILED
        and latest_attempt.download_error
    ):
        context["show_error"] = True
        context["error_message"] = latest_attempt.download_error
        context["active_file"] = in_progress_file

    # Manufacturability check status
    if in_progress_file:
        check_status = (
            ManufacturabilityCheck.objects.filter(project=project)
            .order_by("-created_at")
            .first()
        )
        if check_status:
            context["check_status"] = check_status

    return context
```

**Step 2: Add DownloadAttempt import**

Add import at top of views.py:

```python
from .models import (
    DownloadAttempt,  # ADD THIS
    ManufacturabilityCheck,
    Project,
    ProjectFile,
)
```

**Step 3: Run linting**

Run: `make lint-fix && make lint`
Expected: All checks passed

**Step 4: Commit view update**

```bash
git add wafer_space/projects/views.py
git commit -m "Update ProjectDetailView to use DownloadAttempt

Changed view to access download state via latest_attempt:
- Get latest_attempt from in_progress_file
- Pass latest_attempt to template context
- Progress from attempt.download_progress
- Status from attempt.status
- Error from attempt.download_error

Import DownloadAttempt model for status checks."
```

---

## Task 10: Update ProgressView

**Files:**
- Modify: `wafer_space/projects/views.py` (ProjectFileProgressView ~line 200)

**Step 1: Update progress JSON response**

Find `ProjectFileProgressView.get` method and update:

```python
def get(self, request, *args, **kwargs):
    """Return download progress as JSON.

    Returns:
        JsonResponse: Progress data including percentage, status, and message
    """
    project = self.get_object()
    in_progress_file = project.files.filter(is_active=True).first()

    if not in_progress_file:
        return JsonResponse(
            {"error": "No active file for this project"},
            status=404,
        )

    # Get latest download attempt
    latest_attempt = in_progress_file.latest_attempt
    if not latest_attempt:
        return JsonResponse(
            {"error": "No download attempt found"},
            status=404,
        )

    # Build response from attempt data
    response_data = {
        "progress": latest_attempt.download_progress,
        "status": latest_attempt.status,
        "message": f"Downloaded {latest_attempt.bytes_downloaded:,} bytes",
    }

    # Add file size if known
    if in_progress_file.file_size:
        response_data["total"] = in_progress_file.file_size
        response_data[
            "message"
        ] = f"Downloaded {latest_attempt.bytes_downloaded:,} of {in_progress_file.file_size:,} bytes"

    return JsonResponse(response_data)
```

**Step 2: Run linting**

Run: `make lint-fix && make lint`
Expected: All checks passed

**Step 3: Commit progress view update**

```bash
git add wafer_space/projects/views.py
git commit -m "Update ProjectFileProgressView to use DownloadAttempt

Changed progress API to return data from latest_attempt:
- Check for latest_attempt existence
- Return attempt.download_progress
- Return attempt.status
- Return attempt.bytes_downloaded
- Return 404 if no attempt found

Progress polling now reflects per-attempt state."
```

---

## Task 11: Update Templates - File Display Partial

**Files:**
- Modify: `wafer_space/templates/projects/_file_display.html`

**Step 1: Update partial to accept latest_attempt**

Change the template to expect `latest_attempt` parameter:

```django
{% load static %}

{# Reusable file display partial - used for both submitted and in-progress files #}
{# Parameters: #}
{#   - file: ProjectFile instance to display #}
{#   - latest_attempt: DownloadAttempt instance (optional) #}
{#   - show_details: (optional, default=False) Show errors and checkpoints #}

{# Show filename with transformation if applicable #}
{% if file.processed_filename and file.processed_filename != file.original_filename %}
  {# ... unchanged ... #}
{% endif %}

{# Status Badges #}
<p class="mb-3">
  <strong>Download Status:</strong>
  {% if latest_attempt %}
    <span id="status-badge" class="badge {% if latest_attempt.status == 'completed' %}bg-success{% elif latest_attempt.status == 'failed' %}bg-danger{% elif latest_attempt.status == 'downloading' %}bg-primary{% else %}bg-secondary{% endif %}">
      {% if latest_attempt.status == 'completed' %}
        <i class="bi bi-check-circle"></i>
      {% elif latest_attempt.status == 'failed' %}
        <i class="bi bi-exclamation-triangle"></i>
      {% elif latest_attempt.status == 'downloading' %}
        <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
      {% else %}
        <i class="bi bi-clock"></i>
      {% endif %}
      <span id="status-text">{{ latest_attempt.get_status_display }}</span>
    </span>
  {% else %}
    <span class="badge bg-secondary">
      <i class="bi bi-clock"></i> No attempts yet
    </span>
  {% endif %}

  {# Hash verification badge unchanged #}
  {% if file.hash_verified %}
    <span class="badge bg-success">
      <i class="bi bi-check-circle"></i> Hash Verified
    </span>
  {% elif latest_attempt and latest_attempt.status == 'completed' %}
    <span class="badge bg-warning text-dark">
      <i class="bi bi-exclamation-triangle"></i> Hash Not Verified
    </span>
  {% endif %}
</p>

{# Download Information #}
<div class="card bg-light">
  <div class="card-body">
    <h6 class="card-title">Download Information</h6>
    {# ... URL and file size unchanged ... #}

    {% if latest_attempt %}
      {% if latest_attempt.download_started_at %}
        <p class="mb-2">
          <strong>Download Started:</strong> {{ latest_attempt.download_started_at|date:"Y-m-d H:i:s" }}
        </p>
      {% endif %}
      {% if latest_attempt.download_completed_at and latest_attempt.status == 'completed' %}
        <p class="mb-2">
          <strong>Download Completed:</strong> {{ latest_attempt.download_completed_at|date:"Y-m-d H:i:s" }}
        </p>
      {% endif %}
      {% if latest_attempt.download_duration_seconds %}
        <p class="mb-2">
          <strong>Download Duration:</strong> {{ latest_attempt.download_duration_seconds|floatformat:1 }} seconds
        </p>
      {% endif %}
      {% if latest_attempt.download_speed_formatted %}
        <p class="mb-2">
          <strong>Average Download Speed:</strong> {{ latest_attempt.download_speed_formatted }}
        </p>
      {% endif %}
    {% endif %}

    {# Checkpoints - only if show_details and latest_attempt #}
    {% if show_details|default:False and latest_attempt and latest_attempt.chunks.exists %}
      <hr />
      <h6>Download Performance</h6>
      <p class="mb-2">
        <strong>Checkpoints Tracked:</strong> {{ latest_attempt.chunks.count }}
      </p>
      <details>
        <summary class="text-primary" style="cursor: pointer;">
          <i class="bi bi-graph-up"></i> View Download Timeline
        </summary>
        <div class="table-responsive mt-2">
          <table class="table table-sm table-striped">
            <thead>
              <tr>
                <th>Checkpoint</th>
                <th>Downloaded</th>
                <th>Time</th>
                <th>Speed</th>
              </tr>
            </thead>
            <tbody>
              {% for chunk in latest_attempt.chunks.all|dictsortreversed:"chunk_number" %}
                <tr>
                  <td>#{{ chunk.chunk_number }}</td>
                  <td>{{ chunk.bytes_downloaded|filesizeformat }}</td>
                  <td>{{ chunk.timestamp|date:"Y-m-d H:i:s" }}</td>
                  <td>
                    {% if chunk.speed_since_previous %}
                      {{ chunk.speed_since_previous|floatformat:0|filesizeformat }}/s
                    {% else %}
                      <span class="text-muted">-</span>
                    {% endif %}
                  </td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </details>
    {% endif %}

    {# Hashes section unchanged #}

    {# Errors - only if show_details and latest_attempt #}
    {% if show_details|default:False and latest_attempt and latest_attempt.errors.exists %}
      <hr class="my-3" />
      <div class="alert alert-danger" role="alert">
        <h6 class="alert-heading">
          <i class="bi bi-exclamation-triangle-fill"></i>
          Processing Errors ({{ latest_attempt.errors.count }})
        </h6>
        {% for error in latest_attempt.errors.all %}
          <div class="mb-3">
            <strong>{{ error.get_error_type_display }}:</strong>
            <p class="mb-1">{{ error.error_message|linebreaksbr }}</p>
            <small class="text-muted">
              <i class="bi bi-clock"></i>
              {{ error.occurred_at|date:"F d, Y g:i a" }}
            </small>
          </div>
          {% if not forloop.last %}<hr class="my-2" />{% endif %}
        {% endfor %}
        {# Technical details only for superusers #}
        {% if user.is_superuser and latest_attempt.errors.exists %}
          <hr class="my-3" />
          <details class="mt-2">
            <summary class="text-muted" style="cursor: pointer;">
              <i class="bi bi-shield-lock"></i>
              <strong>Technical Details (Superuser Only)</strong>
            </summary>
            <div class="mt-3">
              {% for error in latest_attempt.errors.all %}
                <div class="card bg-light mb-2">
                  <div class="card-header">
                    <small>
                      <strong>{{ error.get_error_type_display }}</strong> -
                      {{ error.occurred_at|date:"Y-m-d H:i:s" }}
                    </small>
                  </div>
                  <div class="card-body">
                    <pre class="mb-0 small"><code>{{ error.error_detail|pprint }}</code></pre>
                  </div>
                </div>
              {% endfor %}
            </div>
          </details>
        {% endif %}
      </div>
    {% endif %}
  </div>
</div>
```

**Step 2: Commit template update**

```bash
git add wafer_space/templates/projects/_file_display.html
git commit -m "Update _file_display.html to use latest_attempt

Changed partial to receive and use latest_attempt parameter:
- Status badge from attempt.status
- Download timestamps from attempt
- Checkpoints from attempt.chunks
- Errors from attempt.errors

Template now displays per-attempt data correctly."
```

---

## Task 12: Update Templates - Project Detail

**Files:**
- Modify: `wafer_space/templates/projects/project_detail.html`

**Step 1: Pass latest_attempt to file_display partial**

Find the include statements and add latest_attempt parameter:

```django
{# In-Progress File Section #}
{% if in_progress_file %}
  <div class="card mb-3">
    {# ... header unchanged ... #}
    <div class="card-body">
      {# Progress Bar for downloading files #}
      {% if show_progress %}
        {# ... progress bar unchanged ... #}
      {% endif %}
      {% include "projects/_file_display.html" with file=in_progress_file latest_attempt=latest_attempt show_details=True %}
      {# ... rest unchanged ... #}
    </div>
  </div>
{% endif %}

{# Submitted File Section #}
{% if submitted_file %}
  <div class="card mb-3 border-success">
    {# ... header unchanged ... #}
    <div class="card-body">
      {% include "projects/_file_display.html" with file=submitted_file latest_attempt=submitted_file.latest_attempt %}
    </div>
  </div>
{% endif %}
```

**Step 2: Commit template update**

```bash
git add wafer_space/templates/projects/project_detail.html
git commit -m "Update project_detail.html to pass latest_attempt

Added latest_attempt parameter to file_display includes:
- in_progress_file: Use latest_attempt from view context
- submitted_file: Use submitted_file.latest_attempt

Templates now have access to attempt data."
```

---

## Task 13: Write Model Tests

**Files:**
- Create: `wafer_space/projects/tests/test_download_attempt.py`

**Step 1: Write failing tests**

Create new test file:

```python
"""Tests for DownloadAttempt model."""

import pytest
from django.db import IntegrityError
from django.utils import timezone

from wafer_space.projects.models import DownloadAttempt, ProjectFile

pytestmark = pytest.mark.django_db


class TestDownloadAttemptCreation:
    """Test DownloadAttempt creation and constraints."""

    def test_create_attempt(self, project_file: ProjectFile):
        """Test creating a download attempt."""
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
        )
        assert attempt.attempt_number == 1
        assert attempt.status == DownloadAttempt.Status.PENDING
        assert attempt.bytes_downloaded == 0

    def test_unique_constraint(self, project_file: ProjectFile):
        """Test unique constraint on (project_file, attempt_number)."""
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
        )

        # Cannot create duplicate attempt number
        with pytest.raises(IntegrityError):
            DownloadAttempt.objects.create(
                project_file=project_file,
                attempt_number=1,
            )

    def test_multiple_attempts(self, project_file: ProjectFile):
        """Test creating multiple attempts for same file."""
        attempt1 = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
        )
        attempt2 = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=2,
        )

        assert project_file.download_attempts.count() == 2
        assert attempt1.attempt_number == 1
        assert attempt2.attempt_number == 2


class TestDownloadAttemptProperties:
    """Test DownloadAttempt computed properties."""

    def test_download_progress_zero_file_size(self, project_file: ProjectFile):
        """Test progress is 0 when file_size is 0."""
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            bytes_downloaded=100,
        )
        project_file.file_size = 0
        assert attempt.download_progress == 0

    def test_download_progress_partial(self, project_file: ProjectFile):
        """Test progress calculation with partial download."""
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            bytes_downloaded=50,
        )
        project_file.file_size = 100
        assert attempt.download_progress == 50

    def test_download_progress_complete(self, project_file: ProjectFile):
        """Test progress is 100 when fully downloaded."""
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            bytes_downloaded=100,
        )
        project_file.file_size = 100
        assert attempt.download_progress == 100

    def test_download_speed_formatted_no_duration(self, project_file: ProjectFile):
        """Test speed is empty when duration is 0."""
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            bytes_downloaded=1000,
            download_duration_seconds=0,
        )
        assert attempt.download_speed_formatted == ""

    def test_download_speed_formatted_bytes(self, project_file: ProjectFile):
        """Test speed formatting in bytes/s."""
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            bytes_downloaded=500,
            download_duration_seconds=1.0,
        )
        assert "B/s" in attempt.download_speed_formatted

    def test_download_speed_formatted_mb(self, project_file: ProjectFile):
        """Test speed formatting in MB/s."""
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            bytes_downloaded=10_000_000,  # 10 MB
            download_duration_seconds=1.0,
        )
        assert "MB/s" in attempt.download_speed_formatted


class TestProjectFileHelpers:
    """Test ProjectFile helper properties for DownloadAttempt."""

    def test_latest_attempt_none(self, project_file: ProjectFile):
        """Test latest_attempt is None when no attempts exist."""
        assert project_file.latest_attempt is None

    def test_latest_attempt_single(self, project_file: ProjectFile):
        """Test latest_attempt returns the only attempt."""
        attempt = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
        )
        assert project_file.latest_attempt == attempt

    def test_latest_attempt_multiple(self, project_file: ProjectFile):
        """Test latest_attempt returns most recent."""
        attempt1 = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
        )
        attempt2 = DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=2,
        )
        assert project_file.latest_attempt == attempt2

    def test_current_status_no_attempts(self, project_file: ProjectFile):
        """Test current_status is PENDING when no attempts."""
        assert project_file.current_status == DownloadAttempt.Status.PENDING

    def test_current_status_with_attempt(self, project_file: ProjectFile):
        """Test current_status reflects latest attempt."""
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )
        assert project_file.current_status == DownloadAttempt.Status.DOWNLOADING

    def test_retry_count_zero(self, project_file: ProjectFile):
        """Test retry_count is 0 when no attempts."""
        assert project_file.retry_count == 0

    def test_retry_count_multiple(self, project_file: ProjectFile):
        """Test retry_count returns attempt count."""
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=2,
        )
        assert project_file.retry_count == 2

    def test_download_progress_no_attempt(self, project_file: ProjectFile):
        """Test download_progress is 0 when no attempts."""
        assert project_file.download_progress == 0

    def test_download_progress_from_attempt(self, project_file: ProjectFile):
        """Test download_progress delegates to latest attempt."""
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            bytes_downloaded=50,
        )
        project_file.file_size = 100
        assert project_file.download_progress == 50
```

**Step 2: Run tests to verify they fail**

Run: `make test-app APP=projects`
Expected: Tests fail with import errors or assertion failures

**Step 3: Tests should now pass**

Since we already implemented the code, run tests again:

Run: `make test-app APP=projects`
Expected: All new tests pass

**Step 4: Commit tests**

```bash
git add wafer_space/projects/tests/test_download_attempt.py
git commit -m "Add tests for DownloadAttempt model and ProjectFile helpers

Test coverage:
- DownloadAttempt creation and unique constraint
- Multiple attempts per file
- Progress calculation properties
- Speed formatting properties
- ProjectFile.latest_attempt helper
- ProjectFile.current_status helper
- ProjectFile.retry_count helper
- ProjectFile.download_progress helper

All tests passing."
```

---

## Task 14: Update Existing Tests

**Files:**
- Modify: `wafer_space/projects/tests/test_tasks.py`
- Modify: `wafer_space/projects/tests/test_views.py`

**Step 1: Update task tests to create DownloadAttempt**

Find tests that mock or verify download status and update them. Example:

```python
# In test_download_file_success:
def test_download_file_success(self, mock_download, project_file):
    """Test successful file download creates attempt."""
    # Call task
    result = download_file(project_file.id)

    # Verify attempt created
    assert project_file.download_attempts.count() == 1
    attempt = project_file.latest_attempt
    assert attempt.attempt_number == 1
    assert attempt.status == DownloadAttempt.Status.COMPLETED
```

**Step 2: Update view tests to check for latest_attempt in context**

```python
# In test_project_detail_view:
def test_project_detail_includes_latest_attempt(self, client, project_with_file):
    """Test view passes latest_attempt to template."""
    response = client.get(f"/projects/{project_with_file.id}/")
    assert "latest_attempt" in response.context
```

**Step 3: Run tests**

Run: `make test-app APP=projects`
Expected: Fix any failures, all tests should pass

**Step 4: Commit test updates**

```bash
git add wafer_space/projects/tests/
git commit -m "Update existing tests for DownloadAttempt changes

Updated task and view tests to work with new DownloadAttempt model:
- Verify attempt creation in download tests
- Check latest_attempt in view context
- Update assertions to use attempt.status
- Fix any references to old fields

All tests passing."
```

---

## Task 15: Run Full Test Suite

**Files:**
- None (testing only)

**Step 1: Run all unit tests**

Run: `make test`
Expected: All tests pass (586+ tests)

**Step 2: Run browser tests**

Run: `make test-browser-headless`
Expected: All browser tests pass

**Step 3: If any tests fail, fix them**

For each failing test:
1. Identify the issue (usually field access that needs to change)
2. Update the test or code
3. Re-run tests
4. Commit the fix

**Step 4: Commit any final fixes**

```bash
git add .
git commit -m "Fix remaining test failures for DownloadAttempt

Final test fixes:
- [List specific fixes made]

All 586+ unit tests passing
All browser tests passing"
```

---

## Task 16: Manual Testing and Verification

**Files:**
- None (manual testing only)

**Step 1: Start development server**

Run: `make runserver`

**Step 2: Test download attempt creation**

1. Navigate to a project
2. Submit a new file URL
3. Verify download starts and creates attempt #1
4. Check database: `DownloadAttempt` record exists

**Step 3: Test checkpoint creation**

1. Download a large file (>10MB)
2. Verify checkpoints appear in UI
3. Check database: Checkpoints linked to attempt, not file

**Step 4: Test retry creates new attempt**

1. Cancel download or let it fail
2. Click "Retry Download"
3. Verify new attempt #2 created
4. Verify separate checkpoint sets in database

**Step 5: Test error display**

1. Submit URL that will fail (invalid domain)
2. Verify error message displays
3. Check database: Error linked to attempt

**Step 6: Document verification**

Create summary in commit message of manual testing results.

**Step 7: Commit verification notes**

```bash
git commit --allow-empty -m "Manual testing verification complete

Verified:
✓ Download creates DownloadAttempt #1
✓ Checkpoints link to attempt, not file
✓ Retry creates new attempt #2
✓ Separate checkpoint sets per attempt
✓ Errors link to attempt
✓ No duplicate checkpoints
✓ UI displays attempt data correctly
✓ Progress polling works
✓ Error messages display

Ready for deployment."
```

---

## Summary

**Implementation Complete!**

This plan restructures download tracking to use the `DownloadAttempt` model, eliminating duplicate checkpoints and enabling clear retry history.

**Key Changes:**
- New `DownloadAttempt` model tracks each download execution
- `ProjectFileChunk` and `FileProcessingError` now link to attempts
- Clean migration drops existing data (acceptable for development)
- Views and templates updated to use `latest_attempt`
- Full test coverage including model, task, view, and browser tests

**Files Modified:**
- `models.py` - Added DownloadAttempt, updated foreign keys
- `tasks.py` - Create attempts, link checkpoints/errors
- `views.py` - Access via latest_attempt
- `_file_display.html` - Display attempt data
- `project_detail.html` - Pass latest_attempt
- Tests - Full coverage

**Migration Impact:**
- Drops all existing checkpoints
- Drops all existing errors
- Removes download fields from ProjectFile
- Creates new DownloadAttempt structure

**Ready for:** Code review and deployment to staging
