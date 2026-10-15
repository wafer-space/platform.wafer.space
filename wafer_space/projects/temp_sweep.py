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


class TempSweepError(Exception):
    """One or more orphaned directories could not be removed."""


@dataclass
class SweepResult:
    """What one sweep removed, kept and failed to remove."""

    removed: list[Path] = field(default_factory=list)
    kept: list[Path] = field(default_factory=list)
    failed: list[Path] = field(default_factory=list)
    reclaimed_bytes: int = 0


def tree_newest_mtime_and_size(path: Path) -> tuple[float, int]:
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


@dataclass
class _Candidate:
    """A directory that matched a swept layout, and how to judge it."""

    path: Path
    reason: str
    # Re-asked just before deleting: a download may have restarted while the
    # tree was being walked. None for task_* directories (age alone decides).
    project_file_id: int | None = None


def _remove_if_stale(
    candidate: _Candidate, cutoff: float, now: float, result: SweepResult
) -> None:
    """Remove the candidate if nothing in it changed since ``cutoff``."""
    path = candidate.path
    if path.is_symlink() or not path.is_dir():
        logger.info("Temp sweep: leaving %s alone (not a directory)", path)
        result.kept.append(path)
        return
    try:
        newest, size = tree_newest_mtime_and_size(path)
    except FileNotFoundError:
        # Its own task finished and removed it while we were looking.
        logger.info("Temp sweep: %s disappeared while being inspected", path)
        return
    if newest > cutoff:
        result.kept.append(path)
        return
    if (
        candidate.project_file_id is not None
        and _download_dir_orphan_reason(candidate.project_file_id) is None
    ):
        # A download (re)started while the tree was being walked.
        result.kept.append(path)
        return
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        logger.info("Temp sweep: %s disappeared before it was removed", path)
        return
    except OSError:
        logger.exception("Temp sweep: could not remove %s", path)
        result.failed.append(path)
        return
    result.removed.append(path)
    result.reclaimed_bytes += size
    logger.info(
        "Temp sweep: removed %s (%d bytes, idle %.1f h): %s",
        path,
        size,
        (now - newest) / 3600,
        candidate.reason,
    )


def _candidates(temp_root: Path) -> tuple[list[_Candidate], list[Path]]:
    """Directories under temp/ whose layout this sweep knows, in path order.

    Returns the candidates for removal, and the download staging
    directories whose download is in progress or whose retry is pending
    (never removed, whatever their age).
    """
    candidates = [
        _Candidate(entry, "task staging directory")
        for entry in sorted(temp_root.iterdir())
        if TASK_DIR_NAME.match(entry.name)
    ]
    in_use: list[Path] = []
    downloads = temp_root / "downloads"
    if downloads.is_dir():
        for entry in sorted(downloads.iterdir()):
            match = DOWNLOAD_DIR_NAME.match(entry.name)
            if match is None:
                continue
            project_file_id = int(match.group(1))
            reason = _download_dir_orphan_reason(project_file_id)
            if reason is None:
                in_use.append(entry)
                continue
            candidates.append(_Candidate(entry, reason, project_file_id))
    return candidates, in_use


def sweep_temp_dirs(*, now: float | None = None) -> SweepResult:
    """Remove orphaned staging directories under MEDIA_ROOT/temp.

    A directory that cannot be removed is logged at ERROR and the sweep goes
    on with the others; ``TempSweepError`` is raised at the end listing them.

    Args:
        now: Current time as a Unix timestamp (tests pass it; default: now).

    Returns:
        What was removed and kept, and how many bytes were reclaimed.

    Raises:
        TempSweepError: If any orphaned directory could not be removed.
    """
    result = SweepResult()
    temp_root = Path(settings.MEDIA_ROOT) / "temp"
    if not temp_root.is_dir():
        return result
    current = time.time() if now is None else now
    cutoff = current - settings.TEMP_SWEEP_MIN_AGE_SECONDS

    candidates, in_use = _candidates(temp_root)
    result.kept.extend(in_use)
    for candidate in candidates:
        _remove_if_stale(candidate, cutoff, current, result)

    if result.reclaimed_bytes > settings.TEMP_SWEEP_ALERT_BYTES:
        logger.error(
            "Temp sweep reclaimed %d bytes from %d orphaned directories under %s; "
            "workers are being killed mid-task (OOM, restarts or time limits)",
            result.reclaimed_bytes,
            len(result.removed),
            temp_root,
        )
    if result.failed:
        failed = ", ".join(str(path) for path in result.failed)
        msg = f"Temp sweep could not remove {len(result.failed)} directories: {failed}"
        raise TempSweepError(msg)
    return result
