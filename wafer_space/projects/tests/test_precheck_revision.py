from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import PrecheckImageRevision
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory


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


@pytest.mark.django_db
class TestPrecheckImageRevisionStatistics:
    """Tests for PrecheckImageRevision statistics methods."""

    def test_checks_count(self):
        """checks_count returns number of checks using this revision."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234"
        )
        # Create checks with this digest
        ManufacturabilityCheckFactory(docker_image_digest=revision.digest)
        ManufacturabilityCheckFactory(docker_image_digest=revision.digest)
        ManufacturabilityCheckFactory(docker_image_digest="sha256:other")

        expected_count = 2
        assert revision.checks_count == expected_count

    def test_checks_passed_count(self):
        """checks_passed_count returns number of passed checks."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234"
        )
        ManufacturabilityCheckFactory(
            docker_image_digest=revision.digest,
            is_manufacturable=True,
        )
        ManufacturabilityCheckFactory(
            docker_image_digest=revision.digest,
            is_manufacturable=False,
        )

        assert revision.checks_passed_count == 1

    def test_checks_failed_count(self):
        """checks_failed_count returns number of failed checks."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234"
        )
        ManufacturabilityCheckFactory(
            docker_image_digest=revision.digest,
            is_manufacturable=True,
        )
        ManufacturabilityCheckFactory(
            docker_image_digest=revision.digest,
            is_manufacturable=False,
        )

        assert revision.checks_failed_count == 1

    def test_get_run_duration_stats(self):
        """get_run_duration_stats returns average and max duration."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:duration123456789012345678901234567890123456789012345678"
        )
        now = timezone.now()

        # Create checks with known durations
        first_duration_seconds = 60
        second_duration_seconds = 120
        expected_average = 90.0
        expected_max = 120.0

        ManufacturabilityCheckFactory(
            docker_image_digest=revision.digest,
            status=ManufacturabilityCheck.Status.FINISHED,
            container_started_at=now,
            container_finished_at=now + timedelta(seconds=first_duration_seconds),
        )
        ManufacturabilityCheckFactory(
            docker_image_digest=revision.digest,
            status=ManufacturabilityCheck.Status.FINISHED,
            container_started_at=now,
            container_finished_at=now + timedelta(seconds=second_duration_seconds),
        )

        stats = revision.get_run_duration_stats()
        assert stats["average"] == expected_average
        assert stats["max"] == expected_max

    def test_get_run_duration_stats_no_data(self):
        """get_run_duration_stats returns None when no completed checks."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:nodata12345678901234567890123456789012345678901234567890"
        )

        stats = revision.get_run_duration_stats()
        assert stats["average"] is None
        assert stats["max"] is None
