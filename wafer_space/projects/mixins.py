"""Permission mixins for project views."""

from django.contrib.auth.mixins import UserPassesTestMixin


class ProjectOwnerOrSuperuserMixin(UserPassesTestMixin):
    """Mixin to allow access to project owner or superusers.

    This mixin should be used on all project-related views to enforce
    consistent permission checking:
    - Project owner always has access
    - Superusers have access to all projects
    - All other users are denied access

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

        # Owner always has access
        if project.user == user:
            return True

        # Superusers have access to all projects
        # Both checks required for security (fail-closed)
        return user.is_authenticated and user.is_superuser
