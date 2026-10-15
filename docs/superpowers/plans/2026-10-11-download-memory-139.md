# Download Memory and Staging (#139) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No code path in the download task holds a whole file in memory, and each download stages in its own directory on user storage.

**Architecture:**
- The bytes-in, bytes-out URL handler hook becomes path-based. `GoogleSourceHandler` decodes base64 in fixed-size chunks and atomically replaces the file.
- Download staging moves from `tempfile.gettempdir()/wafer_space_downloads` to `MEDIA_ROOT/temp/downloads/file_<ProjectFile.id>/`, keyed by file, so HTTP Range resume survives retries.
- The whole directory is removed on success or final failure, and cleanup failures are logged at ERROR.

**Tech Stack:** Django 5.2, Celery (queue `http:rw:downloads`), pytest, the `projects/tests/read_instrumentation.py` read-size recorder (#275).

**Spec:** `docs/superpowers/specs/2026-10-11-download-memory-139-design.md` (approved by the coordinator 2026-10-11).

## Global Constraints

- Only the `http:rw:downloads` worker writes under `MEDIA_ROOT`; no view or `ro` worker touches the staging dir (CLAUDE.md).
- No `# noqa` / `# type: ignore`; `make lint-fix && make lint && make type-check && make test` before every commit; commit only after reading `EXIT=0`.
- Specific exceptions only (no `except Exception`); fail loud.
- Read chunk size for decode: 1 MiB (`DECODE_CHUNK_SIZE = 1024 * 1024`).
- Staging dir: `Path(settings.MEDIA_ROOT) / "temp" / "downloads" / f"file_{project_file_id}"`.

## Review Focus

1. Base64 input whose 4-byte groups straddle a chunk boundary: the output must equal `base64.b64decode`. Covered in Task 1 by a test with 3 data bytes on each side of the boundary.
2. Line-wrapped base64 (googlesource's real format) with `\n` every 76 characters: must decode identically. Covered in Task 1.
3. Invalid base64: a non-multiple-of-4 total, or padding mid-stream. Must raise `ValueError` and leave the original file byte-for-byte unchanged. Covered in Task 1.
4. A retry after a partial download must find the partial file and resume, not restart. Covered in Task 3 by the stable-path test plus the existing resume tests running against the new path.
5. A cleanup `OSError` on success must be visible (logged at ERROR), not hidden. Covered in Task 4.

---

### Task 1: Streaming base64 decode in `GoogleSourceHandler`

**Files:**
- Modify: `wafer_space/projects/url_handlers.py` (the `URLHandler.post_download` base method, `GoogleSourceHandler.post_download`, and the module docstring example)
- Test: `wafer_space/projects/tests/test_url_handlers.py`

**Interfaces:**
- Produces:
  - `URLHandler.post_download_file(self, path: Path, metadata: dict[str, Any]) -> bool`. The base returns `False` and leaves the file unchanged.
  - `GoogleSourceHandler.post_download_file(...)` decodes `path` in place, returns `True`, and raises `ValueError` on invalid base64.
- `post_download(bytes)` is removed.

- [ ] **Step 1: Write the failing tests**

```python
class TestGoogleSourceStreamingDecode:
    """GoogleSourceHandler decodes on disk in bounded chunks (#139)."""

    @staticmethod
    def _decode(tmp_path: Path, encoded: bytes) -> Path:
        path = tmp_path / "download.b64"
        path.write_bytes(encoded)
        GoogleSourceHandler().post_download_file(path, {"base64_encoded": True})
        return path

    def test_round_trip_matches_b64decode(self, tmp_path: Path) -> None:
        content = bytes(range(256)) * 9000  # > 2 MiB decoded, > 2 chunks
        path = self._decode(tmp_path, base64.b64encode(content))
        assert path.read_bytes() == content

    def test_line_wrapped_input(self, tmp_path: Path) -> None:
        content = b"layout" * 50000
        wrapped = base64.encodebytes(content)  # newline every 76 chars
        path = self._decode(tmp_path, wrapped)
        assert path.read_bytes() == content

    def test_groups_straddling_a_chunk_boundary(self, tmp_path: Path) -> None:
        # Pad so a 4-char group splits across the 1 MiB read boundary.
        encoded = b"\n" * (DECODE_CHUNK_SIZE - 2) + base64.b64encode(b"abcdef")
        path = self._decode(tmp_path, encoded)
        assert path.read_bytes() == b"abcdef"

    def test_reads_are_bounded(self, tmp_path: Path) -> None:
        real = tmp_path / "download.b64"
        real.write_bytes(base64.b64encode(b"x" * (3 * DECODE_CHUNK_SIZE)))
        path = RecordingPath(real)
        path.read_sizes = []
        GoogleSourceHandler().post_download_file(path, {})
        assert path.read_sizes and all(
            0 < size <= DECODE_CHUNK_SIZE for size in path.read_sizes
        )

    @pytest.mark.parametrize(
        "encoded",
        [
            b"YWJ=ZGVm",
            b"YWJjZ",
            b"YWI=" + b"\n" * (DECODE_CHUNK_SIZE - 4) + b"YWJj",
        ],
        ids=["padding-mid", "truncated", "padding-across-chunks"],
    )
    def test_invalid_input_raises_and_leaves_file(
        self, tmp_path: Path, encoded: bytes
    ) -> None:
        path = tmp_path / "download.b64"
        path.write_bytes(encoded)
        with pytest.raises(ValueError, match="base64"):
            GoogleSourceHandler().post_download_file(path, {})
        assert path.read_bytes() == encoded

    def test_base_handler_leaves_file_unchanged(self, tmp_path: Path) -> None:
        path = tmp_path / "f.gds"
        path.write_bytes(b"gds")
        assert URLHandler().post_download_file(path, {}) is False
        assert path.read_bytes() == b"gds"
```

Imports: `base64`, `pytest`, `Path`, `RecordingPath` from `wafer_space.projects.tests.read_instrumentation`, and `DECODE_CHUNK_SIZE`, `GoogleSourceHandler`, `URLHandler` from `wafer_space.projects.url_handlers`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_url_handlers.py -k StreamingDecode -q`
Expected: ImportError / AttributeError (`DECODE_CHUNK_SIZE`, `post_download_file` do not exist).

- [ ] **Step 3: Implement**

```python
DECODE_CHUNK_SIZE = 1024 * 1024
_B64_ALPHABET = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
)
_NON_B64 = bytes(b for b in range(256) if b not in _B64_ALPHABET)


class URLHandler:
    def post_download_file(self, path: Path, metadata: dict[str, Any]) -> bool:
        """Transform the downloaded file in place; True if it changed."""
        return False


class GoogleSourceHandler(URLHandler):
    def post_download_file(self, path: Path, metadata: dict[str, Any]) -> bool:
        decoded_path = path.with_name(path.name + ".decoded")
        try:
            with path.open("rb") as src, decoded_path.open("wb") as dst:
                _stream_b64decode(src, dst)
        except ValueError:
            decoded_path.unlink(missing_ok=True)
            raise
        os.replace(decoded_path, path)
        return True


def _stream_b64decode(src: IO[bytes], dst: IO[bytes]) -> None:
    """Decode base64 from src to dst in DECODE_CHUNK_SIZE reads.

    Non-alphabet bytes (googlesource's line breaks) are dropped, as
    base64.b64decode(validate=False) does. Padding ('=') may only end the
    stream: b64decode(validate=True) rejects it mid-block, and
    seen_padding rejects data after a block that ended in padding.
    """
    carry = b""
    seen_padding = False
    while chunk := src.read(DECODE_CHUNK_SIZE):
        data = carry + chunk.translate(None, _NON_B64)
        if seen_padding and data:
            msg = "Invalid base64 in googlesource download: data after padding"
            raise ValueError(msg)
        usable = len(data) - len(data) % 4
        block = data[:usable]
        dst.write(_b64decode_strict(block))
        seen_padding = block.endswith(b"=")
        carry = data[usable:]
    if carry:
        msg = "Invalid base64 in googlesource download: truncated final group"
        raise ValueError(msg)


def _b64decode_strict(data: bytes) -> bytes:
    """Decode whole 4-byte groups, rejecting padding before the end."""
    try:
        return base64.b64decode(data, validate=True)
    except binascii.Error as exc:
        msg = f"Invalid base64 in googlesource download: {exc}"
        raise ValueError(msg) from exc
```

Add one more test case to `test_invalid_input_raises_and_leaves_file`: padding at the end of one chunk followed by data in the next. Use `b"YWI=" + b"\n" * (DECODE_CHUNK_SIZE - 4) + b"YWJj"`, id `padding-across-chunks`.

- [ ] **Step 4: Run tests, they pass**

Run: `uv run pytest wafer_space/projects/tests/test_url_handlers.py -q`

- [ ] **Step 5: Gate, then commit** (`fix(projects): stream the googlesource base64 decode (#139)`).

### Task 2: `_apply_post_download_processing` uses the file hook

**Files:**
- Modify: `wafer_space/projects/tasks_download.py` (`_apply_post_download_processing`)
- Test: `wafer_space/projects/tests/test_tasks.py` (next to `test_post_download_processing_decodes_google_source_in_place`)

**Interfaces:**
- Consumes: `GoogleSourceHandler.post_download_file` (Task 1).

- [ ] **Step 1: Failing test.** A large file through `_apply_post_download_processing` with a `RecordingPath`: every read is bounded, never `-1`. It fails on main because `read_bytes()` reads with `-1`.

```python
@pytest.mark.django_db
def test_post_download_processing_reads_bounded_chunks(self, tmp_path):
    real = tmp_path / "download.b64"
    real.write_bytes(base64.b64encode(b"y" * (3 * DECODE_CHUNK_SIZE)))
    path = RecordingPath(real)
    path.read_sizes = []
    project_file = ProjectFileFactory(
        handler_metadata={"handler": "GoogleSourceHandler", "base64_encoded": True}
    )
    _apply_post_download_processing(project_file, path)
    assert path.read_sizes and -1 not in path.read_sizes
```

- [ ] **Step 2: Run it; it must FAIL** (`-1` recorded by `read_bytes`).
- [ ] **Step 3: Implement.** Replace the `read_bytes` / `post_download` / `write_bytes` block with:

```python
before = temp_path.stat().st_size
if handler.post_download_file(temp_path, project_file.handler_metadata):
    logger.info("  Content was transformed by handler")
    logger.info("  Original size: %s", _format_bytes(before))
    logger.info("  Processed size: %s", _format_bytes(temp_path.stat().st_size))
```

Update the docstring: "file-based; never reads the download into memory".
- [ ] **Step 4: Run both post-download tests; PASS.**
- [ ] **Step 5: Gate, then commit** (`fix(projects): decode googlesource downloads file to file (#139)`).

### Task 3: Per-file staging directory on user storage

**Files:**
- Modify: `wafer_space/projects/content_pipeline.py` (add `get_download_dir_for_file`)
- Modify: `wafer_space/projects/tasks_download.py` (`_setup_temp_directory` removed; `_setup_download_temp_path`, `_log_download_start`; drop `import tempfile` if unused)
- Test: `wafer_space/projects/tests/test_content_pipeline.py` (or the file covering `get_temp_dir_for_file`) and `test_tasks.py`

**Interfaces:**
- Produces: `get_download_dir_for_file(project_file_id: int) -> Path`, which creates `MEDIA_ROOT/temp/downloads/file_<id>/`. Then `_setup_download_temp_path(project_file) -> Path` returns `get_download_dir_for_file(project_file.id) / project_file.original_filename`.

- [ ] **Step 1: Failing tests**

```python
def test_download_dir_is_per_file_under_media_temp(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    path = get_download_dir_for_file(42)
    assert path == tmp_path / "temp" / "downloads" / "file_42"
    assert path.is_dir()


def test_download_dir_is_stable_across_calls(settings, tmp_path):
    """A retry is a new Celery task and must find the partial file."""
    settings.MEDIA_ROOT = str(tmp_path)
    assert get_download_dir_for_file(7) == get_download_dir_for_file(7)


def test_download_task_no_longer_uses_system_temp():
    source = Path(tasks_download.__file__).read_text()
    assert "gettempdir" not in source
```

- [ ] **Step 2: Run; FAIL.**
- [ ] **Step 3: Implement** the helper next to `get_temp_dir_for_file`, with the same `mkdir(parents=True, exist_ok=True)`. Make `_setup_download_temp_path` and `_log_download_start` use it, and delete `_setup_temp_directory`.
- [ ] **Step 4: Run** `uv run pytest wafer_space/projects/tests -q -k "download or pipeline or resume"`. The existing resume tests must pass unchanged, because they patch or derive the temp path.
- [ ] **Step 5: Gate, then commit** (`fix(projects): stage downloads per file under MEDIA_ROOT/temp (#139)`).

### Task 4: Cleanup removes the directory; failures are loud

**Files:**
- Modify: `wafer_space/projects/tasks_download.py`:
  - the success cleanup (Step 9, `contextlib.suppress(OSError): temp_path.unlink()`);
  - the final-failure cleanup in `_handle_download_failure`;
  - the retryable path, which keeps the file.
- Test: `wafer_space/projects/tests/test_tasks.py`

**Interfaces:**
- Consumes: `get_download_dir_for_file`, `cleanup_temp_dir` (existing, `shutil.rmtree`).

- [ ] **Step 1: Failing tests**
  - A successful `download_project_file` run (reuse the existing success-path fixture in `test_tasks.py`) leaves `get_download_dir_for_file(id)` absent.
  - The same run with `cleanup_temp_dir` patched to raise `OSError("busy")` logs at ERROR, mentioning the directory (`caplog`), and still returns `"completed"`.
  - A final failure removes the directory.
  - A retryable failure keeps the partial file.
- [ ] **Step 2: Run; FAIL** (today only the file is unlinked, and the OSError is suppressed).
- [ ] **Step 3: Implement.** Success:

```python
download_dir = temp_path.parent
try:
    cleanup_temp_dir(download_dir)
except OSError:
    logger.exception("Failed to remove download staging dir %s", download_dir)
else:
    logger.info("  ✓ Staging directory removed")
```

The final failure does the same, where it unlinks today. Retryable paths are unchanged, so the file is kept for resume.
- [ ] **Step 4: Run; PASS.**
- [ ] **Step 5: Gate, then commit** (`fix(projects): remove the staging dir on completion, loudly (#139)`).

### Task 5: PR

- [ ] Independent Sonnet review, briefed to hunt for shortcuts. Fix or answer every finding.
- [ ] PR body:
  - what #139 asked versus what was already fixed (the spec's table);
  - that only the `http:rw:downloads` worker touches the staging dir (the coordinator's note);
  - a link to #364 for the orphan sweep;
  - the deploy note: in-flight partial downloads restart once.
- [ ] Push only in the slot the coordinator gives.
