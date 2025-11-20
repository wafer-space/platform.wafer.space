# Download Flow Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor download pipeline to use common progress-tracked download for all sources (including GitHub artifacts) and verify hashes on final extracted GDS/OASIS files rather than downloaded archives.

**Architecture:**
- GitHub artifact handler returns authenticated download URL instead of bytes
- All downloads (GitHub, direct URLs) flow through `_download_with_progress` for consistent chunk-based progress logging
- Hash calculation moved from download phase to after extraction pipeline
- Hash verification performed on final GDS/OASIS file, not intermediate ZIP/archive

**Tech Stack:** Django 5.2+, Celery, GitHub Actions API, Python pathlib, requests

---

## Current Problems

1. **No progress tracking for GitHub artifacts** - Downloads entire file in one request
2. **Hash verification on wrong file** - Validates downloaded ZIP, not extracted GDS/OASIS
3. **Code duplication** - GitHub artifacts bypass normal download flow
4. **Poor visibility** - Users can't see download progress for authenticated sources

## New Architecture Flow

```
1. Prepare Download Request
   ├─ Standard URL → Set headers, return URL as-is
   └─ GitHub Artifact → Get authenticated URL (60s expiry), set auth headers

2. Download with Progress (COMMON PATH)
   └─ Chunk-based download with database progress updates

3. Content Extraction Pipeline
   ├─ Decompress (if needed)
   ├─ Extract archive (if needed)
   └─ Decompress again (if needed)

4. Hash Verification
   └─ Calculate and verify hashes on FINAL extracted GDS/OASIS file
```

---

## Task 1: Refactor `_download_github_artifact` to Return Authenticated URL

**Objective:** Change GitHub artifact handler from downloading bytes to returning an authenticated download URL that works for 60 seconds.

**Files:**
- Modify: `wafer_space/projects/tasks.py:313-413` (function `_download_github_artifact`)
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Write failing test for new return type**

Add to `test_tasks.py` in the `DownloadTaskTests` class:

```python
@patch("wafer_space.projects.tasks.requests.get")
@patch("django.conf.settings.GITHUB_TOKEN", "test_token")
def test_download_github_artifact_returns_url(self, mock_get):
    """Test that _download_github_artifact returns authenticated URL."""
    # Mock artifact list response
    mock_list_response = MagicMock()
    mock_list_response.json.return_value = {
        "total_count": 1,
        "artifacts": [
            {
                "id": 123456,
                "name": "design-files",
                "size_in_bytes": 1024000,
            }
        ],
    }
    mock_list_response.raise_for_status = MagicMock()

    # Set mock to return list response
    mock_get.return_value = mock_list_response

    # Call function
    from wafer_space.projects.tasks import _download_github_artifact

    result = _download_github_artifact(
        owner="test-owner",
        repo="test-repo",
        run_id="789",
        github_token="test_token",
    )

    # Should return dict with URL and headers
    assert isinstance(result, dict)
    assert "url" in result
    assert "headers" in result
    assert result["url"] == (
        "https://api.github.com/repos/test-owner/test-repo/"
        "actions/artifacts/123456/zip"
    )
    assert result["headers"]["Authorization"] == "Bearer test_token"
```

**Step 2: Run test to verify it fails**

```bash
cd /home/tim/github/wafer-space/platform/.worktrees/content-extraction
uv run pytest wafer_space/projects/tests/test_tasks.py::DownloadTaskTests::test_download_github_artifact_returns_url -xvs
```

Expected: FAIL - function returns bytes, not dict

**Step 3: Refactor `_download_github_artifact` implementation**

In `wafer_space/projects/tasks.py`, modify function (lines 313-413):

```python
def _download_github_artifact(
    owner: str,
    repo: str,
    run_id: str,
    github_token: str | None,
) -> dict[str, str | dict[str, str]]:
    """Get authenticated download URL for GitHub Actions artifact.

    GitHub artifact download URLs are authenticated and expire after 60 seconds.
    This function fetches the artifact list, selects the first artifact, and
    returns the authenticated download URL with required headers.

    Args:
        owner: GitHub repository owner
        repo: GitHub repository name
        run_id: GitHub Actions run ID
        github_token: GitHub personal access token (requires actions:read scope)

    Returns:
        dict with keys:
            - url: Authenticated download URL (valid for 60 seconds)
            - headers: HTTP headers required for download (Authorization, etc.)
            - artifact_name: Name of the selected artifact
            - artifact_size: Size in bytes

    Raises:
        ValueError: If no artifacts found or GitHub token not provided
    """
    logger = logging.getLogger(__name__)

    if not github_token:
        msg = "GitHub token required for artifact download"
        raise ValueError(msg)

    # GitHub API requires specific headers
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # List artifacts for the run
    list_url = (
        f"https://api.github.com/repos/{owner}/{repo}/"
        f"actions/runs/{run_id}/artifacts"
    )

    logger.info("  Fetching artifact list from: %s", list_url)
    list_response = requests.get(list_url, headers=headers, timeout=30)
    list_response.raise_for_status()

    artifacts_data = list_response.json()
    artifacts = artifacts_data.get("artifacts", [])
    total_count = artifacts_data.get("total_count", 0)

    logger.info("  ✓ Found %d artifact(s) for run %s", total_count, run_id)

    if not artifacts:
        msg = f"No artifacts found for run {run_id}"
        raise ValueError(msg)

    # Log all available artifacts
    logger.info("  Available artifacts:")
    for idx, art in enumerate(artifacts, 1):
        art_name = art.get("name", "unknown")
        art_id = art.get("id", "unknown")
        art_size = art.get("size_in_bytes", 0)
        # Format size in human-readable format
        if art_size < BYTES_PER_KILOBYTE:
            size_str = f"{art_size} B"
        elif art_size < BYTES_PER_KILOBYTE * BYTES_PER_KILOBYTE:
            size_str = f"{art_size / BYTES_PER_KILOBYTE:.1f} KB"
        elif art_size < BYTES_PER_KILOBYTE * BYTES_PER_KILOBYTE * BYTES_PER_KILOBYTE:
            size_str = f"{art_size / (BYTES_PER_KILOBYTE * BYTES_PER_KILOBYTE):.1f} MB"
        else:
            size_str = f"{art_size / (BYTES_PER_KILOBYTE * BYTES_PER_KILOBYTE * BYTES_PER_KILOBYTE):.2f} GB"
        logger.info(
            "    %d. %s (ID: %s, Size: %s)",
            idx,
            art_name,
            art_id,
            size_str,
        )

    # Use first artifact (or could be made configurable)
    artifact = artifacts[0]
    artifact_id = artifact["id"]
    artifact_name = artifact["name"]
    artifact_size = artifact.get("size_in_bytes", 0)

    logger.info("  → Selecting artifact #1: %s (ID: %s)", artifact_name, artifact_id)

    # Construct authenticated download URL
    download_url = (
        f"https://api.github.com/repos/{owner}/{repo}/"
        f"actions/artifacts/{artifact_id}/zip"
    )
    logger.info("  ✓ Generated authenticated download URL (valid for 60 seconds)")

    return {
        "url": download_url,
        "headers": headers,
        "artifact_name": artifact_name,
        "artifact_size": artifact_size,
    }
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest wafer_space/projects/tests/test_tasks.py::DownloadTaskTests::test_download_github_artifact_returns_url -xvs
```

Expected: PASS

**Step 5: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "refactor: change _download_github_artifact to return authenticated URL

- Returns dict with url, headers, artifact metadata instead of bytes
- URL is valid for 60 seconds (GitHub API limitation)
- Prepares for using common download flow for GitHub artifacts
- Add test coverage for new return type

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Update `_prepare_download_request` to Handle GitHub Artifacts

**Objective:** Extend `_prepare_download_request` to detect GitHub artifacts and obtain authenticated URL + headers.

**Files:**
- Modify: `wafer_space/projects/tasks.py:467-486` (function `_prepare_download_request`)
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Write failing test**

Add to `test_tasks.py`:

```python
def test_prepare_download_request_with_github_artifact(self):
    """Test that GitHub artifacts get authenticated URL and headers."""
    project = Project.objects.create(
        user=self.user,
        name="Test Project",
    )

    project_file = ProjectFile.objects.create(
        project=project,
        source_url="https://github.com/owner/repo/actions/runs/123/artifacts/456",
        original_filename="design.zip",
        handler_metadata={
            "handler": "GitHubArtifactHandler",
            "owner": "owner",
            "repo": "repo",
            "run_id": "123",
            "requires_github_auth": True,
        },
    )

    temp_path = Path("/tmp/test_download.zip")

    with patch("wafer_space.projects.tasks._download_github_artifact") as mock_gh:
        mock_gh.return_value = {
            "url": "https://api.github.com/repos/owner/repo/actions/artifacts/789/zip",
            "headers": {"Authorization": "Bearer test_token"},
            "artifact_name": "design-files",
            "artifact_size": 1024000,
        }

        from wafer_space.projects.tasks import _prepare_download_request

        url, headers, resume_pos = _prepare_download_request(
            project_file=project_file,
            temp_path=temp_path,
        )

        # Should return authenticated URL and headers
        assert url == "https://api.github.com/repos/owner/repo/actions/artifacts/789/zip"
        assert headers["Authorization"] == "Bearer test_token"
        assert resume_pos == 0
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest wafer_space/projects/tests/test_tasks.py::DownloadTaskTests::test_prepare_download_request_with_github_artifact -xvs
```

Expected: FAIL - function signature doesn't accept `project_file`

**Step 3: Refactor `_prepare_download_request`**

Modify in `wafer_space/projects/tasks.py` (lines 467-486):

```python
def _prepare_download_request(
    project_file: ProjectFile,
    temp_path: Path,
) -> tuple[str, dict[str, str], int]:
    """Prepare download request with resume support and GitHub authentication.

    For GitHub artifacts, obtains authenticated download URL (valid 60 seconds).
    For standard URLs, uses URL as-is with User-Agent header.

    Args:
        project_file: ProjectFile with source_url and handler_metadata
        temp_path: Path to temporary download file

    Returns:
        tuple: (download_url, headers dict, resume byte position)
    """
    logger = logging.getLogger(__name__)

    # Check if this is a GitHub artifact requiring authentication
    if (
        project_file.handler_metadata
        and project_file.handler_metadata.get("requires_github_auth")
    ):
        logger.info("  GitHub artifact detected - obtaining authenticated URL...")

        from django.conf import settings  # noqa: PLC0415

        metadata = project_file.handler_metadata
        auth_data = _download_github_artifact(
            owner=metadata["owner"],
            repo=metadata["repo"],
            run_id=metadata["run_id"],
            github_token=settings.GITHUB_TOKEN,
        )

        url = auth_data["url"]
        headers = auth_data["headers"].copy()  # Copy to avoid mutating original

        # Add User-Agent (GitHub requires it)
        headers["User-Agent"] = "wafer.space/1.0"

        logger.info("  ✓ Authenticated URL obtained (valid for 60 seconds)")

        # GitHub artifact downloads don't support resume (they're dynamic URLs)
        resume_byte_pos = 0

        return url, headers, resume_byte_pos

    # Standard HTTP(S) download
    url = project_file.source_url
    headers = {"User-Agent": "wafer.space/1.0"}
    resume_byte_pos = 0

    if temp_path.exists():
        resume_byte_pos = temp_path.stat().st_size
        headers["Range"] = f"bytes={resume_byte_pos}-"
        formatted_size = _format_bytes(resume_byte_pos)
        logger.info("  Resume: Found partial download (%s)", formatted_size)

    return url, headers, resume_byte_pos
```

**Step 4: Update `_get_download_response` signature**

Modify `_get_download_response` to accept URL instead of getting it from project_file:

```python
def _get_download_response(
    url: str,
    headers: dict[str, str],
    temp_path: Path,
    resume_byte_pos: int,
) -> tuple[requests.Response, int]:
    """Get HTTP response for download, handling resume failures.

    Args:
        url: Download URL
        headers: HTTP headers (may include Range, Authorization, etc.)
        temp_path: Path to temp file
        resume_byte_pos: Byte position to resume from

    Returns:
        tuple: (response object, adjusted resume byte position)
    """
    logger = logging.getLogger(__name__)
    logger.info("  Sending HTTP GET request...")
    response = requests.get(url, headers=headers, stream=True, timeout=30)
    logger.info("  Response status: %s", response.status_code)

    # Check if server supports resume
    if resume_byte_pos > 0 and response.status_code != HTTP_PARTIAL_CONTENT:
        logger.info("  Server doesn't support resume - restarting from beginning")
        resume_byte_pos = 0
        temp_path.unlink(missing_ok=True)
        # Remove Range header for fresh start
        headers_no_range = {k: v for k, v in headers.items() if k != "Range"}
        response = requests.get(url, headers=headers_no_range, stream=True, timeout=30)

    response.raise_for_status()
    return response, resume_byte_pos
```

**Step 5: Update `_download_with_progress` to use new signature**

Modify in `wafer_space/projects/tasks.py` (lines 807-856):

```python
def _download_with_progress(
    task,
    project_file: ProjectFile,
    temp_path: Path,
    *,
    chunk_size: int = 1024 * 1024,  # 1MB chunks
) -> None:
    """Download file with progress tracking and resume capability.

    Handles both standard HTTP(S) downloads and GitHub artifact downloads
    through a common chunked download pathway with progress logging.

    Args:
        task: The Celery task instance (for progress updates)
        project_file: The ProjectFile instance
        temp_path: Path to temporary file for download
        chunk_size: Size of download chunks in bytes

    Returns:
        None - downloads to temp_path
    """
    # Prepare request (gets authenticated URL for GitHub artifacts)
    url, headers, resume_byte_pos = _prepare_download_request(
        project_file, temp_path
    )

    # Get HTTP response
    response, resume_byte_pos = _get_download_response(
        url, headers, temp_path, resume_byte_pos
    )

    # Log file size information
    total_size = _log_file_size(response, project_file, resume_byte_pos)

    # Download chunks with progress tracking (no hash calculation)
    download_state = _ChunkDownloadState(
        response=response,
        temp_path=temp_path,
        task=task,
        project_file=project_file,
        total_size=total_size,
        resume_byte_pos=resume_byte_pos,
        chunk_size=chunk_size,
        start_time=time.time(),
    )
    _download_chunks(download_state)
```

**Step 6: Run test to verify it passes**

```bash
uv run pytest wafer_space/projects/tests/test_tasks.py::DownloadTaskTests::test_prepare_download_request_with_github_artifact -xvs
```

Expected: PASS

**Step 7: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "feat: add GitHub artifact support to _prepare_download_request

- Detects GitHub artifacts via handler_metadata
- Obtains authenticated URL (60-second validity)
- Returns URL + auth headers for download
- Standard URLs use existing resume logic
- All downloads now flow through common pathway

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Remove Hash Calculation from Download Flow

**Objective:** Remove MD5/SHA1 hash calculation from `_download_chunks` and `_download_with_progress`, making them purely focused on downloading with progress tracking.

**Files:**
- Modify: `wafer_space/projects/tasks.py` (multiple functions)
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Write test for download without hash return**

Update existing test to not expect hash return:

```python
@patch("wafer_space.projects.tasks.requests.get")
def test_download_with_progress_no_hash_return(self, mock_get):
    """Test that _download_with_progress only downloads, doesn't return hashes."""
    project = Project.objects.create(user=self.user, name="Test")
    project_file = ProjectFile.objects.create(
        project=project,
        source_url="http://example.com/file.zip",
        original_filename="file.zip",
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Length": "1024"}
    mock_response.iter_content = lambda chunk_size: [b"test" * 256]
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    temp_path = Path(tempfile.mktemp())

    try:
        from wafer_space.projects.tasks import _download_with_progress

        # Mock task
        mock_task = MagicMock()
        mock_task.update_state = MagicMock()

        # Should return None (no hashes)
        result = _download_with_progress(
            mock_task,
            project_file,
            temp_path,
        )

        assert result is None
        assert temp_path.exists()
        assert temp_path.stat().st_size == 1024
    finally:
        temp_path.unlink(missing_ok=True)
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest wafer_space/projects/tests/test_tasks.py::DownloadTaskTests::test_download_with_progress_no_hash_return -xvs
```

Expected: FAIL - function returns tuple of hashes

**Step 3: Remove hash calculators from `_ChunkDownloadState`**

In `wafer_space/projects/tasks.py`, find `_ChunkDownloadState` dataclass and remove hash fields:

```python
@dataclass
class _ChunkDownloadState:
    """State for chunk download operation."""

    response: requests.Response
    temp_path: Path
    task: Any  # Celery task instance
    project_file: ProjectFile
    total_size: int
    resume_byte_pos: int
    chunk_size: int
    start_time: float
    # Removed: md5_hasher and sha1_hasher fields
```

**Step 4: Remove hash calculation from `_download_chunks`**

Find `_download_chunks` function and remove hash update calls:

```python
def _download_chunks(state: _ChunkDownloadState) -> None:
    """Download file in chunks with progress tracking.

    Updates:
    - Writes chunks to temp file
    - Updates database progress every N chunks
    - Logs progress to console

    Does NOT calculate hashes - that happens after extraction.
    """
    logger = logging.getLogger(__name__)

    downloaded = state.resume_byte_pos
    last_update = time.time()
    chunks_since_update = 0

    mode = "ab" if state.resume_byte_pos > 0 else "wb"

    with state.temp_path.open(mode) as temp_file:
        for chunk in state.response.iter_content(chunk_size=state.chunk_size):
            if chunk:
                temp_file.write(chunk)
                downloaded += len(chunk)
                chunks_since_update += 1

                # Update progress every 10 chunks or 5 seconds
                current_time = time.time()
                should_update = (
                    chunks_since_update >= CHUNKS_PER_UPDATE
                    or (current_time - last_update) >= PROGRESS_UPDATE_INTERVAL
                )

                if should_update:
                    _update_download_progress(
                        state, downloaded, current_time, last_update
                    )
                    last_update = current_time
                    chunks_since_update = 0

    # Final progress update
    _update_download_progress(state, downloaded, time.time(), last_update)
```

**Step 5: Remove hash initialization from `_download_with_progress`**

Update `_download_with_progress` to not initialize or return hashes:

```python
def _download_with_progress(
    task,
    project_file: ProjectFile,
    temp_path: Path,
    *,
    chunk_size: int = 1024 * 1024,  # 1MB chunks
) -> None:
    """Download file with progress tracking and resume capability.

    Downloads file in chunks, tracking progress to database.
    Hash calculation is performed separately after extraction pipeline.

    Args:
        task: The Celery task instance (for progress updates)
        project_file: The ProjectFile instance
        temp_path: Path to temporary file for download
        chunk_size: Size of download chunks in bytes

    Returns:
        None - file downloaded to temp_path
    """
    # Prepare request (gets authenticated URL for GitHub artifacts)
    url, headers, resume_byte_pos = _prepare_download_request(
        project_file, temp_path
    )

    # Get HTTP response
    response, resume_byte_pos = _get_download_response(
        url, headers, temp_path, resume_byte_pos
    )

    # Log file size information
    total_size = _log_file_size(response, project_file, resume_byte_pos)

    # Download chunks with progress tracking
    download_state = _ChunkDownloadState(
        response=response,
        temp_path=temp_path,
        task=task,
        project_file=project_file,
        total_size=total_size,
        resume_byte_pos=resume_byte_pos,
        chunk_size=chunk_size,
        start_time=time.time(),
    )
    _download_chunks(download_state)
```

**Step 6: Remove `_initialize_hash_calculators` function**

Delete this function entirely as it's no longer needed:

```python
# DELETE THIS FUNCTION
def _initialize_hash_calculators(
    temp_path: Path,
    resume_byte_pos: int,
) -> tuple[hashlib._Hash, hashlib._Hash]:
    # ... entire function deleted
```

**Step 7: Run test to verify it passes**

```bash
uv run pytest wafer_space/projects/tests/test_tasks.py::DownloadTaskTests::test_download_with_progress_no_hash_return -xvs
```

Expected: PASS

**Step 8: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "refactor: remove hash calculation from download flow

- _download_with_progress now only downloads, no hash calculation
- _download_chunks writes chunks without updating hash state
- Remove _ChunkDownloadState hash fields
- Delete _initialize_hash_calculators function
- Hash calculation moved to after extraction (next task)

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Calculate Hashes on Final Extracted File

**Objective:** Move hash calculation to after the extraction pipeline, so hashes are calculated on the final GDS/OASIS file, not the downloaded ZIP.

**Files:**
- Modify: `wafer_space/projects/tasks.py:1294-1487` (function `download_project_file`)
- Modify: `wafer_space/projects/tasks.py:1091-1161` (function `_process_and_save_content`)
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Write test for final file hash calculation**

```python
def test_hash_calculated_on_extracted_file_not_zip(self):
    """Test that hashes are calculated on extracted GDS, not downloaded ZIP."""
    project = Project.objects.create(user=self.user, name="Test")

    # Create a ZIP containing a GDS file
    import zipfile
    gds_content = b"GDS_FILE_CONTENT_HERE"
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zf:
        zf.writestr("design.gds", gds_content)
    zip_bytes = zip_buffer.getvalue()

    project_file = ProjectFile.objects.create(
        project=project,
        source_url="http://example.com/design.zip",
        original_filename="design.zip",
    )

    # Expected hashes for the GDS content (not the ZIP)
    expected_md5 = hashlib.md5(gds_content, usedforsecurity=False).hexdigest()
    expected_sha1 = hashlib.sha1(gds_content, usedforsecurity=False).hexdigest()

    with patch("wafer_space.projects.tasks._download_with_progress"):
        with patch("wafer_space.projects.tasks.Path.open") as mock_open:
            # Mock reading the downloaded ZIP
            mock_open.return_value.__enter__.return_value.read.return_value = zip_bytes

            # Mock the pipeline to extract GDS
            with patch("wafer_space.projects.tasks._apply_content_pipeline") as mock_pipeline:
                mock_pipeline.return_value = (gds_content, expected_md5, expected_sha1)

                # Run download task
                from wafer_space.projects.tasks import download_project_file

                mock_task = MagicMock()
                mock_task.request.id = "test-task-id"
                mock_task.request.retries = 0
                mock_task.max_retries = 3

                result = download_project_file(mock_task, str(project.id))

    # Verify hashes are for GDS content, not ZIP
    project_file.refresh_from_db()
    assert project_file.hash_md5 == expected_md5
    assert project_file.hash_sha1 == expected_sha1
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest wafer_space/projects/tests/test_tasks.py::DownloadTaskTests::test_hash_calculated_on_extracted_file_not_zip -xvs
```

Expected: FAIL - hashes calculated on ZIP, not extracted file

**Step 3: Update `download_project_file` to remove hash calculation from download phase**

In `wafer_space/projects/tasks.py`, modify `download_project_file` (lines 1364-1387):

```python
# Check if handler requires special download logic (e.g., GitHub artifacts)
# NOTE: With new architecture, ALL downloads go through _download_with_progress
logger.info("  Starting chunked download with progress tracking...")

# Download file (no hash calculation at this stage)
_download_with_progress(
    self,
    project_file,
    temp_path,
)

logger.info("  ✓ Download completed successfully!")
logger.info("  ✓ File saved to: %s", temp_path)
logger.info("  ✓ File size: %s", _format_bytes(temp_path.stat().st_size))

# Read downloaded content
logger.info("Step 5: Reading downloaded content...")
with temp_path.open("rb") as temp_file:
    downloaded_content = temp_file.read()
formatted_size = _format_bytes(len(downloaded_content))
logger.info("  ✓ Read %s from temp file", formatted_size)
```

**Step 4: Update `_apply_content_pipeline` to return hashes**

The pipeline already returns hashes - verify it calculates them correctly:

```python
def _apply_content_pipeline(
    project_file: ProjectFile,
    content: bytes,
    temp_path: Path,
) -> tuple[bytes, str, str]:
    """Apply content extraction pipeline to process compressed/archived files.

    Returns:
        tuple: (processed_content, md5_hash, sha1_hash) for FINAL extracted file
    """
    # ... existing implementation ...

    # Read processed content
    processed_content = result.output_path.read_bytes()

    # Calculate hashes on FINAL extracted file
    logger.info("  Calculating hashes on final extracted file...")
    final_md5, final_sha1 = _calculate_file_hashes(processed_content)
    logger.info("  ✓ MD5: %s", final_md5)
    logger.info("  ✓ SHA1: %s", final_sha1)

    return processed_content, final_md5, final_sha1
```

**Step 5: Update `_process_and_save_content` to use pipeline hashes**

Simplify the function to always use hashes from pipeline:

```python
def _process_and_save_content(
    project_file: ProjectFile,
    downloaded_content: bytes,
    temp_path: Path,
) -> tuple[bytes, str, str]:
    """Process downloaded content and save to Django storage.

    Returns:
        tuple: (processed_content, final_md5_hash, final_sha1_hash)
              Hashes are for the FINAL extracted GDS/OASIS file
    """
    logger = logging.getLogger(__name__)

    # Apply URL handler post-download processing (e.g., base64 decode)
    logger.info("Step 6: Checking for post-download processing...")
    if project_file.handler_metadata:
        logger.info("  Handler metadata found: %s", project_file.handler_metadata)
    processed_content = _apply_post_download_processing(
        project_file,
        downloaded_content,
    )

    if processed_content != downloaded_content:
        logger.info("  Content was transformed by handler")
        logger.info("  Original size: %s", _format_bytes(len(downloaded_content)))
        logger.info("  Processed size: %s", _format_bytes(len(processed_content)))
        temp_path.write_bytes(processed_content)
    else:
        logger.info("  ✓ No transformation needed - using original content")

    # Apply content extraction pipeline
    # This extracts GDS/OASIS from archives and calculates hashes on final file
    logger.info("Step 6.5: Running content extraction pipeline...")
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
        project_file.save(update_fields=["download_status", "download_error"])
        raise

    # Save to Django file field
    logger.info("Step 7: Saving file to Django storage...")
    django_file = ContentFile(processed_content)
    django_file.name = project_file.original_filename
    project_file.file.save(
        project_file.original_filename,
        django_file,
        save=False,
    )
    logger.info("  ✓ File saved to Django storage")

    # Set file size and hashes (for FINAL extracted file)
    project_file.file_size = len(processed_content)
    project_file.hash_md5 = final_md5
    project_file.hash_sha1 = final_sha1
    logger.info("  ✓ File size: %s", _format_bytes(project_file.file_size))
    logger.info("  ✓ MD5 hash: %s", final_md5)
    logger.info("  ✓ SHA1 hash: %s", final_sha1)

    return processed_content, final_md5, final_sha1
```

**Step 6: Update `download_project_file` to not pass hashes to `_process_and_save_content`**

```python
# Process and save content (extracts GDS/OASIS and calculates hashes)
logger.info("Step 7: Processing and saving content...")
_processed_content, final_md5, final_sha1 = _process_and_save_content(
    project_file,
    downloaded_content,
    temp_path,
)

# Verify hashes and create notifications
logger.info("Step 8: Verifying hashes and creating notifications...")
hash_verified, verification_errors = _verify_and_notify(
    project_file,
    final_md5,
    final_sha1,
)
```

**Step 7: Run tests to verify they pass**

```bash
uv run pytest wafer_space/projects/tests/test_tasks.py::DownloadTaskTests::test_hash_calculated_on_extracted_file_not_zip -xvs
uv run pytest wafer_space/projects/tests/test_tasks.py -xvs
```

Expected: All PASS

**Step 8: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/tasks.py wafer_space/projects/tests/test_tasks.py
git commit -m "feat: calculate hashes on final extracted file, not downloaded archive

- Hash calculation moved from download phase to after pipeline
- Hashes calculated on extracted GDS/OASIS file, not ZIP
- _process_and_save_content simplified to always use pipeline hashes
- download_project_file updated to not calculate hashes during download
- Fixes issue where hash verification failed due to ZIP vs GDS mismatch

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Remove Obsolete `_download_file_content` Function

**Objective:** Delete `_download_file_content` function since all downloads now go through `_download_with_progress`.

**Files:**
- Modify: `wafer_space/projects/tasks.py:416-440`
- Test: Verify no tests reference this function

**Step 1: Search for references**

```bash
cd /home/tim/github/wafer-space/platform/.worktrees/content-extraction
grep -r "_download_file_content" wafer_space/
```

Expected: Only definition, no callers

**Step 2: Delete function**

Remove lines 416-440 in `wafer_space/projects/tasks.py`:

```python
# DELETE THIS ENTIRE FUNCTION
def _download_file_content(project_file) -> bytes:
    """Download file content from URL using secure URL validation."""
    # ... deleted ...
```

**Step 3: Run tests**

```bash
uv run pytest wafer_space/projects/tests/test_tasks.py -xvs
```

Expected: All PASS (function not used)

**Step 4: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/tasks.py
git commit -m "refactor: remove obsolete _download_file_content function

- No longer needed - all downloads use _download_with_progress
- Reduces code duplication
- Part of download flow unification

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Update Tests to Match New Flow

**Objective:** Fix any broken tests that expect old behavior (hashes from download, bytes from GitHub handler).

**Files:**
- Modify: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Identify failing tests**

```bash
uv run pytest wafer_space/projects/tests/test_tasks.py -xvs 2>&1 | grep FAILED
```

**Step 2: Fix test for `test_download_with_github_artifact`**

Update test to not expect hash returns:

```python
@patch("django.conf.settings.GITHUB_TOKEN", None)
@patch("wafer_space.projects.tasks._download_github_artifact")
def test_download_with_github_artifact(self, mock_github_download):
    """Test GitHub artifact download with mocked API."""
    project = Project.objects.create(
        user=self.user,
        name="Test Project",
        description="Test",
    )

    # Create file with GitHub metadata
    project_file = ProjectFile.objects.create(
        project=project,
        source_url="https://github.com/owner/repo/actions/runs/123456/artifacts/789",
        original_filename="design.zip",
        is_active=True,
        download_status=ProjectFile.DownloadStatus.PENDING,
        handler_metadata={
            "handler": "GitHubArtifactHandler",
            "owner": "owner",
            "repo": "repo",
            "run_id": "123456",
            "requires_github_auth": True,
        },
    )

    # Mock GitHub artifact handler to return authenticated URL
    mock_github_download.return_value = {
        "url": "https://api.github.com/repos/owner/repo/actions/artifacts/999/zip",
        "headers": {"Authorization": "Bearer test-token"},
        "artifact_name": "design-files",
        "artifact_size": 1024,
    }

    # Mock the download
    with patch("wafer_space.projects.tasks._download_with_progress"):
        with patch("wafer_space.projects.tasks._apply_content_pipeline") as mock_pipeline:
            # Pipeline returns extracted GDS with hashes
            gds_content = b"GDS_CONTENT"
            md5 = hashlib.md5(gds_content, usedforsecurity=False).hexdigest()
            sha1 = hashlib.sha1(gds_content, usedforsecurity=False).hexdigest()
            mock_pipeline.return_value = (gds_content, md5, sha1)

            # ... rest of test

    # Verify GitHub handler was called with correct parameters
    mock_github_download.assert_called_once_with(
        owner="owner",
        repo="repo",
        run_id="123456",
        github_token=None,  # Default from settings (None means not configured)
    )
```

**Step 3: Run tests**

```bash
uv run pytest wafer_space/projects/tests/test_tasks.py -xvs
```

Expected: All PASS

**Step 4: Commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/tests/test_tasks.py
git commit -m "test: update tests to match new download flow architecture

- GitHub handler returns URL, not bytes
- No hash returns from _download_with_progress
- Hashes calculated after pipeline extraction
- All tests passing with new flow

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: Integration Testing

**Objective:** Run full test suite and verify the new flow works end-to-end.

**Step 1: Run full project test suite**

```bash
make test
```

Expected: All PASS

**Step 2: Run browser tests (headless)**

```bash
make test-browser-headless
```

Expected: All PASS

**Step 3: Test with real GitHub artifact URL (manual)**

```bash
# In Django shell
uv run python manage.py shell

from wafer_space.projects.models import Project, ProjectFile
from wafer_space.users.models import User

user = User.objects.first()
project = Project.objects.create(
    user=user,
    name="Test GitHub Download",
    description="Testing new download flow"
)

from wafer_space.projects.services import ProjectFileService

file, metadata = ProjectFileService.submit_file_from_url(
    project=project,
    url="https://github.com/TinyTapeout/tinytapeout-gf-0p2/actions/runs/19443235082/artifacts/4593571166",
    expected_hash_md5="abc123",
    expected_hash_sha1="def456",
)

# Check logs for progress updates
# Exit shell: exit()
```

**Step 4: Verify logs show progress**

Check that logs show:
- GitHub artifact detection
- Authenticated URL generation
- Chunk-by-chunk download progress
- Pipeline extraction
- Hash calculation on final file
- Hash verification

**Step 5: Final commit**

```bash
git add .
git commit -m "chore: integration testing for download flow refactor

All tests passing:
- Unit tests for download functions
- Integration tests for GitHub artifacts
- Browser tests for file submission
- Manual testing with real GitHub URLs

Download flow successfully unified:
✓ GitHub artifacts use common download pathway
✓ Progress tracking works for all sources
✓ Hashes calculated on final extracted files
✓ All error handling preserved

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Verification Checklist

After completing all tasks, verify:

- [ ] All tests pass (`make test`)
- [ ] Browser tests pass (`make test-browser-headless`)
- [ ] Linting passes (`make lint`)
- [ ] Type checking passes (`make type-check`)
- [ ] GitHub artifacts show download progress in logs
- [ ] Hashes calculated on extracted GDS/OASIS files
- [ ] Hash verification works correctly
- [ ] Error handling intact (network errors, auth failures)
- [ ] No code duplication between download paths
- [ ] Logs are informative and show flow progression

---

## Success Criteria

✅ **GitHub artifacts use common download pathway** - Progress tracked in database
✅ **Hash verification on correct file** - Final GDS/OASIS, not ZIP archive
✅ **Code consolidation** - Single download function for all sources
✅ **Backward compatible** - Existing direct URL downloads still work
✅ **Error reporting** - Pipeline failures reported to database
✅ **Test coverage** - All new behavior covered by tests
