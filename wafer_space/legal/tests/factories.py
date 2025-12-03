"""Factories for legal app tests."""

from datetime import UTC
from datetime import datetime

import frontmatter
from factory import Faker
from factory import Sequence
from factory import SubFactory
from factory.django import DjangoModelFactory

from wafer_space.legal.models import TermsOfService
from wafer_space.legal.models import TermsOfServiceAcceptance
from wafer_space.legal.models import TermsOfServiceNotification
from wafer_space.legal.utils import get_tos_versions_directory
from wafer_space.users.tests.factories import UserFactory


class TermsOfServiceFactory(DjangoModelFactory):
    """Factory for TermsOfService model."""

    # Use sequence to ensure unique versions (1.0.0, 1.0.1, 1.0.2, ...)
    version = Sequence(lambda n: f"1.0.{n}")
    is_active = False
    created_by = SubFactory(UserFactory)

    class Meta:
        model = TermsOfService

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Override create to also create markdown file.

        Note: When running in tests, the file system is mocked by the
        mock_tos_filesystem fixture in conftest.py, so no actual files
        are created on disk.
        """
        # Version is already populated by factory_boy before _create is called
        version = kwargs["version"]

        # Create markdown file with test content
        base_dir = get_tos_versions_directory()
        base_dir.mkdir(exist_ok=True)
        file_path = base_dir / f"{version}.md"

        if not file_path.exists():
            test_content = f"""# Terms of Service

## Test Terms of Service

This is test TOS content for version {version}.

1. Test clause 1
2. Test clause 2
3. Test clause 3

These terms are for testing purposes only."""

            post = frontmatter.Post(test_content.strip())

            # Set front matter metadata
            post.metadata["version"] = version
            post.metadata["effective_date"] = "2024-01-01"
            post.metadata["is_active"] = kwargs.get("is_active", False)
            post.metadata["created_at"] = datetime.now(UTC).isoformat()
            post.metadata["created_by"] = (
                kwargs["created_by"].username if kwargs.get("created_by") else None
            )
            post.metadata["description"] = f"Terms of Service v{version}"
            post.metadata["requires_reacceptance"] = True

            # Write markdown file with front matter
            # This will be intercepted by the mock in tests
            with file_path.open("w") as f:
                f.write(frontmatter.dumps(post))

        # Create database entry
        return super()._create(model_class, *args, **kwargs)


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
