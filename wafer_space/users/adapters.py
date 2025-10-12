from __future__ import annotations

import logging
import typing

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.contrib import messages

if typing.TYPE_CHECKING:
    from allauth.socialaccount.models import SocialLogin
    from django.http import HttpRequest

    from wafer_space.users.models import User

logger = logging.getLogger(__name__)


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request: HttpRequest) -> bool:
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)


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
            logger.exception(
                "Error populating user from %s",
                provider,
                extra={
                    "provider": provider,
                    "error": str(e),
                    "data": data,
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
        provider_id: str,
        error: Exception | None = None,
        exception: Exception | None = None,
        extra_context: dict[str, typing.Any] | None = None,
    ) -> None:
        """
        Handle authentication errors and provide better error messages.

        This method is called when authentication fails. We log detailed
        information for debugging and provide user-friendly error messages.
        """
        # Use the exception if provided, otherwise use error
        exc = exception or error

        # Extract provider ID string - handle both string and Provider object
        if hasattr(provider_id, "id"):
            provider_str = provider_id.id
        else:
            provider_str = str(provider_id)

        # Build detailed error context
        error_context = {
            "provider": provider_str,
            "error_type": type(exc).__name__ if exc else "Unknown",
            "error_message": str(exc) if exc else "No error details provided",
        }

        if extra_context:
            error_context.update(extra_context)

        # Log the error with full details
        logger.error(
            "Social authentication error for %s",
            provider_str,
            exc_info=exc if exc else None,
            extra=error_context,
        )

        # Provide user-friendly error message
        provider_name = provider_str.replace("_", " ").title()

        if exc:
            error_msg = str(exc)
            if "email" in error_msg.lower():
                messages.error(
                    request,
                    f"{provider_name} login failed: Email address is required. "
                    f"Please ensure your {provider_name} account has a "
                    f"verified email address.",
                )
            elif "scope" in error_msg.lower():
                messages.error(
                    request,
                    f"{provider_name} login failed: Required permissions "
                    f"were not granted. Please grant access to your profile "
                    f"and email when prompted.",
                )
            elif "token" in error_msg.lower() or "code" in error_msg.lower():
                messages.error(
                    request,
                    f"{provider_name} login failed: Authentication token error. "
                    f"Please try again or contact support if the problem persists.",
                )
            else:
                messages.error(
                    request,
                    f"{provider_name} login failed: {error_msg}. "
                    f"Please try again or contact support.",
                )
        else:
            messages.error(
                request,
                f"{provider_name} login failed. Please try again or contact support.",
            )

        # Call parent implementation
        super().on_authentication_error(
            request,
            provider_id,
            error=error,
            exception=exception,
            extra_context=extra_context,
        )
