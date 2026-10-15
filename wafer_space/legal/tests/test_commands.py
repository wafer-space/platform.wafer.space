"""Tests for the legal app's management commands."""

from pathlib import Path

import pytest
from django.core.management import call_command

from wafer_space.legal.models import TermsOfService


@pytest.mark.django_db
class TestCreateTestTos:
    """create_test_tos seeds the ToS the browser tests start from (#418)."""

    def test_writes_markdown_where_the_model_reads_it(
        self, mock_tos_directory: Path
    ) -> None:
        """The markdown goes to get_tos_versions_directory(), not tos_versions/.

        It used to check the real tos_versions/1.0.0.md, find the real ToS
        there, and write nothing to the mocked directory, leaving the seeded
        row without content.
        """
        call_command("create_test_tos", verbosity=0)

        assert (mock_tos_directory / "1.0.0.md").exists()
        tos = TermsOfService.objects.get(version="1.0.0")
        assert tos.is_active
        assert "Test Terms of Service" in tos.content
