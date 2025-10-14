# Terms of Service Versions

This directory contains all Terms of Service (TOS) versions for the platform.

## File Structure

Each TOS version is stored as a markdown file named with its version number:
- `1.0.0.md` - Version 1.0.0
- `2.0.0.md` - Version 2.0.0
- etc.

## Version Naming Convention

Use semantic versioning (MAJOR.MINOR.PATCH):
- **MAJOR**: Significant legal changes that may require re-acceptance
- **MINOR**: Minor clarifications or additions
- **PATCH**: Typo fixes or formatting changes

## Front Matter Metadata

Each markdown file includes YAML front matter with metadata:
- `version`: Version number matching the filename
- `effective_date`: Date when this version becomes effective
- `is_active`: Whether this is the currently active version
- `created_at`: ISO timestamp of when this version was created
- `created_by`: Username of admin who created this version
- `description`: Brief description of this version
- `requires_reacceptance`: Whether users must re-accept this version

## Adding a New Version

1. Create a new markdown file with the version number (e.g., `2.1.0.md`)
2. Add YAML front matter with metadata
3. Write the TOS content in markdown format
4. Use the Django admin interface or management command to activate the new version

## Markdown Format

TOS files use YAML front matter followed by markdown content:

```markdown
---
version: 1.0.0
effective_date: 2024-01-01
is_active: true
created_at: 2024-01-01T00:00:00Z
created_by: admin
description: Initial Terms of Service
requires_reacceptance: true
---

# Terms of Service

## 1. Acceptance of Terms

By accessing and using this service...

## 2. User Obligations

Users must...
```

## Important Notes

- **DO NOT** delete old versions - they may be needed for legal records
- **DO NOT** modify existing versions - create a new version instead
- All changes are tracked in git history for audit purposes