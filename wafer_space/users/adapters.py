from __future__ import annotations

import logging
import typing

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.base import AuthError
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied

from wafer_space.core.utils import get_client_ip

if typing.TYPE_CHECKING:
    from allauth.socialaccount.models import SocialLogin
    from allauth.socialaccount.providers.base import Provider
    from django.http import HttpRequest

    from wafer_space.users.models import User

logger = logging.getLogger(__name__)


def _is_provider_response(request: HttpRequest) -> bool:
    """Whether the request carries an OAuth provider's ``code`` or ``error``."""
    return "code" in request.GET or "error" in request.GET


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request: HttpRequest) -> bool:
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def get_client_ip(self, request: HttpRequest) -> str:
        """Return the IP resolved by RealClientIPMiddleware (issue #274).

        allauth's default prefers the first X-Forwarded-For entry, which the
        client controls, so its per-IP rate limits (login, signup, password
        reset) could be dodged by rotating a forged header. With no IP at
        all every anonymous visitor would share one rate-limit bucket, which
        only happens when the proxy is misconfigured: fail loudly instead.
        """
        client_ip = get_client_ip(request)
        if client_ip is None:
            logger.error("Cannot determine the client IP for %s", request.path)
            msg = "Unable to determine the client IP address."
            raise PermissionDenied(msg)
        return client_ip


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(
        self,
        request: HttpRequest,
        sociallogin: SocialLogin,
    ) -> bool:
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def populate_user(
        self,
        request: HttpRequest,
        sociallogin: SocialLogin,
        data: dict[str, typing.Any],
    ) -> User:
        """
        Populates user information from social provider info.

        See: https://docs.allauth.org/en/latest/socialaccount/advanced.html#creating-and-populating-user-instances
        """
        provider = sociallogin.account.provider
        logger.info(
            "Populating user from %s provider",
            provider,
            extra={
                "provider": provider,
                "data_keys": list(data.keys()),
                "has_email": bool(data.get("email")),
            },
        )

        try:
            user = super().populate_user(request, sociallogin, data)
            if not user.name:
                if name := data.get("name"):
                    user.name = name
                elif first_name := data.get("first_name"):
                    user.name = first_name
                    if last_name := data.get("last_name"):
                        user.name += f" {last_name}"
        except Exception as e:
            # Log error without exposing sensitive OAuth data
            safe_data_keys = ["email", "name", "first_name", "last_name", "username"]
            safe_data = {k: data.get(k) for k in safe_data_keys if k in data}
            logger.exception(
                "Error populating user from %s",
                provider,
                extra={
                    "provider": provider,
                    "error_type": type(e).__name__,
                    "safe_data": safe_data,
                    "available_keys": list(data.keys()),
                },
            )
            raise
        else:
            return user

    def pre_social_login(
        self,
        request: HttpRequest,
        sociallogin: SocialLogin,
    ) -> None:
        """
        Invoked just after a user successfully authenticates via a social provider.

        This is called before the login is actually processed, allowing us to
        handle account linking, logging, and custom business logic.

        See: https://docs.allauth.org/en/latest/socialaccount/signals.html
        """
        # Log social login attempts for security monitoring
        provider = sociallogin.account.provider
        email = (
            sociallogin.email_addresses[0].email
            if sociallogin.email_addresses
            else "no-email"
        )

        if sociallogin.is_existing:
            logger.info(
                "Social login: existing account",
                extra={
                    "provider": provider,
                    "email": email,
                    "user_id": sociallogin.user.pk if sociallogin.user else None,
                },
            )
        else:
            logger.info(
                "Social login: new account or connection",
                extra={
                    "provider": provider,
                    "email": email,
                },
            )

        # Call parent implementation (handles email-based authentication if configured)
        super().pre_social_login(request, sociallogin)

    def on_authentication_error(
        self,
        request: HttpRequest,
        provider: str | Provider,
        error: str | None = None,
        exception: Exception | None = None,
        extra_context: dict[str, typing.Any] | None = None,
    ) -> None:
        """
        Handle authentication errors and provide better error messages.

        allauth passes ``error`` as an ``AuthError`` string constant
        ("unknown", "cancelled", "denied") and only sets ``exception``
        for genuine failures; a user cancelling the provider consent
        screen arrives here with ``error="cancelled"`` and no exception.
        """
        # Extract provider ID string - handle both string and Provider object
        provider_str = provider if isinstance(provider, str) else str(provider.id)
        error_code = str(error) if error else AuthError.UNKNOWN

        # Build error context - only log safe information, not full error messages
        # that could contain tokens or sensitive URLs. Include the request so
        # AdminEmailHandler can add request data to error emails.
        error_context: dict[str, typing.Any] = {
            "provider": provider_str,
            "error_code": error_code,
            "error_type": type(exception).__name__ if exception else None,
            "request": request,
        }

        # Only add safe extra context (exclude any OAuth response data)
        if extra_context:
            safe_context = {
                k: v
                for k, v in extra_context.items()
                if k not in ["error", "error_description", "error_uri"]
            }
            if safe_context:
                error_context["extra"] = safe_context

        if error_code == AuthError.CANCELLED:
            # User backed out at the provider - not an application error, and
            # allauth already renders its dedicated "login cancelled" page.
            logger.info(
                "Social login cancelled by user for %s",
                provider_str,
                extra=error_context,
            )
        elif exception is None and not _is_provider_response(request):
            # A GET with neither ``code`` nor ``error`` never came from the
            # provider: crawlers fetch the bare callback URL they find in
            # the login redirect (issue #338). Keep a trace, but don't email
            # ADMINS. A real callback that fails (expired session, provider
            # error, bad code) carries one of them and still logs an error.
            logger.warning(
                "Social login callback for %s without a provider response: %s",
                provider_str,
                error_code,
                extra=error_context,
            )
            self._add_authentication_error_message(request, provider_str, exception)
        else:
            logger.error(
                "Social authentication error for %s: %s",
                provider_str,
                error_code,
                exc_info=exception if isinstance(exception, BaseException) else None,
                extra=error_context,
            )
            self._add_authentication_error_message(request, provider_str, exception)

        # Call parent implementation
        super().on_authentication_error(
            request,
            provider,
            error=error,
            exception=exception,
            extra_context=extra_context,
        )

    @staticmethod
    def _add_authentication_error_message(
        request: HttpRequest,
        provider_str: str,
        exception: Exception | None,
    ) -> None:
        """Queue a user-friendly flash message WITHOUT raw error details."""
        provider_name = provider_str.replace("_", " ").title()

        if exception:
            error_msg = str(exception).lower()
            # Check for common error patterns but NEVER display the raw error
            if "email" in error_msg:
                messages.error(
                    request,
                    f"{provider_name} login failed: Email address is required. "
                    f"Please ensure your {provider_name} account has a "
                    f"verified email address.",
                )
            elif "scope" in error_msg or "permission" in error_msg:
                messages.error(
                    request,
                    f"{provider_name} login failed: Required permissions "
                    f"were not granted. Please grant access to your profile "
                    f"and email when prompted.",
                )
            elif "token" in error_msg or "code" in error_msg:
                messages.error(
                    request,
                    f"{provider_name} login failed: Authentication error. "
                    f"Please try again or contact support if the problem persists.",
                )
            else:
                # Generic error - do NOT expose the actual error message
                messages.error(
                    request,
                    f"{provider_name} login failed. "
                    f"Please try again or contact support if the problem persists.",
                )
        else:
            messages.error(
                request,
                f"{provider_name} login failed. "
                f"Please try again or contact support if the problem persists.",
            )
