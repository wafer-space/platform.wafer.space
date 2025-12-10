# Project Metadata: Repository URL + License Tracking

**Date:** 2025-12-10
**Issues:** #137 (Repository URL), #193 (License Tracking)
**Branch:** `feature/project-metadata`

## Overview

Add repository URL and license tracking fields to the Project model. These features were blocked by the project history tracking functionality which has now been merged.

## Data Model

### New Fields on Project Model

```python
# Repository URL (Issue #137)
repository_url = models.URLField(
    blank=True,
    max_length=500,
    help_text="URL to the project's source repository",
)

# License Tracking (Issue #193)
license_type = models.CharField(
    max_length=50,
    choices=LicenseType.choices,
    default=LicenseType.PROPRIETARY,
)
other_license_spdx_id = models.CharField(
    max_length=100,
    blank=True,
    help_text="SPDX identifier when license_type is 'Other'",
)
proprietary_terms_url = models.URLField(
    blank=True,
    max_length=500,
    help_text="URL to proprietary license terms",
)
proprietary_terms_cached = models.TextField(
    blank=True,
    help_text="Cached content from proprietary_terms_url",
)
proprietary_terms_cached_at = models.DateTimeField(
    null=True,
    blank=True,
)
```

### LicenseType Enum

```python
class LicenseType(models.TextChoices):
    PROPRIETARY = "proprietary", "Proprietary (All Rights Reserved)"
    APACHE_2_0 = "Apache-2.0", "Apache License 2.0"
    MIT = "MIT", "MIT License"
    BSD_3_CLAUSE = "BSD-3-Clause", "BSD 3-Clause License"
    ISC = "ISC", "ISC License"
    CERN_OHL_P = "CERN-OHL-P-2.0", "CERN Open Hardware License (Permissive)"
    SOLDERPAD_2_0 = "SHL-2.0", "Solderpad Hardware License 2.0"
    SOLDERPAD_2_1 = "SHL-2.1", "Solderpad Hardware License 2.1"
    CC0 = "CC0-1.0", "CC0 1.0 (Public Domain)"
    CC_BY = "CC-BY-4.0", "Creative Commons Attribution 4.0"
    OTHER = "other", "Other Open Source License"
```

## Field Editability

| Field | User Editable | Staff Editable | Auto-populated |
|-------|--------------|----------------|----------------|
| `repository_url` | Yes | Yes | No |
| `license_type` | Yes | Yes | No |
| `other_license_spdx_id` | Yes | Yes | No |
| `proprietary_terms_url` | Yes | Yes | No |
| `proprietary_terms_cached` | No | No | Yes |
| `proprietary_terms_cached_at` | No | No | Yes |

## Validation Rules

### SPDX Validation (for "other" license type)

- When `license_type == "other"`, `other_license_spdx_id` is required
- Validate by fetching: `https://raw.githubusercontent.com/spdx/license-list-data/main/text/{spdx_id}.txt`
- If fetch fails (404, timeout) → form validation error: "Invalid SPDX identifier"

### Proprietary Terms URL Validation

- When `proprietary_terms_url` is provided/changed → fetch content
- If fetch fails → form validation error: "Could not fetch license terms from URL"
- On success → store content in `proprietary_terms_cached`, update `proprietary_terms_cached_at`

### Conditional Field Logic

| license_type | other_license_spdx_id | proprietary_terms_url |
|--------------|----------------------|----------------------|
| proprietary | Hidden, cleared | Shown |
| MIT, Apache, etc. | Hidden, cleared | Hidden, cleared |
| other | Shown, required | Hidden, cleared |

## Form Updates

### ProjectForm (staff)

Add all new user-editable fields with validation and JavaScript for conditional visibility.

### ProjectUserEditForm (regular users)

Expand from `["is_public"]` to:
- `is_public`
- `repository_url`
- `license_type`
- `other_license_spdx_id`
- `proprietary_terms_url`

Same validation logic and JavaScript as ProjectForm.

## Template Updates

### Project Detail Page

Display after "Visibility" section:

- **License badge** with appropriate color:
  - Proprietary: grey badge, optional link to terms
  - Open source: green badge, link to SPDX page
  - Other: info badge with SPDX ID, link to SPDX page

- **Repository link** (if set)

## Admin Updates

- Add `license_type` to `list_display` and `list_filter`
- Add `repository_url` to `list_display` (truncated)
- Add `repository_url`, `other_license_spdx_id` to `search_fields`

## Migration Strategy

Single migration with all 6 new fields. All existing projects default to `license_type="proprietary"`.

## Test Coverage

### Model Tests
- Default license_type is "proprietary"
- LicenseType enum has expected choices

### Form Tests
- "other" requires valid SPDX ID
- Invalid SPDX ID fails validation (mocked HTTP)
- Proprietary with invalid terms URL fails (mocked HTTP)
- Proprietary with valid terms URL caches content
- Conditional field clearing

### View Tests
- Form renders all new fields
- Successful submission with each license type
- Detail page displays license info correctly

## Implementation Order

1. Add LicenseType enum to models.py
2. Add fields to Project model
3. Create migration
4. Update ProjectForm with fields + validation
5. Update ProjectUserEditForm with fields + validation
6. Add JavaScript for conditional field visibility
7. Update project_detail.html template
8. Update admin.py
9. Write tests
10. Run full test suite
