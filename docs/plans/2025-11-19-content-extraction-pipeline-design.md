# Content Extraction Pipeline Design

**Date:** 2025-11-19
**Status:** Approved
**Author:** Claude Code

## Overview

This design adds support for:
- Extracting GDS/OASIS files from ZIP and tar archives
- Decompressing gzip, bzip2, and xz compressed files
- Downloading GitHub Actions artifacts with authentication
- Validating final content is valid GDS or OASIS format

**Key principle:** Generic content extraction pipeline that works for any source, with GitHub-specific URL handler for authentication.

## Motivation

Current limitations:
- System accepts `.zip`, `.gz`, `.bz2`, `.xz` files but doesn't extract/decompress them
- GitHub Actions artifacts require authentication and return ZIP files
- No validation that compressed/archived files contain valid GDS/OASIS

User need: Submit GitHub artifact URLs and automatically get the GDS/OASIS file inside.

## Architecture

### Two Independent Systems

1. **URLHandler System** (existing, enhanced):
   - Platform-specific URL transformations
   - GitHub handler: converts UI URL → API URL, adds auth headers
   - Handles pre-download URL processing

2. **ContentProcessor System** (new):
   - Format-specific content transformations
   - Processors: ZipExtractor, TarExtractor, GzipDecompressor, Bzip2Decompressor, XzDecompressor
   - Handles post-download content processing
   - Fixed three-stage pipeline architecture

### Download Flow

```
URL → URLHandler (transform URL + auth)
    → Download
    → ContentProcessor Pipeline (extract/decompress)
    → Validate
    → Store
```

**Separation of concerns:** URLHandler transforms HOW we download, ContentProcessor transforms WHAT we downloaded.

## ContentProcessor Framework

### Base Class

```python
class ContentProcessor(ABC):
    @abstractmethod
    def can_process(self, filename: str, file_path: Path) -> bool:
        """Check if processor can handle file (peek at header/magic bytes)."""

    @abstractmethod
    def process(self, input_path: Path, output_path: Path, *, max_size: int) -> ProcessorResult:
        """Stream process: input_path → output_path, abort if exceeds max_size."""

    @abstractmethod
    def get_priority(self) -> int:
        """Return priority (higher = runs first)."""

@dataclass
class ProcessorResult:
    output_path: Path        # Path to processed file on disk
    filename: str            # Updated filename (e.g., "design.gds" from "design.gds.gz")
    size_bytes: int          # Final file size
    metadata: dict[str, Any] # Processing metadata for debugging
```

### Fixed Three-Stage Pipeline

```
Stage 1: Decompression → Stage 2: Archive Extraction → Stage 3: Decompression → Result
```

**Stage 1 - Outer Decompression** (handles .tar.gz, .zip.gz):
- Try decompressors in order: Gzip → Bzip2 → Xz
- First match processes and passes to Stage 2
- If no match, pass content unchanged to Stage 2

**Stage 2 - Archive Extraction** (handles .tar, .zip):
- Try extractors: Tar → Zip
- **Recursively** scans archive for files (including subdirectories like `designs/chip.gds`)
- Ignores non-GDS/OASIS files (README.txt, etc.)
- Validates exactly ONE `.gds`/`.oas`/`.gds.gz`/`.gds.bz2`/`.gds.xz` file found
- Error if 0 or 2+ valid files
- Extracts that file and passes to Stage 3

**Stage 3 - Inner Decompression** (handles extracted .gds.gz):
- Same as Stage 1: try all decompressors
- Returns final raw GDS/OASIS content

**Example Chains:**
- `.tar.gz`: Stage 1 (Gzip) → Stage 2 (Tar extracts .gds.bz2) → Stage 3 (Bzip2) → `.gds` ✓
- `.zip` with `.gds.xz`: Stage 1 (no-op) → Stage 2 (Zip extracts .gds.xz) → Stage 3 (Xz) → `.gds` ✓
- `.gds.gz`: Stage 1 (Gzip) → Stage 2 (no-op) → Stage 3 (no-op) → `.gds` ✓

### Specific Processors

**Decompressors** (priority 100):
- `GzipDecompressor`: .gz → raw content
- `Bzip2Decompressor`: .bz2 → raw content
- `XzDecompressor`: .xz → raw content
- Updates filename (strips compression extension)

**Archive Extractors** (priority 50):
- `ZipExtractor`: .zip → single file
- `TarExtractor`: .tar → single file
- Validates exactly ONE valid file in archive
- Ignores non-GDS/OASIS files (text files, etc.)

### Security - Zipbomb & Size Protection

**Pre-Extraction Size Check:**
- Archives: read central directory, sum uncompressed sizes BEFORE extracting
- Compressed: check header metadata if available
- Fail fast if total exceeds limit

**During Extraction Size Monitoring:**
- Process in chunks (64KB recommended)
- Track cumulative `bytes_written`
- Abort immediately if `bytes_written > max_size`
- Delete partial output file on abort

**Size Limits:**
- Default max: 500MB per file (from existing settings)
- Enforced at EVERY stage of pipeline
- Cumulative check: final file must be ≤ max_size

**Compression Ratio Limits:**
- Track: `compressed_size` vs `decompressed_size`
- Fail if ratio > 100:1 (configurable, default conservative)
- Example: 1MB compressed → max 100MB decompressed

### Streaming Architecture

**Disk-Based Pipeline:**
```
downloaded_file.tmp
→ stage1_decompressed.tmp
→ stage2_extracted.tmp
→ stage3_decompressed.tmp
→ final_validated.gds
```

- Each stage reads from disk, writes to disk
- Cleanup intermediate files after each stage
- Never load entire file into memory
- Prevents memory exhaustion on large files

### Temporary File Management

**Task-Isolated Directories:**
```python
# Unique temp directory per task+file combination
task_temp_dir = settings.MEDIA_ROOT / "temp" / f"task_{task_id}" / f"file_{file_id}"
```

**Cleanup Guarantees:**

```python
def process_pipeline(input_path: Path, max_size: int, *, task_id: str, file_id: int) -> Path:
    """Run pipeline with automatic cleanup."""
    task_temp_dir = create_task_temp_dir(task_id, file_id)
    temp_files: list[Path] = []

    try:
        # Stage 1: Outer decompression
        stage1_output = task_temp_dir / "stage1_output.tmp"
        temp_files.append(stage1_output)
        result1 = run_decompressors(input_path, stage1_output, max_size)

        # Stage 2: Archive extraction
        stage2_output = task_temp_dir / "stage2_output.tmp"
        temp_files.append(stage2_output)
        result2 = run_extractors(result1.output_path, stage2_output, max_size)

        # Stage 3: Inner decompression
        stage3_output = task_temp_dir / "stage3_output.tmp"
        temp_files.append(stage3_output)
        result3 = run_decompressors(result2.output_path, stage3_output, max_size)

        # Move final result to permanent location
        final_path = move_to_permanent_storage(result3.output_path)
        temp_files.remove(result3.output_path)  # Don't delete moved file

        return final_path
    finally:
        # Guaranteed cleanup: delete ALL temp files even on error/abort
        for temp_file in temp_files:
            if temp_file.exists():
                temp_file.unlink()

        # Remove task-specific directory if empty
        if task_temp_dir.exists() and not any(task_temp_dir.iterdir()):
            task_temp_dir.rmdir()
```

**Isolation Strategy:**

1. **Unique Directory per Task:**
   - Path: `media/temp/task_{celery_task_id}/file_{project_file_id}/`
   - Celery task ID is globally unique
   - ProjectFile ID is unique within the system
   - No collisions possible between concurrent Celery workers

2. **Cleanup Hierarchy:**
   - Try/finally pattern ensures cleanup even on exceptions
   - Delete temp files first
   - Delete task directory if empty
   - Parent `media/temp/` persists (may contain other active tasks)

## GitHub Actions Artifact Handler

### GitHubArtifactHandler (URLHandler)

```python
class GitHubArtifactHandler(URLHandler):
    """Handler for GitHub Actions artifact downloads."""

    def can_handle(self, url: str) -> bool:
        """Match artifact URLs from GitHub UI."""
        # https://github.com/{owner}/{repo}/suites/{suite_id}/artifacts/{artifact_id}
        pattern = r'github\.com/.+/suites/\d+/artifacts/\d+'
        return bool(re.search(pattern, url))

    def process_url(self, url: str) -> dict[str, Any]:
        """Transform UI URL to API URL and add auth metadata."""
        # Extract: owner, repo, artifact_id from URL
        # Parse: https://github.com/{owner}/{repo}/suites/{suite_id}/artifacts/{artifact_id}
        # Build: https://api.github.com/repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip

        return {
            "url": api_url,
            "metadata": {
                "handler": "GitHubArtifactHandler",
                "requires_auth": True,
                "auth_type": "bearer",
                "env_var": "GITHUB_TOKEN",
            },
        }

    def post_download(self, content: bytes, metadata: dict[str, Any]) -> bytes:
        """No post-processing needed (auth happens during download)."""
        return content
```

### Authentication Integration

**Download task checks handler metadata:**

```python
def _prepare_download_request(url: str, handler_metadata: dict) -> dict[str, str]:
    """Prepare headers including auth if needed."""
    headers = {"User-Agent": "wafer.space/1.0"}

    if handler_metadata.get("requires_auth"):
        auth_type = handler_metadata.get("auth_type")
        env_var = handler_metadata.get("env_var")

        if auth_type == "bearer":
            token = os.environ.get(env_var)
            if token:
                headers["Authorization"] = f"Bearer {token}"
            else:
                logger.warning("Auth required but %s not found in environment", env_var)

    return headers
```

**Key Points:**
- Handler converts UI URL → API URL
- Metadata signals: "this download needs auth"
- Download task reads `GITHUB_TOKEN` from env, adds to headers
- GitHub API returns 302 redirect (60s expiry) which requests library follows automatically
- No need to store redirect URL (ephemeral)

## Integration with Download Flow

### Complete Download Flow

```python
# In download_project_file task:
def download_project_file(project_file_id: int):
    project_file = ProjectFile.objects.get(id=project_file_id)

    # Step 1: URLHandler processes URL (if applicable)
    handler = get_url_handler(project_file.url)
    if handler:
        result = handler.process_url(project_file.url)
        download_url = result["url"]
        handler_metadata = result["metadata"]
    else:
        download_url = project_file.url
        handler_metadata = {}

    # Step 2: Download with auth headers
    headers = _prepare_download_request(download_url, handler_metadata)
    temp_file = _download_to_temp(download_url, headers)

    # Step 3: ContentProcessor pipeline
    final_file = process_content_pipeline(
        input_path=temp_file,
        original_filename=project_file.filename,
        max_size=settings.MAX_FILE_SIZE,
        task_id=self.request.id,
        file_id=project_file.id,
    )

    # Step 4: Validate final content is valid GDS/OASIS
    format_type = validate_gds_oasis_format(final_file)

    # Step 5: Move to permanent storage
    move_to_storage(final_file, project_file)

    # Step 6: Update ProjectFile record
    project_file.file_format = format_type
    project_file.save()
```

### File Format Validation

```python
def validate_gds_oasis_format(file_path: Path) -> str:
    """Validate file is GDS or OASIS, return format type.

    Raises:
        ValidationError: If file is not valid GDS or OASIS format.
    """
    # Check magic bytes (first few bytes of file)
    with open(file_path, 'rb') as f:
        header = f.read(16)

    # GDS: starts with 0x0006 or 0x0600 (big-endian record header)
    # OASIS: starts with "%SEMI-OASIS" or specific byte sequence

    if is_gds_format(header):
        return "GDS"
    elif is_oasis_format(header):
        return "OASIS"
    else:
        msg = f"File is not valid GDS or OASIS format (magic bytes: {header.hex()})"
        raise ValidationError(msg)
```

### Error Handling

**Clear, actionable error messages:**

1. **Size limit exceeded:**
   ```
   File exceeds size limit: 750MB > 500MB maximum
   Compression ratio: 1500:1 (limit: 100:1)
   This may be a zip bomb.
   ```

2. **No valid files in archive:**
   ```
   Archive contains no GDS or OASIS files.
   Found: README.txt, LICENSE, screenshot.png
   Expected: exactly one .gds, .oas, .gds.gz, .gds.bz2, or .gds.xz file
   ```

3. **Multiple valid files:**
   ```
   Archive contains multiple GDS/OASIS files:
   - design_v1.gds
   - design_v2.gds
   - backup.oas
   Expected: exactly one file
   ```

4. **Nested compression detected:**
   ```
   Invalid nested compression: .gds.gz inside .zip
   Pipeline stages completed: Stage 1 (no-op) → Stage 2 (extracted .gds.gz) → Stage 3 (failed)
   ZIP archives must contain raw .gds or .oas files only, not compressed versions.
   ```

5. **Invalid format:**
   ```
   File is not valid GDS or OASIS format
   Magic bytes found: 504b0304 (ZIP header)
   Expected: GDS (0006) or OASIS (%SEMI-OASIS)
   ```

6. **Authentication failure:**
   ```
   GitHub authentication failed: GITHUB_TOKEN not found
   Set GITHUB_TOKEN environment variable to download artifacts
   ```

## Testing Strategy

### Unit Tests

**ContentProcessor Tests** (per processor):
- Valid inputs: .gz → .gds, .zip with single .gds, .tar.gz → .gds
- Invalid inputs: corrupt archives, wrong formats, empty archives
- Edge cases: exactly one file vs zero/multiple files
- Size limit enforcement: create files that exceed limits
- Cleanup verification: check no temp files remain after processing
- Magic bytes detection: verify can_process() correctly identifies formats

**Pipeline Tests:**
- Full chains: .tar.gz with .gds.bz2 inside
- Stage skipping: .gds.gz (stage 2 skipped), .zip (stage 1 skipped)
- Security: zipbomb detection (high compression ratio)
- Security: absolute size limits during streaming
- Concurrency: multiple tasks processing simultaneously (no collisions)
- Error propagation: cleanup happens even on failures
- Temp directory isolation: verify unique directories per task

**GitHubArtifactHandler Tests:**
- URL matching: artifact URLs vs non-artifact URLs
- URL transformation: UI URL → API URL correctly
- Metadata generation: auth metadata structure correct
- Mock GitHub API responses (avoid real API calls in tests)

### Integration Tests

**End-to-End Tests:**
- GitHub artifact URL → download → extract → validate → store
- Auth token injection: verify Authorization header added
- Format validation: final GDS/OASIS validation works
- Error scenarios: missing token, invalid artifact, size exceeded
- Compressed file URL → download → decompress → validate → store

### Browser Tests

**GitHub Artifact URL Submission:**
- Navigate to project file upload page
- Submit GitHub artifact URL in the URL field
- Verify download starts (status shows "Downloading" or "Queued")
- Wait for completion (use WebDriverWait with condition polling)
- Verify file shows as successfully downloaded
- Verify file details show correct format (GDS/OASIS)

**Error Display:**
- Submit GitHub artifact URL without GITHUB_TOKEN configured
- Verify error message displays (auth failure)
- Submit URL to artifact with multiple .gds files
- Verify validation error message (exactly one file required)
- Submit URL to artifact exceeding size limit
- Verify size limit error with actual size shown

**Compressed File Submission:**
- Submit direct URL to .gds.gz file (not GitHub)
- Verify decompression happens automatically
- Verify final file shows as .gds (not .gds.gz)

### Test Data

**Sample Files:**
- Small valid .gds file (~100KB)
- Small valid .oas file (~50KB)
- Compressed versions: .gds.gz, .gds.bz2, .gds.xz
- Archives: .zip, .tar, .tar.gz with various contents

**Archive Fixtures:**
- Single file: .zip containing one .gds
- Multiple files: .zip with .gds + README.txt (should ignore README)
- Multiple valid: .zip with two .gds files (should error)
- Empty archive: .zip with no valid files (should error)
- Nested: .tar.gz containing .gds.bz2 (should work)

**Security Test Files:**
- Zipbomb: small .zip that expands to >500MB
- High ratio: .gz with 200:1 compression ratio
- Size creep: file that passes pre-check but exceeds during extraction

**Mock GitHub Artifact Server:**
- Returns test ZIP files for integration/browser tests
- Simulates 302 redirect flow
- Tests auth token validation

## Implementation Files

**New Files:**
- `wafer_space/projects/content_processors.py` - Base class and registry
- `wafer_space/projects/processors/decompressors.py` - Gzip, Bzip2, Xz
- `wafer_space/projects/processors/extractors.py` - Zip, Tar
- `wafer_space/projects/processors/pipeline.py` - Pipeline orchestration
- `wafer_space/projects/processors/validation.py` - Format validation

**Modified Files:**
- `wafer_space/projects/url_handlers.py` - Add GitHubArtifactHandler
- `wafer_space/projects/tasks.py` - Integrate pipeline into download task
- `wafer_space/projects/tasks.py` - Add auth header support to _prepare_download_request

**Test Files:**
- `wafer_space/projects/tests/test_content_processors.py`
- `wafer_space/projects/tests/test_pipeline.py`
- `wafer_space/projects/tests/test_github_handler.py`
- `wafer_space/projects/tests/browser/test_artifact_submission.py`

## Migration Path

**Phase 1: ContentProcessor Framework**
- Implement base classes and registry
- Add decompressor processors (Gzip, Bzip2, Xz)
- Add extractor processors (Zip, Tar)
- Implement pipeline orchestration
- Add format validation

**Phase 2: Integration**
- Integrate pipeline into download task
- Add temporary file management
- Add security limits (size, compression ratio)
- Update error handling

**Phase 3: GitHub Handler**
- Implement GitHubArtifactHandler
- Add auth header support to download task
- Environment variable configuration

**Phase 4: Testing**
- Unit tests for all processors
- Pipeline tests
- Integration tests
- Browser tests

**Phase 5: Documentation**
- Update user documentation
- Add developer documentation
- Update .env.example with GITHUB_TOKEN

## Configuration

**Environment Variables:**
```bash
# .env
GITHUB_TOKEN=github_pat_...    # Required for GitHub artifact downloads
MAX_FILE_SIZE=524288000        # 500MB (existing setting)
MAX_COMPRESSION_RATIO=100      # New: compression ratio limit (100:1)
```

**Django Settings:**
```python
# config/settings/base.py
GITHUB_TOKEN = env("GITHUB_TOKEN", default="")
MAX_FILE_SIZE = env.int("MAX_FILE_SIZE", default=500 * 1024 * 1024)  # 500MB
MAX_COMPRESSION_RATIO = env.int("MAX_COMPRESSION_RATIO", default=100)  # 100:1
```

## Security Considerations

1. **Zipbomb Protection:**
   - Pre-extraction size checks
   - Compression ratio limits
   - Streaming with size monitoring
   - Abort on excessive decompression

2. **Resource Limits:**
   - Disk space: 500MB per file
   - Memory: streaming prevents loading entire files
   - CPU: abort on excessive processing time (Celery task timeout)

3. **Concurrency Safety:**
   - Task-isolated temp directories
   - No shared state between workers
   - Atomic file operations

4. **Authentication:**
   - Token from environment variable (not hardcoded)
   - Bearer token in Authorization header
   - No token storage or logging

## Future Enhancements

**Potential future work (not in scope):**

1. **Additional Formats:**
   - 7z archives
   - RAR archives (requires external library)
   - LZ4 compression

2. **Enhanced Validation:**
   - Deep GDS/OASIS structure validation
   - Layer verification
   - Cell name extraction

3. **Progress Reporting:**
   - Real-time extraction progress
   - WebSocket updates to UI

4. **Caching:**
   - Cache GitHub artifact downloads
   - Deduplicate identical archives

## Open Questions

None - design is complete and approved.
