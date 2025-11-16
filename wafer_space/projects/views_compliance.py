"""Views for export compliance certification."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .forms import ComplianceCertificationForm
from .models import Project
from .models import ProjectComplianceCertification


def get_client_ip(request):
    """Extract client IP address from request."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip


@login_required
@require_http_methods(["GET", "POST"])
def compliance_certification_create(request, pk):
    """Create or update compliance certification for a project.

    Args:
        request: Django request object
        pk: Project UUID

    Returns:
        Rendered template or redirect to shuttle list
    """
    project = get_object_or_404(Project, pk=pk, user=request.user)

    # Check if project is manufacturable
    if not hasattr(project, "manufacturability_check"):
        messages.error(
            request,
            "This project has not been checked for manufacturability yet.",
        )
        return redirect("projects:detail", pk=project.pk)

    check = project.manufacturability_check
    if not check.is_manufacturable:
        messages.error(
            request,
            "This project must pass manufacturability checks before certification.",
        )
        return redirect("projects:detail", pk=project.pk)

    # Get or create certification
    certification, _created = ProjectComplianceCertification.objects.get_or_create(
        project=project,
        defaults={"certified_by": request.user},
    )

    if request.method == "POST":
        form = ComplianceCertificationForm(request.POST, instance=certification)
        if form.is_valid():
            certification = form.save(commit=False)
            certification.project = project
            certification.certified_by = request.user
            certification.ip_address = get_client_ip(request)
            certification.user_agent = request.META.get("HTTP_USER_AGENT", "")
            certification.save()

            messages.success(
                request,
                "Compliance certification submitted successfully. "
                "You may now request a shuttle slot.",
            )
            return redirect("shuttles:list")
    else:
        form = ComplianceCertificationForm(instance=certification)

    context = {
        "project": project,
        "form": form,
        "certification": certification,
    }

    return render(
        request,
        "projects/compliance_certification_form.html",
        context,
    )
