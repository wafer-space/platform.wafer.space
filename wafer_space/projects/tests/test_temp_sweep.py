"""Tests for the MEDIA_ROOT/temp sweep of directories left by killed workers (#364)."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from django.conf import settings

from config.celery import app
from wafer_space.projects.content_pipeline import download_dir_path
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.temp_sweep import sweep_temp_dirs
from wafer_space.projects.tests.factories import ProjectFileFactory

if TYPE_CHECKING:
    from pytest_django.fixtures import Settings

PAYLOAD = b"x" * 4096


def _temp_root() -> Path:
    return Path(settings.MEDIA_ROOT) / "temp"


def _make_tree(path: Path, *, age_seconds: float) -> Path:
    """A staging directory holding one file, everything aged ``age_seconds``."""
    (path / "inner").mkdir(parents=True)
    payload = path / "inner" / "part.bin"
    payload.write_bytes(PAYLOAD)
    stamp = time.time() - age_seconds
    for item in [payload, path / "inner", path]:
        os.utime(item, (stamp, stamp))
    return path


def _stale() -> float:
    return settings.TEMP_SWEEP_MIN_AGE_SECONDS + 60


def _attempt(project_file, status: str) -> None:
    DownloadAttempt.objects.create(
        project_file=project_file, attempt_number=1, status=status
    )


def test_no_temp_directory_is_a_no_op() -> None:
    """A MEDIA_ROOT without temp/ sweeps nothing and does not create it."""
    result = sweep_temp_dirs()

    assert result.removed == []
    assert not _temp_root().exists()


def test_stale_task_directory_is_removed() -> None:
    """A task_* directory idle longer than the minimum age is removed."""
    stale = _make_tree(_temp_root() / "task_abc123", age_seconds=_stale())

    result = sweep_temp_dirs()

    assert not stale.exists()
    assert result.removed == [stale]
    assert result.reclaimed_bytes == len(PAYLOAD)


def test_task_directory_with_a_recent_file_is_kept() -> None:
    """A recent write anywhere inside keeps the directory: its task may be live."""
    task_dir = _make_tree(_temp_root() / "task_live", age_seconds=_stale())
    recent = task_dir / "inner" / "part.bin"
    now = time.time()
    os.utime(recent, (now, now))

    result = sweep_temp_dirs()

    assert task_dir.exists()
    assert result.kept == [task_dir]


def test_fresh_task_directory_is_kept() -> None:
    """A task_* directory younger than the minimum age is kept."""
    fresh = _make_tree(_temp_root() / "task_new", age_seconds=60)

    sweep_temp_dirs()

    assert fresh.exists()


@pytest.mark.django_db
def test_download_dir_of_deleted_project_file_is_removed() -> None:
    """Staging for a ProjectFile that no longer exists is removed once stale."""
    project_file = ProjectFileFactory()
    staging = _make_tree(download_dir_path(project_file.pk), age_seconds=_stale())
    project_file.delete()

    sweep_temp_dirs()

    assert not staging.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status", [DownloadAttempt.Status.PENDING, DownloadAttempt.Status.DOWNLOADING]
)
def test_download_dir_in_progress_is_kept_however_old(status: str) -> None:
    """A download running or a retry pending owns its staging: never removed."""
    project_file = ProjectFileFactory()
    _attempt(project_file, status)
    staging = _make_tree(download_dir_path(project_file.pk), age_seconds=_stale() * 10)

    result = sweep_temp_dirs()

    assert staging.exists()
    assert result.kept == [staging]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status", [DownloadAttempt.Status.COMPLETED, DownloadAttempt.Status.FAILED]
)
def test_download_dir_with_no_download_in_progress_is_removed(status: str) -> None:
    """Staging left after a finished download (worker killed in clean-up) goes."""
    project_file = ProjectFileFactory()
    _attempt(project_file, status)
    staging = _make_tree(download_dir_path(project_file.pk), age_seconds=_stale())

    sweep_temp_dirs()

    assert not staging.exists()


@pytest.mark.django_db
def test_fresh_download_dir_without_attempt_is_kept() -> None:
    """A download that has not recorded its attempt yet keeps fresh staging."""
    project_file = ProjectFileFactory()
    staging = _make_tree(download_dir_path(project_file.pk), age_seconds=60)

    sweep_temp_dirs()

    assert staging.exists()


def test_unknown_names_symlinks_and_files_are_left_alone(tmp_path: Path) -> None:
    """Only task_* and downloads/file_<id> are ever considered."""
    other = _make_tree(_temp_root() / "something_else", age_seconds=_stale())
    target = _make_tree(tmp_path / "outside", age_seconds=_stale())
    link = _temp_root() / "task_link"
    link.symlink_to(target)
    stray = _temp_root() / "downloads" / "notes.txt"
    stray.parent.mkdir(parents=True)
    stray.write_text("keep")

    sweep_temp_dirs()

    assert other.exists()
    assert link.is_symlink()
    assert target.exists()
    assert stray.exists()


def test_large_reclaim_logs_an_error(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    """Reclaiming more than the threshold in one sweep is an ERROR."""
    settings.TEMP_SWEEP_ALERT_BYTES = len(PAYLOAD) - 1
    _make_tree(_temp_root() / "task_big", age_seconds=_stale())

    with caplog.at_level(logging.INFO, logger="wafer_space.projects.temp_sweep"):
        sweep_temp_dirs()

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "workers are being killed mid-task" in errors[0].getMessage()


def test_small_reclaim_logs_each_removal_without_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every removal is logged with its size; below the threshold, no ERROR."""
    _make_tree(_temp_root() / "task_small", age_seconds=_stale())

    with caplog.at_level(logging.INFO, logger="wafer_space.projects.temp_sweep"):
        sweep_temp_dirs()

    messages = [r.getMessage() for r in caplog.records]
    assert any(f"({len(PAYLOAD)} bytes" in m for m in messages)
    assert not [r for r in caplog.records if r.levelno == logging.ERROR]


def test_min_age_exceeds_every_task_time_limit() -> None:
    """A task_* directory can only be older than the minimum age if its task died."""
    app.loader.import_default_modules()
    limits = [app.conf.task_time_limit] + [
        task.time_limit for task in app.tasks.values() if task.time_limit is not None
    ]

    assert max(limits) < settings.TEMP_SWEEP_MIN_AGE_SECONDS


def test_sweep_task_runs_on_the_rw_downloads_queue() -> None:
    """Only http:rw:downloads may delete under MEDIA_ROOT (read-only web rule)."""
    task = app.tasks["wafer_space.projects.tasks_download.sweep_orphaned_temp_dirs"]

    assert task.queue == "http:rw:downloads"


def test_sweep_task_is_scheduled_by_beat() -> None:
    """Beat runs the sweep periodically."""
    entry = settings.CELERY_BEAT_SCHEDULE["sweep-orphaned-temp-dirs"]

    assert entry["task"] == (
        "wafer_space.projects.tasks_download.sweep_orphaned_temp_dirs"
    )
    assert entry["schedule"] == settings.TEMP_SWEEP_INTERVAL_SECONDS
