# DRC Update Requeue Design

Automatically re-check projects when a new precheck container version is deployed.

## Overview

When a new precheck Docker image is released, projects that were previously checked with older versions should be re-validated against the latest DRC rules. This design covers:

1. A periodic task that automatically queues re-checks
2. A manual button for users to trigger re-checks
3. Shared logic between both pathways
4. Supporting infrastructure changes

## Components

### 1. PrecheckImageRevision Changes

Add `version_display` property and `format_version_display()` classmethod with caching:

```python
@property
def version_display(self) -> str:
    """Version string for display."""
    return self.precheck_version or self.git_commit_sha[:7] or self.short_digest

@classmethod
def format_version_display(
    cls, check_or_digest: "ManufacturabilityCheck | str | None"
) -> tuple[str, bool | None]:
    """Format version display string and is_latest flag for a check or digest."""
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
    display = revision.version_display if revision else f"sha256:{digest[7:19]}..."

    cache.set(cache_key, display, 60)
    return (display, is_latest)
```

### 2. ManufacturabilityCheck.create_check_drc_update()

Shared method for creating DRC_UPDATE checks:

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

### 3. Periodic Task: checks_drc_update_requeue

Runs every 60 seconds, creates one DRC_UPDATE check per run if capacity allows:

```python
@checks_task()
def checks_drc_update_requeue() -> dict:
    """Create DRC_UPDATE checks for projects with outdated precheck versions.

    Finds projects where the latest check is FINISHED but used an outdated
    docker image digest, and creates new pending checks. Rate-limited to 25%
    of total capacity for DRC_UPDATE checks.
    """
    from collections import defaultdict

    latest_digest = ManufacturabilityCheck.get_latest_precheck_digest()
    if not latest_digest:
        return {"skipped": "no_latest_digest"}

    # Get latest check per project
    latest_checks = (
        ManufacturabilityCheck.objects
        .filter(project_file__project__isnull=False)
        .order_by("project_file__project_id", "-created_at")
        .distinct("project_file__project_id")
        .select_related("project_file", "project_file__project")
    )

    # Collect stats and find outdated FINISHED checks
    stats = {
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
            version_key = PrecheckImageRevision.format_version_display(check)[0]
            stats["finished"][version_key] += 1

            if check.docker_image_digest and check.docker_image_digest != latest_digest:
                outdated_checks.append(check)

    # Sort by oldest first
    outdated_checks.sort(key=lambda c: c.created_at)

    # Calculate DRC_UPDATE capacity limit (25% of total)
    total_capacity = sum(server["max_concurrent"] for server in settings.DOCKER_SERVERS)
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

    return {
        "stats": dict(stats),
        "drc_update_limit": drc_update_limit,
        "drc_update_active": active_drc_updates,
        "drc_update_available": drc_update_available,
        "outdated_count": len(outdated_checks),
        "created": created,
    }
```

### 4. Manual Requeue View

```python
@login_required
def check_drc_update_requeue(request, check_id):
    """Manually trigger a DRC_UPDATE check for outdated precheck version."""
    check = get_object_or_404(ManufacturabilityCheck, pk=check_id)

    # Permission: must own the project or be staff
    if check.project.user != request.user and not request.user.is_staff:
        raise PermissionDenied

    try:
        new_check = check.create_check_drc_update()
        messages.success(request, "Check queued with latest precheck version.")
    except ValueError as e:
        messages.error(request, str(e))

    return redirect("projects:detail", pk=check.project.pk)
```

### 5. Template Button

When `check.is_using_latest_precheck is False`:

```html
<form method="post" action="{% url 'projects:check_drc_update_requeue' check.id %}">
    {% csrf_token %}
    <button type="submit" class="btn btn-sm btn-outline-warning">
        <i class="bi bi-arrow-repeat"></i> Recheck with Latest
    </button>
</form>
```

### 6. Templatetag Updates

Update `precheck_tags.py` to use `format_version_display()`:

- Remove `_get_version_string` helper
- Update `badge_check_version` to use `PrecheckImageRevision.format_version_display(check)`
- Update `badge_check_status_and_version` similarly
- Simplify `get_latest_precheck_version` to one line

### 7. Beat Schedule

Add to `config/settings/base.py`:

```python
CELERY_BEAT_SCHEDULE = {
    # ... existing tasks ...

    "checks-drc-update-requeue": {
        "task": "wafer_space.projects.tasks_checks.checks_drc_update_requeue",
        "schedule": 60.0,  # Every 60 seconds
    },
}
```

## Documentation Updates

1. `docs/celery_tasks_reference.md` - Add task to Orchestration Tasks table, update counts
2. `docs/celery_architecture.md` - Add to Cleanup & Recovery table
3. `docs/systemd-services.md` - Add to both task lists

**Separate GitHub issue:** Update `docs/manufacturability_checking.md` (out of date)

## Tests

### Task Tests (`test_tasks.py`)

1. `test_checks_drc_update_requeue_creates_check_for_outdated_digest`
2. `test_checks_drc_update_requeue_skips_when_no_latest_digest`
3. `test_checks_drc_update_requeue_skips_when_at_capacity`
4. `test_checks_drc_update_requeue_skips_current_version_checks`
5. `test_checks_drc_update_requeue_skips_in_progress_checks`
6. `test_checks_drc_update_requeue_creates_only_one_per_run`
7. `test_checks_drc_update_requeue_sets_parent_check`
8. `test_checks_drc_update_requeue_orders_by_oldest_first`
9. `test_checks_drc_update_requeue_returns_stats`

### Model Method Tests (`test_models.py` or `test_services.py`)

1. `test_create_check_drc_update_success`
2. `test_create_check_drc_update_fails_not_latest_check`
3. `test_create_check_drc_update_fails_no_digest`
4. `test_create_check_drc_update_fails_already_latest`
5. `test_create_check_drc_update_sets_parent_and_trigger_reason`

### PrecheckImageRevision Tests (`test_precheck_revision.py`)

1. `test_format_version_display_with_check`
2. `test_format_version_display_with_digest_string`
3. `test_format_version_display_with_none`
4. `test_format_version_display_caches_result`
5. `test_format_version_display_fallback_to_short_digest`

### View Tests (`test_views.py`)

1. `test_check_drc_update_requeue_success`
2. `test_check_drc_update_requeue_permission_denied`
3. `test_check_drc_update_requeue_invalid_check`

## Summary

| Component | File | Changes |
|-----------|------|---------|
| PrecheckImageRevision | models.py | Add `version_display`, `format_version_display()` |
| ManufacturabilityCheck | models.py | Add `create_check_drc_update()` |
| Periodic task | tasks_checks.py | Add `checks_drc_update_requeue` |
| View | views.py | Add `check_drc_update_requeue` |
| URL | urls.py | Add route for manual requeue |
| Template | templates | Add requeue button |
| Templatetags | precheck_tags.py | Use `format_version_display()` |
| Settings | base.py | Add beat schedule entry |
| Docs | 3 files | Update task lists |
