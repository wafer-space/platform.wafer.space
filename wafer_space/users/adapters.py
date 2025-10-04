from __future__ import annotations

import logging
import typing

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings

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
        user = super().populate_user(request, sociallogin, data)
        if not user.name:
            if name := data.get("name"):
                user.name = name
            elif first_name := data.get("first_name"):
                user.name = first_name
                if last_name := data.get("last_name"):
                    user.name += f" {last_name}"
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
