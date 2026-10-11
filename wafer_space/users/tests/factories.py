from collections.abc import Sequence
from typing import Any

from allauth.account.models import EmailAddress
from factory import Faker
from factory import Sequence as SequenceDeclaration
from factory import post_generation
from factory.django import DjangoModelFactory

from wafer_space.users.models import User


class UserFactory(DjangoModelFactory[User]):
    # Unique by construction: Faker("user_name") repeats now and then, and
    # with django_get_or_create a repeat silently returned an existing user.
    username = SequenceDeclaration(lambda n: f"factory-user-{n}")
    # Unique too: allauth's unique verified-email constraint fails on a
    # repeated Faker("email") just as the primary-address one did.
    email = SequenceDeclaration(lambda n: f"factory-user-{n}@example.com")
    name = Faker("name")

    @post_generation
    def password(self, create: bool, extracted: Sequence[Any], **kwargs):  # noqa: FBT001
        password = (
            extracted
            if extracted
            else Faker(
                "password",
                length=42,
                special_chars=True,
                digits=True,
                upper_case=True,
                lower_case=True,
            ).evaluate(None, None, extra={"locale": None})
        )
        self.set_password(password)

    @post_generation
    def email_address(self, create: bool, extracted: Sequence[Any], **kwargs):  # noqa: FBT001
        """Create a verified EmailAddress for the user.

        This is required for browser tests to avoid allauth redirecting to email
        confirmation page during login.
        """
        if create and not EmailAddress.objects.filter(user=self, primary=True).exists():
            # get_or_create may return an existing user (an explicit, reused
            # username), which already has its primary address: adding a
            # second one breaks the (user_id, primary) unique constraint.
            EmailAddress.objects.create(
                user=self,
                email=self.email,
                verified=True,
                primary=True,
            )

    @classmethod
    def _after_postgeneration(cls, instance, create, results=None):
        """Save again the instance if creating and at least one hook ran."""
        if create and results and not cls._meta.skip_postgeneration_save:
            # Some post-generation hooks ran, and may have modified us.
            instance.save()

    class Meta:
        model = User
        django_get_or_create = ["username"]
