# Admin Project Access Design

**Date:** 2025-11-20
**Status:** Design Complete - Ready for Implementation
**Author:** Claude Code (with user collaboration)

## Overview

This design allows Django staff users to view and manage all projects on the platform while maintaining strict security boundaries for regular users. The implementation uses a centralized mixin pattern to ensure consistent, secure, and auditable admin access.

## Requirements

### Functional Requirements
1. Django staff users (`is_staff=True`) can view all projects from any user
2. Staff users have full access to all project operations (view, edit, delete, submit)
3. Staff users see a unified project list showing all users' projects
4. All staff user access to other users' projects is logged for audit purposes
5. Visual indicators clearly show when viewing/editing another user's project

### Security Requirements
1. Regular users can only access their own projects (existing behavior preserved)
2. Non-staff users cannot access other users' projects
3. Permission checks must fail closed (deny access if check fails)
4. Audit logs are immutable and prevent deletion of accounts with logs
5. Comprehensive test coverage to prevent accidental permission bypass

### User Experience Requirements
1. Prominent warning banner when staff user views another user's project
2. Project list shows owner badges to distinguish own vs others' projects
3. "Admin View" indicators in page titles for staff users
4. No changes to UI/UX for regular users

## Architecture Decision

**Selected Approach:** Centralized Mixin Pattern

**Rationale:**
- **DRY Principle:** Permission logic defined once, not repeated in 7+ views
- **Security:** Centralized logic prevents accidental bypass or inconsistent checks
- **Auditability:** Built-in logging cannot be omitted
- **Maintainability:** Single source of truth for permission behavior

**Rejected Alternatives:**
- Model-level permission method: Requires discipline to call explicitly
- Decorator-based approach: Less structured, harder to enforce consistency

## Component Design

### 1. ProjectOwnerOrStaffMixin

**Location:** `wafer_space/projects/mixins.py`

**Purpose:** Replaces `UserPassesTestMixin` in all project views to add staff user access

**Key Methods:**

#### `test_func()`
Performs permission check with fail-closed security:

```python
def test_func(self):
    """Check if user can access this project.

    Returns True if:
    - User owns the project, OR
    - User is an authenticated staff user

    Returns False otherwise (fails closed for security).
    """
    project = self.get_object()
    user = self.request.user

    # Owner always has access
    if project.user == user:
        return True

    # Staff users have access to all projects
    # Both checks required for security (fail-closed)
    if user.is_authenticated and user.is_staff:
        return True

    return False
```

**Security Analysis:**
- Explicit dual check: `is_authenticated` AND `is_staff`
- Owner check first (fast path for common case)
- Fails closed: If either condition undefined → access denied
- No implicit truthy checks that could be bypassed

#### `dispatch()`
Handles audit logging before view execution:

```python
def dispatch(self, request, *args, **kwargs):
    """Execute view and log admin access if needed."""
    # Run normal authentication/permission checks
    response = super().dispatch(request, *args, **kwargs)

    # Log if staff user accessing another user's project
    if self._is_accessing_others_project():
        self._create_audit_log()

    return response
```

#### `get_context_data()`
Adds visual indicator flags to template context:

```python
def get_context_data(self, **kwargs):
    """Add admin viewing flag to context."""
    context = super().get_context_data(**kwargs)
    project = self.get_object()

    context['viewing_as_admin'] = (
        self.request.user.is_staff and
        project.user != self.request.user
    )
    context['project_owner'] = project.user

    return context
```

#### Helper Methods

```python
def _is_accessing_others_project(self):
    """Check if staff user is accessing someone else's project."""
    if not self.request.user.is_staff:
        return False

    project = self.get_object()
    return project.user != self.request.user

def _get_action_for_view(self):
    """Determine audit log action based on view class."""
    # Maps view class names to ProjectAccessLog.Action choices

def _get_client_ip(self):
    """Extract client IP address from request."""
    # Handles X-Forwarded-For header for proxied requests
```

### 2. ProjectAccessLog Model

**Location:** `wafer_space/projects/models.py`

**Purpose:** Immutable audit trail of staff user access to other users' projects

**Model Definition:**

```python
class ProjectAccessLog(models.Model):
    """Audit log for when admins access other users' projects."""

    class Action(models.TextChoices):
        VIEW = "view", "Viewed"
        EDIT = "edit", "Edited"
        DELETE = "delete", "Deleted"
        SUBMIT = "submit", "Submitted"
        FILE_UPLOAD = "file_upload", "Uploaded File"

    # What was accessed
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="access_logs",
    )

    # Who accessed it
    admin_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,  # SECURITY: Prevent deletion
        related_name="admin_access_logs",
    )

    # When and what
    accessed_at = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=20, choices=Action.choices)

    # Context
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    view_name = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-accessed_at"]
        indexes = [
            models.Index(fields=["project", "-accessed_at"]),
            models.Index(fields=["admin_user", "-accessed_at"]),
        ]
```

**Security Features:**
1. **`on_delete=models.PROTECT`**: Cannot delete staff user accounts with audit logs (prevents covering tracks)
2. **Immutable by design**: No update/delete permissions in admin interface
3. **Comprehensive context**: IP address, user agent, view name for forensics
4. **Indexed queries**: Fast lookup by project or admin user

**Admin Configuration:**
- Read-only display only
- No add/change/delete permissions
- Filterable by project, admin_user, date range, action

### 3. View Migration

**Changes Required:**

All project views must migrate from:
```python
class ProjectDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    def test_func(self):
        project = self.get_object()
        return project.user == self.request.user
```

To:
```python
class ProjectDetailView(LoginRequiredMixin, ProjectOwnerOrStaffMixin, DetailView):
    # No test_func needed - mixin provides it
```

**Views to Update:**
1. `ProjectListView` - Add staff user queryset logic
2. `ProjectDetailView` - Replace mixin
3. `ProjectCreateView` - No changes (only owners create)
4. `ProjectUpdateView` - Replace mixin
5. `ProjectDeleteView` - Replace mixin
6. `ProjectFileSubmitURLView` - Replace mixin
7. `ProjectFileProgressView` - Replace mixin
8. `ProjectSubmitView` - Replace mixin

**ProjectListView Special Case:**

```python
def get_queryset(self):
    """Return projects based on user role."""
    user = cast("User", self.request.user)

    # Staff users see all projects
    if user.is_staff:
        return Project.objects.all().order_by("-created_at")

    # Regular users see only their projects
    return Project.objects.filter(user=user).order_by("-created_at")
```

### 4. UI Changes

#### Admin Warning Banner

Add to `projects/project_detail.html`, `project_form.html`, etc.:

```html
{% if viewing_as_admin %}
<div class="alert alert-warning border-warning mb-4" role="alert">
    <div class="d-flex align-items-center">
        <i class="bi bi-exclamation-triangle-fill me-2 fs-4"></i>
        <div>
            <strong>⚠️ Admin Mode:</strong>
            You are viewing <strong>{{ project_owner.username }}</strong>'s project.
            All actions will be logged for audit purposes.
        </div>
    </div>
</div>
{% endif %}
```

**Styling:**
- Yellow/orange background (`alert-warning`)
- Prominent icon (Bootstrap Icons warning triangle)
- Bold text for owner username
- Positioned at top of page content

#### Project List Changes

Update `projects/project_list.html`:

```html
<h1 class="mb-4">
    Projects
    {% if user.is_staff %}
        <span class="badge bg-primary">All Users - Admin View</span>
    {% endif %}
</h1>

<!-- Each project card -->
<div class="card mb-3">
    <div class="card-body">
        <h3 class="card-title">
            {{ project.name }}
            {% if project.user != user %}
                <span class="badge bg-info">Owner: {{ project.user.username }}</span>
            {% else %}
                <span class="badge bg-success">Your Project</span>
            {% endif %}
        </h3>
        <!-- ... rest of card ... -->
    </div>
</div>
```

**Badge Colors:**
- Own projects: Green (`bg-success`)
- Others' projects: Blue (`bg-info`)
- Admin view indicator: Primary (`bg-primary`)

## Testing Strategy

### Permission Tests

**File:** `wafer_space/projects/tests/test_permissions.py`

**Test Cases:**

```python
class TestProjectOwnerOrStaffMixin:
    """Test permission mixin behavior."""

    def test_owner_can_access_own_project(self):
        """Regular user can access their own project."""

    def test_staff_user_can_access_any_project(self):
        """Superuser can access any user's project."""

    def test_regular_user_cannot_access_others_project(self):
        """Regular user gets 403 when accessing others' project."""

    def test_non_staff_user_cannot_access_others_project(self):
        """Non-staff user (is_staff=False) cannot access other users' projects."""

    def test_unauthenticated_user_redirected_to_login(self):
        """Anonymous user redirected to login page."""

    def test_anonymous_staff_flag_ignored(self):
        """SECURITY: is_staff=True without authentication is denied."""

    def test_permission_check_on_all_views(self):
        """All 7+ project views use correct permission mixin."""
```

### Audit Log Tests

**File:** `wafer_space/projects/tests/test_audit_logging.py`

**Test Cases:**

```python
class TestProjectAccessLog:
    """Test audit logging functionality."""

    def test_log_created_when_staff_user_views_others_project(self):
        """Audit log created with correct action (VIEW)."""

    def test_no_log_when_owner_views_own_project(self):
        """No audit log when user views their own project."""

    def test_no_log_when_staff_user_views_own_project(self):
        """No audit log when staff user views their own project."""

    def test_audit_log_captures_ip_address(self):
        """IP address captured from request."""

    def test_audit_log_captures_user_agent(self):
        """User agent string captured from request."""

    def test_audit_log_immutable_cannot_delete(self):
        """Audit logs cannot be deleted via admin interface."""

    def test_cannot_delete_staff_user_with_audit_logs(self):
        """PROTECT constraint prevents deleting users with logs."""

    def test_different_actions_logged_correctly(self):
        """VIEW, EDIT, DELETE, SUBMIT actions logged appropriately."""

    def test_multiple_accesses_create_multiple_logs(self):
        """Each access creates separate log entry."""
```

### Browser/Integration Tests

**File:** `tests/browser/test_admin_project_access.py`

**Test Cases:**

```python
class TestAdminProjectAccessUI:
    """Test UI behavior for admin project access."""

    def test_admin_sees_warning_banner_on_others_project(self):
        """Warning banner visible when viewing others' project."""

    def test_admin_sees_all_projects_in_list(self):
        """Project list shows all users' projects for staff user."""

    def test_regular_user_sees_only_own_projects(self):
        """Regular user project list unchanged."""

    def test_project_list_shows_owner_badges(self):
        """Owner badges displayed with correct colors."""

    def test_admin_can_edit_others_project(self):
        """Superuser can successfully edit another user's project."""

    def test_admin_can_delete_others_project(self):
        """Superuser can successfully delete another user's project."""

    def test_admin_can_submit_others_project(self):
        """Superuser can submit another user's project."""
```

### Security Edge Case Tests

**Critical Edge Cases:**

```python
def test_is_staff_true_but_not_authenticated():
    """Unauthenticated request with is_staff=True is denied."""
    # Simulates potential attack vector

def test_non_staff_user_denied():
    """Non-staff users cannot access other users' projects."""

def test_removing_staff_status_revokes_access():
    """Removing is_staff immediately prevents access."""

def test_url_manipulation_cannot_bypass_permission():
    """Direct URL access to project still checks permissions."""
```

## Migration Plan

### Database Migration

**File:** `wafer_space/projects/migrations/00XX_add_project_access_log.py`

**Operations:**
1. Create `ProjectAccessLog` model table
2. Add indexes on `project` and `admin_user` fields
3. Add PROTECT constraint on `admin_user` foreign key

**No data migration needed** - this is a new feature, no existing data to migrate.

### Code Migration

**Minimal Risk Migration:**

1. **Create mixin and model** (new files, no breaking changes)
2. **Run migration** (new table, no impact on existing data)
3. **Update views one-by-one** (replace mixin, test each)
4. **Update templates** (add visual indicators)
5. **Run full test suite** (verify no regressions)

**Rollback Plan:**
- Revert view changes (restore `UserPassesTestMixin`)
- Keep `ProjectAccessLog` table (audit data preserved)
- Mixin can remain unused until ready to re-enable

## Security Analysis

### Threat Model

**Threats Mitigated:**

1. **Accidental Permission Bypass**
   - Mitigation: Centralized mixin, comprehensive tests
   - Fail-closed design prevents accidental access grants

2. **Privilege Escalation**
   - Mitigation: Explicit `is_authenticated AND is_staff` check
   - No implicit truthy checks that could be bypassed

3. **Lack of Accountability**
   - Mitigation: Comprehensive audit logging
   - Immutable logs with PROTECT constraint

4. **Accidental Modifications**
   - Mitigation: Prominent visual warnings
   - Clear owner badges in project lists

5. **Regular User Data Exposure**
   - Mitigation: No changes to regular user permission checks
   - Test coverage verifies isolation

**Attack Vectors Considered:**

- ✅ Unauthenticated request with `is_staff=True` → Denied
- ✅ Non-staff user → Denied
- ✅ URL manipulation → Permission checked on every view
- ✅ Removing staff user status → Immediate access revocation
- ✅ Deleting audit logs → Prevented by admin configuration
- ✅ Deleting staff user with logs → Prevented by PROTECT constraint

### Compliance Considerations

**Audit Requirements:**
- All admin access logged with timestamp, IP, user agent
- Logs immutable and protected from deletion
- Fast queries for compliance reporting
- Retention: Logs retained indefinitely (no automatic deletion)

**Access Control:**
- Explicit role-based access (is_staff flag)
- No escalation path for regular users
- Clear separation between owner and admin access

## Implementation Checklist

### Backend
- [ ] Create `wafer_space/projects/mixins.py` with `ProjectOwnerOrStaffMixin`
- [ ] Add `ProjectAccessLog` model to `models.py`
- [ ] Create database migration for `ProjectAccessLog`
- [ ] Run migration on development database
- [ ] Update `ProjectListView` to show all projects for staff users
- [ ] Update `ProjectDetailView` to use new mixin
- [ ] Update `ProjectUpdateView` to use new mixin
- [ ] Update `ProjectDeleteView` to use new mixin
- [ ] Update `ProjectFileSubmitURLView` to use new mixin
- [ ] Update `ProjectFileProgressView` to use new mixin
- [ ] Update `ProjectSubmitView` to use new mixin
- [ ] Configure `ProjectAccessLog` admin (read-only)

### Frontend
- [ ] Add admin warning banner to `project_detail.html`
- [ ] Add admin warning banner to `project_form.html`
- [ ] Add admin warning banner to `project_confirm_delete.html`
- [ ] Update `project_list.html` with admin view indicator
- [ ] Add owner badges to project cards in list
- [ ] Test responsive behavior of warning banners

### Testing
- [ ] Write permission tests (~7 tests)
- [ ] Write audit log tests (~9 tests)
- [ ] Write browser UI tests (~7 tests)
- [ ] Write security edge case tests (~4 tests)
- [ ] Run full test suite and verify no regressions
- [ ] Manual testing with staff user account

### Documentation
- [ ] Update `CLAUDE.md` with new permission model
- [ ] Add docstrings to mixin methods
- [ ] Add docstrings to `ProjectAccessLog` model
- [ ] Document audit log admin configuration
- [ ] Update developer onboarding docs

## Success Criteria

✅ **Functionality:**
- Staff users can view and manage all projects
- Regular users see no changes to existing behavior
- All actions are auditable

✅ **Security:**
- Comprehensive test coverage (>95%)
- All edge cases handled correctly
- Fail-closed permission checks

✅ **User Experience:**
- Clear visual indicators for admin mode
- No confusion about project ownership
- Audit trail accessible for compliance

✅ **Maintainability:**
- Single source of truth for permission logic
- Easy to extend for future admin features
- Well-documented design decisions

## Future Enhancements

**Not in Initial Scope (but designed for):**

1. **Admin Dashboard for Audit Logs**
   - Searchable interface for viewing access logs
   - Filter by date range, admin user, project
   - Export to CSV for compliance reporting

2. **Notification on Admin Access**
   - Email project owner when admin views/edits their project
   - Configurable notification preferences

3. **Read-Only Admin Mode**
   - Toggle between read-only and full access
   - Reduce accidental modifications further

4. **Granular Permissions**
   - Separate permissions for view/edit/delete
   - Allow delegating specific admin capabilities

## References

- Django UserPassesTestMixin: https://docs.djangoproject.com/en/5.2/topics/auth/default/#limiting-access-to-logged-in-users
- Audit Logging Best Practices: https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
- Django Model Meta Options: https://docs.djangoproject.com/en/5.2/ref/models/options/
