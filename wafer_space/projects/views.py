"""Views for project management."""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING
from typing import ClassVar
from typing import cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import CreateView
from django.views.generic import DeleteView
from django.views.generic import DetailView
from django.views.generic import ListView
from django.views.generic import UpdateView
from django.views.generic import View

from wafer_space.core.enums import SlotSize
from wafer_space.shuttles.models import Shuttle

from .exceptions import InvalidStateTransitionError
from .forms import ProjectFileURLSubmitForm
from .forms import ProjectForm
from .mixins import ProjectOwnerOrStaffMixin
from .models import PROJECT_ID_LENGTH
from .models import DownloadAttempt
from .models import ManufacturabilityCheck
from .models import Project
from .models import ProjectFile
from .security import SecurityValidationError
from .services import ProjectFileService

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from wafer_space.users.models import User


class ProjectListView(LoginRequiredMixin, ListView):
    """List all projects for the current user."""

    model = Project
    template_name = "projects/project_list.html"
    context_object_name = "projects"
    paginate_by = 20

    def get_queryset(self):
        """Return projects accessible to current user.

        - Regular users: only their own projects
        - Staff users: all projects from all users
        """
        # Cast user since LoginRequiredMixin ensures authentication
        user = cast("User", self.request.user)

        if user.is_staff:
            # Staff users see all projects
            return Project.objects.all().select_related("user").order_by("-created_at")

        # Regular users see only their own projects
        return Project.objects.filter(user=user).order_by("-created_at")


class ProjectDetailView(LoginRequiredMixin, ProjectOwnerOrStaffMixin, DetailView):
    """View a single project with its files."""

    model = Project
    template_name = "projects/project_detail.html"
    context_object_name = "project"

    def get_context_data(self, **kwargs):
        """Add project files and status to context."""
        context = super().get_context_data(**kwargs)
        project = self.get_object()
        user = self.request.user

        # Flag if staff user is viewing another user's project
        context["viewing_as_admin"] = (
            user.is_authenticated and user.is_staff and project.user != user
        )

        # Get submitted file (file that was submitted for manufacturing)
        submitted_file = project.submitted_file
        context["submitted_file"] = submitted_file

        # Get in-progress file (current active file being worked on)
        in_progress_file = ProjectFile.objects.filter(
            project=project,
            is_active=True,
        ).first()

        # If in-progress file is same as submitted file, don't show it twice
        if (
            in_progress_file
            and submitted_file
            and in_progress_file.id == submitted_file.id
        ):
            in_progress_file = None

        context["in_progress_file"] = in_progress_file

        # If there's an in-progress file with a download in progress, add progress info
        if in_progress_file:
            latest_attempt = in_progress_file.latest_attempt
            context["latest_attempt"] = latest_attempt

            # Get full download attempt history (all attempts, newest first)
            download_attempts = DownloadAttempt.objects.filter(
                project_file=in_progress_file,
            ).order_by("-task_started_at")
            context["download_attempts"] = download_attempts

            # Always set show_progress and show_error flags (tests expect them)
            show_progress = False
            show_error = False

            # Show progress if:
            # 1. There's an attempt in PENDING/DOWNLOADING status, OR
            # 2. There's a download_task_id (task pending but attempt not created yet)
            if latest_attempt and latest_attempt.status in [
                DownloadAttempt.Status.PENDING,
                DownloadAttempt.Status.DOWNLOADING,
            ]:
                show_progress = True
                progress = ProjectFileService.get_download_progress(in_progress_file)
                context["progress"] = progress
            elif in_progress_file.download_task_id and not latest_attempt:
                # Task is pending but DownloadAttempt not created yet
                # This happens immediately after URL submission
                show_progress = True
                progress = ProjectFileService.get_download_progress(in_progress_file)
                context["progress"] = progress

            # Add error information if download failed
            if (
                latest_attempt
                and latest_attempt.status == DownloadAttempt.Status.FAILED
            ):
                show_error = True
                context["error_message"] = latest_attempt.download_error

            context["show_progress"] = show_progress
            context["show_error"] = show_error

        # Get file history (non-active files, newest first)
        # Exclude both submitted and in-progress files from history
        exclude_ids = []
        if submitted_file:
            exclude_ids.append(submitted_file.id)
        if in_progress_file:
            exclude_ids.append(in_progress_file.id)

        history_files = (
            ProjectFile.objects.filter(project=project)
            .exclude(id__in=exclude_ids)
            .order_by("-uploaded_at")
        )
        context["history_files"] = history_files

        # Add manufacturability check (from active file if it exists)
        check = None
        active_file = in_progress_file or submitted_file
        if active_file:
            check = active_file.latest_manufacturability_check
        context["check"] = check

        return context


class ProjectCreateView(LoginRequiredMixin, CreateView):
    """Create a new project."""

    model = Project
    form_class = ProjectForm
    template_name = "projects/project_form.html"

    def get_form_kwargs(self):
        """Pass user to form for field configuration."""
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        """Add is_new flag to context for template."""
        context = super().get_context_data(**kwargs)
        context["is_new"] = True
        return context

    def form_valid(self, form):
        """Set the user before saving."""
        form.instance.user = self.request.user
        messages.success(
            self.request,
            f"Project '{form.instance.name}' created successfully!",
        )
        return super().form_valid(form)

    def get_success_url(self):
        """Redirect to project detail page."""
        # self.object is set after form_valid succeeds
        assert self.object is not None
        return reverse_lazy("projects:detail", kwargs={"pk": self.object.pk})


class ProjectUpdateView(LoginRequiredMixin, ProjectOwnerOrStaffMixin, UpdateView):
    """Update an existing project.

    Uses unified ProjectForm which adapts field editability:
    - Staff can edit all fields including core fields
    - Regular users can edit user fields, core fields are disabled
    """

    model = Project
    form_class = ProjectForm
    template_name = "projects/project_form.html"

    def get_form_kwargs(self):
        """Pass user to form for field configuration."""
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        """Add viewing_as_admin flag and is_new to context."""
        context = super().get_context_data(**kwargs)
        project = self.get_object()
        user = self.request.user

        context["viewing_as_admin"] = (
            user.is_authenticated and user.is_staff and project.user != user
        )
        context["is_new"] = False

        return context

    def form_valid(self, form):
        """Show success message."""
        messages.success(
            self.request,
            f"Project '{form.instance.name}' updated successfully!",
        )
        return super().form_valid(form)

    def get_success_url(self):
        """Redirect to project detail page."""
        # self.object is set after form_valid succeeds
        assert self.object is not None
        return reverse_lazy("projects:detail", kwargs={"pk": self.object.pk})


class ProjectDeleteView(LoginRequiredMixin, ProjectOwnerOrStaffMixin, DeleteView):
    """Delete a project."""

    model = Project
    template_name = "projects/project_confirm_delete.html"
    success_url = reverse_lazy("projects:list")

    def get_context_data(self, **kwargs):
        """Add viewing_as_admin flag to context."""
        context = super().get_context_data(**kwargs)
        project = self.get_object()
        user = self.request.user

        context["viewing_as_admin"] = (
            user.is_authenticated and user.is_staff and project.user != user
        )

        return context

    def form_valid(self, form):
        """Show success message."""
        project_name = self.object.name
        messages.success(
            self.request,
            f"Project '{project_name}' deleted successfully!",
        )
        return super().form_valid(form)


class ProjectFileSubmitURLView(LoginRequiredMixin, ProjectOwnerOrStaffMixin, View):
    """Submit a file URL for background download."""

    def get_object(self):
        """Get the project object for permission checking."""
        return get_object_or_404(Project, pk=self.kwargs["pk"])

    def get(self, request, pk):
        """Show the URL submission form."""
        project = get_object_or_404(Project, pk=pk)
        form = ProjectFileURLSubmitForm()
        return self.render_form(request, project, form)

    def post(self, request, pk):
        """Process the URL submission."""
        project = get_object_or_404(Project, pk=pk)

        form = ProjectFileURLSubmitForm(request.POST)

        if form.is_valid():
            try:
                # Submit file for download via service layer
                project_file, metadata = ProjectFileService.submit_file_from_url(
                    project=project,
                    url=form.cleaned_data["url"],
                    expected_hash_md5=form.cleaned_data.get("expected_hash_md5", ""),
                    expected_hash_sha1=form.cleaned_data.get("expected_hash_sha1", ""),
                    expected_hash_sha256=form.cleaned_data.get(
                        "expected_hash_sha256", ""
                    ),
                )

                # Build success message
                msg = f"File '{project_file.original_filename}' submitted for download!"
                if metadata["url_rewritten"]:
                    msg += f" (URL rewritten: {metadata['rewrite_reason']})"

                messages.success(request, msg)
                return redirect("projects:detail", pk=pk)

            except SecurityValidationError as e:
                messages.error(request, f"Security validation failed: {e}")

            except ValueError as e:
                messages.error(request, f"Invalid input: {e}")

            except OSError as e:
                # Catch file and network-related errors
                messages.error(request, f"An error occurred: {e}")

        return self.render_form(request, project, form)

    def render_form(self, request, project, form):
        """Render the form template."""
        user = request.user

        # Add viewing_as_admin flag for template
        viewing_as_admin = (
            user.is_authenticated and user.is_staff and project.user != user
        )

        # Check if there's a running manufacturability check that would be cancelled
        running_check = None
        active_file = ProjectFile.objects.filter(
            project=project,
            is_active=True,
        ).first()

        if active_file:
            check = active_file.latest_manufacturability_check
            if check and check.is_cancellable:
                running_check = check

        return render(
            request,
            "projects/project_file_submit_url.html",
            {
                "project": project,
                "form": form,
                "viewing_as_admin": viewing_as_admin,
                "running_check": running_check,
            },
        )


class ProjectFileProgressView(LoginRequiredMixin, ProjectOwnerOrStaffMixin, View):
    """Get download progress for a project file (AJAX endpoint)."""

    def get_object(self):
        """Get the project object for permission checking."""
        return get_object_or_404(Project, pk=self.kwargs["pk"])

    def get(self, request, pk):
        """Return progress as JSON with comprehensive status information.

        Returns:
            JsonResponse: Progress data containing:
                - status: Current download status
                - progress: Percentage (0-100)
                - current: Bytes downloaded
                - total: Total file size
                - message: User-friendly status message
                - error: Error message if failed (optional)
        """
        project = get_object_or_404(Project, pk=pk)

        # Get active file
        active_file = ProjectFile.objects.filter(
            project=project,
            is_active=True,
        ).first()

        if not active_file:
            return JsonResponse({"error": "No active file found"}, status=404)

        # Get latest download attempt
        latest_attempt = active_file.latest_attempt
        if not latest_attempt:
            return JsonResponse({"error": "No active download"}, status=404)

        # Get progress from service layer
        progress = ProjectFileService.get_download_progress(active_file)

        # Add attempt count for UI to detect new attempts
        progress["attempt_count"] = active_file.download_attempts.count()

        # Add error information if download failed
        if latest_attempt.status == DownloadAttempt.Status.FAILED:
            progress["error"] = latest_attempt.download_error or "Download failed"

        return JsonResponse(progress)


class ManufacturabilityCheckStatusView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Get manufacturability check status (AJAX endpoint)."""

    def test_func(self):
        """Only allow the owner to view check status."""
        project = get_object_or_404(Project, pk=self.kwargs["pk"])
        return project.user == self.request.user

    def get(self, request, pk):
        """Return check status as JSON.

        Returns:
            JsonResponse: Check status data containing:
                - status: Current check status (pending, running, finished, error)
                - processing_logs: Raw logs from the check
                - is_manufacturable: Boolean or null
                - error_message: Error message if error occurred
        """
        project = get_object_or_404(Project, pk=pk)

        # Check if user owns the project
        if project.user != request.user:
            return JsonResponse({"error": "Permission denied"}, status=403)

        # Get active file's manufacturability check
        active_file = ProjectFile.objects.filter(
            project=project,
            is_active=True,
        ).first()

        if not active_file:
            return JsonResponse({"error": "No active file found"}, status=404)

        check = active_file.latest_manufacturability_check
        if not check:
            return JsonResponse(
                {"error": "No manufacturability check found"}, status=404
            )

        started = (
            check.container_started_at.isoformat()
            if check.container_started_at
            else None
        )
        finished = (
            check.analysis_completed_at.isoformat()
            if check.analysis_completed_at
            else None
        )

        return JsonResponse(
            {
                "status": check.status,
                "processing_logs": check.processing_logs or "",
                "is_manufacturable": check.is_manufacturable,
                "error_message": check.error_message or "",
                "started_at": started,
                "completed_at": finished,
            }
        )


class ManufacturabilityCheckCancelView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Cancel a running manufacturability check (POST-only)."""

    def test_func(self):
        """Allow owner, staff, or superuser to cancel the check."""
        user = self.request.user
        if user.is_authenticated and (user.is_superuser or user.is_staff):
            return True
        project = get_object_or_404(Project, pk=self.kwargs["pk"])
        return project.user == user

    def post(self, request, pk, check_id):
        """Handle check cancellation."""
        project = get_object_or_404(Project, pk=pk)

        # Get the specific check by ID
        check = get_object_or_404(
            ManufacturabilityCheck,
            pk=check_id,
            project=project,
        )

        try:
            # Indicate whether cancelled by owner or admin
            if project.user == request.user:
                reason = "Cancelled by owner"
            else:
                reason = f"Cancelled by admin ({request.user.username})"
            check.mark_cancelling(reason=reason)
            messages.success(request, "Cancellation requested. Cleanup in progress...")
        except InvalidStateTransitionError:
            msg = "Check could not be cancelled (already finished or in error state)."
            messages.warning(request, msg)

        return redirect("projects:detail", pk=pk)


class ManufacturabilityCheckAdminStatusView(
    LoginRequiredMixin, UserPassesTestMixin, View
):
    """Admin-only status page for monitoring all manufacturability checks."""

    def test_func(self):
        """Only allow staff users to view this page."""
        return self.request.user.is_staff

    def get(self, request):
        """Display manufacturability check status dashboard."""
        # Get counts by status
        status_counts = {}
        for status_value, status_label in ManufacturabilityCheck.Status.choices:
            count = ManufacturabilityCheck.objects.filter(status=status_value).count()
            status_counts[status_value] = {
                "label": status_label,
                "count": count,
            }

        # Get recent checks (last 50)
        recent_checks = ManufacturabilityCheck.objects.select_related(
            "project",
            "project__user",
            "project_file",
        ).order_by("-id")[:50]

        # Build active sections for all non-terminal statuses
        active_sections = []
        for status in ManufacturabilityCheck.Status.non_terminal():
            # Get metadata for this status
            metadata = ManufacturabilityCheck.get_status_metadata(status)

            # Get checks for this status (ordered newest first)
            checks = (
                ManufacturabilityCheck.objects.filter(status=status)
                .select_related(
                    "project",
                    "project__user",
                    "project_file",
                )
                .order_by("-created_at")
            )

            count = checks.count()
            if count > 0:
                active_sections.append(
                    {
                        "status": status,
                        "label": metadata["label"],
                        "color": metadata["color"],
                        "icon": metadata["icon"],
                        "show_spinner": metadata["show_spinner"],
                        "checks": checks,
                        "count": count,
                    }
                )

        # Reverse order so running checks appear first
        active_sections.reverse()

        return render(
            request,
            "projects/manufacturability_check_status.html",
            {
                "status_counts": status_counts,
                "recent_checks": recent_checks,
                "active_sections": active_sections,
            },
        )


class ProjectSubmitView(LoginRequiredMixin, ProjectOwnerOrStaffMixin, View):
    """Submit a project for manufacturing (POST-only)."""

    def get_object(self):
        """Get the project object for permission checking."""
        return get_object_or_404(Project, pk=self.kwargs["pk"])

    def post(self, request, pk):
        """Handle project submission."""
        project = get_object_or_404(Project, pk=pk)

        try:
            # Attempt to submit the project
            project.submit()

            messages.success(
                request,
                f"Project '{project.name}' submitted successfully for manufacturing!",
            )

        except ValidationError as e:
            # Handle validation errors with user-friendly messages
            messages.error(
                request,
                f"Cannot submit project: {e.message}",
            )

        except Exception:
            # Log unexpected errors
            logger.exception(
                "Unexpected error submitting project %s",
                project.pk,
            )
            messages.error(
                request,
                "An unexpected error occurred while submitting the project. "
                "Please try again later.",
            )

        # Always redirect back to project detail page
        return redirect("projects:detail", pk=pk)


class ProjectIDCheckView(LoginRequiredMixin, View):
    """AJAX endpoint to check if project ID is available within a shuttle."""

    def get(self, request):
        """Check if project_id is available for the given shuttle.

        Query parameters:
            shuttle: Shuttle primary key
            project_id: 4-character project ID to check

        Returns:
            JSON response with availability status and message
        """
        shuttle_id = request.GET.get("shuttle")
        project_id_raw = request.GET.get("project_id", "").strip()
        project_id = project_id_raw.upper()

        if not shuttle_id or not project_id:
            return JsonResponse(
                {"available": False, "message": "Missing parameters"},
                status=400,
            )

        # Validate project_id format
        if len(project_id) != PROJECT_ID_LENGTH:
            return JsonResponse(
                {
                    "available": False,
                    "message": f"Project ID must be {PROJECT_ID_LENGTH} characters",
                },
            )

        if not project_id.isalnum():
            return JsonResponse(
                {"available": False, "message": "Project ID must be alphanumeric"},
            )

        # Check uppercase requirement (matches model validator)
        if project_id != project_id_raw:
            return JsonResponse(
                {"available": False, "message": "Project ID must be uppercase"},
            )

        # Validate shuttle exists
        try:
            Shuttle.objects.get(pk=shuttle_id)
        except (Shuttle.DoesNotExist, ValueError):
            return JsonResponse(
                {"available": False, "message": "Invalid shuttle"},
                status=400,
            )

        # Check if already exists for this shuttle
        exists = Project.objects.filter(
            shuttle_id=shuttle_id,
            project_id=project_id,
        ).exists()

        return JsonResponse(
            {
                "available": not exists,
                "message": f"ID {project_id} is {'taken' if exists else 'available'}",
            },
        )


class ShuttleAvailableSizesView(LoginRequiredMixin, View):
    """AJAX endpoint to get available slot sizes for a shuttle.

    For Phase A, returns all slot sizes from SlotSize enum.
    For Phase B, will query shuttle's actual available sizes based on grid layout.
    """

    def get(self, request):
        """Get available slot sizes for the given shuttle.

        Query parameters:
            shuttle: Shuttle primary key

        Returns:
            JSON response with list of available size options
        """
        shuttle_id = request.GET.get("shuttle")

        if not shuttle_id:
            return JsonResponse({"sizes": []})

        try:
            # Verify shuttle exists
            Shuttle.objects.get(pk=shuttle_id)

            # Phase A: Return all slot sizes
            # Phase B will query shuttle.get_available_slot_sizes()
            size_options = [
                {"value": value, "label": label} for value, label in SlotSize.choices
            ]

            return JsonResponse({"sizes": size_options})
        except (Shuttle.DoesNotExist, ValueError):
            return JsonResponse({"sizes": []}, status=404)


class ProjectAdminSummaryView(LoginRequiredMixin, UserPassesTestMixin, ListView):
    """Staff-only summary of all projects with sortable columns."""

    template_name = "projects/admin_summary.html"
    context_object_name = "projects"

    SORT_FIELDS: ClassVar[dict[str, tuple[str, ...]]] = {
        "full_id": ("shuttle__name", "project_id"),
        "size": ("slot_size",),
        "name": ("name",),
        "owner": ("user__username",),
        "email": ("user__email",),
    }
    DEFAULT_SORT: ClassVar[str] = "name"

    def test_func(self) -> bool:
        """Only staff users can access this view."""
        return self.request.user.is_staff

    def get_sort_params(self) -> tuple[str, bool]:
        """Parse sort parameter and return (field, descending)."""
        sort = self.request.GET.get("sort", self.DEFAULT_SORT)
        descending = sort.startswith("-")
        field = sort.lstrip("-")
        if field not in self.SORT_FIELDS:
            field = self.DEFAULT_SORT
            descending = False
        return field, descending

    def get_queryset(self):
        """Return all projects with optimized queries and sorting."""
        qs = Project.objects.select_related("user", "shuttle").prefetch_related(
            Prefetch(
                "files",
                queryset=ProjectFile.objects.filter(is_active=True).prefetch_related(
                    "manufacturability_checks"
                ),
                to_attr="active_files",
            )
        )

        field, descending = self.get_sort_params()
        order_fields = self.SORT_FIELDS[field]
        if descending:
            order_fields = tuple(f"-{f}" for f in order_fields)
        return qs.order_by(*order_fields)

    def get_context_data(self, **kwargs):
        """Add sort information and summary statistics to context."""
        context = super().get_context_data(**kwargs)
        field, descending = self.get_sort_params()
        context["current_sort"] = field
        context["sort_descending"] = descending

        # Compute summary statistics from the projects list
        projects = context["projects"]
        context["summary"] = self._compute_summary_stats(projects)
        return context

    def _compute_summary_stats(self, projects):
        """Compute summary statistics for the projects list."""
        # Initialize counters
        status_counts: Counter[str] = Counter()
        manufacturable_by_size: Counter[str] = Counter()
        non_manufacturable_by_size: Counter[str] = Counter()
        pending_by_size: Counter[str] = Counter()  # No result yet

        for project in projects:
            size = project.slot_size
            active_file = project.active_files[0] if project.active_files else None
            check = active_file.latest_manufacturability_check if active_file else None

            if check:
                status_counts[check.status] += 1
                if check.is_manufacturable is True:
                    manufacturable_by_size[size] += 1
                elif check.is_manufacturable is False:
                    non_manufacturable_by_size[size] += 1
                else:
                    # Has check but no result yet
                    pending_by_size[size] += 1
            else:
                # No check at all
                status_counts["no_check"] += 1
                pending_by_size[size] += 1

        # Build status summary with display names and colors
        status_summary = []
        for status in ManufacturabilityCheck.Status:
            count = status_counts.get(status.value, 0)
            if count > 0:
                metadata = ManufacturabilityCheck.get_status_metadata(status.value)
                status_summary.append(
                    {
                        "label": status.label,
                        "count": count,
                        "color": metadata["color"],
                    }
                )
        if status_counts.get("no_check", 0) > 0:
            status_summary.append(
                {
                    "label": "No Check",
                    "count": status_counts["no_check"],
                    "color": "secondary",
                }
            )

        # Build size breakdowns with short display labels
        # Extract short name from label (e.g., "1×1 - Full Slot..." → "1×1")
        short_size_labels = {
            choice.value: choice.label.split(" - ")[0] for choice in SlotSize
        }

        def build_size_breakdown(counter):
            return [
                {"size": short_size_labels.get(size, size), "count": count}
                for size, count in sorted(counter.items())
                if count > 0
            ]

        return {
            "total": len(projects),
            "manufacturable_total": sum(manufacturable_by_size.values()),
            "manufacturable_by_size": build_size_breakdown(manufacturable_by_size),
            "non_manufacturable_total": sum(non_manufacturable_by_size.values()),
            "non_manufacturable_by_size": build_size_breakdown(
                non_manufacturable_by_size
            ),
            "pending_total": sum(pending_by_size.values()),
            "pending_by_size": build_size_breakdown(pending_by_size),
            "status_counts": status_summary,
        }
