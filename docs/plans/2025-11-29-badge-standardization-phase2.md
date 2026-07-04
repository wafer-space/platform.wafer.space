# Badge Standardization Phase 2 - Design Document

**Date:** 2025-11-29
**Status:** Approved
**Branch:** `feature/badge-standardization` (extends existing work)

## Overview

Complete the badge standardization effort started in `feature/badge-standardization` by converting all remaining hardcoded badges to use the unified badge system.

## Existing Foundation (Phase 1 - Complete)

The branch already includes:
- `BadgeType` enum and `BadgeInfo` dataclass in `wafer_space/core/badges.py`
- `{% render_badge badge %}` template tag
- `_badge.html` template partial
- `ManufacturabilityCheck.get_badge()` method
- `ProjectFile.get_download_badge()`, `get_hash_badge()`, `get_manufacturability_badge()`, `get_badges()` methods
- `Project.get_badges()` method (delegates to active file)
- Updated `_file_badges.html` template
- Status badges added to `project_list.html`

## Phase 2 Scope

### Templates to Convert

| Template | Current Issue | Solution |
|----------|---------------|----------|
| `_download_attempt.html:19` | Hardcoded status badge | Use `DownloadAttempt.get_badge()` |
| `project_detail.html:43` | Hardcoded project status | Use `Project.get_status_badge()` |
| `compliance_certification_form.html:135` | Hardcoded project status | Use `Project.get_status_badge()` |
| `manufacturability_check_status.html:174-210` | Hardcoded check badges | Use existing `ManufacturabilityCheck.get_badge()` |
| `notification_list.html:55` | Hardcoded notification type badge | Use `Notification.get_type_badge()` |
| `_file_display.html:72-138, 323-359` | Hardcoded file status badges | Use existing `ProjectFile` badge methods |
| `project_detail.html` JS (291-318) | Duplicated badge logic in JavaScript | Server-rendered `badge_html` in API response |

### Intentional Exclusions

| Location | Reason |
|----------|--------|
| `allauth/elements/badge.html` | Third-party template override |
| `project_list.html:29,31` | Ownership indicators ("Your Project"), not status |
| `_download_attempt.html:17` | "Latest" indicator, not status |
| `notification_list.html:31` | Unread count (numeric), not status |

### New Model Methods Required

1. **`DownloadAttempt.get_badge()`** - PENDING/DOWNLOADING/COMPLETED/FAILED status
2. **`Project.get_status_badge()`** - DRAFT/SUBMITTED/MANUFACTURABLE etc.
3. **`Notification.get_type_badge()`** - notification type display

### Future-Proofing (No Templates Yet)

These models have status fields but no templates currently:
- `Shuttle.get_badge()` - PLANNING/OPEN/FULL/LOCKED/IN_PRODUCTION/COMPLETED/CANCELLED
- `ShuttleSlot.get_badge()` - AVAILABLE/RESERVED/OCCUPIED/CANCELLED
- `ReferralEarning.get_badge()` - PENDING/CONFIRMED/PAID/CANCELLED
- `PayoutRequest.get_badge()` - PENDING/PROCESSING/COMPLETED/FAILED/CANCELLED

## Technical Design

### Server-Rendered Badge HTML for AJAX

Add utility function to avoid duplicating render logic:

```python
# wafer_space/core/badges.py
def render_badge_html(badge: BadgeInfo) -> str:
    """Render a BadgeInfo to HTML string for AJAX responses."""
    from django.template.loader import render_to_string
    from wafer_space.core.templatetags.badges import BADGE_CSS_MAP

    return render_to_string("core/_badge.html", {
        "text": badge.text,
        "css_class": BADGE_CSS_MAP[badge.badge_type],
        "icon": badge.icon,
        "is_processing": badge.badge_type == BadgeType.PROCESSING,
    })
```

### API Response Updates

`ProjectFileProgressView` will include:
```json
{
  "status": "downloading",
  "progress": 45,
  "badge_html": "<span class=\"badge bg-primary\"><span class=\"spinner-border...\">Downloading</span>"
}
```

JavaScript becomes:
```javascript
if (data.badge_html) {
    statusBadge.outerHTML = data.badge_html;
}
```

## Implementation Order (Vertical Slices)

Each slice = model method + tests + template update + commit

1. **DownloadAttempt badge** - `get_badge()` + `_download_attempt.html`
2. **Project status badge** - `get_status_badge()` + `project_detail.html` + `compliance_certification_form.html`
3. **Manufacturability status page** - template only (method exists) + `manufacturability_check_status.html`
4. **Notification type badge** - `get_type_badge()` + `notification_list.html`
5. **File display cleanup** - template only (methods exist) + `_file_display.html`
6. **Real-time updates** - `render_badge_html()` + API update + JS simplification
7. **Future-proofing models** - `Shuttle`, `ShuttleSlot`, `ReferralEarning`, `PayoutRequest` methods

## Verification

After implementation, grep audit to confirm no remaining hardcoded badges:
```bash
grep -rn "bg-success\|bg-danger\|bg-warning\|bg-info\|bg-secondary\|bg-primary" \
  --include="*.html" wafer_space/templates/ wafer_space/*/templates/
```

All results should be either:
- In `_badge.html` (the single source of truth)
- In intentionally excluded templates (documented above)
- Non-badge uses (card headers, etc.)
