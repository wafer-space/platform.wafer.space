from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.cache import cache
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
        assert stats["average"] == pytest.approx(expected_average)
        assert stats["max"] == pytest.approx(expected_max)

    def test_get_run_duration_stats_no_data(self):
        """get_run_duration_stats returns None when no completed checks."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:nodata12345678901234567890123456789012345678901234567890"
        )

        stats = revision.get_run_duration_stats()
        assert stats["average"] is None
        assert stats["max"] is None


@pytest.mark.django_db
class TestManufacturabilityCheckLatestDigest:
    """Tests for ManufacturabilityCheck.get_latest_precheck_digest."""

    def setup_method(self):
        """Clear cache before each test."""
        cache.clear()

    def test_get_latest_precheck_digest_returns_most_recent(self):
        """get_latest_precheck_digest returns most recently started digest."""
        now = timezone.now()
        # Older check
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:older",
            container_started_at=now - timedelta(hours=2),
        )
        # Newer check
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:newer",
            container_started_at=now - timedelta(hours=1),
        )

        assert ManufacturabilityCheck.get_latest_precheck_digest() == "sha256:newer"

    def test_get_latest_precheck_digest_ignores_empty(self):
        """get_latest_precheck_digest ignores checks with empty digest."""
        now = timezone.now()
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:valid",
            container_started_at=now - timedelta(hours=2),
        )
        # More recent but empty digest
        ManufacturabilityCheckFactory(
            docker_image_digest="",
            container_started_at=now - timedelta(hours=1),
        )

        assert ManufacturabilityCheck.get_latest_precheck_digest() == "sha256:valid"

    def test_get_latest_precheck_digest_returns_none_when_no_checks(self):
        """get_latest_precheck_digest returns None when no checks exist."""
        assert ManufacturabilityCheck.get_latest_precheck_digest() is None

    def test_get_latest_precheck_digest_ignores_null_started_at(self):
        """get_latest_precheck_digest ignores checks with NULL container_started_at.

        Regression test for issue #241: PostgreSQL sorts NULL values first in DESC
        order, so checks that never started were incorrectly returned as "latest".
        """
        now = timezone.now()
        # Valid check with timestamp
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:valid",
            container_started_at=now - timedelta(hours=1),
        )
        # Check with NULL container_started_at (should be ignored)
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:null_started",
            container_started_at=None,
        )

        assert ManufacturabilityCheck.get_latest_precheck_digest() == "sha256:valid"

    def test_is_using_latest_precheck_true(self):
        """is_using_latest_precheck returns True when using latest."""
        check = ManufacturabilityCheckFactory(
            docker_image_digest="sha256:latest",
            container_started_at=timezone.now(),
        )

        assert check.is_using_latest_precheck is True

    def test_is_using_latest_precheck_false(self):
        """is_using_latest_precheck returns False when outdated."""
        now = timezone.now()
        old_check = ManufacturabilityCheckFactory(
            docker_image_digest="sha256:old",
            container_started_at=now - timedelta(hours=2),
        )
        ManufacturabilityCheckFactory(
            docker_image_digest="sha256:new",
            container_started_at=now - timedelta(hours=1),
        )
        cache.clear()  # Clear cache to get fresh result

        assert old_check.is_using_latest_precheck is False

    def test_is_using_latest_precheck_none_when_no_digest(self):
        """is_using_latest_precheck returns None when check has no digest."""
        check = ManufacturabilityCheckFactory(docker_image_digest="")

        assert check.is_using_latest_precheck is None

    def test_precheck_revision_property(self):
        """precheck_revision returns linked revision if exists."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234"
        )
        check = ManufacturabilityCheckFactory(docker_image_digest=revision.digest)

        assert check.precheck_revision == revision

    def test_precheck_revision_property_none_when_not_cataloged(self):
        """precheck_revision returns None if revision not in catalog."""
        check = ManufacturabilityCheckFactory(docker_image_digest="sha256:uncataloged")

        assert check.precheck_revision is None


@pytest.mark.django_db
class TestPrecheckImageRevisionVersionDisplay:
    """Tests for PrecheckImageRevision.version_display property."""

    def test_version_display_returns_precheck_version_when_available(self):
        """version_display prefers precheck_version."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234",
            precheck_version="1.5.2",
            git_commit_sha="abc1234567890",
        )
        assert revision.version_display == "1.5.2"

    def test_version_display_falls_back_to_git_commit_sha(self):
        """version_display uses git_commit_sha[:7] if no precheck_version."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:def456abc789012345678901234567890123456789012345678901234567",
            precheck_version="",
            git_commit_sha="abc1234567890",
        )
        assert revision.version_display == "abc1234"

    def test_version_display_falls_back_to_short_digest(self):
        """version_display uses short_digest if no version info."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:xyz789abc123456789012345678901234567890123456789012345678901",
            precheck_version="",
            git_commit_sha="",
        )
        assert revision.version_display == "sha256:xyz789abc123..."
