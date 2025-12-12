# Container Version Tracking Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Track Docker precheck image revisions and display version status across the platform.

**Architecture:** Decoupled revision catalog populated asynchronously via Celery tasks. ManufacturabilityCheck stores digest, PrecheckImageRevision stores metadata. "Latest" computed via query. Shared template tags for consistent badge rendering.

**Tech Stack:** Django 5.2+, Celery, PostgreSQL, Bootstrap Icons, GHCR API

---

## Task 1: Create PrecheckImageRevision Model

**Files:**
- Modify: `wafer_space/projects/models.py` (add after ManufacturabilityCheck class)
- Create: `wafer_space/projects/tests/test_precheck_revision.py`

**Step 1: Write the failing test**

```python
# wafer_space/projects/tests/test_precheck_revision.py
from __future__ import annotations

import pytest
from django.utils import timezone

from wafer_space.projects.models import PrecheckImageRevision


@pytest.mark.django_db
class TestPrecheckImageRevision:
    """Tests for PrecheckImageRevision model."""

    def test_create_revision_with_digest(self):
        """Can create a revision with a digest."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234"
        )
        assert revision.pk is not None
        assert revision.digest.startswith("sha256:")
        assert revision.first_seen_at is not None

    def test_digest_is_unique(self):
        """Digest must be unique."""
        digest = "sha256:abc123def456789012345678901234567890123456789012345678901234"
        PrecheckImageRevision.objects.create(digest=digest)

        with pytest.raises(Exception):  # IntegrityError
            PrecheckImageRevision.objects.create(digest=digest)

    def test_short_digest_property(self):
        """short_digest returns truncated digest."""
        revision = PrecheckImageRevision(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234"
        )
        assert revision.short_digest == "sha256:abc123def456..."

    def test_github_commit_url_with_sha(self):
        """github_commit_url returns URL when git_commit_sha is set."""
        revision = PrecheckImageRevision(
            digest="sha256:abc123",
            git_commit_sha="a261f14ae7f90a0f74c6db18f28eeafce9b6e803"
        )
        assert revision.github_commit_url == (
            "https://github.com/wafer-space/gf180mcu-precheck/commit/"
            "a261f14ae7f90a0f74c6db18f28eeafce9b6e803"
        )

    def test_github_commit_url_without_sha(self):
        """github_commit_url returns None when git_commit_sha is empty."""
        revision = PrecheckImageRevision(digest="sha256:abc123")
        assert revision.github_commit_url is None

    def test_ghcr_package_url(self):
        """ghcr_package_url returns correct URL."""
        revision = PrecheckImageRevision(digest="sha256:abc123")
        assert revision.ghcr_package_url == (
            "https://github.com/wafer-space/gf180mcu-precheck/pkgs/container/gf180mcu-precheck"
        )
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_precheck_revision.py -v`
Expected: FAIL with "cannot import name 'PrecheckImageRevision'"

**Step 3: Write the model implementation**

Add to `wafer_space/projects/models.py` after the imports section:

```python
PRECHECK_GITHUB_REPO = "wafer-space/gf180mcu-precheck"
```

Add the model class (place after ManufacturabilityCheck or at end of file):

```python
class PrecheckImageRevision(models.Model):
    """
    Catalog of known precheck Docker image versions.

    Populated asynchronously when new digests are discovered from completed
    ManufacturabilityChecks. Linked by digest string match, NOT foreign key.
    """

    # Primary identifier - the immutable digest
    digest = models.CharField(
        max_length=100,
        unique=True,
        help_text="SHA256 digest (e.g., sha256:abc123...)",
    )

    # When we first saw this digest used in a check
    first_seen_at = models.DateTimeField(auto_now_add=True)

    # Metadata fetched from GHCR/GitHub
    image_created_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the image was pushed to GHCR",
    )
    git_commit_sha = models.CharField(
        max_length=40,
        blank=True,
        help_text="Git commit from image labels",
    )

    # Version information
    precheck_version = models.CharField(
        max_length=50,
        blank=True,
        help_text="Precheck tool version (e.g., 1.5.2)",
    )
    pdk_version = models.CharField(
        max_length=50,
        blank=True,
        help_text="PDK version (if available)",
    )
    tool_versions = models.JSONField(
        default=dict,
        blank=True,
        help_text="Tool versions dict (e.g., {magic: '8.3.x', klayout: '0.28.x'})",
    )

    # Tracking
    metadata_fetched_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When GHCR metadata was last fetched",
    )

    class Meta:
        ordering = ["-first_seen_at"]
        indexes = [
            models.Index(fields=["digest"]),
            models.Index(fields=["-first_seen_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.short_digest} (seen {self.first_seen_at.date()})"

    # --- URL helpers ---

    @property
    def github_commit_url(self) -> str | None:
        """URL to the specific commit, or None if unknown."""
        if not self.git_commit_sha:
            return None
        return f"https://github.com/{PRECHECK_GITHUB_REPO}/commit/{self.git_commit_sha}"

    @property
    def ghcr_package_url(self) -> str:
        """URL to the package on GitHub Container Registry."""
        return f"https://github.com/{PRECHECK_GITHUB_REPO}/pkgs/container/gf180mcu-precheck"

    @property
    def short_digest(self) -> str:
        """Truncated digest for display."""
        assert self.digest and self.digest.startswith("sha256:")
        return f"sha256:{self.digest[7:19]}..."
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_precheck_revision.py -v`
Expected: FAIL (no migration yet)

**Step 5: Create migration**

Run: `uv run python manage.py makemigrations projects --name add_precheck_image_revision`

**Step 6: Run test again**

Run: `uv run pytest wafer_space/projects/tests/test_precheck_revision.py -v`
Expected: PASS (6 tests)

**Step 7: Lint and commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/migrations/ wafer_space/projects/tests/test_precheck_revision.py
git commit -m "feat: add PrecheckImageRevision model

Catalog of known precheck Docker image versions with:
- Digest as unique identifier
- GHCR metadata fields (image_created_at, git_commit_sha)
- Version fields (precheck_version, pdk_version, tool_versions)
- URL helpers for GitHub commit and GHCR package links

Part of container version tracking (issues #191, #201)"
```

---

## Task 2: Add Statistics Methods to PrecheckImageRevision

**Files:**
- Modify: `wafer_space/projects/models.py`
- Modify: `wafer_space/projects/tests/test_precheck_revision.py`

**Step 1: Write the failing tests**

Add to `test_precheck_revision.py`:

```python
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory


@pytest.mark.django_db
class TestPrecheckImageRevisionStatistics:
    """Tests for PrecheckImageRevision statistics methods."""

    def test_checks_count(self):
        """checks_count returns number of checks using this revision."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234"
        )
        # Create checks with this digest
        ManufacturabilityCheckFactory(docker_image_digest=revision.digest)
        ManufacturabilityCheckFactory(docker_image_digest=revision.digest)
        ManufacturabilityCheckFactory(docker_image_digest="sha256:other")

        assert revision.checks_count == 2

    def test_checks_passed_count(self):
        """checks_passed_count returns number of passed checks."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234"
        )
        from wafer_space.projects.models import ManufacturabilityCheck
        ManufacturabilityCheckFactory(
            docker_image_digest=revision.digest,
            result=ManufacturabilityCheck.Result.PASSED,
        )
        ManufacturabilityCheckFactory(
            docker_image_digest=revision.digest,
            result=ManufacturabilityCheck.Result.FAILED,
        )

        assert revision.checks_passed_count == 1

    def test_checks_failed_count(self):
        """checks_failed_count returns number of failed checks."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234"
        )
        from wafer_space.projects.models import ManufacturabilityCheck
        ManufacturabilityCheckFactory(
            docker_image_digest=revision.digest,
            result=ManufacturabilityCheck.Result.PASSED,
        )
        ManufacturabilityCheckFactory(
            docker_image_digest=revision.digest,
            result=ManufacturabilityCheck.Result.FAILED,
        )

        assert revision.checks_failed_count == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_precheck_revision.py::TestPrecheckImageRevisionStatistics -v`
Expected: FAIL with "has no attribute 'checks_count'"

**Step 3: Add statistics methods to model**

Add to `PrecheckImageRevision` class in `models.py`:

```python
    # --- Statistics helpers ---

    def _get_checks_queryset(self) -> models.QuerySet["ManufacturabilityCheck"]:
        """Get all ManufacturabilityChecks that used this revision."""
        return ManufacturabilityCheck.objects.filter(docker_image_digest=self.digest)

    @property
    def checks_count(self) -> int:
        """Total number of checks that used this revision."""
        return self._get_checks_queryset().count()

    @property
    def checks_passed_count(self) -> int:
        """Number of checks that passed with this revision."""
        return self._get_checks_queryset().filter(
            result=ManufacturabilityCheck.Result.PASSED
        ).count()

    @property
    def checks_failed_count(self) -> int:
        """Number of checks that failed with this revision."""
        return self._get_checks_queryset().filter(
            result=ManufacturabilityCheck.Result.FAILED
        ).count()

    def get_run_duration_stats(self) -> dict[str, float | None]:
        """Get average and max run duration for checks using this revision.

        Returns:
            {"average": float|None, "max": float|None} in seconds
        """
        completed = self._get_checks_queryset().filter(
            status=ManufacturabilityCheck.Status.FINISHED,
            container_started_at__isnull=False,
            container_finished_at__isnull=False,
        )

        stats = completed.aggregate(
            avg_duration=models.Avg(
                models.F("container_finished_at") - models.F("container_started_at")
            ),
            max_duration=models.Max(
                models.F("container_finished_at") - models.F("container_started_at")
            ),
        )

        return {
            "average": stats["avg_duration"].total_seconds()
            if stats["avg_duration"]
            else None,
            "max": stats["max_duration"].total_seconds()
            if stats["max_duration"]
            else None,
        }
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_precheck_revision.py -v`
Expected: PASS

**Step 5: Lint and commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/tests/test_precheck_revision.py
git commit -m "feat: add statistics methods to PrecheckImageRevision

- checks_count: total checks using revision
- checks_passed_count: passed checks
- checks_failed_count: failed checks
- get_run_duration_stats(): average and max duration"
```

---

## Task 3: Add Latest Digest Methods to ManufacturabilityCheck

**Files:**
- Modify: `wafer_space/projects/models.py`
- Modify: `wafer_space/projects/tests/test_precheck_revision.py`

**Step 1: Write the failing tests**

Add to `test_precheck_revision.py`:

```python
from django.core.cache import cache


@pytest.mark.django_db
class TestManufacturabilityCheckLatestDigest:
    """Tests for ManufacturabilityCheck.get_latest_precheck_digest."""

    def setup_method(self):
        """Clear cache before each test."""
        cache.clear()

    def test_get_latest_precheck_digest_returns_most_recent(self):
        """get_latest_precheck_digest returns digest from most recently started check."""
        from wafer_space.projects.models import ManufacturabilityCheck
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()
        # Older check
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:older",
            container_started_at=now - timedelta(hours=2),
        )
        # Newer check
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:newer",
            container_started_at=now - timedelta(hours=1),
        )

        assert ManufacturabilityCheck.get_latest_precheck_digest() == "sha256:newer"

    def test_get_latest_precheck_digest_ignores_empty(self):
        """get_latest_precheck_digest ignores checks with empty digest."""
        from wafer_space.projects.models import ManufacturabilityCheck
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:valid",
            container_started_at=now - timedelta(hours=2),
        )
        # More recent but empty digest
        ManufacturabilityCheckFactory(
            docker_image_digest="",
            container_started_at=now - timedelta(hours=1),
        )

        assert ManufacturabilityCheck.get_latest_precheck_digest() == "sha256:valid"

    def test_get_latest_precheck_digest_returns_none_when_no_checks(self):
        """get_latest_precheck_digest returns None when no checks exist."""
        from wafer_space.projects.models import ManufacturabilityCheck

        assert ManufacturabilityCheck.get_latest_precheck_digest() is None

    def test_is_using_latest_precheck_true(self):
        """is_using_latest_precheck returns True when using latest."""
        from django.utils import timezone

        check = ManufacturabilityCheckFactory(
            docker_image_digest="sha256:latest",
            container_started_at=timezone.now(),
        )

        assert check.is_using_latest_precheck is True

    def test_is_using_latest_precheck_false(self):
        """is_using_latest_precheck returns False when outdated."""
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()
        old_check = ManufacturabilityCheckFactory(
            docker_image_digest="sha256:old",
            container_started_at=now - timedelta(hours=2),
        )
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new",
            container_started_at=now - timedelta(hours=1),
        )
        cache.clear()  # Clear cache to get fresh result

        assert old_check.is_using_latest_precheck is False

    def test_is_using_latest_precheck_none_when_no_digest(self):
        """is_using_latest_precheck returns None when check has no digest."""
        check = ManufacturabilityCheckFactory(docker_image_digest="")

        assert check.is_using_latest_precheck is None

    def test_precheck_revision_property(self):
        """precheck_revision returns linked revision if exists."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234"
        )
        check = ManufacturabilityCheckFactory(docker_image_digest=revision.digest)

        assert check.precheck_revision == revision

    def test_precheck_revision_property_none_when_not_cataloged(self):
        """precheck_revision returns None if revision not in catalog."""
        check = ManufacturabilityCheckFactory(docker_image_digest="sha256:uncataloged")

        assert check.precheck_revision is None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_precheck_revision.py::TestManufacturabilityCheckLatestDigest -v`
Expected: FAIL with "has no attribute 'get_latest_precheck_digest'"

**Step 3: Add methods to ManufacturabilityCheck model**

Add to `ManufacturabilityCheck` class in `models.py`:

```python
    @classmethod
    def get_latest_precheck_digest(cls) -> str | None:
        """Get the digest of the most recently used precheck image.

        Returns the docker_image_digest from the check with the most recent
        container_started_at timestamp. Cached for 60 seconds.
        """
        from django.core.cache import cache

        cache_key = "precheck_latest_digest"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached or None

        digest = (
            cls.objects.exclude(docker_image_digest="")
            .order_by("-container_started_at")
            .values_list("docker_image_digest", flat=True)
            .first()
        )

        cache.set(cache_key, digest or "", 60)  # 1 minute TTL
        return digest

    @property
    def is_using_latest_precheck(self) -> bool | None:
        """Whether this check used the latest precheck image version.

        Returns:
            True - used latest version
            False - used outdated version
            None - cannot determine (no digest or no latest known)
        """
        if not self.docker_image_digest:
            return None
        latest = self.get_latest_precheck_digest()
        if latest is None:
            return None
        return self.docker_image_digest == latest

    @property
    def precheck_revision(self) -> "PrecheckImageRevision | None":
        """Get the PrecheckImageRevision for this check, if cataloged."""
        if not self.docker_image_digest:
            return None
        return PrecheckImageRevision.objects.filter(
            digest=self.docker_image_digest
        ).first()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_precheck_revision.py -v`
Expected: PASS

**Step 5: Lint and commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/models.py wafer_space/projects/tests/test_precheck_revision.py
git commit -m "feat: add latest digest methods to ManufacturabilityCheck

- get_latest_precheck_digest(): cached query for most recent digest
- is_using_latest_precheck: property to check if using latest
- precheck_revision: property to get linked PrecheckImageRevision"
```

---

## Task 4: Register PrecheckImageRevision in Admin

**Files:**
- Modify: `wafer_space/projects/admin.py`

**Step 1: Add admin registration**

Add to `wafer_space/projects/admin.py`:

```python
from wafer_space.projects.models import PrecheckImageRevision


@admin.register(PrecheckImageRevision)
class PrecheckImageRevisionAdmin(admin.ModelAdmin):
    """Admin for PrecheckImageRevision."""

    list_display = [
        "short_digest",
        "precheck_version",
        "git_commit_sha_short",
        "first_seen_at",
        "checks_count",
        "metadata_fetched_at",
    ]
    list_filter = ["first_seen_at", "metadata_fetched_at"]
    search_fields = ["digest", "git_commit_sha", "precheck_version"]
    readonly_fields = [
        "digest",
        "first_seen_at",
        "short_digest",
        "github_commit_url",
        "ghcr_package_url",
        "checks_count",
        "checks_passed_count",
        "checks_failed_count",
    ]
    ordering = ["-first_seen_at"]

    @admin.display(description="Commit")
    def git_commit_sha_short(self, obj: PrecheckImageRevision) -> str:
        """Display truncated git commit SHA."""
        if obj.git_commit_sha:
            return obj.git_commit_sha[:7]
        return "-"
```

**Step 2: Run checks and commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/admin.py
git commit -m "feat: register PrecheckImageRevision in Django admin"
```

---

## Task 5: Create Celery Tasks for Revision Discovery

**Files:**
- Create: `wafer_space/projects/tasks_revisions.py`
- Create: `wafer_space/projects/tests/test_tasks_revisions.py`

**Step 1: Write the failing tests**

```python
# wafer_space/projects/tests/test_tasks_revisions.py
from __future__ import annotations

from unittest.mock import patch

import pytest

from wafer_space.projects.models import ManufacturabilityCheck, PrecheckImageRevision
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory


@pytest.mark.django_db
class TestRevisionsNeedsFetching:
    """Tests for revisions_needs_fetching task."""

    def test_discovers_new_digest(self):
        """Task discovers digest not in PrecheckImageRevision."""
        from wafer_space.projects.tasks_revisions import revisions_needs_fetching

        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:newdigest123456789012345678901234567890123456789012345678"
        )

        with patch(
            "wafer_space.projects.tasks_revisions.do_revision_fetch.delay"
        ) as mock_fetch:
            result = revisions_needs_fetching()

        assert result["new_revisions_queued"] == 1
        assert PrecheckImageRevision.objects.filter(
            digest="sha256:newdigest123456789012345678901234567890123456789012345678"
        ).exists()
        mock_fetch.assert_called_once()

    def test_ignores_known_digest(self):
        """Task ignores digest already in PrecheckImageRevision."""
        from wafer_space.projects.tasks_revisions import revisions_needs_fetching

        digest = "sha256:knowndigest12345678901234567890123456789012345678901234567"
        PrecheckImageRevision.objects.create(digest=digest)
        ManufacturabilityCheckFactory(docker_image_digest=digest)

        with patch(
            "wafer_space.projects.tasks_revisions.do_revision_fetch.delay"
        ) as mock_fetch:
            result = revisions_needs_fetching()

        assert result["new_revisions_queued"] == 0
        mock_fetch.assert_not_called()

    def test_ignores_empty_digest(self):
        """Task ignores checks with empty digest."""
        from wafer_space.projects.tasks_revisions import revisions_needs_fetching

        ManufacturabilityCheckFactory(docker_image_digest="")

        with patch(
            "wafer_space.projects.tasks_revisions.do_revision_fetch.delay"
        ) as mock_fetch:
            result = revisions_needs_fetching()

        assert result["new_revisions_queued"] == 0
        mock_fetch.assert_not_called()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_tasks_revisions.py -v`
Expected: FAIL with "No module named 'wafer_space.projects.tasks_revisions'"

**Step 3: Create tasks_revisions.py**

```python
# wafer_space/projects/tasks_revisions.py
"""Celery tasks for precheck image revision tracking."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(queue="none:ro:default")
def revisions_needs_fetching() -> dict[str, int]:
    """Find revisions needing metadata fetch, queue fetch tasks.

    Discovers docker_image_digest values from ManufacturabilityCheck that
    are not yet cataloged in PrecheckImageRevision. Creates stub records
    and queues metadata fetch tasks.

    Returns:
        {"new_revisions_queued": int}
    """
    from wafer_space.projects.models import ManufacturabilityCheck, PrecheckImageRevision

    known_digests = set(
        PrecheckImageRevision.objects.values_list("digest", flat=True)
    )

    new_digests = (
        ManufacturabilityCheck.objects.exclude(docker_image_digest="")
        .exclude(docker_image_digest__in=known_digests)
        .values_list("docker_image_digest", flat=True)
        .distinct()
    )

    queued = 0
    for digest in new_digests:
        PrecheckImageRevision.objects.get_or_create(digest=digest)
        do_revision_fetch.delay(digest)
        queued += 1
        logger.info("Queued metadata fetch for new revision: %s", digest[:20])

    return {"new_revisions_queued": queued}


@shared_task(queue="http:ro:metadata", bind=True, max_retries=3)
def do_revision_fetch(self, digest: str) -> dict[str, Any]:
    """Fetch metadata for a revision from GHCR.

    Retrieves OCI image labels from GitHub Container Registry and
    populates PrecheckImageRevision fields.

    Args:
        digest: The SHA256 digest to fetch metadata for

    Returns:
        {"status": str, "digest": str} or {"error": str}
    """
    from django.utils import timezone

    from wafer_space.projects.models import PrecheckImageRevision

    try:
        revision = PrecheckImageRevision.objects.get(digest=digest)
    except PrecheckImageRevision.DoesNotExist:
        return {"error": f"Revision not found: {digest}"}

    if revision.metadata_fetched_at:
        return {"status": "already_fetched", "digest": digest}

    try:
        metadata = _fetch_ghcr_metadata(digest)

        revision.image_created_at = metadata.get("image_created_at")
        revision.git_commit_sha = metadata.get("git_commit_sha", "")
        revision.precheck_version = metadata.get("precheck_version", "")
        revision.metadata_fetched_at = timezone.now()
        revision.save()

        logger.info("Fetched metadata for revision: %s", digest[:20])
        return {"status": "success", "digest": digest}

    except Exception as exc:
        logger.warning("Failed to fetch metadata for %s: %s", digest[:20], exc)
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries))


def _fetch_ghcr_metadata(digest: str) -> dict[str, Any]:
    """Fetch metadata from GHCR API.

    Args:
        digest: SHA256 digest of the image

    Returns:
        Dict with image_created_at, git_commit_sha, precheck_version
    """
    import requests
    from datetime import datetime

    # Get anonymous token
    token_resp = requests.get(
        "https://ghcr.io/token?scope=repository:wafer-space/gf180mcu-precheck:pull",
        timeout=30,
    )
    token_resp.raise_for_status()
    token = token_resp.json()["token"]

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.oci.image.manifest.v1+json",
    }

    # Get manifest
    manifest_url = f"https://ghcr.io/v2/wafer-space/gf180mcu-precheck/manifests/{digest}"
    manifest_resp = requests.get(manifest_url, headers=headers, timeout=30)
    manifest_resp.raise_for_status()
    manifest = manifest_resp.json()

    # Get config blob containing labels
    config_digest = manifest.get("config", {}).get("digest")
    if not config_digest:
        return {}

    blob_url = f"https://ghcr.io/v2/wafer-space/gf180mcu-precheck/blobs/{config_digest}"
    blob_resp = requests.get(blob_url, headers=headers, timeout=30)
    blob_resp.raise_for_status()
    config = blob_resp.json()

    labels = config.get("config", {}).get("Labels", {})

    # Parse timestamp
    created_str = labels.get("org.opencontainers.image.created")
    image_created_at = None
    if created_str:
        try:
            image_created_at = datetime.fromisoformat(
                created_str.replace("Z", "+00:00")
            )
        except ValueError:
            pass

    return {
        "image_created_at": image_created_at,
        "git_commit_sha": labels.get("org.opencontainers.image.revision", ""),
        "precheck_version": labels.get("org.opencontainers.image.version", ""),
    }
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_tasks_revisions.py -v`
Expected: PASS

**Step 5: Lint and commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/tasks_revisions.py wafer_space/projects/tests/test_tasks_revisions.py
git commit -m "feat: add Celery tasks for revision discovery and metadata fetch

- revisions_needs_fetching: discovers new digests, queues fetch
- do_revision_fetch: fetches metadata from GHCR API
- _fetch_ghcr_metadata: GHCR API integration"
```

---

## Task 6: Add Celery Beat Schedule

**Files:**
- Modify: `config/settings/base.py`

**Step 1: Add beat schedule entry**

Add to `CELERY_BEAT_SCHEDULE` in `config/settings/base.py`:

```python
    # Precheck revision tracking
    "revisions-needs-fetching": {
        "task": "wafer_space.projects.tasks_revisions.revisions_needs_fetching",
        "schedule": 300.0,  # Every 5 minutes
    },
```

**Step 2: Commit**

```bash
make lint-fix && make lint
git add config/settings/base.py
git commit -m "feat: add Celery beat schedule for revision discovery

Runs revisions_needs_fetching every 5 minutes to discover and
catalog new precheck image revisions."
```

---

## Task 7: Create http:ro:metadata Systemd Service

**Files:**
- Create: `deployment/systemd/django-celery-http-ro-metadata.service`
- Modify: `deployment/systemd/install.sh`

**Step 1: Create service file**

```ini
# deployment/systemd/django-celery-http-ro-metadata.service
[Unit]
Description=platform.wafer.space Celery Worker (http:ro:metadata)
After=network.target postgresql.service django-gunicorn.service
Requires=postgresql.service

[Service]
Type=forking
User=www-data
Group=www-data
WorkingDirectory=/home/django/platform.wafer.space
EnvironmentFile=/home/django/platform.wafer.space/.env

# Isolated runtime and log directories (created automatically)
RuntimeDirectory=platform.wafer.space-celery-http-ro-metadata
RuntimeDirectoryMode=0750
LogsDirectory=platform.wafer.space-celery-http-ro-metadata
LogsDirectoryMode=0750

PIDFile=/run/platform.wafer.space-celery-http-ro-metadata/worker.pid

ExecStart=/home/django/platform.wafer.space/.venv/bin/celery \
    -A config \
    worker \
    --loglevel=info \
    --logfile=${LOGS_DIRECTORY}/worker.log \
    --pidfile=${RUNTIME_DIRECTORY}/worker.pid \
    --detach \
    --queues=http:ro:metadata \
    --hostname=http-ro-metadata@%h

ExecStop=/bin/kill -s TERM $MAINPID
ExecReload=/bin/kill -s HUP $MAINPID

# Startup timeout - give celery time to write PID file
TimeoutStartSec=30s

# Security hardening
# Queue: http:ro:metadata - metadata fetch from GHCR API
# Network: http - HTTPS traffic to ghcr.io and api.github.com
# Filesystem: ro - no writes needed, only fetches metadata
NoNewPrivileges=true
PrivateDevices=true
PrivateTmp=true
ProtectSystem=strict
ReadOnlyPaths=/home/django/platform.wafer.space

# Restart policy
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
```

**Step 2: Update install.sh to include new service**

Check if install.sh lists services explicitly and add the new one.

**Step 3: Commit**

```bash
git add deployment/systemd/django-celery-http-ro-metadata.service deployment/systemd/install.sh
git commit -m "feat: add http:ro:metadata Celery worker systemd service

New worker for fetching precheck revision metadata from GHCR.
Read-only HTTP access, no filesystem writes needed."
```

---

## Task 8: Create Template Tags for Badges

**Files:**
- Create: `wafer_space/projects/templatetags/__init__.py`
- Create: `wafer_space/projects/templatetags/precheck_tags.py`
- Create: `wafer_space/projects/tests/test_templatetags.py`

**Step 1: Create templatetags directory**

```bash
mkdir -p wafer_space/projects/templatetags
touch wafer_space/projects/templatetags/__init__.py
```

**Step 2: Write the failing tests**

```python
# wafer_space/projects/tests/test_templatetags.py
from __future__ import annotations

import pytest
from django.template import Context, Template

from wafer_space.projects.models import PrecheckImageRevision
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory


@pytest.mark.django_db
class TestPrecheckBadgeTemplateTags:
    """Tests for precheck badge template tags."""

    def test_badge_precheck_status_renders(self):
        """badge_precheck_status renders without error."""
        check = ManufacturabilityCheckFactory(
            docker_image_digest="sha256:abc123def456789012345678901234567890123456789012345678901234"
        )
        template = Template(
            "{% load precheck_tags %}{% badge_precheck_status check %}"
        )
        context = Context({"check": check})
        result = template.render(context)

        assert "badge" in result
        assert "bi-" in result  # Bootstrap icon

    def test_badge_precheck_status_none_check(self):
        """badge_precheck_status handles None check."""
        template = Template(
            "{% load precheck_tags %}{% badge_precheck_status check %}"
        )
        context = Context({"check": None})
        result = template.render(context)

        assert "No check" in result

    def test_badge_precheck_version_renders(self):
        """badge_precheck_version renders version string."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234",
            precheck_version="1.5.2",
        )
        check = ManufacturabilityCheckFactory(docker_image_digest=revision.digest)

        template = Template(
            "{% load precheck_tags %}{% badge_precheck_version check %}"
        )
        context = Context({"check": check})
        result = template.render(context)

        assert "v1.5.2" in result
        assert "bi-cloud" in result

    def test_badge_precheck_version_fallback_to_commit(self):
        """badge_precheck_version falls back to git commit when no version."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234",
            git_commit_sha="a261f14ae7f90a0f74c6db18f28eeafce9b6e803",
        )
        check = ManufacturabilityCheckFactory(docker_image_digest=revision.digest)

        template = Template(
            "{% load precheck_tags %}{% badge_precheck_version check %}"
        )
        context = Context({"check": check})
        result = template.render(context)

        assert "a261f14" in result

    def test_badge_precheck_version_fallback_to_unknown(self):
        """badge_precheck_version shows ???? when no version info."""
        check = ManufacturabilityCheckFactory(
            docker_image_digest="sha256:uncataloged123456789012345678901234567890123456789012"
        )

        template = Template(
            "{% load precheck_tags %}{% badge_precheck_version check %}"
        )
        context = Context({"check": check})
        result = template.render(context)

        assert "????" in result

    def test_badge_precheck_combined_renders(self):
        """badge_precheck_combined renders status and version."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234",
            precheck_version="1.5.2",
        )
        check = ManufacturabilityCheckFactory(
            docker_image_digest=revision.digest,
            result="PASSED",
        )

        template = Template(
            "{% load precheck_tags %}{% badge_precheck_combined check %}"
        )
        context = Context({"check": check})
        result = template.render(context)

        assert "Passed" in result
        assert "v1.5.2" in result
```

**Step 3: Run test to verify it fails**

Run: `uv run pytest wafer_space/projects/tests/test_templatetags.py -v`
Expected: FAIL with "No module named 'wafer_space.projects.templatetags.precheck_tags'"

**Step 4: Create precheck_tags.py**

```python
# wafer_space/projects/templatetags/precheck_tags.py
"""Template tags for precheck badge rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import SafeString

if TYPE_CHECKING:
    from wafer_space.projects.models import ManufacturabilityCheck, PrecheckImageRevision

register = template.Library()


@register.simple_tag
def badge_precheck_status(check: "ManufacturabilityCheck | None") -> SafeString:
    """Render precheck status badge with version indicator.

    Usage: {% badge_precheck_status check %}
    """
    if not check:
        return format_html(
            '<span class="badge bg-light text-muted border">No check</span>'
        )

    url = reverse("admin:projects_manufacturabilitycheck_change", args=[check.pk])
    icon, label, bg_class = _get_status_display(check)
    version_indicator = _get_version_indicator_html(check)

    return format_html(
        '<a href="{}" class="badge {} text-decoration-none">'
        '<i class="bi bi-{}"></i> {}{}</a>',
        url,
        bg_class,
        icon,
        label,
        version_indicator,
    )


@register.simple_tag
def badge_precheck_version(check: "ManufacturabilityCheck | None") -> SafeString:
    """Render precheck version-only badge.

    Usage: {% badge_precheck_version check %}
    """
    if not check or not check.docker_image_digest:
        return format_html("")

    revision = check.precheck_revision
    version_str = _get_version_string(check, revision)
    is_latest = check.is_using_latest_precheck
    icon, icon_class = _get_version_icon(is_latest)

    if is_latest:
        bg_class = "bg-success-subtle text-success border-success"
    else:
        bg_class = "bg-warning-subtle text-warning-emphasis border-warning"

    if revision and revision.github_commit_url:
        return format_html(
            '<a href="{}" class="badge {} border text-decoration-none" target="_blank">'
            '{} <i class="bi bi-{} {}"></i></a>',
            revision.github_commit_url,
            bg_class,
            version_str,
            icon,
            icon_class,
        )

    return format_html(
        '<span class="badge {} border">'
        '{} <i class="bi bi-{} {}"></i></span>',
        bg_class,
        version_str,
        icon,
        icon_class,
    )


@register.simple_tag
def badge_precheck_combined(check: "ManufacturabilityCheck | None") -> SafeString:
    """Render combined status + version badge.

    Usage: {% badge_precheck_combined check %}
    """
    if not check:
        return format_html(
            '<span class="badge bg-light text-muted border">No check</span>'
        )

    url = reverse("admin:projects_manufacturabilitycheck_change", args=[check.pk])
    icon, label, bg_class = _get_status_display(check)

    if check.docker_image_digest:
        revision = check.precheck_revision
        version_str = _get_version_string(check, revision)
        is_latest = check.is_using_latest_precheck
        version_icon, version_icon_class = _get_version_icon(is_latest)
        version_part = format_html(
            ' | {} <i class="bi bi-{} {}"></i>',
            version_str,
            version_icon,
            version_icon_class,
        )
    else:
        version_part = ""

    return format_html(
        '<a href="{}" class="badge {} text-decoration-none">'
        '<i class="bi bi-{}"></i> {}{}</a>',
        url,
        bg_class,
        icon,
        label,
        version_part,
    )


# --- Helper functions ---


def _get_status_display(
    check: "ManufacturabilityCheck",
) -> tuple[str, str, str]:
    """Return (icon, label, bg_class) for check status."""
    if check.result == "PASSED":
        return ("check-circle", "Passed", "bg-success")
    elif check.result == "FAILED":
        return ("x-circle", "Failed", "bg-danger")
    elif check.status in ("RUNNING", "ANALYZING"):
        return ("gear", "Running", "bg-primary")
    elif check.status in ("PENDING", "DISPATCHING", "STARTING"):
        return ("hourglass-split", "Queued", "bg-warning text-dark")
    elif check.status == "ERROR":
        return ("exclamation-circle", "Error", "bg-danger")
    elif check.status == "CANCELLED":
        return ("slash-circle", "Cancelled", "bg-secondary")
    return ("question", str(check.status), "bg-secondary")


def _get_version_indicator_html(check: "ManufacturabilityCheck") -> SafeString:
    """Return HTML for version indicator icon."""
    if not check.docker_image_digest:
        return format_html("")

    is_latest = check.is_using_latest_precheck
    icon, icon_class = _get_version_icon(is_latest)
    return format_html(' <i class="bi bi-{} {}"></i>', icon, icon_class)


def _get_version_icon(is_latest: bool | None) -> tuple[str, str]:
    """Return (icon_name, css_class) for version status."""
    if is_latest is True:
        return ("cloud-check-fill", "text-success")
    elif is_latest is False:
        return ("cloud-arrow-up-fill", "text-warning")
    return ("cloud", "text-muted")


def _get_version_string(
    check: "ManufacturabilityCheck",
    revision: "PrecheckImageRevision | None",
) -> str:
    """Return version string for badge display."""
    if revision:
        if revision.precheck_version:
            return f"v{revision.precheck_version}"
        if revision.git_commit_sha:
            return revision.git_commit_sha[:7]
    return "????"
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest wafer_space/projects/tests/test_templatetags.py -v`
Expected: PASS

**Step 6: Lint and commit**

```bash
make lint-fix && make lint && make type-check
git add wafer_space/projects/templatetags/
git add wafer_space/projects/tests/test_templatetags.py
git commit -m "feat: add precheck badge template tags

- badge_precheck_status: status with version indicator
- badge_precheck_version: version-only badge
- badge_precheck_combined: status + version combined

Uses cloud icons for version status (distinct from status icons)"
```

---

## Task 9: Update _manufacturability_check.html (Issue #201)

**Files:**
- Modify: `wafer_space/templates/projects/_manufacturability_check.html`

**Step 1: Add template tag load and version badge**

At the top of the file, add:

```django
{% load precheck_tags %}
```

Find the Docker Info section (around line 480-491, after the Digest row) and add:

```django
<tr>
  <td>
    <strong>Version:</strong>
  </td>
  <td>
    {% badge_precheck_version check %}
  </td>
</tr>
```

**Step 2: Test manually by running dev server**

```bash
make runserver
# Visit a project with a manufacturability check
```

**Step 3: Commit**

```bash
git add wafer_space/templates/projects/_manufacturability_check.html
git commit -m "feat: add version badge to manufacturability check display (#201)

Shows precheck version with latest/outdated indicator in Docker Info section."
```

---

## Task 10: Update manufacturability_check_status.html (Issue #202)

**Files:**
- Modify: `wafer_space/templates/projects/manufacturability_check_status.html`
- Modify: `wafer_space/projects/views.py` (if context changes needed)

**Step 1: Add template tag load**

At the top of the file, add:

```django
{% load precheck_tags %}
```

**Step 2: Add server/container columns to running checks table**

Find the running checks table header and add columns:

```django
<th>Server</th>
<th>Container</th>
```

And in the row:

```django
<td><code>{{ check.docker_server_id|default:"-" }}</code></td>
<td>
  <code title="{{ check.docker_container_id }}">
    {{ check.docker_container_id|truncatechars:12|default:"-" }}
  </code>
</td>
```

**Step 3: Add queue position to pending checks**

Add to pending checks table:

```django
<td>
  <span class="badge bg-secondary">#{{ forloop.counter }}</span>
</td>
```

**Step 4: Commit**

```bash
git add wafer_space/templates/projects/manufacturability_check_status.html
git commit -m "feat: add server/container info and queue position to check status (#202)"
```

---

## Task 11: Update assignment_dashboard.html (Issue #203)

**Files:**
- Modify: `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`

**Step 1: Add template tag load**

```django
{% load precheck_tags %}
```

**Step 2: Replace status badge with combined badge**

Find the status column (around line 137-144) and replace with:

```django
<td data-sort-value="{% if project.is_manufacturable %}0{% elif project.is_manufacturable is None %}2{% else %}1{% endif %}">
  {% with check=project.latest_manufacturability_check %}
    {% badge_precheck_combined check %}
  {% endwith %}
</td>
```

**Step 3: Commit**

```bash
git add wafer_space/shuttles/templates/shuttles/assignment_dashboard.html
git commit -m "feat: use combined precheck badge on slot allocation page (#203)"
```

---

## Task 12: Update admin_summary.html (Issue #204)

**Files:**
- Modify: `wafer_space/templates/projects/admin_summary.html`
- Modify: `wafer_space/projects/views.py` (add context)

**Step 1: Add version summary to view context**

Find the view that renders admin_summary.html and add to context:

```python
from wafer_space.projects.models import ManufacturabilityCheck

latest_digest = ManufacturabilityCheck.get_latest_precheck_digest()
# ... add to context
```

**Step 2: Add version summary card to template**

Add after the existing summary cards:

```django
<!-- Precheck Version Summary -->
<div class="col-md-4">
  <div class="card">
    <div class="card-header">
      <strong>Precheck Version</strong>
    </div>
    <div class="card-body">
      <div class="small text-muted">
        <strong>Current:</strong>
        <code>{{ latest_digest|truncatechars:20|default:"None" }}</code>
      </div>
    </div>
  </div>
</div>
```

**Step 3: Commit**

```bash
git add wafer_space/templates/projects/admin_summary.html wafer_space/projects/views.py
git commit -m "feat: add precheck version summary to admin summary page (#204)"
```

---

## Task 13: Update Deployment Documentation

**Files:**
- Modify: `deployment/README.md`

**Step 1: Add http:ro:metadata queue documentation**

Add section about the new queue:

```markdown
### http:ro:metadata Queue

The `http:ro:metadata` queue handles fetching precheck revision metadata from GHCR.

**Service:** `django-celery-http-ro-metadata.service`
**Access:** HTTP (read-only to ghcr.io)
**Tasks:** `do_revision_fetch`
```

**Step 2: Commit**

```bash
git add deployment/README.md
git commit -m "docs: add http:ro:metadata queue to deployment documentation"
```

---

## Task 14: Run Full Test Suite

**Step 1: Run all checks**

```bash
make check-all
```

**Step 2: Fix any issues**

**Step 3: Final commit if needed**

---

## Summary

| Task | Component | Files |
|------|-----------|-------|
| 1 | PrecheckImageRevision model | models.py, migrations, tests |
| 2 | Statistics methods | models.py, tests |
| 3 | Latest digest methods | models.py, tests |
| 4 | Admin registration | admin.py |
| 5 | Celery tasks | tasks_revisions.py, tests |
| 6 | Beat schedule | base.py |
| 7 | Systemd service | deployment/systemd/ |
| 8 | Template tags | templatetags/, tests |
| 9 | Issue #201 | _manufacturability_check.html |
| 10 | Issue #202 | manufacturability_check_status.html |
| 11 | Issue #203 | assignment_dashboard.html |
| 12 | Issue #204 | admin_summary.html, views.py |
| 13 | Documentation | deployment/README.md |
| 14 | Final verification | make check-all |
