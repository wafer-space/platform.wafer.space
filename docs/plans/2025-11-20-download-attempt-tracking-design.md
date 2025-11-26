# Download Attempt Tracking Design

**Date:** 2025-11-20
**Status:** Approved
**Migration:** Breaking change - drops existing checkpoint and error data

## Problem Statement

Currently, `ProjectFile` has a one-to-many relationship with `ProjectFileChunk` (checkpoints) and `FileProcessingError` (errors). When downloads are retried or state verification runs multiple times, duplicate checkpoints are created with the same chunk numbers but different timestamps. This makes it impossible to distinguish between download attempts or track the history of retry attempts.

**Example of Current Problem:**
```
Checkpoint #103 - 2025-11-20 11:37:58 - 102.1 MB
Checkpoint #103 - 2025-11-20 11:39:36 - 102.1 MB  (duplicate!)
Checkpoint #103 - 2025-11-20 11:41:24 - 102.1 MB  (duplicate!)
```

## Solution Overview

Introduce a `DownloadAttempt` model to track each download execution separately. Each attempt has its own set of checkpoints and errors, eliminating duplicates and providing clear download history.

**New Data Model Hierarchy:**
```
Project
  └─ ProjectFile (one-to-many)
       └─ DownloadAttempt (one-to-many)
            ├─ ProjectFileChunk (one-to-many) - checkpoints for THIS attempt
            └─ FileProcessingError (one-to-many) - errors for THIS attempt
```

## Design Decisions

### Trigger for New Attempt
**Decision:** Create a new DownloadAttempt on every download task execution.

**Rationale:** Maximum granularity - tracks retries, manual retries, and state verification separately. Each execution gets its own attempt record.

### Data Migration
**Decision:** Delete existing checkpoint and error data, start fresh.

**Rationale:**
- Simplest migration path
- No complex data transformation
- Clean separation with new model
- Acceptable data loss during active development
- No risk of migration bugs

### Progress Field Location
**Decision:** Move all download-related fields from ProjectFile to DownloadAttempt.

**Rationale:**
- Clean separation of concerns: ProjectFile = file metadata, DownloadAttempt = download execution
- No data duplication
- Self-contained attempt records
- Proper normalization

## Data Model Changes

### New Model: DownloadAttempt

```python
class DownloadAttempt(models.Model):
    """Tracks a single download attempt for a ProjectFile.

    Created at the start of each download task execution. Tracks the full
    lifecycle of that execution including progress, checkpoints, and errors.
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
        related_name="download_attempts"
    )

    # Attempt tracking
    attempt_number = models.IntegerField(
        help_text="Sequential attempt number (1, 2, 3...)"
    )
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )

    # Download details (moved from ProjectFile)
    download_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When download actually started (after task setup)"
    )
    download_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When download finished (success or failure)"
    )
    download_error = models.TextField(
        blank=True,
        help_text="Error message if download failed"
    )
    download_duration_seconds = models.FloatField(
        null=True,
        blank=True,
        help_text="Total download duration in seconds"
    )
    bytes_downloaded = models.BigIntegerField(
        default=0,
        help_text="Total bytes downloaded in this attempt"
    )

    # Metadata
    last_activity = models.DateTimeField(
        auto_now=True,
        help_text="Last update to this attempt (for staleness detection)"
    )

    class Meta:
        ordering = ["-attempt_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["project_file", "attempt_number"],
                name="unique_attempt_per_file"
            )
        ]
        indexes = [
            models.Index(fields=["project_file", "-attempt_number"]),
            models.Index(fields=["status"]),
            models.Index(fields=["last_activity"]),
        ]

    def __str__(self):
        return f"{self.project_file.original_filename} - Attempt #{self.attempt_number} ({self.status})"
```

### Updated Model: ProjectFileChunk

**Change:** Foreign key from `ProjectFile` to `DownloadAttempt`

```python
class ProjectFileChunk(models.Model):
    """Track checkpoint during a specific download attempt."""

    download_attempt = models.ForeignKey(  # Changed from project_file
        DownloadAttempt,
        on_delete=models.CASCADE,
        related_name="chunks"
    )
    # ... rest unchanged
```

### Updated Model: FileProcessingError

**Change:** Foreign key from `ProjectFile` to `DownloadAttempt`

```python
class FileProcessingError(models.Model):
    """Log errors that occurred during a specific download attempt."""

    download_attempt = models.ForeignKey(  # Changed from project_file
        DownloadAttempt,
        on_delete=models.CASCADE,
        related_name="errors"
    )
    # ... rest unchanged
```

### Updated Model: ProjectFile

**Fields Removed:**
- `download_status` → Now `DownloadAttempt.status`
- `download_started_at` → Now `DownloadAttempt.download_started_at`
- `download_completed_at` → Now `DownloadAttempt.download_completed_at`
- `download_error` → Now `DownloadAttempt.download_error`
- `download_duration_seconds` → Now `DownloadAttempt.download_duration_seconds`
- `retry_count` → Calculate from `download_attempts.count()`
- `next_retry_at` → Calculate based on latest attempt
- `auto_retry_enabled` → Determine from project/file state
- `max_retries` → Use settings constant
- `last_activity` → Now `DownloadAttempt.last_activity`

**Fields Kept:**
- `original_filename` - Immutable, belongs to file
- `processed_filename` - Final result, belongs to file
- `original_url` - Source URL, belongs to file
- `file_size` - Final verified size, belongs to file
- `is_active` - File activation status, belongs to file
- `hash_md5`, `hash_sha1`, `expected_hash_md5`, `expected_hash_sha1`
- `hash_verified` - Final verification status
- `uploaded_at` - When file record was created

**New Helper Properties:**

```python
@property
def latest_attempt(self) -> DownloadAttempt | None:
    """Get the most recent download attempt."""
    return self.download_attempts.first()  # Already ordered by -attempt_number

@property
def current_status(self) -> str:
    """Get current download status from latest attempt."""
    attempt = self.latest_attempt
    return attempt.status if attempt else DownloadAttempt.Status.PENDING

@property
def retry_count(self) -> int:
    """Get number of download attempts."""
    return self.download_attempts.count()
```

## Migration Strategy

### Migration 0014 - Clean Slate Restructure

**Operations:**
1. Drop `projects_projectfilechunk` table
2. Drop `projects_fileprocessingerror` table
3. Remove download-related fields from `projects_projectfile`
4. Create `projects_downloadattempt` table
5. Recreate `projects_projectfilechunk` with FK to DownloadAttempt
6. Recreate `projects_fileprocessingerror` with FK to DownloadAttempt

**Data Impact:**
- All historical checkpoint data will be lost
- All historical error logs will be lost
- Existing in-progress downloads will need to be restarted
- All existing ProjectFiles will have zero download_attempts

**Post-Migration State:**
- Clean data model with proper separation
- First download task execution creates attempt #1
- System works normally going forward

## Implementation Changes

### Task Changes (tasks.py)

**1. Attempt Creation at Task Start:**

```python
def download_file(project_file_id):
    project_file = ProjectFile.objects.get(id=project_file_id)

    # Create new download attempt
    attempt = DownloadAttempt.objects.create(
        project_file=project_file,
        attempt_number=project_file.download_attempts.count() + 1,
        status=DownloadAttempt.Status.DOWNLOADING
    )

    # Rest of download logic uses `attempt` instead of `project_file`
```

**2. Progress Updates:**

```python
# OLD:
project_file.last_activity = timezone.now()
project_file.save(update_fields=["last_activity"])

# NEW:
attempt.last_activity = timezone.now()
attempt.save(update_fields=["last_activity"])
```

**3. Checkpoint Creation:**

```python
# OLD:
ProjectFileChunk.objects.create(
    project_file=project_file,
    bytes_downloaded=downloaded,
    chunk_number=chunk_count
)

# NEW:
ProjectFileChunk.objects.create(
    download_attempt=attempt,
    bytes_downloaded=downloaded,
    chunk_number=chunk_count
)
```

**4. Error Logging:**

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

**5. Completion:**

```python
# At end of task (success or failure)
attempt.completed_at = timezone.now()
attempt.status = DownloadAttempt.Status.COMPLETED  # or FAILED
attempt.download_duration_seconds = (
    attempt.completed_at - attempt.started_at
).total_seconds()
attempt.save()
```

### View Changes (views.py)

**ProjectDetailView:**

```python
# OLD:
context['show_progress'] = project_file.download_status == 'downloading'
context['progress'] = {
    'progress': project_file.download_progress,
    'message': '...'
}

# NEW:
latest_attempt = project_file.latest_attempt
context['latest_attempt'] = latest_attempt
context['show_progress'] = (
    latest_attempt and
    latest_attempt.status == DownloadAttempt.Status.DOWNLOADING
)
if latest_attempt:
    context['progress'] = {
        'progress': latest_attempt.download_progress,
        'message': '...'
    }
```

**ProgressView:**

```python
# OLD:
return JsonResponse({
    'progress': project_file.download_progress,
    'status': project_file.download_status,
    'message': '...'
})

# NEW:
latest_attempt = project_file.latest_attempt
if not latest_attempt:
    return JsonResponse({'error': 'No active download'}, status=404)

return JsonResponse({
    'progress': latest_attempt.download_progress,
    'status': latest_attempt.status,
    'message': '...'
})
```

### Template Changes

**Template Access Pattern:**

```django
{# OLD #}
{{ file.download_status }}
{{ file.chunks.all }}
{{ file.errors.all }}

{# NEW #}
{{ latest_attempt.status }}
{{ latest_attempt.chunks.all }}
{{ latest_attempt.errors.all }}
```

**Updated _file_display.html:**
- Accept `latest_attempt` parameter instead of deriving from file
- Access status, checkpoints, errors via latest_attempt

**Updated project_detail.html:**
- Pass `latest_attempt` to file_display partial
- Use `latest_attempt.status` for progress polling

## Testing Strategy

### Model Tests

```python
def test_download_attempt_creation():
    """Test DownloadAttempt creation and uniqueness."""
    attempt1 = DownloadAttempt.objects.create(
        project_file=file,
        attempt_number=1
    )
    # Cannot create duplicate attempt number
    with pytest.raises(IntegrityError):
        DownloadAttempt.objects.create(
            project_file=file,
            attempt_number=1
        )

def test_latest_attempt_property():
    """Test ProjectFile.latest_attempt returns most recent."""
    attempt1 = create_attempt(file, number=1)
    attempt2 = create_attempt(file, number=2)
    assert file.latest_attempt == attempt2

def test_current_status_property():
    """Test ProjectFile.current_status reflects latest attempt."""
    assert file.current_status == DownloadAttempt.Status.PENDING
    attempt = create_attempt(file, status=DownloadAttempt.Status.DOWNLOADING)
    assert file.current_status == DownloadAttempt.Status.DOWNLOADING
```

### Task Tests

```python
def test_download_creates_attempt():
    """Test download task creates DownloadAttempt."""
    download_file(project_file.id)
    assert project_file.download_attempts.count() == 1
    attempt = project_file.latest_attempt
    assert attempt.attempt_number == 1

def test_retry_creates_new_attempt():
    """Test retry creates separate attempt."""
    download_file(project_file.id)  # Attempt 1
    download_file(project_file.id)  # Attempt 2 (retry)
    assert project_file.download_attempts.count() == 2
    assert project_file.latest_attempt.attempt_number == 2

def test_checkpoints_linked_to_attempt():
    """Test checkpoints belong to specific attempt."""
    download_file(project_file.id)
    attempt1 = project_file.latest_attempt
    assert attempt1.chunks.count() > 0

    download_file(project_file.id)  # Retry
    attempt2 = project_file.latest_attempt

    # Separate checkpoint sets
    assert attempt1.chunks.count() != attempt2.chunks.count()
    assert attempt1.chunks.first() != attempt2.chunks.first()
```

### View Tests

```python
def test_project_detail_includes_latest_attempt():
    """Test view passes latest_attempt to template."""
    response = client.get(f'/projects/{project.id}/')
    assert 'latest_attempt' in response.context
    assert response.context['latest_attempt'] == project_file.latest_attempt
```

## Benefits

1. **No Duplicate Checkpoints:** Each attempt has its own checkpoint set
2. **Clear History:** Can see all download attempts and their outcomes
3. **Better Debugging:** Errors clearly associated with specific attempt
4. **Proper Modeling:** Download execution separate from file metadata
5. **Scalability:** Can query/analyze attempts independently
6. **Clean UI:** Show only latest attempt by default, history available

## Migration Risks

**Risk:** Data loss of existing checkpoints/errors
**Mitigation:** Acceptable - active development, data not critical

**Risk:** Breaking existing code that accesses `file.download_status`
**Mitigation:** Comprehensive test coverage, systematic replacement

**Risk:** Performance impact of extra join for latest_attempt
**Mitigation:** Indexed properly, can add select_related in queries

## Future Enhancements

- Retry strategy based on attempt history
- Download speed trends across attempts
- Automatic attempt cleanup (keep last N attempts)
- Attempt comparison UI showing what changed between retries
