# Implementation Plan: Filename and Error Logging Fix

**Date:** 2025-11-20
**Branch:** `content-extraction`
**Related PR:** https://github.com/wafer-space/platform.wafer.space/pull/45

## Problem Statement

Two critical bugs identified in the file download/processing system:

### Bug 1: Filename Expansion
- **Symptom**: Filenames like `file.gds.gds.gds.gds.zip` appearing after processing
- **Root Cause**: `ProjectFile.original_filename` field modified multiple times during pipeline
  - Line 1387 in tasks.py: First modification when detecting file type
  - Line 1073 in tasks.py: Second modification after pipeline processing
- **Impact**: Users see confusing filenames, original download name is lost

### Bug 2: Pipeline Errors Not Displayed
- **Symptom**: Pipeline errors (e.g., "Archive contains multiple GDS/OASIS files") not visible in UI
- **Root Cause**: No error capture around `_apply_content_pipeline()` call (line 1145 in tasks.py)
- **Example Error**:
  ```
  ValueError: Archive contains multiple GDS/OASIS files:
  - RUN_2025-11-17_20-22-46/16-magic-streamout/tt_gf_wrapper.gds
  - RUN_2025-11-17_20-22-46/16-magic-streamout/tt_gf_wrapper.magic.gds
  - RUN_2025-11-17_20-22-46/final/gds/tt_gf_wrapper.gds
  - RUN_2025-11-17_20-22-46/final/mag_gds/tt_gf_wrapper.magic.gds
  ```
  (From extractors.py:85-91)
- **Impact**: Users don't see why their uploads failed, no way to diagnose issues

## Requirements

1. **Display both filenames** - Original downloaded name AND final extracted filename
2. **Show errors everywhere** - Notifications, project overview, and detail pages
3. **Structured error logging** - Queryable error log for all processing stages
4. **Handle complex pipelines** - ZIP→.gds.gz→.gds transformations, multiple file scenarios
5. **Security-first** - Technical details only for superusers
6. **No backward compatibility** - Clean break, fix all references

## Solution Design

### 1. Model Changes

#### ProjectFile Model (wafer_space/projects/models.py)

**Add new field:**
```python
class ProjectFile(models.Model):
    # ... existing fields ...

    # IMMUTABLE - what was originally downloaded
    original_filename = models.CharField(max_length=255)  # Keep existing

    # NEW - what we extracted/processed (final result)
    processed_filename = models.CharField(
        max_length=255,
        blank=True,
        help_text="Final filename after extraction/decompression pipeline"
    )
```

**Field semantics:**
- `original_filename`: What the user submitted or what we downloaded (NEVER modified after initial save)
- `processed_filename`: Final filename after all pipeline processing (set after `_apply_content_pipeline()`)
- If `processed_filename` is blank → processing not complete yet
- If `processed_filename == original_filename` → no transformation needed (direct .gds upload)

#### New FileProcessingError Model

```python
class FileProcessingError(models.Model):
    """Log of errors that occurred during file processing.

    Stores structured error information for all processing stages:
    download, extraction, validation, and pipeline processing.
    """

    class ErrorType(models.TextChoices):
        DOWNLOAD = "download", "Download Error"
        EXTRACTION = "extraction", "Extraction Error"
        VALIDATION = "validation", "Validation Error"
        PIPELINE = "pipeline", "Pipeline Error"

    project_file = models.ForeignKey(
        ProjectFile,
        on_delete=models.CASCADE,
        related_name="errors"
    )
    error_type = models.CharField(max_length=20, choices=ErrorType.choices)
    error_message = models.TextField(
        help_text="User-friendly error message"
    )
    error_detail = models.JSONField(
        default=dict,
        blank=True,
        help_text="Technical details: stack trace, context, etc. (superuser only)"
    )
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["project_file", "-occurred_at"]),
            models.Index(fields=["error_type", "-occurred_at"]),
        ]

    def __str__(self):
        return f"{self.get_error_type_display()}: {self.error_message[:50]}"
```

### 2. Code Changes in tasks.py

#### Fix 1: Remove first filename modification (Line 1380-1388)

**Current buggy code:**
```python
# Line 1380-1388
base_name = project_file.original_filename.rsplit(".", 1)[0]
if base_name == "download" or not base_name:
    base_name = "file"
new_filename = f"{base_name}{detected_extension}"
old_name = project_file.original_filename
logger.info("  ✓ Updated filename: %s → %s", old_name, new_filename)
project_file.original_filename = new_filename  # BUG: Don't modify original_filename!
project_file.save(update_fields=["original_filename"])
```

**Fixed code:**
```python
# Line 1380-1388 (approximately)
# Don't modify original_filename - just log what we detected
base_name = project_file.original_filename.rsplit(".", 1)[0]
if base_name == "download" or not base_name:
    base_name = "file"
detected_filename = f"{base_name}{detected_extension}"
logger.info(
    "  ✓ Detected file type: %s (extension: %s)",
    project_file.original_filename,
    detected_extension,
)
# Note: original_filename stays unchanged - it's what was downloaded
```

#### Fix 2: Set processed_filename instead (Line 1068-1073)

**Current buggy code:**
```python
# Line 1068-1073 in _apply_content_pipeline
if result.filename != project_file.original_filename:
    logger.info(
        "  ✓ Filename updated: %s → %s",
        project_file.original_filename,
        result.filename,
    )
    project_file.original_filename = result.filename  # BUG: Second modification!
```

**Fixed code:**
```python
# Always set processed_filename (even if unchanged from original)
# This indicates processing completed successfully
project_file.processed_filename = result.filename

if result.filename != project_file.original_filename:
    logger.info(
        "  ✓ Pipeline transformed: %s → %s",
        project_file.original_filename,
        result.filename,
    )
else:
    logger.info(
        "  ✓ No transformation needed: %s",
        result.filename,
    )
```

#### Fix 3: Add error capture around pipeline (Line 1145-1155)

**Current code (missing error capture):**
```python
try:
    processed_content, final_md5, final_sha1 = _apply_content_pipeline(
        project_file,
        processed_content,
        temp_path,
    )
except ValueError as e:
    logger.exception("Pipeline processing failed")
    project_file.download_status = ProjectFile.DownloadStatus.FAILED
    project_file.download_error = str(e)
    project_file.save()
    raise
```

**Fixed code:**
```python
import traceback
from wafer_space.projects.models import FileProcessingError

try:
    processed_content, final_md5, final_sha1 = _apply_content_pipeline(
        project_file,
        processed_content,
        temp_path,
    )
except ValueError as e:
    logger.exception("Pipeline processing failed")

    # Create structured error log
    FileProcessingError.objects.create(
        project_file=project_file,
        error_type=FileProcessingError.ErrorType.PIPELINE,
        error_message=str(e),
        error_detail={
            "stage": "content_extraction",
            "traceback": traceback.format_exc(),
            "original_filename": project_file.original_filename,
            "file_size": processed_content.stat().st_size if processed_content else None,
        },
    )

    project_file.download_status = ProjectFile.DownloadStatus.FAILED
    project_file.download_error = f"Pipeline error: {e}"
    project_file.save()
    raise
```

#### Fix 4: Add error capture for download failures (existing try/except blocks)

Add `FileProcessingError` logging to existing error handlers:

**Download errors** (around line 1125):
```python
except (HTTPError, ConnectionError, Timeout, RequestException) as e:
    logger.exception("Download failed")

    # Create structured error log
    FileProcessingError.objects.create(
        project_file=project_file,
        error_type=FileProcessingError.ErrorType.DOWNLOAD,
        error_message=f"Download failed: {e}",
        error_detail={
            "url": project_file.original_url,
            "error_type": e.__class__.__name__,
            "traceback": traceback.format_exc(),
        },
    )

    project_file.download_status = ProjectFile.DownloadStatus.FAILED
    project_file.download_error = str(e)
    project_file.save()
    raise
```

**Validation errors** (around line 1390):
```python
except ValueError as e:
    logger.exception("File validation failed")

    # Create structured error log
    FileProcessingError.objects.create(
        project_file=project_file,
        error_type=FileProcessingError.ErrorType.VALIDATION,
        error_message=str(e),
        error_detail={
            "original_filename": project_file.original_filename,
            "traceback": traceback.format_exc(),
        },
    )

    # ... existing error handling ...
```

### 3. Template Changes

#### _file_display.html - Show Both Filenames

**Location:** `wafer_space/templates/projects/_file_display.html`

**Replace line 5** (currently `<h6>{{ file.original_filename }}</h6>`):

```html
{# Show filename with transformation if applicable #}
{% if file.processed_filename and file.processed_filename != file.original_filename %}
  <h6>
    {{ file.original_filename }}
    <i class="bi bi-arrow-right text-muted mx-2"></i>
    <span class="text-primary">{{ file.processed_filename }}</span>
  </h6>
  <p class="text-muted small mb-2">
    <i class="bi bi-info-circle"></i>
    Downloaded as <code>{{ file.original_filename }}</code>,
    extracted to <code>{{ file.processed_filename }}</code>
  </p>
{% elif file.processed_filename %}
  <h6>{{ file.processed_filename }}</h6>
  <p class="text-muted small mb-2">
    <i class="bi bi-file-earmark"></i>
    Filename: <code>{{ file.processed_filename }}</code>
  </p>
{% else %}
  <h6>{{ file.original_filename }}</h6>
  <p class="text-muted small mb-2">
    <i class="bi bi-hourglass"></i>
    Processing: <code>{{ file.original_filename }}</code>
  </p>
{% endif %}
```

#### _file_display.html - Add Error Display Section

**Add after hash verification section** (around line 171):

```html
{# Error Log Display #}
{% if file.errors.exists %}
  <hr class="my-3" />
  <div class="alert alert-danger" role="alert">
    <h6 class="alert-heading">
      <i class="bi bi-exclamation-triangle-fill"></i>
      Processing Errors ({{ file.errors.count }})
    </h6>

    {% for error in file.errors.all %}
      <div class="mb-3">
        <strong>{{ error.get_error_type_display }}:</strong>
        <p class="mb-1">{{ error.error_message }}</p>
        <small class="text-muted">
          <i class="bi bi-clock"></i>
          {{ error.occurred_at|date:"F d, Y g:i a" }}
        </small>
      </div>
      {% if not forloop.last %}<hr class="my-2" />{% endif %}
    {% endfor %}

    {# Technical details only for superusers #}
    {% if user.is_superuser and file.errors.exists %}
      <hr class="my-3" />
      <details class="mt-2">
        <summary class="text-muted" style="cursor: pointer;">
          <i class="bi bi-shield-lock"></i>
          <strong>Technical Details (Superuser Only)</strong>
        </summary>
        <div class="mt-3">
          {% for error in file.errors.all %}
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
```

#### project_detail.html - Update File History Table

**Update line 258** (filename display in history table):

```html
<td>
  <i class="bi bi-file-earmark"></i>
  {% if file.processed_filename and file.processed_filename != file.original_filename %}
    {{ file.original_filename }}
    <i class="bi bi-arrow-right text-muted small"></i>
    <span class="text-primary">{{ file.processed_filename }}</span>
  {% elif file.processed_filename %}
    {{ file.processed_filename }}
  {% else %}
    {{ file.original_filename }}
  {% endif %}
</td>
```

### 4. View Changes

#### ProjectDetailView - Add Error Context

**Location:** `wafer_space/projects/views.py`

**Update context to include errors:**

```python
def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)

    # ... existing context setup ...

    # Add error information for active file
    if active_file:
        context["active_file_errors"] = active_file.errors.all()[:5]  # Latest 5 errors

    return context
```

### 5. Migration

**Create migration:**
```bash
make makemigrations
```

**Expected migration operations:**
1. Add `processed_filename` field to `ProjectFile` model (blank=True)
2. Create `FileProcessingError` model
3. Create indexes on `FileProcessingError`

**Migration file should include:**
- `AddField` operation for `processed_filename`
- `CreateModel` operation for `FileProcessingError`
- `AddIndex` operations for the two indexes

### 6. Testing Strategy

#### Test Complex Pipeline Scenarios

**Test 1: ZIP containing .gds.gz**
```python
def test_zip_containing_compressed_gds(self):
    """Test ZIP → .gds.gz → .gds pipeline."""
    # Create test.gds.gz
    # Create ZIP containing test.gds.gz
    # Upload ZIP
    # Assert: original_filename = "test.zip"
    # Assert: processed_filename = "test.gds"
```

**Test 2: ZIP with multiple GDS files**
```python
def test_zip_with_multiple_gds_files_creates_error(self):
    """Test that multiple GDS files in ZIP creates proper error log."""
    # Create ZIP with 2+ .gds files
    # Upload ZIP
    # Assert: download_status = FAILED
    # Assert: FileProcessingError exists with PIPELINE type
    # Assert: error_message contains "multiple GDS/OASIS files"
```

**Test 3: Direct .gds upload (no transformation)**
```python
def test_direct_gds_upload_sets_both_filenames(self):
    """Test that direct .gds upload sets both filenames identically."""
    # Upload test.gds directly
    # Assert: original_filename = "test.gds"
    # Assert: processed_filename = "test.gds"
```

**Test 4: Nested compression (.tar.gz containing .gds.gz)**
```python
def test_nested_compression_pipeline(self):
    """Test tar.gz → .gds.gz → .gds pipeline."""
    # Create test.gds.gz
    # Create test.tar.gz containing test.gds.gz
    # Upload tar.gz
    # Assert: original_filename = "test.tar.gz"
    # Assert: processed_filename = "test.gds"
```

#### Test Error Logging and Display

**Test 5: Error appears in UI**
```python
def test_pipeline_error_appears_in_detail_view(self):
    """Test that pipeline errors display on project detail page."""
    # Create ZIP with multiple GDS files
    # Load project detail page
    # Assert: Error message visible in response
    # Assert: "Archive contains multiple GDS/OASIS files" in response
```

**Test 6: Technical details only for superusers**
```python
def test_error_technical_details_superuser_only(self):
    """Test that error technical details only show for superusers."""
    # Create error with technical details
    # Login as regular user
    # Assert: error_message visible
    # Assert: "Technical Details" NOT in response
    # Login as superuser
    # Assert: "Technical Details" in response
    # Assert: traceback visible
```

#### Test Filename Display

**Test 7: Both filenames displayed when different**
```python
def test_both_filenames_displayed_when_transformed(self):
    """Test that both filenames show when processing changed the name."""
    # Upload file.zip → file.gds
    # Load project detail page
    # Assert: "file.zip" in response
    # Assert: "file.gds" in response
    # Assert: Arrow icon between them
```

**Test 8: Single filename when identical**
```python
def test_single_filename_displayed_when_identical(self):
    """Test that only one filename shows when no transformation."""
    # Upload file.gds directly
    # Load project detail page
    # Assert: "file.gds" appears once (not duplicated)
```

### 7. Implementation Order

**Phase 1: Models and Migration**
1. Add `processed_filename` field to `ProjectFile`
2. Create `FileProcessingError` model
3. Create and run migration
4. Verify migration with `make migrate`

**Phase 2: Core Logic in tasks.py**
1. Remove first filename modification (line 1387)
2. Add `processed_filename` assignment (line 1073)
3. Add `FileProcessingError` import
4. Add error capture for pipeline failures
5. Add error capture for download failures
6. Add error capture for validation failures
7. Run tests: `make test-app APP=projects`

**Phase 3: Template Updates**
1. Update `_file_display.html` for dual filename display
2. Add error display section to `_file_display.html`
3. Update `project_detail.html` file history table
4. Test templates with `make test-browser-headless`

**Phase 4: View Updates**
1. Update `ProjectDetailView` to include error context
2. Verify context data in tests

**Phase 5: Comprehensive Testing**
1. Write tests for complex pipeline scenarios
2. Write tests for error logging and display
3. Write tests for security (superuser-only details)
4. Write tests for filename display
5. Run full test suite: `make test`
6. Run browser tests: `make test-browser-headless`

**Phase 6: Verification**
1. Manual testing with real files
2. Test with ZIP containing .gds.gz
3. Test with ZIP containing multiple GDS files
4. Verify error messages appear correctly
5. Verify superuser vs. regular user visibility
6. Run linting: `make lint-fix && make lint`
7. Run type checking: `make type-check`

## Pipeline Processing Details

### Three-Stage Pipeline (content_pipeline.py)

The pipeline runs up to 3 stages:
1. **Stage 1**: Usually decompression (gzip/bzip2/xz) - priority 100
2. **Stage 2**: Usually extraction (zip/tar) - priority 50
3. **Stage 3**: Decompression again (for nested compression)

**Key behavior:**
- Each stage updates `current_filename` based on processor output
- Processors derive new filename from `input_path.name`
- Pipeline renames intermediate files to match `result.filename`
- Final `result.filename` goes into `processed_filename`

### Example: test.zip containing test.gds.gz

```
Downloaded:     test.zip          → original_filename = "test.zip"
Stage 1 (Zip):  test.gds.gz       → current_filename = "test.gds.gz"
Stage 2 (Gzip): test.gds          → current_filename = "test.gds"
Stage 3:        (no processor)
Final:          test.gds          → processed_filename = "test.gds"
```

### Valid File Extensions (extractors.py:19-32)

Archives can contain these compressed formats:
- `.gds`, `.gdsii`, `.gds2`
- `.oas`, `.oasis`
- `.gds.gz`, `.gds.bz2`, `.gds.xz`
- `.oas.gz`, `.oas.bz2`, `.oas.xz`

## Security Considerations

1. **Information Disclosure Prevention**
   - User-facing error messages: Simple, actionable
   - Technical details (stack traces): Superuser only
   - No file paths or internal details exposed to regular users

2. **Error Detail JSONField Structure**
   ```python
   error_detail = {
       "traceback": "...",           # Full stack trace
       "original_filename": "...",   # Context
       "file_size": 12345,          # Context
       "url": "...",                # For download errors
       "stage": "...",              # For pipeline errors
   }
   ```

3. **Template Security**
   - `{% if user.is_superuser %}` wraps all technical details
   - No accidental leakage through template variables
   - Error messages sanitized (Django auto-escaping)

## Success Criteria

1. ✅ `original_filename` never modified after initial download
2. ✅ `processed_filename` set after successful pipeline processing
3. ✅ Both filenames displayed in UI when different
4. ✅ Pipeline errors captured in `FileProcessingError` model
5. ✅ Errors visible on project detail page
6. ✅ Technical details only visible to superusers
7. ✅ All tests pass (unit + browser)
8. ✅ Complex pipeline scenarios work (ZIP→.gds.gz→.gds)
9. ✅ Multiple GDS file error properly logged and displayed
10. ✅ No linting errors, all type checks pass

## Risks and Mitigations

**Risk 1: Migration on production data**
- Mitigation: `processed_filename` is `blank=True`, safe to add
- Existing files will have `processed_filename=""` until next processing

**Risk 2: Missing error capture locations**
- Mitigation: Comprehensive test coverage for all error paths
- Manual testing with various failure scenarios

**Risk 3: Template rendering errors**
- Mitigation: Test with files that have errors
- Test with both superuser and regular user accounts

**Risk 4: Performance impact of error queries**
- Mitigation: Indexed `project_file` foreign key
- Limit error display to latest 5 per file
- Queries are simple select with FK lookup

## Related Files

- `wafer_space/projects/models.py` - Model definitions
- `wafer_space/projects/tasks.py` - Download and pipeline logic
- `wafer_space/projects/content_pipeline.py` - Pipeline orchestration
- `wafer_space/projects/processors/extractors.py` - ZIP/tar extraction
- `wafer_space/projects/processors/decompressors.py` - Gzip/bzip2/xz decompression
- `wafer_space/templates/projects/project_detail.html` - Main project page
- `wafer_space/templates/projects/_file_display.html` - File display partial
- `wafer_space/projects/views.py` - View logic

## References

- Original error: extractors.py:85-91 (multiple GDS files validation)
- Bug location 1: tasks.py:1387 (first filename modification)
- Bug location 2: tasks.py:1073 (second filename modification)
- Missing error capture: tasks.py:1145-1155 (pipeline processing)
