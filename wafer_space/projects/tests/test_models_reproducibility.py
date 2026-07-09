"""Tests for ManufacturabilityCheck reproducibility methods."""

import pytest
from django.test import TestCase

from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.shuttles.tests.factories import ShuttleFactory
from wafer_space.users.models import User

from .constants import TEST_PASSWORD


@pytest.mark.django_db
class TestManufacturabilityCheckReproducibility(TestCase):
    """Test reproducibility and issue reporting methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        # Shuttle + project_id are immutable after creation and are required
        # for the precheck command embedded in reproduction instructions.
        self.shuttle = ShuttleFactory(name="G850")
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
            status=Project.Status.DRAFT,
            shuttle=self.shuttle,
            project_id="ABCD",
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            original_url="https://example.com/test.gds",
            source_url="https://example.com/test.gds",
            is_active=True,
            hash_md5="abc123def456",
            hash_sha1="sha1hash123",
            top_cell="chip_top",
        )
        # Create DownloadAttempt to set download_status to COMPLETED
        DownloadAttempt.objects.create(
            project_file=self.project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

    def test_get_reproduction_instructions(self):
        """Test generation of reproduction instructions."""
        # Create a check with version tracking data
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            docker_image="ghcr.io/wafer-space/gf180mcu-precheck:v1.0.0",
            docker_image_digest="sha256:abc123def456",
            precheck_version="v1.0.0",
            tool_versions={
                "magic": "8.3.450",
                "klayout": "0.28.12",
                "pdk": "gf180mcuD-v1.2.3",
            },
        )

        # Get reproduction instructions
        instructions = check.get_reproduction_instructions()

        # Verify it's markdown format
        assert "# Reproducing Manufacturability Check Locally" in instructions
        assert "## Prerequisites" in instructions
        assert "## Steps" in instructions

        # Verify Docker command is included
        assert "docker pull" in instructions
        assert check.docker_image in instructions
        assert check.docker_image_digest in instructions

        # Verify file hash information
        assert self.project_file.hash_md5 in instructions
        assert self.project_file.hash_sha1 in instructions

        # Verify tool versions
        assert "8.3.450" in instructions
        assert "0.28.12" in instructions
        assert "gf180mcuD-v1.2.3" in instructions

        # Verify the embedded precheck command reflects the real run inputs
        assert "--top chip_top" in instructions
        assert "--id G850ABCD" in instructions
        assert "--workdir /workspace" in instructions

    def test_generate_github_issue_url(self):
        """Test GitHub issue URL generation."""
        # Create a check with error data
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            docker_image="ghcr.io/wafer-space/gf180mcu-precheck:v1.0.0",
            docker_image_digest="sha256:abc123def456",
            precheck_version="v1.0.0",
            tool_versions={"magic": "8.3.450", "klayout": "0.28.12"},
            errors=[{"message": "DRC violation at (100, 200)", "category": "DRC"}],
            processing_logs="Error: Multiple violations detected\nDetails...",
        )

        # Generate issue URL
        issue_url = check.generate_github_issue_url()

        # Verify it's a GitHub URL
        assert issue_url.startswith(
            "https://github.com/wafer-space/gf180mcu-precheck/issues/new?"
        )

        # Verify URL parameters are present
        assert "title=" in issue_url
        assert "body=" in issue_url
        assert "labels=" in issue_url

        # Verify project name in title (URL encoded)
        assert self.project.name.replace(" ", "+") in issue_url or (
            self.project.name.replace(" ", "%20") in issue_url
        )

        # Verify environment info is in body (URL encoded)
        assert (
            "docker_image" in issue_url.lower() or "docker+image" in issue_url.lower()
        )
