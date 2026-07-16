# Admin "Duplicate Project to Another Shuttle" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin duplicate an existing project onto a different shuttle from the Django admin, copying the design file and precheck provenance and queueing a fresh manufacturability check.

**Architecture:** A service-layer function (`duplication_service.py`) performs the whole copy inside one transaction; a custom `ProjectAdmin` view (button on the change page → intermediate confirmation page) calls it. No task imports are needed — the periodic check scanner dispatches any PENDING `ManufacturabilityCheck`, and the copied file is shaped so the download recovery scanner ignores it.

**Tech Stack:** Django 5.2, pytest-django, factory-boy, uv, ruff, mypy, djlint.

**Spec:** `docs/superpowers/specs/2026-07-16-duplicate-project-shuttle-design.md` — read it before starting; it is the authority on copy semantics.

**Worktree:** `/home/tim/github/wafer-space/platform.wafer.space/.worktrees/duplicate-project-shuttle` (branch `feature/duplicate-project-to-shuttle`). Run all commands from this directory.

**Repo rules that apply to every task (from CLAUDE.md):**

- Before EVERY commit: `make lint-fix && make lint && make type-check && make test`. All must pass. No `# noqa` / `# type: ignore` ever without explicit user permission.
- Layering: the service imports models only; the admin imports the service.
- All public functions need type hints; `from __future__ import annotations` at module top.
- Ruff EM102: assign exception messages to a variable before raising.
- Templates: before committing, also run `uv run pre-commit run --files <template paths>` (djlint reformats are not covered by `make lint`).
- Shuttle test fixtures must pass explicit `name=` values (never rely on the factory sequence or the migration-seeded G801 shuttle).

---

## File map

| File | Change |
|------|--------|
| `wafer_space/projects/models.py` | Add `TriggerReason.DUPLICATED` choice (1 line) |
| `wafer_space/projects/migrations/0060_*.py` | Generated migration for the choices change |
| `wafer_space/projects/exceptions.py` | Add `ProjectDuplicationError` |
| `wafer_space/projects/services/duplication_service.py` | New: the whole copy operation |
| `wafer_space/projects/services/__init__.py` | Re-export the new service symbols |
| `wafer_space/projects/admin.py` | Form + `get_urls()` + duplicate view on `ProjectAdmin` |
| `wafer_space/templates/admin/projects/project/change_form.html` | New: object-tools button |
| `wafer_space/templates/admin/projects/project/duplicate_confirm.html` | New: confirmation page |
| `wafer_space/projects/tests/test_duplication_service.py` | New: service tests |
| `wafer_space/projects/tests/test_admin_duplicate.py` | New: admin view tests |

---

### Task 1: `TriggerReason.DUPLICATED` choice + migration

**Files:**
- Modify: `wafer_space/projects/models.py:1597-1602` (the `TriggerReason` TextChoices)
- Create: `wafer_space/projects/migrations/0060_alter_manufacturabilitycheck_trigger_reason.py` (generated)

- [ ] **Step 1: Add the choice**

In `wafer_space/projects/models.py`, extend `ManufacturabilityCheck.TriggerReason`:

```python
    class TriggerReason(models.TextChoices):
        INITIAL = "initial", "Initial Check"
        DRC_UPDATE = "drc_update", "DRC Rules Updated"
        ADMIN_RERUN = "admin_rerun", "Admin Requested Re-run"
        RETRY = "retry", "Retry After Error"
        COB_CHANGE = "cob_change", "Chip-on-Board Option Changed"
        DUPLICATED = "duplicated", "Project Duplicated"
```

- [ ] **Step 2: Generate the migration**

Run: `uv run python manage.py makemigrations projects`
Expected: creates `0060_alter_manufacturabilitycheck_trigger_reason.py` (an `AlterField` on `trigger_reason` and its historical twin if simple_history tracks it). Inspect the file — it must contain only trigger_reason `AlterField` operations.

- [ ] **Step 3: Apply and verify**

Run: `uv run python manage.py migrate projects`
Expected: `OK`.

- [ ] **Step 4: Pre-commit checks and commit**

Run: `make lint-fix && make lint && make type-check && make test`
Expected: all pass (note: `test_tos_version_displayed` is a known flaky browser test — re-run once before blaming this change).

```bash
git add wafer_space/projects/models.py wafer_space/projects/migrations/0060_*.py
git commit -m "feat(projects): add DUPLICATED manufacturability-check trigger reason"
```

---

### Task 2: `ProjectDuplicationError`

**Files:**
- Modify: `wafer_space/projects/exceptions.py` (append)

- [ ] **Step 1: Add the exception**

Append to `wafer_space/projects/exceptions.py` (match the existing docstring style):

```python
class ProjectDuplicationError(Exception):
    """Raised when duplicating a project onto another shuttle fails.

    The message is user-facing: the admin view shows it verbatim via
    the messages framework.
    """
```

- [ ] **Step 2: Pre-commit checks and commit**

Run: `make lint-fix && make lint && make type-check && make test`

```bash
git add wafer_space/projects/exceptions.py
git commit -m "feat(projects): add ProjectDuplicationError exception"
```

---

### Task 3: Service — validation rules (TDD)

**Files:**
- Create: `wafer_space/projects/services/duplication_service.py`
- Create: `wafer_space/projects/tests/test_duplication_service.py`

- [ ] **Step 1: Write the test file with a source-project helper and validation tests**

Create `wafer_space/projects/tests/test_duplication_service.py`:

```python
"""Tests for the project duplication service."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.db.models import Q
from django.test import TestCase
from django.utils import timezone

from wafer_space.projects.exceptions import ProjectDuplicationError
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.services import duplicate_project_to_shuttle
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.models import User

from .constants import TEST_PASSWORD
from .factories import ProjectFactory
from .factories import ProjectFileFactory

GDS_BYTES = b"fake-gds-content-for-duplication-tests"


def make_shuttle(name: str, status: str = Shuttle.Status.OPEN) -> Shuttle:
    """Create a shuttle with an explicit name (never rely on G801)."""
    return Shuttle.objects.create(
        name=name,
        description=f"Test shuttle {name}",
        status=status,
    )


def make_source_project(
    *,
    shuttle: Shuttle,
    project_id: str = "ABCD",
    with_file: bool = True,
    with_finished_check: bool = True,
) -> Project:
    """Create a fully 'manufactured' source project on the given shuttle."""
    project = ProjectFactory(
        shuttle=shuttle,
        project_id=project_id,
        status=Project.Status.SUBMITTED,
        crowd_supply_order_id="327373",
        repository_url="https://example.com/repo",
    )
    if not with_file:
        return project

    project_file = ProjectFileFactory(
        project=project,
        is_active=True,
        original_filename="design.gds",
        hash_verified=True,
        hash_sha256="a" * 64,
        top_cell="top",
        download_task_id="celery-task-original",
    )
    project_file.file.save("design.gds", ContentFile(GDS_BYTES), save=True)
    DownloadAttempt.objects.create(
        project_file=project_file,
        attempt_number=1,
        status=DownloadAttempt.Status.COMPLETED,
        completed_at=timezone.now(),
        download_started_at=timezone.now(),
        download_completed_at=timezone.now(),
        download_duration_seconds=1.5,
        bytes_downloaded=len(GDS_BYTES),
    )
    if with_finished_check:
        ManufacturabilityCheck.objects.create(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
            warnings=["minor spacing"],
            docker_image_digest="sha256:" + "b" * 64,
            precheck_version="v1.2.3",
            log_file_sha256="c" * 64,
        )
    return project


@pytest.mark.django_db
class TestDuplicationValidation(TestCase):
    """Validation failures raise ProjectDuplicationError and create nothing."""

    def setUp(self) -> None:
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=TEST_PASSWORD,
        )
        self.source_shuttle = make_shuttle("G890")
        self.target_shuttle = make_shuttle("G891")

    def assert_fails(self, project: Project, target: Shuttle, match: str) -> None:
        projects_before = Project.objects.count()
        files_before = ProjectFile.objects.count()
        checks_before = ManufacturabilityCheck.objects.count()
        with pytest.raises(ProjectDuplicationError, match=match):
            duplicate_project_to_shuttle(
                project=project,
                target_shuttle=target,
                admin_user=self.admin_user,
            )
        assert Project.objects.count() == projects_before
        assert ProjectFile.objects.count() == files_before
        assert ManufacturabilityCheck.objects.count() == checks_before

    def test_source_without_shuttle_fails(self) -> None:
        project = ProjectFactory(shuttle=None)
        self.assert_fails(project, self.target_shuttle, "not assigned to a shuttle")

    def test_same_shuttle_fails(self) -> None:
        project = make_source_project(shuttle=self.source_shuttle)
        self.assert_fails(project, self.source_shuttle, "same shuttle")

    def test_ineligible_target_status_fails(self) -> None:
        project = make_source_project(shuttle=self.source_shuttle)
        for status in (
            Shuttle.Status.IN_PRODUCTION,
            Shuttle.Status.COMPLETED,
            Shuttle.Status.CANCELLED,
        ):
            self.target_shuttle.status = status
            self.target_shuttle.save()
            self.assert_fails(project, self.target_shuttle, "cannot accept")

    def test_project_id_collision_fails(self) -> None:
        project = make_source_project(shuttle=self.source_shuttle)
        ProjectFactory(shuttle=self.target_shuttle, project_id="ABCD")
        self.assert_fails(project, self.target_shuttle, "already used")

    def test_no_active_file_fails(self) -> None:
        project = make_source_project(shuttle=self.source_shuttle, with_file=False)
        self.assert_fails(project, self.target_shuttle, "active file")

    def test_incomplete_download_fails(self) -> None:
        project = make_source_project(shuttle=self.source_shuttle)
        attempt = DownloadAttempt.objects.get(
            project_file__project=project,
        )
        attempt.status = DownloadAttempt.Status.FAILED
        attempt.save()
        self.assert_fails(project, self.target_shuttle, "download")
```

- [ ] **Step 2: Run tests to verify they fail on import**

Run: `uv run pytest wafer_space/projects/tests/test_duplication_service.py -v`
Expected: collection error — `duplicate_project_to_shuttle` not importable.

- [ ] **Step 3: Write the service module with validation only**

Create `wafer_space/projects/services/duplication_service.py`:

```python
"""Duplicate a project from one shuttle onto another.

Admin-triggered operation: copies the project metadata, the active
design file (bytes included), and the latest FINISHED manufacturability
check as provenance, then queues a fresh check. See the design spec:
docs/superpowers/specs/2026-07-16-duplicate-project-shuttle-design.md
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from wafer_space.projects.exceptions import ProjectDuplicationError
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.shuttles.models import Shuttle

if TYPE_CHECKING:
    from wafer_space.users.models import User

logger = logging.getLogger(__name__)

# Shuttles a project may be duplicated onto. Runs that are already in
# production (or beyond) never accept new projects.
ELIGIBLE_TARGET_SHUTTLE_STATUSES = (
    Shuttle.Status.PLANNING,
    Shuttle.Status.OPEN,
    Shuttle.Status.FULL,
    Shuttle.Status.LOCKED,
)


def duplicate_project_to_shuttle(
    *,
    project: Project,
    target_shuttle: Shuttle,
    admin_user: User,
) -> Project:
    """Duplicate ``project`` onto ``target_shuttle``.

    Returns the new DRAFT project. Raises ProjectDuplicationError with a
    user-facing message when validation fails; nothing is created in that
    case.
    """
    _validate_duplication(project, target_shuttle)
    raise NotImplementedError


def _validate_duplication(project: Project, target_shuttle: Shuttle) -> ProjectFile:
    """Validate the duplication request, returning the source's active file."""
    if project.shuttle_id is None:
        msg = "Source project is not assigned to a shuttle."
        raise ProjectDuplicationError(msg)

    if project.shuttle_id == target_shuttle.pk:
        msg = "Target shuttle is the same shuttle the project is already on."
        raise ProjectDuplicationError(msg)

    if target_shuttle.status not in ELIGIBLE_TARGET_SHUTTLE_STATUSES:
        msg = (
            f"Shuttle {target_shuttle.name} cannot accept duplicated projects "
            f"(status: {target_shuttle.get_status_display()})."
        )
        raise ProjectDuplicationError(msg)

    collision = Project.objects.filter(
        shuttle=target_shuttle,
        project_id=project.project_id,
    ).exists()
    if collision:
        msg = (
            f"Project ID {project.project_id!r} is already used on shuttle "
            f"{target_shuttle.name}."
        )
        raise ProjectDuplicationError(msg)

    try:
        source_file = project.files.get(is_active=True)
    except ProjectFile.DoesNotExist as exc:
        msg = "Source project has no active file."
        raise ProjectDuplicationError(msg) from exc

    if source_file.download_status != ProjectFile.DownloadStatus.COMPLETED:
        msg = (
            "Source project's file download is not completed "
            f"(status: {source_file.get_download_status_display()})."
        )
        raise ProjectDuplicationError(msg)

    if not source_file.file:
        msg = "Source project's file has no stored content."
        raise ProjectDuplicationError(msg)

    return source_file
```

Note: `download_status` on `ProjectFile` is a derived property; check how
`get_download_status_display` exists — if the property has no
`get_..._display` companion, format the raw value instead (verify in
`wafer_space/projects/models.py` around line 1061 and adjust — the tests
assert only on the word "download").

- [ ] **Step 4: Export from the services package**

In `wafer_space/projects/services/__init__.py`, add (alphabetical order with the existing imports and `__all__` entries):

```python
from .duplication_service import ELIGIBLE_TARGET_SHUTTLE_STATUSES
from .duplication_service import duplicate_project_to_shuttle
```

and add `"ELIGIBLE_TARGET_SHUTTLE_STATUSES"` and `"duplicate_project_to_shuttle"` to `__all__`.

- [ ] **Step 5: Run the validation tests**

Run: `uv run pytest wafer_space/projects/tests/test_duplication_service.py -v`
Expected: all `TestDuplicationValidation` tests PASS (the happy path isn't tested yet; `NotImplementedError` is fine because no test reaches it).

- [ ] **Step 6: Pre-commit checks and commit**

Run: `make lint-fix && make lint && make type-check && make test`

```bash
git add wafer_space/projects/services/duplication_service.py \
        wafer_space/projects/services/__init__.py \
        wafer_space/projects/tests/test_duplication_service.py
git commit -m "feat(projects): duplication service validation rules"
```

---

### Task 4: Service — the copy itself (TDD)

**Files:**
- Modify: `wafer_space/projects/services/duplication_service.py`
- Modify: `wafer_space/projects/tests/test_duplication_service.py` (append)

- [ ] **Step 1: Write the happy-path tests**

Append to `test_duplication_service.py`:

```python
@pytest.mark.django_db
class TestDuplicationCopy(TestCase):
    """Happy-path duplication copies exactly what the spec says."""

    def setUp(self) -> None:
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=TEST_PASSWORD,
        )
        self.source_shuttle = make_shuttle("G890")
        self.target_shuttle = make_shuttle("G891")
        self.source = make_source_project(shuttle=self.source_shuttle)
        self.duplicate = duplicate_project_to_shuttle(
            project=self.source,
            target_shuttle=self.target_shuttle,
            admin_user=self.admin_user,
        )

    def test_project_metadata_copied(self) -> None:
        assert self.duplicate.pk != self.source.pk
        assert self.duplicate.user == self.source.user
        assert self.duplicate.name == self.source.name
        assert self.duplicate.description == self.source.description
        assert self.duplicate.slot_size == self.source.slot_size
        assert self.duplicate.is_public == self.source.is_public
        assert self.duplicate.chip_on_board == self.source.chip_on_board
        assert self.duplicate.repository_url == self.source.repository_url
        assert self.duplicate.license_type == self.source.license_type

    def test_project_fresh_fields(self) -> None:
        assert self.duplicate.shuttle == self.target_shuttle
        assert self.duplicate.project_id == self.source.project_id
        assert self.duplicate.status == Project.Status.DRAFT
        assert self.duplicate.submitted_at is None
        assert self.duplicate.submitted_file is None
        assert self.duplicate.crowd_supply_order_id == ""

    def test_source_untouched(self) -> None:
        self.source.refresh_from_db()
        assert self.source.shuttle == self.source_shuttle
        assert self.source.status == Project.Status.SUBMITTED

    def test_file_bytes_copied_to_new_path(self) -> None:
        new_file = self.duplicate.files.get(is_active=True)
        source_file = self.source.files.get(is_active=True)
        assert new_file.file.name != source_file.file.name
        with new_file.file.open("rb") as handle:
            assert handle.read() == GDS_BYTES

    def test_file_metadata_copied(self) -> None:
        new_file = self.duplicate.files.get(is_active=True)
        source_file = self.source.files.get(is_active=True)
        assert new_file.hash_sha256 == source_file.hash_sha256
        assert new_file.hash_verified is True
        assert new_file.original_filename == source_file.original_filename
        assert new_file.top_cell == source_file.top_cell
        assert new_file.replaced_by is None

    def test_file_invisible_to_download_recovery_scanner(self) -> None:
        """Replicates the querysets in ensure_download_tasks_queued."""
        new_file = self.duplicate.files.get(is_active=True)
        assert new_file.download_task_id.startswith("duplicated:")
        assert new_file.download_status == ProjectFile.DownloadStatus.COMPLETED

        pending = ProjectFile.objects.filter(is_active=True).filter(
            Q(download_task_id="") | Q(download_task_id__isnull=True),
        )
        assert new_file not in pending

        queued = (
            ProjectFile.objects.filter(is_active=True)
            .exclude(
                Q(download_task_id="") | Q(download_task_id__isnull=True),
            )
            .exclude(
                download_attempts__status__in=[
                    DownloadAttempt.Status.DOWNLOADING,
                    DownloadAttempt.Status.COMPLETED,
                    DownloadAttempt.Status.FAILED,
                ],
            )
        )
        assert new_file not in queued

    def test_download_attempt_copied(self) -> None:
        new_file = self.duplicate.files.get(is_active=True)
        attempt = new_file.download_attempts.get()
        assert attempt.status == DownloadAttempt.Status.COMPLETED
        assert attempt.attempt_number == 1
        assert attempt.bytes_downloaded == len(GDS_BYTES)

    def test_provenance_check_copied(self) -> None:
        new_file = self.duplicate.files.get(is_active=True)
        provenance = new_file.manufacturability_checks.get(
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        assert provenance.is_manufacturable is True
        assert provenance.warnings == ["minor spacing"]
        assert provenance.precheck_version == "v1.2.3"
        assert provenance.log_file_sha256 == "c" * 64
        assert not provenance.log_file
        assert not provenance.runs_archive
        assert not provenance.output_gds
        assert not provenance.docker_layer_export
        assert provenance.parent_check is None

    def test_fresh_check_queued(self) -> None:
        new_file = self.duplicate.files.get(is_active=True)
        fresh = new_file.manufacturability_checks.get(
            status=ManufacturabilityCheck.Status.PENDING,
        )
        assert (
            fresh.trigger_reason == ManufacturabilityCheck.TriggerReason.DUPLICATED
        )
        assert fresh.parent_check is not None
        assert fresh.parent_check.status == ManufacturabilityCheck.Status.FINISHED


@pytest.mark.django_db
class TestDuplicationCheckSelection(TestCase):
    """Provenance uses the latest FINISHED check; non-terminal never copied."""

    def setUp(self) -> None:
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=TEST_PASSWORD,
        )
        self.source_shuttle = make_shuttle("G890")
        self.target_shuttle = make_shuttle("G891")

    def test_newer_pending_check_is_ignored(self) -> None:
        source = make_source_project(shuttle=self.source_shuttle)
        source_file = source.files.get(is_active=True)
        ManufacturabilityCheck.objects.create(
            project=source,
            project_file=source_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        duplicate = duplicate_project_to_shuttle(
            project=source,
            target_shuttle=self.target_shuttle,
            admin_user=self.admin_user,
        )
        new_file = duplicate.files.get(is_active=True)
        finished = new_file.manufacturability_checks.filter(
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        assert finished.count() == 1
        assert finished.get().precheck_version == "v1.2.3"
        # Exactly one PENDING check: the fresh DUPLICATED one, not a copy
        # of the source's pending check.
        pending = new_file.manufacturability_checks.filter(
            status=ManufacturabilityCheck.Status.PENDING,
        )
        assert pending.count() == 1
        assert (
            pending.get().trigger_reason
            == ManufacturabilityCheck.TriggerReason.DUPLICATED
        )

    def test_no_finished_check_skips_provenance(self) -> None:
        source = make_source_project(
            shuttle=self.source_shuttle,
            with_finished_check=False,
        )
        duplicate = duplicate_project_to_shuttle(
            project=source,
            target_shuttle=self.target_shuttle,
            admin_user=self.admin_user,
        )
        new_file = duplicate.files.get(is_active=True)
        checks = new_file.manufacturability_checks.all()
        assert checks.count() == 1
        fresh = checks.get()
        assert fresh.status == ManufacturabilityCheck.Status.PENDING
        assert fresh.parent_check is None
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_duplication_service.py -v`
Expected: new tests FAIL with `NotImplementedError`; validation tests still PASS.

- [ ] **Step 3: Implement the copy**

In `duplication_service.py`, add imports:

```python
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.core.files.base import File
from django.db import IntegrityError
from django.db import transaction

from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
```

Replace the `raise NotImplementedError` body of `duplicate_project_to_shuttle` with:

```python
    source_file = _validate_duplication(project, target_shuttle)
    try:
        with transaction.atomic():
            new_project = _copy_project(project, target_shuttle)
            new_file = _copy_file(source_file, new_project)
            provenance = _copy_provenance_check(source_file, new_project, new_file)
            ManufacturabilityCheck.objects.create(
                project=new_project,
                project_file=new_file,
                trigger_reason=ManufacturabilityCheck.TriggerReason.DUPLICATED,
                parent_check=provenance,
            )
    except (IntegrityError, ValidationError) as exc:
        msg = f"Duplication failed while saving: {exc}"
        raise ProjectDuplicationError(msg) from exc

    logger.info(
        "Project %s duplicated to %s as %s by %s",
        project.pk,
        target_shuttle.name,
        new_project.pk,
        admin_user,
    )
    return new_project
```

Add the three helpers:

```python
def _copy_project(project: Project, target_shuttle: Shuttle) -> Project:
    """Create the duplicate Project row (crowd_supply_order_id NOT copied)."""
    new_project = Project(
        user=project.user,
        name=project.name,
        description=project.description,
        slot_size=project.slot_size,
        is_public=project.is_public,
        chip_on_board=project.chip_on_board,
        repository_url=project.repository_url,
        license_type=project.license_type,
        other_license_spdx_id=project.other_license_spdx_id,
        proprietary_terms_url=project.proprietary_terms_url,
        proprietary_terms_cached=project.proprietary_terms_cached,
        proprietary_terms_cached_at=project.proprietary_terms_cached_at,
        shuttle=target_shuttle,
        project_id=project.project_id,
        status=Project.Status.DRAFT,
    )
    new_project.save()
    return new_project


def _copy_file(source_file: ProjectFile, new_project: Project) -> ProjectFile:
    """Copy the active file, shaped so recovery scanners ignore it.

    The COMPLETED DownloadAttempt copy makes the derived download_status
    COMPLETED; the sentinel download_task_id keeps the file out of the
    recovery scanner's "pending" queryset.
    """
    new_file = ProjectFile(
        project=new_project,
        file_type=source_file.file_type,
        original_url=source_file.original_url,
        source_url=source_file.source_url,
        expected_hash_md5=source_file.expected_hash_md5,
        expected_hash_sha1=source_file.expected_hash_sha1,
        expected_hash_sha256=source_file.expected_hash_sha256,
        hash_md5=source_file.hash_md5,
        hash_sha1=source_file.hash_sha1,
        hash_sha256=source_file.hash_sha256,
        hash_verified=source_file.hash_verified,
        handler_metadata=source_file.handler_metadata,
        file_size=source_file.file_size,
        original_filename=source_file.original_filename,
        processed_filename=source_file.processed_filename,
        top_cell=source_file.top_cell,
        content_type=source_file.content_type,
        download_started_at=source_file.download_started_at,
        download_completed_at=source_file.download_completed_at,
        download_task_id=f"duplicated:{source_file.pk}",
        is_active=True,
    )
    with source_file.file.open("rb") as source_handle:
        new_file.file.save(
            PurePosixPath(source_file.file.name).name,
            File(source_handle),
            save=False,
        )
    new_file.save()

    # Newest attempt; COMPLETED per validation. The None guard exists for
    # mypy (first() is typed Optional) and for races where attempts were
    # deleted between validation and here.
    source_attempt = source_file.download_attempts.first()
    if source_attempt is None:
        msg = "Source file has no download attempt to copy."
        raise ProjectDuplicationError(msg)
    DownloadAttempt.objects.create(
        project_file=new_file,
        attempt_number=1,
        status=DownloadAttempt.Status.COMPLETED,
        completed_at=source_attempt.completed_at,
        download_started_at=source_attempt.download_started_at,
        download_completed_at=source_attempt.download_completed_at,
        download_duration_seconds=source_attempt.download_duration_seconds,
        bytes_downloaded=source_attempt.bytes_downloaded,
    )
    return new_file


def _copy_provenance_check(
    source_file: ProjectFile,
    new_project: Project,
    new_file: ProjectFile,
) -> ManufacturabilityCheck | None:
    """Copy the latest FINISHED check as an inert provenance record.

    Only FINISHED checks are copied: a copied PENDING row would be
    dispatched as a real run by the periodic check scanner, and copied
    active states would reference Docker containers that don't exist.
    Artifact FileFields stay empty (no storage sharing); their SHA-256
    fields are kept as a record of what the original run produced.
    """
    source_check = (
        source_file.manufacturability_checks.filter(
            status=ManufacturabilityCheck.Status.FINISHED,
        )
        .order_by("-created_at")
        .first()
    )
    if source_check is None:
        return None
    return ManufacturabilityCheck.objects.create(
        project=new_project,
        project_file=new_file,
        status=ManufacturabilityCheck.Status.FINISHED,
        trigger_reason=source_check.trigger_reason,
        docker_server_id=source_check.docker_server_id,
        docker_container_id=source_check.docker_container_id,
        dispatching_started_at=source_check.dispatching_started_at,
        starting_started_at=source_check.starting_started_at,
        container_started_at=source_check.container_started_at,
        container_finished_at=source_check.container_finished_at,
        analysis_completed_at=source_check.analysis_completed_at,
        docker_exit_code=source_check.docker_exit_code,
        is_manufacturable=source_check.is_manufacturable,
        errors=source_check.errors,
        warnings=source_check.warnings,
        processing_logs=source_check.processing_logs,
        log_file_sha256=source_check.log_file_sha256,
        runs_archive_sha256=source_check.runs_archive_sha256,
        output_gds_sha256=source_check.output_gds_sha256,
        docker_layer_sha256=source_check.docker_layer_sha256,
        error_message=source_check.error_message,
        docker_image=source_check.docker_image,
        docker_image_digest=source_check.docker_image_digest,
        docker_command=source_check.docker_command,
        tool_versions=source_check.tool_versions,
        precheck_version=source_check.precheck_version,
        rerun_reason=source_check.rerun_reason,
    )
```

Field-name caution: this kwargs list was transcribed from
`wafer_space/projects/models.py:1700-1920`. Before running, re-check the
model for exact field names (e.g. `logs_downloaded_until` was deliberately
left at its default) — a typo fails loudly with `TypeError`, which is fine.

- [ ] **Step 4: Run the service tests**

Run: `uv run pytest wafer_space/projects/tests/test_duplication_service.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Add the atomicity test and run it**

Append to `test_duplication_service.py`:

```python
@pytest.mark.django_db
class TestDuplicationAtomicity(TestCase):
    """A failure mid-copy rolls back everything."""

    def test_integrityerror_rolls_back_and_becomes_duplication_error(self) -> None:
        admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=TEST_PASSWORD,
        )
        source_shuttle = make_shuttle("G890")
        target_shuttle = make_shuttle("G891")
        source = make_source_project(shuttle=source_shuttle)
        projects_before = Project.objects.count()
        files_before = ProjectFile.objects.count()

        with (
            patch(
                "wafer_space.projects.services.duplication_service."
                "_copy_provenance_check",
                side_effect=IntegrityError("boom"),
            ),
            pytest.raises(ProjectDuplicationError, match="boom"),
        ):
            duplicate_project_to_shuttle(
                project=source,
                target_shuttle=target_shuttle,
                admin_user=admin_user,
            )

        assert Project.objects.count() == projects_before
        assert ProjectFile.objects.count() == files_before
```

Run: `uv run pytest wafer_space/projects/tests/test_duplication_service.py -v`
Expected: ALL PASS.

- [ ] **Step 6: Pre-commit checks and commit**

Run: `make lint-fix && make lint && make type-check && make test`

```bash
git add wafer_space/projects/services/duplication_service.py \
        wafer_space/projects/tests/test_duplication_service.py
git commit -m "feat(projects): implement project duplication service"
```

---

### Task 5: Admin form, view, and URL (TDD)

**Files:**
- Modify: `wafer_space/projects/admin.py`
- Create: `wafer_space/projects/tests/test_admin_duplicate.py`

- [ ] **Step 1: Write the admin view tests**

Create `wafer_space/projects/tests/test_admin_duplicate.py`:

```python
"""Tests for the admin duplicate-to-shuttle view."""

from __future__ import annotations

import pytest
from django.contrib.admin.models import ADDITION
from django.contrib.admin.models import CHANGE
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from wafer_space.projects.models import Project
from wafer_space.shuttles.models import Shuttle

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_NOT_FOUND
from .constants import HTTP_OK
from .constants import TEST_PASSWORD
from .factories import ProjectFactory
from .test_duplication_service import make_shuttle
from .test_duplication_service import make_source_project

User = get_user_model()
```

(Check `wafer_space/projects/tests/constants.py` first — it already defines
`TEST_PASSWORD` and the `HTTP_*` codes; import exactly the names that exist
there and define any missing one locally as a module constant.)

```python


@pytest.mark.django_db
class TestAdminDuplicateView(TestCase):
    """The duplicate view: permissions, form, POST behaviour."""

    def setUp(self) -> None:
        self.superuser = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=TEST_PASSWORD,
        )
        self.client.force_login(self.superuser)
        self.source_shuttle = make_shuttle("G890")
        self.target_shuttle = make_shuttle("G891")
        self.production_shuttle = make_shuttle(
            "G892",
            status=Shuttle.Status.IN_PRODUCTION,
        )
        self.project = make_source_project(shuttle=self.source_shuttle)
        self.url = reverse(
            "admin:projects_project_duplicate",
            args=[self.project.pk],
        )

    def test_button_on_change_page(self) -> None:
        change_url = reverse(
            "admin:projects_project_change",
            args=[self.project.pk],
        )
        response = self.client.get(change_url)
        assert response.status_code == HTTP_OK
        self.assertContains(response, self.url)

    def test_get_shows_eligible_shuttles_only(self) -> None:
        response = self.client.get(self.url)
        assert response.status_code == HTTP_OK
        self.assertContains(response, self.target_shuttle.name)
        self.assertNotContains(response, self.production_shuttle.name)
        # Source shuttle is not offered as a target
        form = response.context["form"]
        assert self.source_shuttle not in form.fields["target_shuttle"].queryset

    def test_post_duplicates_and_redirects(self) -> None:
        response = self.client.post(
            self.url,
            {"target_shuttle": self.target_shuttle.pk},
        )
        duplicate = Project.objects.get(shuttle=self.target_shuttle)
        assert response.status_code == HTTP_FOUND
        assert response.url == reverse(
            "admin:projects_project_change",
            args=[duplicate.pk],
        )
        assert duplicate.status == Project.Status.DRAFT
        assert LogEntry.objects.filter(
            action_flag=ADDITION,
            object_id=str(duplicate.pk),
        ).exists()
        assert LogEntry.objects.filter(
            action_flag=CHANGE,
            object_id=str(self.project.pk),
        ).exists()

    def test_post_collision_shows_error(self) -> None:
        ProjectFactory(
            shuttle=self.target_shuttle,
            project_id=self.project.project_id,
        )
        response = self.client.post(
            self.url,
            {"target_shuttle": self.target_shuttle.pk},
        )
        assert response.status_code == HTTP_OK
        messages = [str(m) for m in response.context["messages"]]
        assert any("already used" in m for m in messages)

    def test_staff_without_add_permission_forbidden(self) -> None:
        staff = User.objects.create_user(
            username="staffer",
            email="staffer@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        self.client.force_login(staff)
        response = self.client.get(self.url)
        assert response.status_code == HTTP_FORBIDDEN

    def test_unknown_project_404(self) -> None:
        url = reverse(
            "admin:projects_project_duplicate",
            args=["00000000-0000-0000-0000-000000000000"],
        )
        response = self.client.get(url)
        # Django admin redirects unknown objects to the index with a message
        assert response.status_code in (HTTP_FOUND, HTTP_NOT_FOUND)
```

Note: `test_button_on_change_page` will fail until Task 6 adds the template;
that is expected — implement view + URL first, template second. Run only the
other tests in this task (use `-k "not button"`).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest wafer_space/projects/tests/test_admin_duplicate.py -v -k "not button"`
Expected: FAIL — `NoReverseMatch` for `projects_project_duplicate`.

- [ ] **Step 3: Implement form + view + URL in `admin.py`**

Add imports to `wafer_space/projects/admin.py` (keep one-per-line style):

```python
from typing import Any

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from django.urls import reverse

from wafer_space.projects.exceptions import ProjectDuplicationError
from wafer_space.projects.services import ELIGIBLE_TARGET_SHUTTLE_STATUSES
from wafer_space.projects.services import duplicate_project_to_shuttle
from wafer_space.shuttles.models import Shuttle
```

Add the form (above `ProjectAdmin`):

```python
class DuplicateProjectForm(forms.Form):
    """Pick the shuttle to duplicate a project onto."""

    target_shuttle = forms.ModelChoiceField(
        queryset=Shuttle.objects.none(),
        label="Target shuttle",
        help_text="The duplicate is created as a draft on this shuttle.",
    )

    def __init__(
        self,
        *args: Any,
        source_shuttle: Shuttle | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        queryset = Shuttle.objects.filter(
            status__in=ELIGIBLE_TARGET_SHUTTLE_STATUSES,
        ).order_by("name")
        if source_shuttle is not None:
            queryset = queryset.exclude(pk=source_shuttle.pk)
        self.fields["target_shuttle"].queryset = queryset
```

Extend `ProjectAdmin`:

```python
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<uuid:object_id>/duplicate/",
                self.admin_site.admin_view(self.duplicate_view),
                name="projects_project_duplicate",
            ),
        ]
        return custom_urls + urls

    def duplicate_view(
        self,
        request: HttpRequest,
        object_id: object,
    ) -> HttpResponse:
        """Intermediate page: pick a target shuttle, then duplicate."""
        project = self.get_object(request, str(object_id))
        if project is None:
            return self._get_obj_does_not_exist_redirect(
                request,
                self.opts,
                str(object_id),
            )
        if not self.has_add_permission(request):
            raise PermissionDenied

        form = DuplicateProjectForm(
            request.POST if request.method == "POST" else None,
            source_shuttle=project.shuttle,
        )
        if request.method == "POST" and form.is_valid():
            target_shuttle = form.cleaned_data["target_shuttle"]
            try:
                duplicate = duplicate_project_to_shuttle(
                    project=project,
                    target_shuttle=target_shuttle,
                    admin_user=request.user,
                )
            except ProjectDuplicationError as exc:
                messages.error(request, str(exc))
            else:
                self.log_addition(
                    request,
                    duplicate,
                    f"Duplicated from project {project.pk} "
                    f"(shuttle {project.shuttle.name})",
                )
                self.log_change(
                    request,
                    project,
                    f"Duplicated to shuttle {target_shuttle.name} "
                    f"as project {duplicate.pk}",
                )
                messages.success(
                    request,
                    f"Project duplicated onto shuttle {target_shuttle.name}. "
                    "A fresh manufacturability check has been queued.",
                )
                return redirect(
                    reverse(
                        "admin:projects_project_change",
                        args=[duplicate.pk],
                    ),
                )

        source_file = project.files.filter(is_active=True).first()
        context = {
            **self.admin_site.each_context(request),
            "title": f"Duplicate {project.name}",
            "opts": self.opts,
            "project": project,
            "source_file": source_file,
            "form": form,
        }
        return TemplateResponse(
            request,
            "admin/projects/project/duplicate_confirm.html",
            context,
        )
```

Implementation notes:
- `self.opts` is the public alias for the model's `_meta` on `ModelAdmin` — do not use `self.model._meta` (SLF001).
- `_get_obj_does_not_exist_redirect` is the standard `ModelAdmin` helper other admin views use for missing objects; if mypy/ruff rejects the private call, replace with `raise Http404` (`from django.http import Http404`) — the test accepts either.
- No `change_form_template` attribute is needed: Django automatically picks up `admin/projects/project/change_form.html` (created in Task 6) by template-name convention.

- [ ] **Step 4: Run the view tests**

Run: `uv run pytest wafer_space/projects/tests/test_admin_duplicate.py -v -k "not button"`
Expected: PASS (all except the excluded button test).

- [ ] **Step 5: Proceed directly to Task 6 — Tasks 5 and 6 are committed together**

`make test` runs the whole suite including `test_button_on_change_page`,
which needs the Task 6 template. Do NOT commit yet; the single commit for
both tasks happens at the end of Task 6.

---

### Task 6: Admin templates

**Files:**
- Create: `wafer_space/templates/admin/projects/project/change_form.html`
- Create: `wafer_space/templates/admin/projects/project/duplicate_confirm.html`

- [ ] **Step 1: Create the change-form override (button)**

`wafer_space/templates/admin/projects/project/change_form.html`:

```django
{% extends "admin/change_form.html" %}

{% block object-tools-items %}
    {% if original and has_add_permission %}
        <li>
            <a href="{% url 'admin:projects_project_duplicate' original.pk %}">
                Duplicate to another shuttle…
            </a>
        </li>
    {% endif %}
    {{ block.super }}
{% endblock object-tools-items %}
```

- [ ] **Step 2: Create the confirmation page**

`wafer_space/templates/admin/projects/project/duplicate_confirm.html`:

```django
{% extends "admin/base_site.html" %}

{% block content %}
    <h1>Duplicate “{{ project.name }}” to another shuttle</h1>

    <p>This creates a new <strong>draft</strong> project owned by
        <strong>{{ project.user }}</strong> with the same design file and a
        fresh manufacturability check. The original project is not changed.</p>

    <table>
        <tr>
            <th scope="row">Source shuttle</th>
            <td>{{ project.shuttle.name }}</td>
        </tr>
        <tr>
            <th scope="row">Project ID (kept on the new shuttle)</th>
            <td>{{ project.project_id }}</td>
        </tr>
        <tr>
            <th scope="row">Design file</th>
            <td>{{ source_file.original_filename|default:"—" }}</td>
        </tr>
        <tr>
            <th scope="row">Latest check result</th>
            <td>{{ source_file.output_check.get_status_display|default:"—" }}</td>
        </tr>
        <tr>
            <th scope="row">Not copied</th>
            <td>CrowdSupply order ID, slot assignment, submission state</td>
        </tr>
    </table>

    <form method="post">
        {% csrf_token %}
        {{ form.as_p }}
        <input type="submit" value="Duplicate project">
        <a href="{% url 'admin:projects_project_change' project.pk %}">Cancel</a>
    </form>
{% endblock content %}
```

- [ ] **Step 3: Run the full admin test file (button test included)**

Run: `uv run pytest wafer_space/projects/tests/test_admin_duplicate.py -v`
Expected: ALL PASS.

- [ ] **Step 4: Run djlint pre-commit on the templates**

Run:

```bash
uv run pre-commit run --files \
    wafer_space/templates/admin/projects/project/change_form.html \
    wafer_space/templates/admin/projects/project/duplicate_confirm.html
```

Expected: passes (djlint may reformat; if it does, re-run until clean and keep the reformatted files).

- [ ] **Step 5: Pre-commit checks and commit**

Run: `make lint-fix && make lint && make type-check && make test`

```bash
git add wafer_space/projects/admin.py \
        wafer_space/projects/tests/test_admin_duplicate.py \
        wafer_space/templates/admin/projects/project/
git commit -m "feat(admin): duplicate project to another shuttle"
```

(This commit covers Tasks 5 and 6 together — view, form, URL, and templates.)

---

### Task 7: Final verification

- [ ] **Step 1: Full quality gate**

Run: `make check-all`
Expected: lint, type-check, template lint, and the full test suite all pass.

- [ ] **Step 2: Verify against the spec**

Re-read `docs/superpowers/specs/2026-07-16-duplicate-project-shuttle-design.md` section by section and confirm each behaviour is implemented and tested. REQUIRED SUB-SKILL for the claim of completion: superpowers:verification-before-completion.

- [ ] **Step 3: Exercise the flow end-to-end (manual smoke via dev server)**

Run: `make runserver` (port 8081), then in the admin:
1. Open an existing project's admin change page — the "Duplicate to another shuttle…" button appears in object-tools.
2. Click it, pick a target shuttle, submit.
3. Confirm redirect to the new draft project; its Files section shows the copied file; its checks list shows one FINISHED provenance check (no artifacts) and one PENDING check with reason "Project Duplicated".

(If no suitable local data exists, `uv run python manage.py populate_dev_data` seeds projects/shuttles first.)

- [ ] **Step 4: Commit any remaining changes and stop**

Use superpowers:finishing-a-development-branch to decide merge/PR next steps with the user.
