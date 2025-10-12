"""Factories for legal app tests."""

from factory import Faker
from factory import SubFactory
from factory.django import DjangoModelFactory

from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.legal.models import TermsOfServiceNotification
from wafer_space.users.tests.factories import UserFactory


class TermsOfServiceFactory(DjangoModelFactory):
    """Factory for TermsOfService model."""

    version = Faker("numerify", text="#.#.#")
    content = Faker("text", max_nb_chars=500)
    is_active = False
    created_by = SubFactory(UserFactory)

    class Meta:
        model = TermsOfService


class TermsOfServiceAcceptanceFactory(DjangoModelFactory):
    """Factory for TermsOfServiceAcceptance model."""

    user = SubFactory(UserFactory)
    tos_version = SubFactory(TermsOfServiceFactory)
    ip_address = Faker("ipv4")
    user_agent = Faker("user_agent")

    class Meta:
        model = TermsOfServiceAcceptance


class TermsOfServiceNotificationFactory(DjangoModelFactory):
    """Factory for TermsOfServiceNotification model."""

    user = SubFactory(UserFactory)
    tos_version = SubFactory(TermsOfServiceFactory)
    status = TermsOfServiceNotification.Status.PENDING

    class Meta:
        model = TermsOfServiceNotification
