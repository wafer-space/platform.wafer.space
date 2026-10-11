# Download task: no whole-file reads, per-file temp directory on user storage

**Date:** 2026-10-11
**Issue:** [#139](https://github.com/wafer-space/platform.wafer.space/issues/139) (download task loads entire files into memory and uses two temp locations)
**Priority:** P2 (Run #3 traffic risk, coordinator, 11 Oct)
**Status:** Draft, for review by the coordinator

## Where #139 stands on main (88464b8)

Issue #139 was written against an older `tasks.py`. Re-reading the code today:

| #139 problem | Today | Evidence |
|---|---|---|
| Download read whole into memory | **Fixed.** Streamed in `iter_content` chunks, capped by `MAX_DOWNLOAD_SIZE` (100 GB) | `tasks_download.py` `_download_chunks` (around line 841) |
| `temp_path.read_bytes()` then `write_bytes()` on every download | **Fixed for the common path.** Remains only for the googlesource base64 handler | `_apply_post_download_processing`, `tasks_download.py:1337` |
| Extracted file read into memory, then `ContentFile` | **Fixed.** Streamed with `File(open(...))` into storage | `_process_and_save_content`, around line 1507 |
| Extraction or decompression unbounded | **Fixed.** Chunked, capped by `MAX_EXTRACTED_SIZE` (10 GB) | `processors/decompressors.py`, `processors/extractors.py` |
| Two temp locations (`/tmp/wafer_space_downloads` and `media/temp/...`) | **Still true** | `_setup_temp_directory`, `tasks_download.py:108`; `_log_download_start:1645` |

So two things are left:

1. **The googlesource handler reads the whole download into memory.** `GoogleSourceHandler.post_download(content: bytes) -> bytes` does `base64.b64decode(content)`. The caller holds both the encoded and the decoded copy, roughly 1.75 times the file size. A 2 GB layout served base64 by googlesource needs about 4.7 GB of worker RAM. The `http:rw:downloads` worker runs several downloads at once.
2. **The download is staged in the system temp directory.** `Path(tempfile.gettempdir()) / "wafer_space_downloads" / f"{file_id}_{name}"` is:
   - on the root filesystem, not user storage (`/mnt/user-files`), so a 100 GB download can fill `/`;
   - under systemd `PrivateTmp`, so it is invisible to everything outside the service;
   - a different filesystem from the final storage location, so saving copies instead of renaming.
   The pipeline already uses `MEDIA_ROOT/temp/task_<id>/file_<id>/`.

## Goals

- No code path in the download task holds a whole downloaded or extracted file in memory. Peak memory per download is bounded by a constant (chunk sizes), not by the file size.
- Each download stages in its own directory on user storage, on the same filesystem as the final file.
- The temp directory is stable across retries of the same `ProjectFile`, so the existing HTTP Range resume (`_prepare_download_request`) keeps working.
- All file writes stay in the `http:rw:downloads` worker. No view writes media; CLAUDE.md is unchanged.

## Non-goals

- `_safe_urlopen` (`tasks_download.py:172`) returns `response.read()`, but it has no production caller, only tests. It belongs to the dead-code work, not here. Not changed.
- No change to `MAX_DOWNLOAD_SIZE` / `MAX_EXTRACTED_SIZE` values or to the extraction processors, which already stream.
- No change to the GitHub artifact flow beyond the shared temp path. Its artifact zip goes through the same chunked download.

## Design

### 1. File-to-file post-download processing

Replace the bytes-in, bytes-out handler hook with a path-based one:

```python
class URLHandler:
    def post_download_file(self, path: Path, metadata: dict[str, Any]) -> bool:
        """Transform the downloaded file in place; return True if it changed."""
        return False
```

`GoogleSourceHandler.post_download_file` decodes in a stream:

- Read the encoded file in 1 MiB chunks.
- Keep only base64-alphabet bytes (`A-Z a-z 0-9 + / =`). This matches `base64.b64decode(..., validate=False)`, which the current code relies on to skip googlesource's line breaks.
- Decode whole 4-byte groups; carry the remainder to the next chunk.
- Write to `path.with_suffix(path.suffix + ".decoded")` in the same directory, then `os.replace()` it over `path`. The replace is atomic, and there is never a half-decoded file at `path`.
- Invalid base64 (a stray `=` mid-stream, or a final group that cannot be completed) raises `ValueError`. That reaches the existing pipeline-error handling in `_process_and_save_content`: a `FileProcessingError` row, a FAILED attempt and `download_error` set. Never a silent partial file.

`_apply_post_download_processing` calls `post_download_file(temp_path, metadata)` and logs the size before and after when it returns True. `post_download(bytes)` and its docs are removed. It has one implementation and one caller, both changed here.

### 2. Per-file staging directory on user storage

New helper, next to `get_temp_dir_for_file` in `content_pipeline.py`:

```python
def get_download_dir_for_file(project_file_id: int) -> Path:
    """MEDIA_ROOT/temp/downloads/file_<id>/ (created if missing)."""
```

- It is keyed by `ProjectFile.id` only, **not** by Celery task id (unlike the pipeline dir). A retry is a new task, and it must find the partial file to resume. One `ProjectFile` has at most one download in flight: `download_task_id` and the attempt row ensure it.
- The temp file inside is `<original_filename>`, so the directory is the per-download namespace. The old `<id>_<name>` prefix is no longer needed.
- `_setup_temp_directory()` and the duplicate path computation in `_log_download_start` are removed. `_setup_download_temp_path` uses the new helper, and `_log_download_start` logs the same path.
- Cleanup:
  - after a successful save, and on final failure, the whole `file_<id>/` directory is removed (`cleanup_temp_dir`), not just the file;
  - on a retryable failure it is kept, so the next attempt can resume.
- The success path currently does `contextlib.suppress(OSError): temp_path.unlink()` and then logs "Temp file removed" regardless. It will log the `OSError` at ERROR (admin email) instead of hiding it. A leftover directory on user storage is a disk leak someone must see.

Deploy note:
- `MEDIA_ROOT/temp/` already exists and is written by this same worker; the pipeline dirs live there. No hetzner-ansible change is needed.
- Partial downloads in the old `/tmp/wafer_space_downloads` location are abandoned at deploy, and their resume is lost; they restart from 0. On the next service restart, `PrivateTmp` discards them.
- hetzner-ansible should confirm the `http:rw:downloads` unit has `/mnt/user-files` writable. The pipeline already requires that.

### 3. Tests (TDD, each watched failing first)

- **Never whole in memory:** run `_apply_post_download_processing` on a base64 file larger than 8 times the chunk size. Use `RecordingPath` / `ReadSizeRecorder` (`projects/tests/read_instrumentation.py`, the #275 pattern) to assert every `read()` has a bounded size, never `-1` and never the file size. Assert the decoded output equals `base64.b64decode` of the input.
- Line-wrapped base64 (googlesource's real format) decodes identically to `b64decode`.
- Invalid base64 raises `ValueError` and leaves the original file untouched (atomic replace).
- `get_download_dir_for_file(id)` is under `MEDIA_ROOT/temp/downloads/` and stable across calls, so resume works across tasks.
- A download that fails with a retryable error keeps its partial file in that directory; the next attempt sends `Range: bytes=<size>-`. This extends the existing resume tests, with the path changed.
- Success removes the directory. A final failure removes it too.
- A cleanup `OSError` on success is logged at ERROR (`caplog`), not suppressed.
- No test or code path references `tempfile.gettempdir()` in `tasks_download.py` (grep-style assertion), so the old location cannot come back unnoticed.

## Risks

- **Resume across deploy:** in-flight partial downloads restart once (see the deploy note). This is acceptable; at worst one re-download per in-flight file.
- **Disk use moves from `/` to `/mnt/user-files`:** this is intended. The storage volume is sized for user files, and the root disk is not.
- **Handler API change:** `post_download` is internal (one subclass, one caller). No external users.

## Out of scope, noted for later

- `_safe_urlopen` (dead in production; it reads whole responses). Dead-code work.
- A periodic sweep of `MEDIA_ROOT/temp/` for directories left by killed workers. The pipeline dirs have the same exposure today. If wanted, it becomes one beat task for both, as a separate issue.
