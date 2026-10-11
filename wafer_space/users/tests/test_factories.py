"""UserFactory is deterministic (the account_emailaddress CI flake)."""

from __future__ import annotations

import pytest
from allauth.account.models import EmailAddress

from wafer_space.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

MANY = 200


def test_same_username_twice_reuses_user_without_second_primary_email() -> None:
    """get_or_create on username returned the existing user, and the
    email_address hook then added a second primary EmailAddress, failing the
    (user_id, primary) unique constraint whenever Faker repeated a name."""
    first = UserFactory(username="duplicate")
    second = UserFactory(username="duplicate")
    assert second.pk == first.pk
    assert EmailAddress.objects.filter(user=first, primary=True).count() == 1


def test_default_usernames_are_unique() -> None:
    """Without an explicit username, every call makes a new user."""
    users = UserFactory.create_batch(MANY)
    assert len({user.username for user in users}) == MANY


def test_default_emails_are_unique() -> None:
    """allauth requires verified emails to be unique across users."""
    users = UserFactory.create_batch(MANY)
    assert len({user.email for user in users}) == MANY
