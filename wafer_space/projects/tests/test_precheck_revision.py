from __future__ import annotations

import pytest
from django.db import IntegrityError

from wafer_space.projects.models import PrecheckImageRevision


@pytest.mark.django_db
class TestPrecheckImageRevision:
    """Tests for PrecheckImageRevision model."""

    def test_create_revision_with_digest(self):
        """Can create a revision with a digest."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234"
        )
        assert revision.pk is not None
        assert revision.digest.startswith("sha256:")
        assert revision.first_seen_at is not None

    def test_digest_is_unique(self):
        """Digest must be unique."""
        digest = "sha256:abc123def456789012345678901234567890123456789012345678901234"
        PrecheckImageRevision.objects.create(digest=digest)

        with pytest.raises(IntegrityError):
            PrecheckImageRevision.objects.create(digest=digest)

    def test_short_digest_property(self):
        """short_digest returns truncated digest."""
        revision = PrecheckImageRevision(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234"
        )
        assert revision.short_digest == "sha256:abc123def456..."

    def test_github_commit_url_with_sha(self):
        """github_commit_url returns URL when git_commit_sha is set."""
        revision = PrecheckImageRevision(
            digest="sha256:abc123",
            git_commit_sha="a261f14ae7f90a0f74c6db18f28eeafce9b6e803",
        )
        assert revision.github_commit_url == (
            "https://github.com/wafer-space/gf180mcu-precheck/commit/"
            "a261f14ae7f90a0f74c6db18f28eeafce9b6e803"
        )

    def test_github_commit_url_without_sha(self):
        """github_commit_url returns None when git_commit_sha is empty."""
        revision = PrecheckImageRevision(digest="sha256:abc123")
        assert revision.github_commit_url is None

    def test_ghcr_package_url(self):
        """ghcr_package_url returns correct URL."""
        revision = PrecheckImageRevision(digest="sha256:abc123")
        assert revision.ghcr_package_url == (
            "https://github.com/wafer-space/gf180mcu-precheck/pkgs/container/gf180mcu-precheck"
        )
