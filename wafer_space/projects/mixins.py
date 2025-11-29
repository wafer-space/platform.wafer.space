"""Permission mixins for project views."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from django.contrib.auth.mixins import UserPassesTestMixin
from django.views.generic.edit import DeleteView

from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectAccessLog

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http import HttpResponseBase

    from wafer_space.users.models import User

# HTTP status code boundary for successful responses
HTTP_SUCCESS_THRESHOLD = 400


class ProjectOwnerOrStaffMixin(UserPassesTestMixin):
    """Mixin to allow access to project owner or staff users.

    This mixin should be used on all project-related views to enforce
    consistent permission checking:
    - Project owner always has access
    - Staff users have access to all projects
    - All other users are denied access

    Audit Logging:
    - When staff users access projects they don't own, an audit log is created
    - Logs include: timestamp, IP address, user agent, action, view name
    - Owner access is NOT logged (normal operation)

    Security Design:
    - Fail-closed: Returns False by default
    - Explicit dual check: user.is_authenticated AND user.is_staff
    - Prevents bypass via unauthenticated staff accounts

    Usage:
        class ProjectDetailView(
            LoginRequiredMixin,
            ProjectOwnerOrStaffMixin,
            DetailView,
        ):
            model = Project
    """

    # Type stubs for attributes provided by the view class this mixin is combined with
    # request is provided by View, get_object() is provided by SingleObjectMixin
    request: HttpRequest
    _accessed_project: Project | None

    def test_func(self) -> bool:
        """Check if user can access this project.

        Returns True if:
        - User owns the project, OR
        - User is an authenticated staff user

        Returns False for:
        - Non-owners
        - Regular users without staff flag
        - Unauthenticated users (even if is_staff=True)
        """
        project: Project = self.get_object()  # type: ignore[attr-defined]
        user = self.request.user

        # Store project reference for use in handle_no_permission
        self._accessed_project = project

        # Owner always has access
        if project.user == user:
            return True

        # Staff users have access to all projects
        # Both checks required for security (fail-closed)
        return user.is_authenticated and user.is_staff

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        """Dispatch request and create audit log for staff access."""
        # Get project BEFORE dispatch (DeleteView will delete it)
        project: Project = self.get_object()  # type: ignore[attr-defined]
        user = request.user

        # Check if this is a delete operation (POST to DeleteView)
        is_delete_view = isinstance(self, DeleteView)
        is_delete_operation = is_delete_view and request.method == "POST"

        # Get response from parent
        response = super().dispatch(request, *args, **kwargs)

        # Only log if access was granted (status < 400)
        # Note: DELETE operations via DeleteView POST are NOT logged because:
        # 1. The project is deleted, so FK constraint would fail if logged after
        # 2. Creating log before delete causes orphaned FK (CASCADE timing issue)
        # 3. A proper fix requires making project FK nullable (SET_NULL)
        # TODO: Consider adding nullable project FK to preserve DELETE audit logs
        if response.status_code < HTTP_SUCCESS_THRESHOLD:
            # Only log staff access to OTHER users' projects (non-DELETE)
            is_admin_access = (
                user.is_authenticated and user.is_staff and project.user != user
            )
            if is_admin_access and not is_delete_operation:
                # Cast is safe: is_admin_access check confirms user.is_authenticated
                self._create_audit_log(project, cast("User", user), request)

        return response

    def handle_no_permission(self):
        """Handle denied access and log the attempt.

        This method is called by UserPassesTestMixin when test_func returns False.
        We only log denied access attempts for staff users because:
        1. Regular users being denied is expected (not their project)
        2. ProjectAccessLog.admin_user has on_delete=PROTECT, which would make
           all logged users undeletable
        3. Staff users being denied is unexpected and worth auditing
        """
        user = self.request.user
        project = getattr(self, "_accessed_project", None)

        # Only log denied access for staff users (unexpected scenario worth auditing)
        # Regular users being denied is normal and doesn't need logging
        if user.is_authenticated and user.is_staff and project is not None:
            self._create_denied_access_log(project, user, self.request)

        # Return standard 403 response
        return super().handle_no_permission()

    def _create_audit_log(
        self, project: Project, admin_user: User, request: HttpRequest
    ) -> None:
        """Create audit log entry for admin access.

        Args:
            project: Project being accessed
            admin_user: Staff user accessing the project
            request: HTTP request object
        """
        # Determine action based on request method
        action_map = {
            "GET": ProjectAccessLog.Action.VIEW,
            "POST": ProjectAccessLog.Action.EDIT,
            "PUT": ProjectAccessLog.Action.EDIT,
            "PATCH": ProjectAccessLog.Action.EDIT,
            "DELETE": ProjectAccessLog.Action.DELETE,
        }
        method = request.method or "GET"
        action = action_map.get(method, ProjectAccessLog.Action.VIEW)

        # Get client IP address
        x_forwarded_for = request.headers.get("x-forwarded-for")
        if x_forwarded_for:
            ip_address: str | None = x_forwarded_for.split(",")[0].strip()
        else:
            ip_address = request.META.get("REMOTE_ADDR")

        # Create log entry
        ProjectAccessLog.objects.create(
            project=project,
            admin_user=admin_user,
            action=action,
            ip_address=ip_address,
            user_agent=request.headers.get("user-agent", ""),
            view_name=self.__class__.__name__,
        )

    def _create_denied_access_log(
        self, project: Project, user: User, request: HttpRequest
    ) -> None:
        """Create audit log entry for denied access attempt.

        Args:
            project: Project that user attempted to access
            user: User who was denied access
            request: HTTP request object
        """
        # Get client IP address
        x_forwarded_for = request.headers.get("x-forwarded-for")
        if x_forwarded_for:
            ip_address: str | None = x_forwarded_for.split(",")[0].strip()
        else:
            ip_address = request.META.get("REMOTE_ADDR")

        # Create log entry with ACCESS_DENIED action
        ProjectAccessLog.objects.create(
            project=project,
            admin_user=user,
            action=ProjectAccessLog.Action.ACCESS_DENIED,
            ip_address=ip_address,
            user_agent=request.headers.get("user-agent", ""),
            view_name=self.__class__.__name__,
        )
