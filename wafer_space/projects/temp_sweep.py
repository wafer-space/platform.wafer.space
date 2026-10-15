"""Sweep staging directories under MEDIA_ROOT/temp left by killed workers (#364).

Download workers stage work on user storage and remove it when their task
ends normally:

- ``temp/task_<celery id>/file_<id>/``: the extraction pipeline
  (``content_pipeline.get_temp_dir_for_file``), removed in a ``finally``;
- ``temp/downloads/file_<ProjectFile id>/``: the resumable download staging
  (``content_pipeline.download_dir_path``, #139), kept across a retryable
  failure so the retry can resume with an HTTP Range request.

A worker killed mid-task (OOM, a deploy restart, the hard time limit) runs no
``finally``, so its directory stays forever; downloads reach 100 GB. This
module finds those directories and removes them, and never one a live task
can own:

- a ``task_*`` directory goes only when nothing in it has changed for
  ``TEMP_SWEEP_MIN_AGE_SECONDS``, which is longer than any task may run;
- a ``downloads/file_<id>`` directory goes only when it is that old too *and*
  its ProjectFile is gone or has no download in progress or retry pending
  (latest DownloadAttempt not PENDING or DOWNLOADING).

Anything else under ``temp/`` (unknown names, symlinks, plain files) is left
alone. Only the ``http:rw:downloads`` worker may call this: it is the worker
that creates these directories and may write under MEDIA_ROOT.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import time
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from django.conf import settings

from .models import DownloadAttempt
from .models import ProjectFile

logger = logging.getLogger(__name__)

TASK_DIR_NAME = re.compile(r"^task_[A-Za-z0-9_-]+$")
DOWNLOAD_DIR_NAME = re.compile(r"^file_(\d+)$")
DOWNLOAD_IN_PROGRESS = frozenset(
    {DownloadAttempt.Status.PENDING, DownloadAttempt.Status.DOWNLOADING}
)


@dataclass
class SweepResult:
    """What one sweep removed and kept."""

    removed: list[Path] = field(default_factory=list)
    kept: list[Path] = field(default_factory=list)
    reclaimed_bytes: int = 0


def _tree_newest_mtime_and_size(path: Path) -> tuple[float, int]:
    """Newest mtime of anything in the tree, and the total size of its files.

    Symlinks are not followed: their own lstat counts, never their target.
    """
    newest = path.lstat().st_mtime
    total = 0
    for root, dirs, files in os.walk(path):
        for name in [*dirs, *files]:
            info = (Path(root) / name).lstat()
            newest = max(newest, info.st_mtime)
            if not stat.S_ISDIR(info.st_mode):
                total += info.st_size
    return newest, total


def _download_dir_orphan_reason(project_file_id: int) -> str | None:
    """Why a download staging directory is orphaned, or None if it may be in use."""
    project_file = ProjectFile.objects.filter(pk=project_file_id).first()
    if project_file is None:
        return f"ProjectFile {project_file_id} no longer exists"
    latest = project_file.latest_attempt
    if latest is not None and latest.status in DOWNLOAD_IN_PROGRESS:
        return None
    status = latest.status if latest is not None else "none"
    return (
        f"ProjectFile {project_file_id} has no download in progress "
        f"(latest attempt: {status})"
    )


def _remove_if_stale(
    path: Path, cutoff: float, reason: str, result: SweepResult
) -> None:
    """Remove ``path`` if nothing in it changed since ``cutoff``; log either way."""
    if path.is_symlink() or not path.is_dir():
        logger.warning("Temp sweep: leaving %s alone (not a directory)", path)
        result.kept.append(path)
        return
    try:
        newest, size = _tree_newest_mtime_and_size(path)
    except FileNotFoundError:
        # Its own task finished and removed it while we were looking.
        logger.info("Temp sweep: %s disappeared while being inspected", path)
        return
    if newest > cutoff:
        result.kept.append(path)
        return
    shutil.rmtree(path)
    result.removed.append(path)
    result.reclaimed_bytes += size
    logger.info(
        "Temp sweep: removed %s (%d bytes, idle %.1f h): %s",
        path,
        size,
        (time.time() - newest) / 3600,
        reason,
    )


def sweep_temp_dirs(*, now: float | None = None) -> SweepResult:
    """Remove orphaned staging directories under MEDIA_ROOT/temp.

    Args:
        now: Current time as a Unix timestamp (tests pass it; default: now).

    Returns:
        What was removed and kept, and how many bytes were reclaimed.
    """
    result = SweepResult()
    temp_root = Path(settings.MEDIA_ROOT) / "temp"
    if not temp_root.is_dir():
        return result
    current = time.time() if now is None else now
    cutoff = current - settings.TEMP_SWEEP_MIN_AGE_SECONDS

    for entry in sorted(temp_root.iterdir()):
        if TASK_DIR_NAME.match(entry.name):
            _remove_if_stale(entry, cutoff, "task staging directory", result)

    downloads = temp_root / "downloads"
    if downloads.is_dir():
        for entry in sorted(downloads.iterdir()):
            match = DOWNLOAD_DIR_NAME.match(entry.name)
            if match is None:
                continue
            reason = _download_dir_orphan_reason(int(match.group(1)))
            if reason is None:
                result.kept.append(entry)
                continue
            _remove_if_stale(entry, cutoff, reason, result)

    if result.reclaimed_bytes > settings.TEMP_SWEEP_ALERT_BYTES:
        logger.error(
            "Temp sweep reclaimed %d bytes from %d orphaned directories under %s; "
            "workers are being killed mid-task (OOM, restarts or time limits)",
            result.reclaimed_bytes,
            len(result.removed),
            temp_root,
        )
    return result
