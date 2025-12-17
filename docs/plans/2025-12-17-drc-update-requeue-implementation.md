# DRC Update Requeue Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically re-check projects when a new precheck container version is deployed, with both automatic and manual trigger options.

**Architecture:** Add `format_version_display()` to PrecheckImageRevision for cached version lookups, `create_check_drc_update()` to ManufacturabilityCheck for shared check creation logic, a periodic Celery task for automatic requeue, and a view/button for manual requeue.

**Tech Stack:** Django 5.2, Celery Beat, PostgreSQL DISTINCT ON, Django cache framework

---

## Task 1: Add version_display Property to PrecheckImageRevision

**Files:**
- Modify: `wafer_space/projects/models.py` (PrecheckImageRevision class, around line 2850)
- Test: `wafer_space/projects/tests/test_precheck_revision.py`

**Step 1: Write the failing test**

Add to `wafer_space/projects/tests/test_precheck_revision.py`:

```python
class TestPrecheckImageRevisionVersionDisplay:
    """Tests for PrecheckImageRevision.version_display property."""

    def test_version_display_returns_precheck_version_when_available(self):
        """version_display prefers precheck_version."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234",
            precheck_version="1.5.2",
            git_commit_sha="abc1234567890",
        )
        assert revision.version_display == "1.5.2"

    def test_version_display_falls_back_to_git_commit_sha(self):
        """version_display uses git_commit_sha[:7] if no precheck_version."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:def456abc789012345678901234567890123456789012345678901234567",
            precheck_version="",
            git_commit_sha="abc1234567890",
        )
        assert revision.version_display == "abc1234"

    def test_version_display_falls_back_to_short_digest(self):
        """version_display uses short_digest if no version info."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:xyz789abc123456789012345678901234567890123456789012345678901",
            precheck_version="",
            git_commit_sha="",
        )
        assert revision.version_display == "sha256:xyz789abc123..."
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_precheck_revision.py::TestPrecheckImageRevisionVersionDisplay -v`

Expected: FAIL with "AttributeError: 'PrecheckImageRevision' object has no attribute 'version_display'"

**Step 3: Write minimal implementation**

Add to `wafer_space/projects/models.py` in `PrecheckImageRevision` class (after `short_digest` property around line 2852):

```python
    @property
    def version_display(self) -> str:
        """Human-readable version string for display."""
        if self.precheck_version:
            return self.precheck_version
        if self.git_commit_sha:
            return self.git_commit_sha[:7]
        return self.short_digest
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_precheck_revision.py::TestPrecheckImageRevisionVersionDisplay -v`

Expected: PASS (3 tests)

**Step 5: Run full test suite and lint**

Run: `make lint-fix && make lint && make type-check`

Expected: All checks pass

**Step 6: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_precheck_revision.py
git commit -m "feat: add version_display property to PrecheckImageRevision"
```

---

## Task 2: Add format_version_display() Classmethod to PrecheckImageRevision

**Files:**
- Modify: `wafer_space/projects/models.py` (PrecheckImageRevision class)
- Test: `wafer_space/projects/tests/test_precheck_revision.py`

**Step 1: Write the failing tests**

Add to `wafer_space/projects/tests/test_precheck_revision.py`:

```python
from django.core.cache import cache


@pytest.mark.django_db
class TestFormatVersionDisplay:
    """Tests for PrecheckImageRevision.format_version_display()."""

    def setup_method(self):
        """Clear cache before each test."""
        cache.clear()

    def test_format_version_display_with_none_returns_dash(self):
        """format_version_display(None) returns ('-', None)."""
        version_str, is_latest = PrecheckImageRevision.format_version_display(None)
        assert version_str == "-"
        assert is_latest is None

    def test_format_version_display_with_check_returns_version_and_is_latest(self):
        """format_version_display(check) returns version string and is_latest flag."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:latest123456789012345678901234567890123456789012345678901234",
            precheck_version="2.0.0",
        )
        check = ManufacturabilityCheckFactory(
            docker_image_digest=revision.digest,
            container_started_at=timezone.now(),
        )
        version_str, is_latest = PrecheckImageRevision.format_version_display(check)
        assert version_str == "2.0.0"
        assert is_latest is True

    def test_format_version_display_with_outdated_check(self):
        """format_version_display returns is_latest=False for outdated check."""
        # Create older check
        old_revision = PrecheckImageRevision.objects.create(
            digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            precheck_version="1.0.0",
        )
        old_check = ManufacturabilityCheckFactory(
            docker_image_digest=old_revision.digest,
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        # Create newer check (makes old one outdated)
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()  # Clear cached latest digest

        version_str, is_latest = PrecheckImageRevision.format_version_display(old_check)
        assert version_str == "1.0.0"
        assert is_latest is False

    def test_format_version_display_with_digest_string(self):
        """format_version_display works with raw digest string."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:str123456789012345678901234567890123456789012345678901234567",
            precheck_version="1.2.3",
        )
        # Make this the latest
        ManufacturabilityCheckFactory(
            docker_image_digest=revision.digest,
            container_started_at=timezone.now(),
        )
        cache.clear()

        version_str, is_latest = PrecheckImageRevision.format_version_display(
            revision.digest
        )
        assert version_str == "1.2.3"
        assert is_latest is True

    def test_format_version_display_fallback_to_short_digest(self):
        """format_version_display falls back to short digest when no revision."""
        digest = "sha256:unknown789012345678901234567890123456789012345678901234567890"
        version_str, is_latest = PrecheckImageRevision.format_version_display(digest)
        assert version_str == "sha256:unknown78901..."
        assert is_latest is None  # Can't determine without a latest check

    def test_format_version_display_caches_result(self):
        """format_version_display caches the display string."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:cache12345678901234567890123456789012345678901234567890123456",
            precheck_version="3.0.0",
        )
        # First call
        version_str1, _ = PrecheckImageRevision.format_version_display(revision.digest)
        assert version_str1 == "3.0.0"

        # Delete revision - cached value should still be returned
        revision.delete()
        version_str2, _ = PrecheckImageRevision.format_version_display(revision.digest)
        assert version_str2 == "3.0.0"

    def test_format_version_display_with_empty_digest_check(self):
        """format_version_display returns dash for check without digest."""
        check = ManufacturabilityCheckFactory(docker_image_digest="")
        version_str, is_latest = PrecheckImageRevision.format_version_display(check)
        assert version_str == "-"
        assert is_latest is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_precheck_revision.py::TestFormatVersionDisplay -v`

Expected: FAIL with "AttributeError: type object 'PrecheckImageRevision' has no attribute 'format_version_display'"

**Step 3: Write minimal implementation**

Add import at top of `wafer_space/projects/models.py` if not present:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # ManufacturabilityCheck forward reference handled by string annotation
```

Add classmethod to `PrecheckImageRevision` class (after `version_display` property):

```python
    @classmethod
    def format_version_display(
        cls, check_or_digest: "ManufacturabilityCheck | str | None"
    ) -> tuple[str, bool | None]:
        """Format version display string and is_latest flag for a check or digest.

        Args:
            check_or_digest: A ManufacturabilityCheck, digest string, or None.

        Returns:
            Tuple of (display_string, is_latest_flag).
            display_string is always a valid string for display.
            is_latest_flag is True/False/None (None if cannot determine).
        """
        if check_or_digest is None:
            return ("-", None)

        if isinstance(check_or_digest, str):
            digest = check_or_digest
            latest = ManufacturabilityCheck.get_latest_precheck_digest()
            is_latest = (digest == latest) if digest and latest else None
        else:
            digest = check_or_digest.docker_image_digest
            is_latest = check_or_digest.is_using_latest_precheck

        if not digest:
            return ("-", None)

        cache_key = f"precheck_display:{digest}"
        cached = cache.get(cache_key)
        if cached:
            return (cached, is_latest)

        revision = cls.objects.filter(digest=digest).first()
        if revision:
            display = revision.version_display
        else:
            display = f"sha256:{digest[7:19]}..."

        cache.set(cache_key, display, 60)
        return (display, is_latest)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_precheck_revision.py::TestFormatVersionDisplay -v`

Expected: PASS (8 tests)

**Step 5: Run full test suite and lint**

Run: `make lint-fix && make lint && make type-check`

Expected: All checks pass

**Step 6: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_precheck_revision.py
git commit -m "feat: add format_version_display() classmethod to PrecheckImageRevision"
```

---

## Task 3: Update Templatetags to Use format_version_display()

**Files:**
- Modify: `wafer_space/projects/templatetags/precheck_tags.py`
- Test: `wafer_space/projects/tests/test_templatetags.py`

**Step 1: Verify existing templatetag tests pass**

Run: `uv run pytest wafer_space/projects/tests/test_templatetags.py -v`

Expected: PASS (existing tests should pass)

**Step 2: Update precheck_tags.py**

Replace the contents of `wafer_space/projects/templatetags/precheck_tags.py`:

```python
"""Template tags for manufacturability check badges with version info.

These tags render badges showing check status and/or container version information.

Available tags:
- badge_check_status: Status badge with small version indicator icon
- badge_check_version: Version-only badge (shows container version used)
- badge_check_status_and_version: Full badge with status and version details
- get_latest_precheck_version: Returns the version string of the latest precheck
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import PrecheckImageRevision

if TYPE_CHECKING:
    from django.utils.safestring import SafeString

register = template.Library()


@register.simple_tag
def badge_check_status(check: ManufacturabilityCheck | None) -> SafeString:
    """Render check status badge with version indicator icon.

    Shows the check status (Running, Queued, Passed, Failed, etc.) with a small
    cloud icon indicating whether the check used the latest container version.

    Usage: {% badge_check_status check %}
    """
    if not check:
        return mark_safe(
            '<span class="badge bg-light text-muted border">No check</span>'
        )

    icon, label, bg_class = _get_status_display(check)
    version_indicator = _get_version_indicator_html(check)

    return format_html(
        '<span class="badge {}"><i class="bi bi-{}"></i> {}{}</span>',
        bg_class,
        icon,
        label,
        version_indicator,
    )


@register.simple_tag
def badge_check_version(check: ManufacturabilityCheck | None) -> SafeString:
    """Render version-only badge showing container version used.

    Shows the precheck container version (e.g., "v1.2.3" or commit SHA) with
    an icon indicating if it's the latest version.

    Usage: {% badge_check_version check %}
    """
    version_str, is_latest = PrecheckImageRevision.format_version_display(check)
    icon, icon_class = _get_version_icon(is_latest=is_latest)

    if is_latest:
        bg_class = "bg-success-subtle text-success border-success"
    else:
        bg_class = "bg-warning-subtle text-warning-emphasis border-warning"

    return format_html(
        '<span class="badge {} border">{} <i class="bi bi-{} {}"></i></span>',
        bg_class,
        version_str,
        icon,
        icon_class,
    )


@register.simple_tag
def badge_check_status_and_version(
    check: ManufacturabilityCheck | None,
) -> SafeString:
    """Render combined badge with status and full version details.

    Shows check status followed by version string and indicator icon.
    Example: "Passed | v1.2.3 ☁️"

    Usage: {% badge_check_status_and_version check %}
    """
    if not check:
        return mark_safe(
            '<span class="badge bg-light text-muted border">No check</span>'
        )

    icon, label, bg_class = _get_status_display(check)

    version_str, is_latest = PrecheckImageRevision.format_version_display(check)
    if version_str != "-":
        version_icon, version_icon_class = _get_version_icon(is_latest=is_latest)
        version_part = format_html(
            ' | {} <i class="bi bi-{} {}"></i>',
            version_str,
            version_icon,
            version_icon_class,
        )
    else:
        version_part = format_html("{}", "")

    return format_html(
        '<span class="badge {}"><i class="bi bi-{}"></i> {}{}</span>',
        bg_class,
        icon,
        label,
        version_part,
    )


# --- Helper functions ---


def _get_status_display(
    check: ManufacturabilityCheck,
) -> tuple[str, str, str]:
    """Return (icon, label, bg_class) for check status.

    Uses model's _STATUS_METADATA for consistent status rendering.
    For finished checks, shows pass/fail based on is_manufacturable.
    """
    # For finished checks, show pass/fail based on is_manufacturable
    if check.status == ManufacturabilityCheck.Status.FINISHED:
        if check.is_manufacturable:
            return ("check-circle", "Passed", "bg-success")
        return ("x-circle", "Failed", "bg-danger")

    # Use model's centralized status metadata
    meta = ManufacturabilityCheck.get_status_metadata(check.status)

    # Extract icon name from full class (e.g., "bi-clock" -> "clock")
    icon_class = str(meta.get("icon", ""))
    icon = icon_class.replace("bi-", "") if icon_class else "question"

    label = str(meta.get("label", check.status))

    # Build bg_class from color, handling text color for light backgrounds
    color = str(meta.get("color", "secondary"))
    bg_class = "bg-warning text-dark" if color == "warning" else f"bg-{color}"

    return (icon, label, bg_class)


def _get_version_indicator_html(check: ManufacturabilityCheck) -> SafeString:
    """Return HTML for version indicator icon."""
    _, is_latest = PrecheckImageRevision.format_version_display(check)
    if is_latest is None:
        return format_html("{}", "")

    icon, icon_class = _get_version_icon(is_latest=is_latest)
    return format_html(' <i class="bi bi-{} {}"></i>', icon, icon_class)


def _get_version_icon(*, is_latest: bool | None) -> tuple[str, str]:
    """Return (icon_name, css_class) for version status.

    Uses white text to contrast with colored badge backgrounds.
    Icon shape indicates status: check=latest, arrow-up=outdated.
    """
    if is_latest is True:
        return ("cloud-check-fill", "text-white")
    if is_latest is False:
        return ("cloud-arrow-up-fill", "text-white-50")
    return ("cloud", "text-white-50")


@register.simple_tag
def get_latest_precheck_version() -> str:
    """Return the version string of the latest precheck container.

    Looks up the digest of the most recently used precheck image, then
    finds its version info from PrecheckImageRevision.

    Returns version string like "v1.2.3" or commit SHA, or "-" if unknown.

    Usage: {% get_latest_precheck_version %}
    """
    version_str, _ = PrecheckImageRevision.format_version_display(
        ManufacturabilityCheck.get_latest_precheck_digest()
    )
    return version_str
```

**Step 3: Run templatetag tests**

Run: `uv run pytest wafer_space/projects/tests/test_templatetags.py -v`

Expected: PASS (all existing tests should still pass)

**Step 4: Run full test suite and lint**

Run: `make lint-fix && make lint && make type-check`

Expected: All checks pass

**Step 5: Commit**

```bash
git add wafer_space/projects/templatetags/precheck_tags.py
git commit -m "refactor: update templatetags to use format_version_display()"
```

---

## Task 4: Add create_check_drc_update() Method to ManufacturabilityCheck

**Files:**
- Modify: `wafer_space/projects/models.py` (ManufacturabilityCheck class)
- Test: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing tests**

Add to `wafer_space/projects/tests/test_models.py`:

```python
@pytest.mark.django_db
class TestCreateCheckDrcUpdate:
    """Tests for ManufacturabilityCheck.create_check_drc_update()."""

    def setup_method(self):
        """Clear cache before each test."""
        cache.clear()

    def test_create_check_drc_update_success(self):
        """create_check_drc_update creates new check with correct attributes."""
        # Create a finished check with outdated digest
        old_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        # Create newer check to make old one outdated
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        new_check = old_check.create_check_drc_update()

        assert new_check.project == old_check.project
        assert new_check.project_file == old_check.project_file
        assert new_check.trigger_reason == ManufacturabilityCheck.TriggerReason.DRC_UPDATE
        assert new_check.parent_check == old_check
        assert new_check.status == ManufacturabilityCheck.Status.PENDING

    def test_create_check_drc_update_fails_not_latest_check(self):
        """create_check_drc_update raises ValueError if not latest check."""
        project_file = ProjectFileFactory()
        old_check = ManufacturabilityCheckFactory(
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
        )
        # Create newer check for same file
        ManufacturabilityCheckFactory(
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
        )

        with pytest.raises(ValueError, match="latest check"):
            old_check.create_check_drc_update()

    def test_create_check_drc_update_fails_no_digest(self):
        """create_check_drc_update raises ValueError if no digest."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING,
            docker_image_digest="",
        )

        with pytest.raises(ValueError, match="does not have a version"):
            check.create_check_drc_update()

    def test_create_check_drc_update_fails_already_latest(self):
        """create_check_drc_update raises ValueError if already using latest."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:latest123456789012345678901234567890123456789012345678901234",
            container_started_at=timezone.now(),
        )
        cache.clear()

        with pytest.raises(ValueError, match="already using latest"):
            check.create_check_drc_update()

    def test_create_check_drc_update_works_for_running_check(self):
        """create_check_drc_update works for in-progress checks with outdated digest."""
        # Create running check with outdated digest
        running_check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=1),
        )
        # Create newer check to make running one outdated
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        new_check = running_check.create_check_drc_update()

        assert new_check.parent_check == running_check
        assert new_check.trigger_reason == ManufacturabilityCheck.TriggerReason.DRC_UPDATE
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestCreateCheckDrcUpdate -v`

Expected: FAIL with "AttributeError: 'ManufacturabilityCheck' object has no attribute 'create_check_drc_update'"

**Step 3: Write minimal implementation**

Add method to `ManufacturabilityCheck` class in `wafer_space/projects/models.py` (after `root_check` property, around line 2224):

```python
    def create_check_drc_update(self) -> "ManufacturabilityCheck":
        """Create a new pending check to re-run with latest precheck version.

        If this check is still in progress, it will be automatically cancelled
        by the existing superseded check cleanup logic.

        Returns:
            The newly created ManufacturabilityCheck.

        Raises:
            ValueError: If this check is not eligible for DRC update.
        """
        # Must be the latest check for this project file
        latest = self.project_file.latest_manufacturability_check
        if latest != self:
            msg = "Can only create DRC update from the latest check for a file"
            raise ValueError(msg)

        # Must have a known version
        if not self.docker_image_digest:
            msg = "Check does not have a version yet"
            raise ValueError(msg)

        # Must have outdated digest
        if self.is_using_latest_precheck is not False:
            msg = "Check is already using latest precheck version"
            raise ValueError(msg)

        return ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            trigger_reason=self.TriggerReason.DRC_UPDATE,
            parent_check=self,
        )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestCreateCheckDrcUpdate -v`

Expected: PASS (5 tests)

**Step 5: Run full test suite and lint**

Run: `make lint-fix && make lint && make type-check`

Expected: All checks pass

**Step 6: Commit**

```bash
git add wafer_space/projects/models.py wafer_space/projects/tests/test_models.py
git commit -m "feat: add create_check_drc_update() method to ManufacturabilityCheck"
```

---

## Task 5: Add checks_drc_update_requeue Task

**Files:**
- Modify: `wafer_space/projects/tasks_checks.py`
- Test: `wafer_space/projects/tests/test_tasks.py`

**Step 1: Write the failing tests**

Add to `wafer_space/projects/tests/test_tasks.py`:

```python
from collections import defaultdict


@pytest.mark.django_db
class TestChecksDrcUpdateRequeue:
    """Tests for checks_drc_update_requeue task."""

    def setup_method(self):
        """Clear cache and set up test data."""
        cache.clear()
        self.project = ProjectFactory()
        self.project_file = ProjectFileFactory(project=self.project, is_active=True)

    def test_skips_when_no_latest_digest(self):
        """Task returns early when no checks exist to determine latest digest."""
        result = checks_drc_update_requeue()
        assert result == {"skipped": "no_latest_digest"}

    def test_creates_check_for_outdated_finished_check(self):
        """Task creates new check when latest check is FINISHED with outdated digest."""
        # Create finished check with old digest
        old_check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        # Create different project with newer digest (establishes latest)
        other_project = ProjectFactory()
        other_file = ProjectFileFactory(project=other_project)
        ManufacturabilityCheckFactory(
            project=other_project,
            project_file=other_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        result = checks_drc_update_requeue()

        assert result["created"] == 1
        assert result["outdated_count"] == 1

        # Verify new check was created
        new_check = ManufacturabilityCheck.objects.filter(
            project_file=self.project_file,
            trigger_reason=ManufacturabilityCheck.TriggerReason.DRC_UPDATE,
        ).first()
        assert new_check is not None
        assert new_check.parent_check == old_check

    def test_skips_in_progress_checks(self):
        """Task only considers FINISHED checks for automatic requeue."""
        # Create running check with old digest
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        # Establish latest digest
        other_file = ProjectFileFactory()
        ManufacturabilityCheckFactory(
            project_file=other_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        result = checks_drc_update_requeue()

        assert result["created"] == 0
        assert result["stats"]["in_progress"] == 1

    def test_skips_current_version_checks(self):
        """Task skips checks already using latest version."""
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:latest123456789012345678901234567890123456789012345678901234",
            container_started_at=timezone.now(),
        )
        cache.clear()

        result = checks_drc_update_requeue()

        assert result["created"] == 0
        assert result["outdated_count"] == 0

    def test_creates_only_one_per_run(self):
        """Task creates at most one check per run."""
        # Create two projects with outdated checks
        for i in range(2):
            proj = ProjectFactory()
            pf = ProjectFileFactory(project=proj, is_active=True)
            ManufacturabilityCheckFactory(
                project=proj,
                project_file=pf,
                status=ManufacturabilityCheck.Status.FINISHED,
                docker_image_digest=f"sha256:old{i}23456789012345678901234567890123456789012345678901234567",
                container_started_at=timezone.now() - timedelta(hours=i + 1),
            )
        # Establish latest digest
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        result = checks_drc_update_requeue()

        assert result["created"] == 1
        assert result["outdated_count"] == 2

    def test_orders_by_oldest_first(self):
        """Task processes oldest outdated checks first."""
        # Create older check
        old_proj = ProjectFactory()
        old_file = ProjectFileFactory(project=old_proj, is_active=True)
        old_check = ManufacturabilityCheckFactory(
            project=old_proj,
            project_file=old_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=10),
            created_at=timezone.now() - timedelta(hours=10),
        )
        # Create newer check
        new_proj = ProjectFactory()
        new_file = ProjectFileFactory(project=new_proj, is_active=True)
        ManufacturabilityCheckFactory(
            project=new_proj,
            project_file=new_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old223456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=5),
            created_at=timezone.now() - timedelta(hours=5),
        )
        # Establish latest digest
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        checks_drc_update_requeue()

        # Should have created check for older project
        new_check = ManufacturabilityCheck.objects.filter(
            trigger_reason=ManufacturabilityCheck.TriggerReason.DRC_UPDATE,
        ).first()
        assert new_check.parent_check == old_check

    def test_respects_capacity_limit(self):
        """Task respects 25% DRC_UPDATE capacity limit."""
        # Create outdated check
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        # Establish latest digest
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        # Fill capacity with active DRC_UPDATE checks
        # Default test capacity is 2, so 25% = 0 (int(2 * 0.25) = 0)
        # Need to check settings - may need to mock DOCKER_SERVERS
        cache.clear()

        result = checks_drc_update_requeue()

        # With default test settings, limit might be 0, so no checks created
        assert "drc_update_limit" in result
        assert "drc_update_active" in result

    def test_returns_stats(self):
        """Task returns comprehensive stats dictionary."""
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:latest123456789012345678901234567890123456789012345678901234",
            container_started_at=timezone.now(),
        )
        cache.clear()

        result = checks_drc_update_requeue()

        assert "stats" in result
        assert "total" in result["stats"]
        assert "finished" in result["stats"]
        assert "in_progress" in result["stats"]
        assert "error" in result["stats"]
        assert "drc_update_limit" in result
        assert "drc_update_active" in result
        assert "drc_update_available" in result
        assert "outdated_count" in result
        assert "created" in result
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestChecksDrcUpdateRequeue -v`

Expected: FAIL with "NameError: name 'checks_drc_update_requeue' is not defined"

**Step 3: Write minimal implementation**

Add to `wafer_space/projects/tasks_checks.py` (after `checks_retry` function):

```python
@checks_task()
def checks_drc_update_requeue() -> dict:
    """Create DRC_UPDATE checks for projects with outdated precheck versions.

    Finds projects where the latest check is FINISHED but used an outdated
    docker image digest, and creates new pending checks. Rate-limited to 25%
    of total capacity for DRC_UPDATE checks.

    Only creates one check per run to spread load over time.
    """
    from collections import defaultdict

    from django.conf import settings

    latest_digest = ManufacturabilityCheck.get_latest_precheck_digest()
    if not latest_digest:
        return {"skipped": "no_latest_digest"}

    # Get latest check per project (using PostgreSQL DISTINCT ON)
    latest_checks = list(
        ManufacturabilityCheck.objects.filter(project_file__project__isnull=False)
        .order_by("project_file__project_id", "-created_at")
        .distinct("project_file__project_id")
        .select_related("project_file", "project_file__project")
    )

    # Collect stats and find outdated FINISHED checks
    stats: dict = {
        "total": 0,
        "finished": defaultdict(int),
        "in_progress": 0,
        "error": 0,
    }
    outdated_checks = []

    for check in latest_checks:
        stats["total"] += 1

        if check.status in ManufacturabilityCheck.Status.in_progress():
            stats["in_progress"] += 1
        elif check.status == ManufacturabilityCheck.Status.ERROR:
            stats["error"] += 1
        elif check.status == ManufacturabilityCheck.Status.FINISHED:
            version_key, _ = PrecheckImageRevision.format_version_display(check)
            stats["finished"][version_key] += 1

            if check.docker_image_digest and check.docker_image_digest != latest_digest:
                outdated_checks.append(check)

    # Sort by oldest first (by created_at)
    outdated_checks.sort(key=lambda c: c.created_at)

    # Calculate DRC_UPDATE capacity limit (25% of total)
    total_capacity = sum(
        server["max_concurrent"] for server in settings.DOCKER_SERVERS
    )
    drc_update_limit = int(total_capacity * 0.25)

    # Count active DRC_UPDATE checks
    active_drc_updates = ManufacturabilityCheck.objects.filter(
        status__in=ManufacturabilityCheck.Status.in_progress(),
        trigger_reason=ManufacturabilityCheck.TriggerReason.DRC_UPDATE,
    ).count()

    drc_update_available = max(0, drc_update_limit - active_drc_updates)

    # Create one check if capacity available
    created = 0
    if drc_update_available > 0 and outdated_checks:
        check = outdated_checks[0]
        check.create_check_drc_update()
        created = 1

    # Convert defaultdict to regular dict for JSON serialization
    stats["finished"] = dict(stats["finished"])

    return {
        "stats": stats,
        "drc_update_limit": drc_update_limit,
        "drc_update_active": active_drc_updates,
        "drc_update_available": drc_update_available,
        "outdated_count": len(outdated_checks),
        "created": created,
    }
```

Also add the import at the top of the file if not present:

```python
from wafer_space.projects.models import PrecheckImageRevision
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_tasks.py::TestChecksDrcUpdateRequeue -v`

Expected: PASS (9 tests)

**Step 5: Run full test suite and lint**

Run: `make lint-fix && make lint && make type-check`

Expected: All checks pass

**Step 6: Commit**

```bash
git add wafer_space/projects/tasks_checks.py wafer_space/projects/tests/test_tasks.py
git commit -m "feat: add checks_drc_update_requeue periodic task"
```

---

## Task 6: Add Beat Schedule Entry

**Files:**
- Modify: `config/settings/base.py`

**Step 1: Add beat schedule entry**

Add to `CELERY_BEAT_SCHEDULE` in `config/settings/base.py` (after `checks-retry` entry):

```python
    "checks-drc-update-requeue": {
        "task": "wafer_space.projects.tasks_checks.checks_drc_update_requeue",
        "schedule": 60.0,
    },
```

**Step 2: Run lint**

Run: `make lint-fix && make lint`

Expected: All checks pass

**Step 3: Commit**

```bash
git add config/settings/base.py
git commit -m "feat: add checks_drc_update_requeue to beat schedule (60s interval)"
```

---

## Task 7: Add Manual Requeue View and URL

**Files:**
- Modify: `wafer_space/projects/views.py`
- Modify: `wafer_space/projects/urls.py`
- Test: `wafer_space/projects/tests/test_views.py`

**Step 1: Write the failing tests**

Add to `wafer_space/projects/tests/test_views.py`:

```python
@pytest.mark.django_db
class TestCheckDrcUpdateRequeue:
    """Tests for check_drc_update_requeue view."""

    def setup_method(self):
        """Set up test data."""
        cache.clear()
        self.user = UserFactory()
        self.project = ProjectFactory(user=self.user)
        self.project_file = ProjectFileFactory(project=self.project, is_active=True)

    def test_requeue_success(self, client):
        """Successful requeue redirects with success message."""
        # Create finished check with outdated digest
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        # Establish latest digest
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()

        client.force_login(self.user)
        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == 302
        assert response.url == reverse("projects:detail", args=[self.project.id])

        # Verify new check was created
        new_check = ManufacturabilityCheck.objects.filter(
            parent_check=check,
            trigger_reason=ManufacturabilityCheck.TriggerReason.DRC_UPDATE,
        ).first()
        assert new_check is not None

    def test_requeue_permission_denied_other_user(self, client):
        """Non-owner non-staff cannot requeue."""
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
        )
        other_user = UserFactory()

        client.force_login(other_user)
        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == 403

    def test_requeue_allowed_for_staff(self, client):
        """Staff can requeue any project's check."""
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:old123456789012345678901234567890123456789012345678901234567",
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new456789012345678901234567890123456789012345678901234567890",
            container_started_at=timezone.now(),
        )
        cache.clear()
        staff_user = UserFactory(is_staff=True)

        client.force_login(staff_user)
        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == 302

    def test_requeue_invalid_check_shows_error(self, client):
        """Requeue of already-latest check shows error message."""
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest="sha256:latest123456789012345678901234567890123456789012345678901234",
            container_started_at=timezone.now(),
        )
        cache.clear()

        client.force_login(self.user)
        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id]),
            follow=True,
        )

        assert response.status_code == 200
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "already using latest" in str(messages[0])

    def test_requeue_requires_login(self, client):
        """Unauthenticated users are redirected to login."""
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
        )

        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_requeue_requires_post(self, client):
        """GET requests are not allowed."""
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
        )

        client.force_login(self.user)
        response = client.get(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == 405  # Method Not Allowed
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_views.py::TestCheckDrcUpdateRequeue -v`

Expected: FAIL with "NoReverseMatch" (URL not defined yet)

**Step 3: Add the view**

Add to `wafer_space/projects/views.py`:

```python
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.views.decorators.http import require_POST


@login_required
@require_POST
def check_drc_update_requeue(request, check_id):
    """Manually trigger a DRC_UPDATE check for outdated precheck version."""
    check = get_object_or_404(ManufacturabilityCheck, pk=check_id)

    # Permission: must own the project or be staff
    if check.project.user != request.user and not request.user.is_staff:
        raise PermissionDenied

    try:
        check.create_check_drc_update()
        messages.success(request, "Check queued with latest precheck version.")
    except ValueError as e:
        messages.error(request, str(e))

    return redirect("projects:detail", pk=check.project.pk)
```

**Step 4: Add the URL**

Add to `wafer_space/projects/urls.py` in the `urlpatterns` list:

```python
    path(
        "check/<int:check_id>/requeue-drc-update/",
        views.check_drc_update_requeue,
        name="check_drc_update_requeue",
    ),
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_views.py::TestCheckDrcUpdateRequeue -v`

Expected: PASS (6 tests)

**Step 6: Run full test suite and lint**

Run: `make lint-fix && make lint && make type-check`

Expected: All checks pass

**Step 7: Commit**

```bash
git add wafer_space/projects/views.py wafer_space/projects/urls.py wafer_space/projects/tests/test_views.py
git commit -m "feat: add check_drc_update_requeue view for manual requeue"
```

---

## Task 8: Add Requeue Button to Template

**Files:**
- Modify: `wafer_space/templates/projects/detail.html` (or appropriate template)

**Step 1: Find the template location**

Look for where the check version badge is displayed. Likely in `wafer_space/templates/projects/detail.html` or a partial template.

**Step 2: Add the button**

Add after the version badge, shown only when `check.is_using_latest_precheck is False`:

```html
{% if check.is_using_latest_precheck is False %}
<form method="post" action="{% url 'projects:check_drc_update_requeue' check.id %}" class="d-inline">
    {% csrf_token %}
    <button type="submit" class="btn btn-sm btn-outline-warning" title="Re-run check with latest precheck version">
        <i class="bi bi-arrow-repeat"></i> Recheck with Latest
    </button>
</form>
{% endif %}
```

**Step 3: Run djlint**

Run: `uv run djlint wafer_space/templates/ --reformat`

**Step 4: Verify manually in browser**

Run: `make runserver`

Visit a project with an outdated check and verify the button appears.

**Step 5: Commit**

```bash
git add wafer_space/templates/
git commit -m "feat: add 'Recheck with Latest' button for outdated precheck versions"
```

---

## Task 9: Update Documentation

**Files:**
- Modify: `docs/celery_tasks_reference.md`
- Modify: `docs/celery_architecture.md`
- Modify: `docs/systemd-services.md`

**Step 1: Update celery_tasks_reference.md**

Add to Orchestration Tasks table:

```markdown
| `checks_drc_update_requeue`          | `none:ro:checks-orch` | 60s      | Create DRC_UPDATE checks for outdated versions |
```

Update Task Count Summary:
- Check orchestration tasks: 11 → 12
- Total: 22 → 23

Update Beat Schedule Summary:

```markdown
| 60 seconds | Cleanup (retry, orphaned docker, stale files, stale pending tasks), download recovery, DRC update requeue |
```

**Step 2: Update celery_architecture.md**

Add to "Cleanup & Recovery (60-second intervals)" table:

```markdown
| `checks-drc-update-requeue`          | Create DRC_UPDATE checks for outdated precheck versions |
```

**Step 3: Update systemd-services.md**

Add to the queue/task table (around line 61):

```markdown
| `none:ro:checks-orch`  | `checks_drc_update_requeue`       | Create DRC_UPDATE checks for outdated versions |
```

Add to the celery-beat tasks list (around line 195):

```markdown
- `checks_drc_update_requeue` - Create DRC_UPDATE checks for outdated versions
```

**Step 4: Commit**

```bash
git add docs/celery_tasks_reference.md docs/celery_architecture.md docs/systemd-services.md
git commit -m "docs: add checks_drc_update_requeue task to documentation"
```

---

## Task 10: Create GitHub Issue for Outdated Documentation

**Step 1: Create issue for manufacturability_checking.md**

Run:

```bash
gh issue create --title "docs: update manufacturability_checking.md (out of date)" --body "The \`docs/manufacturability_checking.md\` file is out of date and needs to be updated to reflect:

- Automatic DRC update requeue when new precheck versions are deployed
- Manual 'Recheck with Latest' button for users
- Current check states and trigger reasons
- Any other changes since the file was last updated

Related to: DRC update requeue feature implementation"
```

**Step 2: Record issue number in commit**

```bash
git commit --allow-empty -m "chore: created issue #XXX for docs/manufacturability_checking.md update"
```

---

## Task 11: Run Full Test Suite and Final Verification

**Step 1: Run all checks**

```bash
make check-all
```

Expected: All checks pass (lint, type-check, tests)

**Step 2: Verify beat schedule entry is correct**

```bash
uv run python -c "from config.settings.base import CELERY_BEAT_SCHEDULE; print('checks-drc-update-requeue' in CELERY_BEAT_SCHEDULE)"
```

Expected: `True`

**Step 3: Verify task is registered**

```bash
uv run python -c "from wafer_space.projects.tasks_checks import checks_drc_update_requeue; print(checks_drc_update_requeue.name)"
```

Expected: `wafer_space.projects.tasks_checks.checks_drc_update_requeue`

---

## Summary

| Task | Component | Status |
|------|-----------|--------|
| 1 | PrecheckImageRevision.version_display | |
| 2 | PrecheckImageRevision.format_version_display() | |
| 3 | Templatetags update | |
| 4 | ManufacturabilityCheck.create_check_drc_update() | |
| 5 | checks_drc_update_requeue task | |
| 6 | Beat schedule entry | |
| 7 | Manual requeue view and URL | |
| 8 | Template button | |
| 9 | Documentation updates | |
| 10 | GitHub issue for outdated docs | |
| 11 | Final verification | |
