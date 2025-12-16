# Container Version Tracking Design

**Date:** 2025-12-12
**Issues:** #191, #201, #202, #203, #204, #88
**Branch:** `feature/container-version-tracking`

## Summary

Track Docker precheck image revisions and display version status across the platform, helping users understand if their manufacturability check results are current or if they should re-run with a newer container version.

## Goals

1. Track which precheck image version each ManufacturabilityCheck used
2. Show whether a check used the "latest" version (most recently seen)
3. Display version status consistently across all relevant pages
4. Fetch and display metadata from GHCR (git commit, precheck version)

## Architecture Decisions

### No Foreign Key Relationship

`ManufacturabilityCheck` does **not** have a FK to `PrecheckImageRevision`. Instead:

- Checks store `docker_image_digest` (already exists)
- Revisions are linked by digest string match
- This decouples check execution from revision cataloging

**Rationale:** Check execution should not depend on or modify the revision catalog. The catalog is populated asynchronously after checks complete.

### "Latest" Is a Query, Not a Flag

"Latest" = the digest used by the most recently started check.

```python
ManufacturabilityCheck.objects
    .exclude(docker_image_digest='')
    .order_by('-container_started_at')
    .values_list('docker_image_digest', flat=True)
    .first()
```

No `is_latest` flag on `PrecheckImageRevision`. When a new check starts with a different digest, that digest becomes "latest" automatically.

### Asynchronous Metadata Fetching

When a check runs with a new digest:
1. Check completes normally (unchanged behavior)
2. Periodic task discovers the new digest
3. Background task fetches metadata from GHCR
4. `PrecheckImageRevision` record is populated

Check execution never blocks on or triggers metadata fetching.

---

## Data Model

### PrecheckImageRevision

New model in `wafer_space/projects/models.py`:

```python
PRECHECK_GITHUB_REPO = "wafer-space/gf180mcu-precheck"


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
        help_text="SHA256 digest (e.g., sha256:abc123...)"
    )

    # When we first saw this digest used in a check
    first_seen_at = models.DateTimeField(auto_now_add=True)

    # Metadata fetched from GHCR/GitHub
    image_created_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the image was pushed to GHCR"
    )
    git_commit_sha = models.CharField(
        max_length=40, blank=True,
        help_text="Git commit from image labels"
    )

    # Version information
    precheck_version = models.CharField(
        max_length=50, blank=True,
        help_text="Precheck tool version (e.g., 1.5.2)"
    )
    pdk_version = models.CharField(
        max_length=50, blank=True,
        help_text="PDK version (if available)"
    )
    tool_versions = models.JSONField(
        default=dict, blank=True,
        help_text="Tool versions dict (Issue #88)"
    )

    # Tracking
    metadata_fetched_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When GHCR metadata was last fetched"
    )

    class Meta:
        ordering = ['-first_seen_at']
        indexes = [
            models.Index(fields=['digest']),
            models.Index(fields=['-first_seen_at']),
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

    # --- Statistics helpers ---

    def _get_checks_queryset(self):
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
        """Get average and max run duration for checks using this revision."""
        from django.db.models import Avg, Max, F

        completed = self._get_checks_queryset().filter(
            status=ManufacturabilityCheck.Status.FINISHED,
            container_started_at__isnull=False,
            container_finished_at__isnull=False,
        )

        stats = completed.aggregate(
            avg_duration=Avg(F('container_finished_at') - F('container_started_at')),
            max_duration=Max(F('container_finished_at') - F('container_started_at')),
        )

        return {
            "average": stats['avg_duration'].total_seconds() if stats['avg_duration'] else None,
            "max": stats['max_duration'].total_seconds() if stats['max_duration'] else None,
        }
```

### ManufacturabilityCheck Additions

Add methods to existing model:

```python
class ManufacturabilityCheck(models.Model):
    # ... existing fields ...

    @classmethod
    def get_latest_precheck_digest(cls) -> str | None:
        """Get the digest of the most recently used precheck image."""
        from django.core.cache import cache

        cache_key = "precheck_latest_digest"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached or None

        digest = (
            cls.objects
            .exclude(docker_image_digest='')
            .order_by('-container_started_at')
            .values_list('docker_image_digest', flat=True)
            .first()
        )

        cache.set(cache_key, digest or "", 60)  # 1 minute TTL
        return digest

    @property
    def is_using_latest_precheck(self) -> bool | None:
        """Whether this check used the latest precheck image version."""
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

---

## Celery Tasks

### New Queue: `http:ro:metadata`

Create `deployment/systemd/django-celery-http-ro-metadata.service`:

- Runs as `www-data`
- HTTP access for GHCR API calls
- No filesystem write access needed (read-only)

### Task: `revisions_needs_fetching`

Periodic task on `none:ro:default` queue:

```python
@shared_task(queue="none:ro:default")
def revisions_needs_fetching() -> dict[str, int]:
    """Find revisions needing metadata fetch, queue fetch tasks."""
    known_digests = set(
        PrecheckImageRevision.objects.values_list('digest', flat=True)
    )

    new_digests = (
        ManufacturabilityCheck.objects
        .exclude(docker_image_digest='')
        .exclude(docker_image_digest__in=known_digests)
        .values_list('docker_image_digest', flat=True)
        .distinct()
    )

    queued = 0
    for digest in new_digests:
        PrecheckImageRevision.objects.get_or_create(digest=digest)
        do_revision_fetch.delay(digest)
        queued += 1

    return {"new_revisions_queued": queued}
```

### Task: `do_revision_fetch`

Action task on `http:ro:metadata` queue:

```python
@shared_task(queue="http:ro:metadata", bind=True, max_retries=3)
def do_revision_fetch(self, digest: str) -> dict[str, Any]:
    """Fetch metadata for a revision from GHCR."""
    # ... implementation fetches from GHCR API ...
```

### Celery Beat Schedule

```python
"revisions-needs-fetching": {
    "task": "wafer_space.projects.tasks_revisions.revisions_needs_fetching",
    "schedule": 300.0,  # Every 5 minutes
},
```

---

## GHCR Integration

### Available OCI Labels

Current labels on `ghcr.io/wafer-space/gf180mcu-precheck:latest`:

| Label | Example Value | Maps To |
|-------|---------------|---------|
| `org.opencontainers.image.created` | `2025-12-11T14:37:47.886Z` | `image_created_at` |
| `org.opencontainers.image.revision` | `a261f14ae7f90a0f74c6db18f28eeafce9b6e803` | `git_commit_sha` |
| `org.opencontainers.image.version` | `1.5.2` | `precheck_version` |

Tool versions are not currently in labels (see Issue #88).

### API Flow

1. Get anonymous token from `https://ghcr.io/token?scope=repository:wafer-space/gf180mcu-precheck:pull`
2. Fetch manifest index for digest
3. Get config blob containing labels
4. Extract and store metadata

---

## UI Components

### Template Tags

Create `wafer_space/projects/templatetags/precheck_tags.py`:

```python
@register.simple_tag
def badge_precheck_status(check):
    """Render status badge with version indicator."""
    # Returns: [<icon> Passed <cloud-icon>]

@register.simple_tag
def badge_precheck_version(check):
    """Render version-only badge."""
    # Returns: [v1.5.2 <cloud-icon>]

@register.simple_tag
def badge_precheck_combined(check):
    """Render combined status + version badge."""
    # Returns: [<icon> Passed | v1.5.2 <cloud-icon>]
```

### Version Display Logic

```python
def _get_version_string(check, revision) -> str:
    """Return version string for badge display."""
    if revision:
        if revision.precheck_version:
            return f"v{revision.precheck_version}"  # e.g., "v1.5.2"
        if revision.git_commit_sha:
            return revision.git_commit_sha[:7]  # e.g., "a261f14"
    return "????"  # No version info available
```

### Version Status Icons

Using Bootstrap Icons (cloud family for visual distinction from status icons):

| Status | Icon | Meaning |
|--------|------|---------|
| Latest | `bi-cloud-check-fill` (green) | Using current version |
| Outdated | `bi-cloud-arrow-up-fill` (warning) | Newer version available |

### Badge Examples

| Scenario | Output |
|----------|--------|
| Passed, latest | `[✓ Passed | v1.5.2 ☁✓]` |
| Passed, outdated | `[✓ Passed | v1.5.2 ☁↑]` |
| Running, latest | `[⚙ Running | a261f14 ☁✓]` |
| No revision info | `[✓ Passed | ???? ☁✓]` |

Badges link to:
- Status portion → ManufacturabilityCheck admin page
- Version portion → GitHub commit (if available)

---

## Template Changes

### Issue #201: `_manufacturability_check.html`

Add version badge in Docker Info section after digest row.

### Issue #202: `manufacturability_check_status.html`

- Add current container version summary card
- Add server/container columns to running checks table
- Add queue position to pending checks

### Issue #203: `assignment_dashboard.html`

Replace simple status badge with combined badge showing version:

```django
{% load precheck_tags %}
{% badge_precheck_combined project.latest_manufacturability_check %}
```

### Issue #204: `admin_summary.html`

Add precheck version summary card showing:
- Checks using latest count
- Checks outdated count
- Current latest digest

---

## Files to Create/Modify

### New Files

| File | Purpose |
|------|---------|
| `wafer_space/projects/tasks_revisions.py` | Revision discovery and fetch tasks |
| `wafer_space/projects/templatetags/precheck_tags.py` | Badge template tags |
| `deployment/systemd/django-celery-http-ro-metadata.service` | New worker service |
| `wafer_space/projects/migrations/XXXX_add_precheck_image_revision.py` | Model migration |

### Modified Files

| File | Changes |
|------|---------|
| `wafer_space/projects/models.py` | Add `PrecheckImageRevision`, methods on `ManufacturabilityCheck` |
| `wafer_space/projects/admin.py` | Register `PrecheckImageRevision` |
| `config/settings/base.py` | Add beat schedule, `GHCR_READ_TOKEN` setting |
| `deployment/systemd/install.sh` | Include new service |
| `deployment/README.md` | Document new queue |
| `wafer_space/templates/projects/_manufacturability_check.html` | Version badge |
| `wafer_space/templates/projects/manufacturability_check_status.html` | Version info, queue position |
| `wafer_space/templates/shuttles/assignment_dashboard.html` | Combined badges |
| `wafer_space/templates/projects/admin_summary.html` | Version summary card |

---

## Implementation Order

1. **Model + Migration** - `PrecheckImageRevision` model
2. **Tasks + Queue** - `revisions_needs_fetching`, `do_revision_fetch`, systemd service
3. **Template Tags** - `badge_precheck_*` tags
4. **UI Updates** - Templates for issues #201, #202, #203, #204
5. **Tests** - Model tests, task tests (with mocked GHCR)
6. **Documentation** - Update deployment docs

---

## Out of Scope (Future Work)

- **Issue #88:** Extracting tool versions from Docker image (requires running container or additional labels)
- **Multiple PDK support:** Currently hardcoded to `gf180mcu-precheck`
- **Re-run suggestions:** UI to suggest re-running outdated checks
- **Notifications:** Alerting when many checks use outdated versions
