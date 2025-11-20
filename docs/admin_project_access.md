# Admin Project Access

## Overview

Django superusers can view, edit, and manage any user's project on the platform. This feature includes comprehensive audit logging and visual indicators to ensure transparency and accountability.

## Who Has Access

**Superusers Only**: Access is restricted to users with `is_superuser=True`.

**Staff users** (`is_staff=True` without `is_superuser=True`) do **NOT** have access to other users' projects.

## Features

### 1. Full Project Access

Superusers can:
- **View** any project's details, files, and status
- **Edit** project name, description, and metadata
- **Delete** projects
- **Submit** projects for manufacturing
- **Upload/manage** project files

### 2. Unified Project List

When superusers visit the project list page, they see **all users' projects**, not just their own.

Regular users continue to see only their own projects.

### 3. Visual Indicators

**Warning Banner**: When viewing another user's project, superusers see a prominent yellow warning banner:

```
⚠️ Admin Mode: You are viewing [username]'s project.
All actions will be logged for audit purposes.
```

**Owner Badges**: Project list shows colored badges:
- Green "Your Project" for own projects
- Blue "[username]'s Project" for other users' projects

### 4. Comprehensive Audit Logging

**All superuser access to other users' projects is logged**, including:
- Timestamp
- Admin username
- Project accessed
- Action type (view, edit, delete, submit, file upload)
- IP address
- User agent
- View name

**Owner access is NOT logged** (normal operation).

## Audit Log Retention

- Audit logs are **immutable** (cannot be edited or deleted through UI)
- Admin users **cannot be deleted** if they have audit log entries (database PROTECT constraint)
- Logs are retained indefinitely for compliance
- Logs cascade delete when associated project is deleted

## Viewing Audit Logs

Superusers can view audit logs through Django admin:

1. Navigate to Django admin (`/admin/`)
2. Go to "Projects" → "Project Access Logs"
3. Filter by action, date, or admin user
4. Search by username, project name, or IP address

## Security Features

1. **Fail-Closed Design**: Permission checks default to deny if undefined
2. **Explicit Dual Check**: Both `is_authenticated` AND `is_superuser` required
3. **Centralized Logic**: Single mixin (`ProjectOwnerOrSuperuserMixin`) prevents bypass
4. **Protected Audit Logs**: Cannot delete users with log entries
5. **No Backdoors**: Staff users without superuser flag explicitly denied

## Implementation Details

### Permission Mixin

All project views use `ProjectOwnerOrSuperuserMixin`:

```python
class ProjectDetailView(LoginRequiredMixin, ProjectOwnerOrSuperuserMixin, DetailView):
    model = Project
```

### Audit Logging

Audit logs are created automatically in mixin's `dispatch()` method when:
- User is authenticated superuser
- Project owner is different from current user
- Access is granted (status < 400)

### Context Variables

Views set `viewing_as_admin` flag for template rendering:

```python
def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    project = self.get_object()
    user = self.request.user

    context["viewing_as_admin"] = (
        user.is_authenticated
        and user.is_superuser
        and project.user != user
    )

    return context
```

## Testing

Comprehensive test coverage includes:
- **Permission tests**: Owner, superuser, non-owner, staff without superuser
- **Audit log tests**: Creation, immutability, protection, cascade
- **Integration tests**: All views with superuser access
- **Browser tests**: Warning banner, project list, edit access, audit logging

Run tests:
```bash
make test                    # Unit tests
make test-browser-headless   # Browser tests
```

## Migration Guide

If extending this feature to new views:

1. Add `ProjectOwnerOrSuperuserMixin` to view class
2. Remove old `test_func()` method if present
3. Add `get_context_data()` to set `viewing_as_admin` flag
4. Include `_admin_warning_banner.html` in template
5. Write tests for permission and audit logging

See `wafer_space/projects/views.py` for examples.
