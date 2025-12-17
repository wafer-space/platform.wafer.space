"""Tests for generate_reticle_package management command."""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
class TestGenerateReticlePackageCommand:
    """Tests for the management command."""

    def test_command_requires_output(self):
        """Command fails without --output argument."""
        out = StringIO()
        with pytest.raises(CommandError):
            call_command("generate_reticle_package", "G801", stdout=out)

    def test_command_fails_for_nonexistent_shuttle(self, tmp_path):
        """Command fails with clear error for non-existent shuttle."""
        out = StringIO()
        output_dir = tmp_path / "output"

        with pytest.raises(CommandError, match="not found"):
            call_command(
                "generate_reticle_package",
                "NONEXISTENT",
                "--output",
                str(output_dir),
                stdout=out,
            )
