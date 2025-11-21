"""Permission mixins for project views."""

from django.contrib.auth.mixins import UserPassesTestMixin

from wafer_space.projects.models import ProjectAccessLog

# HTTP status code boundary for successful responses
HTTP_SUCCESS_THRESHOLD = 400


class ProjectOwnerOrSuperuserMixin(UserPassesTestMixin):
    """Mixin to allow access to project owner or superusers.

    This mixin should be used on all project-related views to enforce
    consistent permission checking:
    - Project owner always has access
    - Superusers have access to all projects
    - All other users are denied access

    Audit Logging:
    - When superusers access projects they don't own, an audit log is created
    - Logs include: timestamp, IP address, user agent, action, view name
    - Owner access is NOT logged (normal operation)

    Security Design:
    - Fail-closed: Returns False by default
    - Explicit dual check: user.is_authenticated AND user.is_superuser
    - Prevents bypass via unauthenticated superuser accounts

    Usage:
        class ProjectDetailView(
            LoginRequiredMixin,
            ProjectOwnerOrSuperuserMixin,
            DetailView,
        ):
            model = Project
    """

    def test_func(self):
        """Check if user can access this project.

        Returns True if:
        - User owns the project, OR
        - User is an authenticated superuser

        Returns False for:
        - Non-owners
        - Staff users without superuser flag
        - Unauthenticated users (even if is_superuser=True)
        """
        project = self.get_object()  # type: ignore[attr-defined]
        user = self.request.user  # type: ignore[attr-defined]

        # Store project reference for use in handle_no_permission
        self._accessed_project = project

        # Owner always has access
        if project.user == user:
            return True

        # Superusers have access to all projects
        # Both checks required for security (fail-closed)
        return user.is_authenticated and user.is_superuser

    def dispatch(self, request, *args, **kwargs):
        """Dispatch request and create audit log for superuser access."""
        # Get project BEFORE dispatch (DeleteView will delete it)
        project = self.get_object()  # type: ignore[attr-defined]
        user = request.user

        # Get response from parent
        response = super().dispatch(request, *args, **kwargs)

        # Only log if access was granted (status < 400)
        if response.status_code < HTTP_SUCCESS_THRESHOLD:
            # Only log superuser access to OTHER users' projects
            if user.is_authenticated and user.is_superuser and project.user != user:
                self._create_audit_log(project, user, request)

        return response

    def handle_no_permission(self):
        """Handle denied access and log the attempt.

        This method is called by UserPassesTestMixin when test_func returns False.
        We log unauthorized access attempts for security auditing before returning
        the standard 403 Forbidden response.
        """
        user = self.request.user  # type: ignore[attr-defined]
        project = getattr(self, "_accessed_project", None)

        # Only log if we have both user and project information
        # Log for authenticated users who were denied (not owners, not superusers)
        if user.is_authenticated and project is not None:
            self._create_denied_access_log(project, user, self.request)  # type: ignore[attr-defined]

        # Return standard 403 response
        return super().handle_no_permission()

    def _create_audit_log(self, project, admin_user, request):
        """Create audit log entry for admin access.

        Args:
            project: Project being accessed
            admin_user: Superuser accessing the project
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
        action = action_map.get(request.method, ProjectAccessLog.Action.VIEW)

        # Get client IP address
        x_forwarded_for = request.headers.get("x-forwarded-for")
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(",")[0].strip()
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

    def _create_denied_access_log(self, project, user, request):
        """Create audit log entry for denied access attempt.

        Args:
            project: Project that user attempted to access
            user: User who was denied access
            request: HTTP request object
        """
        # Get client IP address
        x_forwarded_for = request.headers.get("x-forwarded-for")
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(",")[0].strip()
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
