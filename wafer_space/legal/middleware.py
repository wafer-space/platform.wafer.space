"""Middleware for Terms of Service acceptance enforcement."""

from urllib.parse import urlparse

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class TOSAcceptanceMiddleware:
    """Middleware to enforce TOS acceptance before accessing site functionality."""

    def __init__(self, get_response):
        """Initialize middleware."""
        self.get_response = get_response

    def __call__(self, request):
        """Process request and enforce TOS acceptance."""
        # Skip TOS check if user is not authenticated
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Skip TOS check for superusers (allow admin access)
        if request.user.is_superuser:
            return self.get_response(request)

        # Skip TOS check for exempt URLs
        if self._is_exempt_url(request.path):
            return self.get_response(request)

        # Check if user has accepted the active TOS
        from .models import TermsOfServiceAcceptance  # noqa: PLC0415

        if not TermsOfServiceAcceptance.has_accepted_active(request.user):
            # Redirect to TOS acceptance page
            tos_accept_url = reverse("legal:tos_accept")
            if request.path != tos_accept_url:
                # Store the original URL to redirect back after acceptance
                request.session["tos_redirect_after_accept"] = request.path
                return redirect(tos_accept_url)

        return self.get_response(request)

    def _is_exempt_url(self, path: str) -> bool:
        """Check if URL is exempt from TOS requirement."""
        exempt_patterns = [
            # Authentication URLs
            "/accounts/login/",
            "/accounts/logout/",
            "/accounts/signup/",
            "/accounts/",  # All allauth URLs
            # Legal URLs
            "/legal/",
            # Admin URLs
            f"/{settings.ADMIN_URL}",
            # Debug toolbar (development only)
            "/__debug__/",
        ]

        # Add static and media URLs if configured
        # Handle both path and full URL formats
        if settings.STATIC_URL:
            static_path = urlparse(settings.STATIC_URL).path or settings.STATIC_URL
            exempt_patterns.append(static_path)
        if settings.MEDIA_URL:
            media_path = urlparse(settings.MEDIA_URL).path or settings.MEDIA_URL
            exempt_patterns.append(media_path)

        return any(pattern and path.startswith(pattern) for pattern in exempt_patterns)
