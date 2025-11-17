"""Views for project management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import ValidationError
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

from .forms import ProjectFileURLSubmitForm
from .forms import ProjectForm
from .models import DownloadAttempt
from .models import Project
from .models import ProjectComplianceCertification
from .models import ProjectFile
from .security import SecurityValidationError
from .services import ManufacturabilityService
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
        """Return only projects owned by the current user."""
        # Cast user since LoginRequiredMixin ensures authentication
        user = cast("User", self.request.user)
        return Project.objects.filter(user=user).order_by("-created_at")


class ProjectDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    """View a single project with its files."""

    model = Project
    template_name = "projects/project_detail.html"
    context_object_name = "project"

    def test_func(self):
        """Only allow the owner to view the project."""
        project = self.get_object()
        return project.user == self.request.user

    def get_context_data(self, **kwargs):
        """Add project files and status to context."""
        context = super().get_context_data(**kwargs)
        project = self.get_object()

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
            ).order_by("-started_at")
            context["download_attempts"] = download_attempts

            # Always set show_progress and show_error flags (tests expect them)
            show_progress = False
            show_error = False

            # Show progress if:
            # 1. There's an attempt in PENDING/DOWNLOADING status, OR
            # 2. There's a download_task_id (task queued but attempt not created yet)
            if latest_attempt and latest_attempt.status in [
                DownloadAttempt.Status.PENDING,
                DownloadAttempt.Status.DOWNLOADING,
            ]:
                show_progress = True
                progress = ProjectFileService.get_download_progress(in_progress_file)
                context["progress"] = progress
            elif in_progress_file.download_task_id and not latest_attempt:
                # Task is queued but DownloadAttempt not created yet
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

        # Add manufacturability check status
        check_status = ManufacturabilityService.get_check_status(project)
        context["check_status"] = check_status

        # Add compliance certification status
        try:
            compliance_cert = project.compliance_certification
            context["compliance_certification"] = compliance_cert
        except ProjectComplianceCertification.DoesNotExist:
            context["compliance_certification"] = None

        return context


class ProjectCreateView(LoginRequiredMixin, CreateView):
    """Create a new project."""

    model = Project
    form_class = ProjectForm
    template_name = "projects/project_form.html"

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


class ProjectUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    """Update an existing project."""

    model = Project
    form_class = ProjectForm
    template_name = "projects/project_form.html"

    def test_func(self):
        """Only allow the owner to update the project."""
        project = self.get_object()
        return project.user == self.request.user

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


class ProjectDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    """Delete a project."""

    model = Project
    template_name = "projects/project_confirm_delete.html"
    success_url = reverse_lazy("projects:list")

    def test_func(self):
        """Only allow the owner to delete the project."""
        project = self.get_object()
        return project.user == self.request.user

    def form_valid(self, form):
        """Show success message."""
        project_name = self.object.name
        messages.success(
            self.request,
            f"Project '{project_name}' deleted successfully!",
        )
        return super().form_valid(form)


class ProjectFileSubmitURLView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Submit a file URL for background download."""

    def test_func(self):
        """Only allow the owner to submit files."""
        project = get_object_or_404(Project, pk=self.kwargs["pk"])
        return project.user == self.request.user

    def get(self, request, pk):
        """Show the URL submission form."""
        project = get_object_or_404(Project, pk=pk)

        # Check if user owns the project
        if project.user != request.user:
            messages.error(
                request,
                "You don't have permission to add files to this project.",
            )
            return redirect("projects:detail", pk=pk)

        form = ProjectFileURLSubmitForm()
        return self.render_form(request, project, form)

    def post(self, request, pk):
        """Process the URL submission."""
        project = get_object_or_404(Project, pk=pk)

        # Check if user owns the project
        if project.user != request.user:
            messages.error(
                request,
                "You don't have permission to add files to this project.",
            )
            return redirect("projects:detail", pk=pk)

        form = ProjectFileURLSubmitForm(request.POST)

        if form.is_valid():
            try:
                # Submit file for download via service layer
                project_file, metadata = ProjectFileService.submit_file_from_url(
                    project=project,
                    url=form.cleaned_data["url"],
                    expected_hash_md5=form.cleaned_data.get("expected_hash_md5", ""),
                    expected_hash_sha1=form.cleaned_data.get("expected_hash_sha1", ""),
                )

                # Build success message
                msg = f"File '{project_file.original_filename}' submitted for download!"
                if metadata["url_rewritten"]:
                    msg += f" (URL rewritten: {metadata['rewrite_reason']})"

                messages.success(request, msg)
                return redirect("projects:detail", pk=pk)

            except SecurityValidationError as e:
                messages.error(request, f"Security validation failed: {e}")
                return self.render_form(request, project, form)

            except ValueError as e:
                messages.error(request, f"Invalid input: {e}")
                return self.render_form(request, project, form)

            except OSError as e:
                # Catch file and network-related errors
                messages.error(request, f"An error occurred: {e}")
                return self.render_form(request, project, form)

        return self.render_form(request, project, form)

    def render_form(self, request, project, form):
        """Render the form template."""
        return render(
            request,
            "projects/project_file_submit_url.html",
            {
                "project": project,
                "form": form,
            },
        )


class ProjectFileProgressView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Get download progress for a project file (AJAX endpoint)."""

    def test_func(self):
        """Only allow the owner to view progress."""
        project = get_object_or_404(Project, pk=self.kwargs["pk"])
        return project.user == self.request.user

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

        # Check if user owns the project
        if project.user != request.user:
            return JsonResponse({"error": "Permission denied"}, status=403)

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


class ProjectSubmitView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Submit a project for manufacturing (POST-only)."""

    def test_func(self):
        """Only allow the owner to submit the project."""
        project = get_object_or_404(Project, pk=self.kwargs["pk"])
        return project.user == self.request.user

    def post(self, request, pk):
        """Handle project submission."""
        project = get_object_or_404(Project, pk=pk)

        # Verify ownership (redundant with test_func but explicit)
        if project.user != request.user:
            messages.error(
                request,
                "You don't have permission to submit this project.",
            )
            return redirect("projects:detail", pk=pk)

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
