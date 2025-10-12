"""Views for Terms of Service management."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .models import TermsOfService
from .models import TermsOfServiceAcceptance


def tos_display(request):
    """Display the current Terms of Service (public view)."""
    active_tos = TermsOfService.get_active()

    if not active_tos:
        msg = "No Terms of Service is currently active."
        raise Http404(msg)

    context = {
        "tos": active_tos,
    }
    return render(request, "legal/tos_display.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def tos_accept(request):
    """Handle Terms of Service acceptance."""
    active_tos = TermsOfService.get_active()

    if not active_tos:
        messages.error(request, "No Terms of Service is currently active.")
        return redirect("home")

    # Check if user has already accepted
    if TermsOfServiceAcceptance.has_accepted_active(request.user):
        messages.info(request, "You have already accepted the Terms of Service.")
        return redirect(request.session.get("tos_redirect_after_accept", "home"))

    if request.method == "POST":
        # Check if user agreed
        if request.POST.get("agree") == "on":
            # Get IP address from request
            x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(",")[0].strip()
            else:
                ip_address = request.META.get("REMOTE_ADDR")

            # Get user agent
            user_agent = request.META.get("HTTP_USER_AGENT", "")

            # Create acceptance record
            TermsOfServiceAcceptance.objects.create(
                user=request.user,
                tos_version=active_tos,
                ip_address=ip_address,
                user_agent=user_agent,
            )

            messages.success(
                request,
                "Thank you for accepting the Terms of Service.",
            )

            # Redirect to original page or home
            redirect_url = request.session.pop("tos_redirect_after_accept", "home")
            return redirect(redirect_url)

        # User didn't check the agreement box
        messages.error(
            request,
            "You must agree to the Terms of Service to continue.",
        )

    context = {
        "tos": active_tos,
    }
    return render(request, "legal/tos_accept.html", context)
