# Badge System Design

## What is a Badge?

A badge is a visual indicator that communicates the state or status of an
entity at a glance. Badges appear inline with content and use color, icons,
and text to convey meaning quickly.

## Scope

This system standardizes badges for **general model state**: project status,
file download status, hash verification, download attempts, and notification
types.

**Manufacturability check badges are out of scope.** Checks have their own
badge tags in `wafer_space/projects/templatetags/precheck_tags.py`
(`badge_check_status`, `badge_check_version`,
`badge_check_status_and_version`), driven by
`ManufacturabilityCheck._STATUS_METADATA`. Those tags add precheck container
version indicators that this system deliberately does not model. Templates
mix both systems side by side (see `_file_badges.html`).

## Badge Anatomy

```text
┌─────────────────────────────────┐
│ [icon] [text]                   │
│  ↑       ↑                      │
│  │       └── Label (required)   │
│  └────────── Icon (optional)    │
│                                 │
│ Background color = badge type   │
│ Text color = auto contrast      │
└─────────────────────────────────┘
```

### Components

| Component | Required | Description |
|-----------|----------|-------------|
| **Text** | Yes | Short label (1-3 words) describing the state |
| **Background Color** | Yes | Determined by BadgeType - conveys semantic meaning |
| **Icon** | No | Bootstrap icon, adds visual reinforcement |
| **Spinner** | Auto | Shown automatically for PROCESSING type |

## Badge Types (Semantic Meaning)

| Type | Color | Bootstrap Class | Meaning |
|------|-------|-----------------|---------|
| SUCCESS | Green | `bg-success` | Completed successfully, verified, positive |
| DANGER | Red | `bg-danger` | Failed, error, requires attention |
| WARNING | Yellow | `bg-warning text-dark` | Uncertain, potential issue |
| INFO | Light blue | `bg-info` | Informational, transitional |
| PROCESSING | Blue | `bg-primary` + spinner | Active work in progress |
| NEUTRAL | Gray | `bg-secondary` | Inactive, pending, default |

## Badge Pipeline Model

File badges represent stages in a processing pipeline. Each stage must
complete successfully before the next stage's badge appears:

```text
Download → Hash Verification
```

Failure at any stage stops progression. The manufacturability check that
follows the pipeline is rendered separately via `precheck_tags` (see Scope).

## Usage in Templates

```django
{% load badges %}

{# Render the download/hash pipeline badges for a file #}
{% for badge in file.get_badges %}
  {% render_badge badge %}
{% endfor %}

{# Render single badge #}
{% render_badge project.get_status_badge %}
```

## Usage in Models

```python
from wafer_space.core.badges import BadgeInfo, BadgeType

class MyModel(Model):
    def get_badge(self) -> BadgeInfo:
        if self.status == "success":
            return BadgeInfo(
                text="Completed",
                badge_type=BadgeType.SUCCESS,
                icon="bi-check-circle",
            )
        return BadgeInfo(
            text="Pending",
            badge_type=BadgeType.NEUTRAL,
        )
```

## State-to-Badge Mappings

### Project.Status

| Status | BadgeType | Text | Icon |
|--------|-----------|------|------|
| DRAFT | NEUTRAL | Draft | bi-pencil |
| SUBMITTED | INFO | Submitted | bi-send |
| CHECKING | PROCESSING | Checking | (spinner) |
| MANUFACTURABLE | SUCCESS | Manufacturable | bi-check-circle |
| NOT_MANUFACTURABLE | DANGER | Not Manufacturable | bi-x-circle |
| ASSIGNED_TO_SHUTTLE | INFO | Assigned to Shuttle | bi-truck |
| IN_PRODUCTION | PROCESSING | In Production | (spinner) |
| COMPLETED | SUCCESS | Completed | bi-check-circle-fill |
| CANCELLED | NEUTRAL | Cancelled | bi-x-circle |

### ProjectFile.DownloadStatus

| Status | BadgeType | Text | Icon |
|--------|-----------|------|------|
| PENDING | NEUTRAL | Download Pending | bi-clock |
| QUEUED | NEUTRAL | Queued | bi-hourglass-split |
| DOWNLOADING | PROCESSING | Downloading | (spinner) |
| COMPLETED | SUCCESS | Downloaded | bi-check-circle |
| FAILED | DANGER | Download Failed | bi-exclamation-triangle |

### Hash Verification

| State | BadgeType | Text | Icon |
|-------|-----------|------|------|
| Verified | SUCCESS | Hash Verified | bi-shield-check |
| Mismatch | DANGER | Hash Mismatch | bi-shield-x |
| Unverified | WARNING | Hash Unverified | bi-shield-exclamation |

### DownloadAttempt.Status

| Status | BadgeType | Text | Icon |
|--------|-----------|------|------|
| PENDING | NEUTRAL | Pending | bi-clock |
| DOWNLOADING | PROCESSING | Downloading | (spinner) |
| COMPLETED | SUCCESS | Completed | bi-check-circle |
| FAILED | DANGER | Failed | bi-exclamation-triangle |

### Notification.Type

| Type | BadgeType | Icon |
|------|-----------|------|
| DOWNLOAD_COMPLETE | SUCCESS | bi-check-circle |
| DOWNLOAD_FAILED | DANGER | bi-exclamation-triangle |
| CHECKSUM_VERIFIED | SUCCESS | bi-shield-check |
| CHECKSUM_MISMATCH | WARNING | bi-shield-x |
| MANUFACTURING_COMPLETE | SUCCESS | bi-box-seam |
| TOS_UPDATE | INFO | bi-file-text |

Unknown notification types fall back to a NEUTRAL badge showing the raw type
value, so new types degrade gracefully until a mapping is added.
