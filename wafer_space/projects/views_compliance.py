"""Views for export compliance certification."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from wafer_space.core.utils import get_client_ip

from .forms import ComplianceCertificationForm
from .models import Project
from .models import ProjectComplianceCertification

if TYPE_CHECKING:
    from uuid import UUID

    from django.http import HttpRequest
    from django.http import HttpResponse


@login_required
@require_http_methods(["GET", "POST"])
def compliance_certification_create(request: HttpRequest, pk: UUID) -> HttpResponse:
    """Create or update compliance certification for a project.

    Args:
        request: Django request object
        pk: Project UUID

    Returns:
        Rendered template or redirect to shuttle list
    """
    project = get_object_or_404(Project, pk=pk, user=request.user)

    # The latest file revision must be manufacturable (its latest finished
    # check passed) - see docs/manufacturable_vs_submitted.md. A check on an
    # older revision must not open the gate for a newer, unchecked one.
    if not project.latest_file_check:
        messages.error(
            request,
            "This project has not been checked for manufacturability yet.",
        )
        return redirect("projects:detail", pk=project.pk)
    if project.latest_file_manufacturable is not True:
        messages.error(
            request,
            "This project must pass manufacturability checks before certification.",
        )
        return redirect("projects:detail", pk=project.pk)

    # Check if already certified for context
    try:
        existing_cert = ProjectComplianceCertification.objects.get(project=project)
    except ProjectComplianceCertification.DoesNotExist:
        existing_cert = None

    if request.method == "POST":
        form = ComplianceCertificationForm(request.POST)
        if form.is_valid():
            # Check if already exists
            if existing_cert:
                # Update existing certification
                for field in [
                    "export_control_compliant",
                    "not_restricted_entity",
                    "end_use_statement",
                ]:
                    setattr(existing_cert, field, form.cleaned_data[field])
                certification = existing_cert
            else:
                # Create new certification
                certification = form.save(commit=False)
                certification.project = project
                certification.certified_by = request.user

            # Capture IP address and user agent
            certification.ip_address = get_client_ip(request)
            certification.user_agent = request.headers.get("user-agent", "")
            certification.save()

            messages.success(
                request,
                "Compliance certification completed successfully.",
            )
            return redirect("projects:detail", pk=project.pk)

        messages.error(request, "Please correct the errors below.")
    # Pre-populate form if already certified
    elif existing_cert:
        form = ComplianceCertificationForm(instance=existing_cert)
        messages.info(
            request,
            "This project has already been certified. "
            "You can update your certification below.",
        )
    else:
        form = ComplianceCertificationForm()

    context = {
        "project": project,
        "form": form,
        "certification": existing_cert,
    }

    return render(
        request,
        "projects/compliance_certification_form.html",
        context,
    )
