"""Management command to promote a user to staff/admin status."""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

User = get_user_model()


class Command(BaseCommand):
    """Promote an existing user to staff and/or superuser status."""

    help = "Promote an existing user to staff (admin) and/or superuser status"

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Add command arguments."""
        parser.add_argument(
            "username",
            type=str,
            nargs="?",
            default=None,
            help="Username or email of the user to promote",
        )
        parser.add_argument(
            "--staff",
            action="store_true",
            default=False,
            help="Grant staff status (access to admin site)",
        )
        parser.add_argument(
            "--superuser",
            action="store_true",
            default=False,
            help="Grant superuser status (all permissions)",
        )
        parser.add_argument(
            "--demote",
            action="store_true",
            default=False,
            help="Remove the specified permissions instead of granting them",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            default=False,
            dest="list_users",
            help="List all staff/superusers instead of promoting",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Execute the command."""
        if options["list_users"]:
            self._list_staff_users()
            return

        username = options["username"]
        if not username:
            msg = "Username is required unless using --list"
            raise CommandError(msg)

        user = self._find_user(username)
        self._update_permissions(user, options)
        self._show_status(user)
        return

    def _find_user(self, username: str) -> Any:
        """Find user by username or email."""
        try:
            return User.objects.get(username=username)
        except User.DoesNotExist:
            pass

        try:
            return User.objects.get(email=username)
        except User.DoesNotExist:
            msg = f"User '{username}' not found (checked username and email)"
            raise CommandError(msg) from None

    def _update_permissions(self, user: Any, options: dict[str, Any]) -> None:
        """Update user permissions based on options."""
        grant_staff = options["staff"]
        grant_superuser = options["superuser"]
        demote = options["demote"]

        # If neither specified, default to --staff
        if not grant_staff and not grant_superuser:
            grant_staff = True

        changes = []

        if demote:
            changes = self._demote_user(
                user, grant_staff=grant_staff, grant_superuser=grant_superuser
            )
        else:
            changes = self._promote_user(
                user, grant_staff=grant_staff, grant_superuser=grant_superuser
            )

        if changes:
            user.save()
            action = "Demoted" if demote else "Promoted"
            self.stdout.write(
                self.style.SUCCESS(
                    f"{action} user '{user.username}': {', '.join(changes)}"
                )
            )
        else:
            msg = "doesn't have" if demote else "already has"
            self.stdout.write(
                self.style.WARNING(
                    f"User '{user.username}' {msg} the specified permissions"
                )
            )

    def _promote_user(self, user, *, grant_staff: bool, grant_superuser: bool) -> list:
        """Grant permissions to user."""
        changes = []
        if grant_staff and not user.is_staff:
            user.is_staff = True
            changes.append("granted staff status")
        if grant_superuser and not user.is_superuser:
            user.is_superuser = True
            changes.append("granted superuser status")
        return changes

    def _demote_user(self, user, *, grant_staff: bool, grant_superuser: bool) -> list:
        """Remove permissions from user."""
        changes = []
        if grant_staff and user.is_staff:
            user.is_staff = False
            changes.append("removed staff status")
        if grant_superuser and user.is_superuser:
            user.is_superuser = False
            changes.append("removed superuser status")
        return changes

    def _show_status(self, user: Any) -> None:
        """Display current user status."""
        self.stdout.write(f"\nCurrent status for '{user.username}':")
        self.stdout.write(f"  Email: {user.email}")
        self.stdout.write(f"  Staff: {user.is_staff}")
        self.stdout.write(f"  Superuser: {user.is_superuser}")

    def _list_staff_users(self) -> None:
        """List all staff and superusers."""
        staff_users = User.objects.filter(is_staff=True).order_by("username")
        superusers = User.objects.filter(is_superuser=True).order_by("username")

        self.stdout.write(self.style.SUCCESS("\n=== Staff Users ==="))
        if staff_users.exists():
            for user in staff_users:
                su_marker = " [SUPERUSER]" if user.is_superuser else ""
                self.stdout.write(f"  {user.username} ({user.email}){su_marker}")
        else:
            self.stdout.write("  (none)")

        self.stdout.write(self.style.SUCCESS("\n=== Superusers ==="))
        if superusers.exists():
            for user in superusers:
                self.stdout.write(f"  {user.username} ({user.email})")
        else:
            self.stdout.write("  (none)")

        self.stdout.write(
            f"\nTotal: {staff_users.count()} staff, {superusers.count()} superusers"
        )
