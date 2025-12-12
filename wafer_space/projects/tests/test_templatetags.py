"""Tests for precheck badge template tags."""

from __future__ import annotations

import pytest
from django.template import Context
from django.template import Template

from wafer_space.projects.models import PrecheckImageRevision
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory


@pytest.mark.django_db
class TestPrecheckBadgeTemplateTags:
    """Tests for precheck badge template tags."""

    def test_badge_precheck_status_renders(self):
        """badge_precheck_status renders without error."""
        check = ManufacturabilityCheckFactory(
            docker_image_digest="sha256:abc123def456789012345678901234567890123456789012345678901234"
        )
        template = Template(
            "{% load precheck_tags %}{% badge_precheck_status check %}"
        )
        context = Context({"check": check})
        result = template.render(context)

        assert "badge" in result
        assert "bi-" in result  # Bootstrap icon

    def test_badge_precheck_status_none_check(self):
        """badge_precheck_status handles None check."""
        template = Template(
            "{% load precheck_tags %}{% badge_precheck_status check %}"
        )
        context = Context({"check": None})
        result = template.render(context)

        assert "No check" in result

    def test_badge_precheck_version_renders(self):
        """badge_precheck_version renders version string."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234",
            precheck_version="1.5.2",
        )
        check = ManufacturabilityCheckFactory(docker_image_digest=revision.digest)

        template = Template(
            "{% load precheck_tags %}{% badge_precheck_version check %}"
        )
        context = Context({"check": check})
        result = template.render(context)

        assert "v1.5.2" in result
        assert "bi-cloud" in result

    def test_badge_precheck_version_fallback_to_commit(self):
        """badge_precheck_version falls back to git commit when no version."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234",
            git_commit_sha="a261f14ae7f90a0f74c6db18f28eeafce9b6e803",
        )
        check = ManufacturabilityCheckFactory(docker_image_digest=revision.digest)

        template = Template(
            "{% load precheck_tags %}{% badge_precheck_version check %}"
        )
        context = Context({"check": check})
        result = template.render(context)

        assert "a261f14" in result

    def test_badge_precheck_version_fallback_to_unknown(self):
        """badge_precheck_version shows ???? when no version info."""
        check = ManufacturabilityCheckFactory(
            docker_image_digest="sha256:uncataloged123456789012345678901234567890123456789012"
        )

        template = Template(
            "{% load precheck_tags %}{% badge_precheck_version check %}"
        )
        context = Context({"check": check})
        result = template.render(context)

        assert "????" in result

    def test_badge_precheck_combined_renders(self):
        """badge_precheck_combined renders status and version."""
        revision = PrecheckImageRevision.objects.create(
            digest="sha256:abc123def456789012345678901234567890123456789012345678901234",
            precheck_version="1.5.2",
        )
        check = ManufacturabilityCheckFactory(
            docker_image_digest=revision.digest,
            status="finished",
            is_manufacturable=True,
        )

        template = Template(
            "{% load precheck_tags %}{% badge_precheck_combined check %}"
        )
        context = Context({"check": check})
        result = template.render(context)

        assert "Passed" in result
        assert "v1.5.2" in result
