"""Tests for project forms."""

from unittest.mock import patch

import pytest
from django.test import TestCase
from django.utils import timezone

from wafer_space.projects.forms import ProjectFileURLSubmitForm
from wafer_space.projects.forms import ProjectForm
from wafer_space.projects.models import Project
from wafer_space.projects.security import SecurityValidationError
from wafer_space.projects.services.license_service import LicenseValidationError
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.models import User

from .constants import TEST_PASSWORD


@pytest.mark.django_db
class TestProjectForm(TestCase):
    """Test ProjectForm."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a test shuttle for form tests
        self.shuttle = Shuttle.objects.create(
            name="G800", description="Test Shuttle", status=Shuttle.Status.OPEN
        )

    def test_form_valid_with_all_fields(self):
        """Test form is valid with name, description, and slot_size."""
        form_data = {
            "name": "Test Project",
            "description": "This is a test project",
            "shuttle": self.shuttle.pk,
            "project_id": "TEST",
            "slot_size": "1x1",
        }
        form = ProjectForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["name"] == "Test Project"
        assert form.cleaned_data["description"] == "This is a test project"
        assert form.cleaned_data["shuttle"] == self.shuttle
        assert form.cleaned_data["project_id"] == "TEST"
        assert form.cleaned_data["slot_size"] == "1x1"

    def test_form_valid_without_description(self):
        """Test form is valid without description (optional field)."""
        form_data = {
            "name": "Test Project",
            "shuttle": self.shuttle.pk,
            "project_id": "ABCD",
            "slot_size": "1x1",
        }
        form = ProjectForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["name"] == "Test Project"
        assert form.cleaned_data["description"] == ""

    def test_form_invalid_without_name(self):
        """Test form is invalid without name (required field)."""
        form_data = {
            "description": "This is a test project",
        }
        form = ProjectForm(data=form_data)

        assert not form.is_valid()
        assert "name" in form.errors

    def test_form_invalid_with_empty_name(self):
        """Test form is invalid with empty name."""
        form_data = {
            "name": "",
            "description": "Test",
        }
        form = ProjectForm(data=form_data)

        assert not form.is_valid()
        assert "name" in form.errors

    def test_chip_on_board_field_present_and_optional(self):
        """chip_on_board is on the form and optional."""
        form = ProjectForm()
        assert "chip_on_board" in form.fields
        assert form.fields["chip_on_board"].required is False

    def test_chip_on_board_editable_for_non_staff_on_existing_project(self):
        """chip_on_board is a user field — never disabled on edit."""
        user = User.objects.create_user(
            username="formuser", email="form@example.com", password=TEST_PASSWORD
        )
        project = Project.objects.create(
            user=user,
            name="Form Project",
            shuttle=self.shuttle,
            project_id="FRMP",
        )
        form = ProjectForm(user=user, instance=project)
        assert form.fields["chip_on_board"].disabled is False

    def test_form_saves_correctly(self):
        """Test form saves project correctly."""
        user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )

        form_data = {
            "name": "My Project",
            "description": "My description",
            "shuttle": self.shuttle.pk,
            "project_id": "SAVE",
            "slot_size": "0p5x0p5",
        }
        form = ProjectForm(data=form_data)

        assert form.is_valid()

        # Save with user
        project = form.save(commit=False)
        project.user = user
        project.save()

        # Verify saved correctly
        assert Project.objects.count() == 1
        saved_project = Project.objects.first()
        assert saved_project is not None
        assert saved_project.name == "My Project"
        assert saved_project.description == "My description"
        assert saved_project.user == user
        assert saved_project.slot_size == "0p5x0p5"


@pytest.mark.django_db
class TestProjectFileURLSubmitForm(TestCase):
    """Test ProjectFileURLSubmitForm."""

    def test_form_invalid_with_url_only(self):
        """Test form is invalid with just URL (requires at least one hash)."""
        form_data = {
            "url": "https://example.com/file.gds",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert not form.is_valid()
        assert "__all__" in form.errors
        assert "At least one checksum" in str(form.errors["__all__"])

    def test_form_valid_with_md5_hash(self):
        """Test form is valid with MD5 hash."""
        expected_md5 = "abc123def456789012345678901234ab"
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": expected_md5,
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_md5"] == expected_md5

    def test_form_valid_with_sha1_hash(self):
        """Test form is valid with SHA1 hash."""
        expected_sha1 = "abc123def456789012345678901234567890abcd"
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_sha1": expected_sha1,
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_sha1"] == expected_sha1

    def test_form_valid_with_both_hashes(self):
        """Test form is valid with both MD5 and SHA1 hashes."""
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": "abc123def456789012345678901234ab",
            "expected_hash_sha1": "abc123def456789012345678901234567890abcd",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()

    def test_form_invalid_without_url(self):
        """Test form is invalid without URL."""
        form_data: dict[str, str] = {}
        form = ProjectFileURLSubmitForm(data=form_data)

        assert not form.is_valid()
        assert "url" in form.errors

    def test_form_invalid_with_empty_url(self):
        """Test form is invalid with empty URL."""
        form_data = {
            "url": "",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert not form.is_valid()
        assert "url" in form.errors

    def test_form_invalid_with_whitespace_only_url(self):
        """Test form is invalid with whitespace-only URL."""
        form_data = {
            "url": "   ",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert not form.is_valid()
        assert "url" in form.errors

    def test_form_strips_url_whitespace(self):
        """Test form strips whitespace from URL."""
        form_data = {
            "url": "  https://example.com/file.gds  ",
            "expected_hash_md5": "abc123def456789012345678901234ab",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["url"] == "https://example.com/file.gds"

    def test_form_invalid_with_malformed_url(self):
        """Test form is invalid with malformed URL."""
        form_data = {
            "url": "not-a-valid-url",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert not form.is_valid()
        assert "url" in form.errors

    def test_form_md5_hash_cleaned_lowercase(self):
        """Test MD5 hash is converted to lowercase."""
        expected_md5 = "abc123def456789012345678901234ab"
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": "ABC123DEF456789012345678901234AB",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_md5"] == expected_md5

    def test_form_sha1_hash_cleaned_lowercase(self):
        """Test SHA1 hash is converted to lowercase."""
        expected_sha1 = "abc123def456789012345678901234567890abcd"
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_sha1": "ABC123DEF456789012345678901234567890ABCD",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_sha1"] == expected_sha1

    def test_form_md5_hash_with_whitespace_stripped(self):
        """Test MD5 hash with whitespace is stripped and normalized."""
        expected_md5 = "abc123def456789012345678901234ab"
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": "abc123 def456 789012 345678 901234ab",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        # Whitespace is stripped by clean method
        assert form.is_valid()
        assert form.cleaned_data["expected_hash_md5"] == expected_md5

    def test_form_md5_hash_with_dashes_stripped(self):
        """Test MD5 hash with dashes is stripped and normalized."""
        expected_md5 = "abc123def456789012345678901234ab"
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": "abc123-def456-789012-345678-901234ab",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        # Dashes are stripped by clean method
        assert form.is_valid()
        assert form.cleaned_data["expected_hash_md5"] == expected_md5

    def test_form_invalid_md5_hash_wrong_length(self):
        """Test MD5 hash with wrong length is invalid."""
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": "abc123",  # Too short
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert not form.is_valid()
        assert "expected_hash_md5" in form.errors
        assert "32 hexadecimal characters" in str(form.errors["expected_hash_md5"])

    def test_form_invalid_md5_hash_non_hex(self):
        """Test MD5 hash with non-hex characters is invalid."""
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": "gggggggggggggggggggggggggggggggg",  # 'g' is not hex
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert not form.is_valid()
        assert "expected_hash_md5" in form.errors
        assert "hexadecimal characters" in str(form.errors["expected_hash_md5"])

    def test_form_invalid_sha1_hash_wrong_length(self):
        """Test SHA1 hash with wrong length is invalid."""
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_sha1": "abc123",  # Too short
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert not form.is_valid()
        assert "expected_hash_sha1" in form.errors
        assert "40 hexadecimal characters" in str(form.errors["expected_hash_sha1"])

    def test_form_invalid_sha1_hash_non_hex(self):
        """Test SHA1 hash with non-hex characters is invalid."""
        form_data = {
            "url": "https://example.com/file.gds",
            # 'g' is not a valid hex character
            "expected_hash_sha1": "gggggggggggggggggggggggggggggggggggggggg",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert not form.is_valid()
        assert "expected_hash_sha1" in form.errors
        assert "hexadecimal characters" in str(form.errors["expected_hash_sha1"])

    def test_form_empty_md5_hash_allowed_with_sha1(self):
        """Test empty MD5 hash is allowed when SHA1 is provided."""
        expected_sha1 = "abc123def456789012345678901234567890abcd"
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": "",
            "expected_hash_sha1": expected_sha1,
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_md5"] == ""
        assert form.cleaned_data["expected_hash_sha1"] == expected_sha1

    def test_form_empty_sha1_hash_allowed_with_md5(self):
        """Test empty SHA1 hash is allowed when MD5 is provided."""
        expected_md5 = "abc123def456789012345678901234ab"
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": expected_md5,
            "expected_hash_sha1": "",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_md5"] == expected_md5
        assert form.cleaned_data["expected_hash_sha1"] == ""

    def test_form_requires_at_least_one_hash(self):
        """Test that form requires at least one hash (MD5, SHA1, or SHA256)."""
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": "",
            "expected_hash_sha1": "",
            "expected_hash_sha256": "",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert not form.is_valid()
        assert "__all__" in form.errors
        error_msg = str(form.errors["__all__"])
        assert "At least one checksum" in error_msg
        assert "MD5, SHA1, or SHA256" in error_msg

    def test_form_md5_hash_strips_md5_prefix(self):
        """Test MD5 hash with 'md5:' prefix is stripped and normalized."""
        expected_md5 = "abc123def456789012345678901234ab"
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": f"md5:{expected_md5}",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_md5"] == expected_md5

    def test_form_md5_hash_strips_sha256_prefix(self):
        """Test MD5 hash with 'sha256:' prefix is stripped (any prefix works)."""
        expected_md5 = "abc123def456789012345678901234ab"
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": f"sha256:{expected_md5}",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_md5"] == expected_md5

    def test_form_md5_hash_strips_uppercase_prefix(self):
        """Test MD5 hash with uppercase prefix is stripped and hash normalized."""
        expected_md5 = "abc123def456789012345678901234ab"
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": f"MD5:{expected_md5.upper()}",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        # Hash should be lowercased
        assert form.cleaned_data["expected_hash_md5"] == expected_md5

    def test_form_sha1_hash_strips_sha1_prefix(self):
        """Test SHA1 hash with 'sha1:' prefix is stripped and normalized."""
        expected_sha1 = "abc123def456789012345678901234567890abcd"
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_sha1": f"sha1:{expected_sha1}",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_sha1"] == expected_sha1

    def test_form_sha1_hash_strips_sha256_prefix(self):
        """Test SHA1 hash with 'sha256:' prefix is stripped (any prefix works)."""
        expected_sha1 = "abc123def456789012345678901234567890abcd"
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_sha1": f"sha256:{expected_sha1}",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_sha1"] == expected_sha1

    def test_form_sha1_hash_strips_uppercase_dashed_prefix(self):
        """Test SHA1 hash with 'SHA-256:' prefix is stripped and hash normalized."""
        expected_sha1 = "abc123def456789012345678901234567890abcd"
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_sha1": f"SHA-256:{expected_sha1.upper()}",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        # Hash should be lowercased
        assert form.cleaned_data["expected_hash_sha1"] == expected_sha1

    def test_form_hash_without_prefix_still_works(self):
        """Test that hashes without prefixes still work (backwards compatibility)."""
        expected_md5 = "abc123def456789012345678901234ab"
        expected_sha1 = "abc123def456789012345678901234567890abcd"
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": expected_md5,
            "expected_hash_sha1": expected_sha1,
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_md5"] == expected_md5
        assert form.cleaned_data["expected_hash_sha1"] == expected_sha1

    def test_form_valid_with_sha256_hash(self):
        """Test form is valid with SHA256 hash only."""
        expected_sha256 = (
            "abc123def456789012345678901234567890abcdef123456789012345678abcd"
        )
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_sha256": expected_sha256,
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_sha256"] == expected_sha256

    def test_form_valid_with_all_three_hashes(self):
        """Test form is valid with MD5, SHA1, and SHA256 hashes."""
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": "abc123def456789012345678901234ab",
            "expected_hash_sha1": "abc123def456789012345678901234567890abcd",
            "expected_hash_sha256": (
                "abc123def456789012345678901234567890abcdef123456789012345678abcd"
            ),
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()

    def test_form_invalid_sha256_hash_wrong_length(self):
        """Test SHA256 hash with wrong length is invalid."""
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_sha256": "abc123",  # Too short
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert not form.is_valid()
        assert "expected_hash_sha256" in form.errors
        assert "64 hexadecimal characters" in str(form.errors["expected_hash_sha256"])

    def test_form_invalid_sha256_hash_non_hex(self):
        """Test SHA256 hash with non-hex characters is invalid."""
        invalid_sha256 = (
            "gggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggg"
        )
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_sha256": invalid_sha256,
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert not form.is_valid()
        assert "expected_hash_sha256" in form.errors
        assert "hexadecimal characters" in str(form.errors["expected_hash_sha256"])

    def test_form_sha256_hash_cleaned_lowercase(self):
        """Test SHA256 hash is converted to lowercase."""
        expected_sha256 = (
            "abc123def456789012345678901234567890abcdef123456789012345678abcd"
        )
        uppercase_sha256 = (
            "ABC123DEF456789012345678901234567890ABCDEF123456789012345678ABCD"
        )
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_sha256": uppercase_sha256,
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_sha256"] == expected_sha256

    def test_form_sha256_hash_strips_sha256_prefix(self):
        """Test SHA256 hash with 'sha256:' prefix is stripped and normalized."""
        expected_sha256 = (
            "abc123def456789012345678901234567890abcdef123456789012345678abcd"
        )
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_sha256": f"sha256:{expected_sha256}",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_sha256"] == expected_sha256

    def test_form_sha256_hash_with_whitespace_stripped(self):
        """Test SHA256 hash with whitespace is stripped and normalized."""
        expected_sha256 = (
            "abc123def456789012345678901234567890abcdef123456789012345678abcd"
        )
        sha256_with_spaces = (
            "abc123 def456 789012 345678 901234 567890 abcdef 123456 789012 345678abcd"
        )
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_sha256": sha256_with_spaces,
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_sha256"] == expected_sha256

    def test_form_sha256_hash_with_dashes_stripped(self):
        """Test SHA256 hash with dashes is stripped and normalized."""
        expected_sha256 = (
            "abc123def456789012345678901234567890abcdef123456789012345678abcd"
        )
        sha256_with_dashes = (
            "abc123-def456-789012-345678-901234-567890-abcdef-123456-789012-345678abcd"
        )
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_sha256": sha256_with_dashes,
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_sha256"] == expected_sha256

    def test_form_requires_at_least_one_hash_including_sha256(self):
        """Test that form accepts SHA256 as the required hash."""
        # SHA256 alone should be valid
        valid_sha256 = (
            "abc123def456789012345678901234567890abcdef123456789012345678abcd"
        )
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_sha256": valid_sha256,
        }
        form = ProjectFileURLSubmitForm(data=form_data)
        assert form.is_valid()

        # Empty hashes should be invalid
        form_data_empty = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": "",
            "expected_hash_sha1": "",
            "expected_hash_sha256": "",
        }
        form_empty = ProjectFileURLSubmitForm(data=form_data_empty)
        assert not form_empty.is_valid()
        assert "__all__" in form_empty.errors


@pytest.mark.django_db
class TestProjectFormLicenseValidation:
    """Tests for license field validation in ProjectForm."""

    @pytest.fixture
    def open_shuttle(self, db):
        """Create an open shuttle for testing."""
        return Shuttle.objects.create(
            name="G899",
            description="Test Shuttle for License Validation",
            status=Shuttle.Status.OPEN,
        )

    @pytest.fixture
    def base_form_data(self, open_shuttle):
        """Base valid form data."""
        return {
            "name": "Test Project",
            "description": "A test project",
            "shuttle": open_shuttle.pk,
            "project_id": "TEST",
            "slot_size": "1x1",
            "is_public": False,
            "repository_url": "",
            "license_type": "proprietary",
            "other_license_spdx_id": "",
            "proprietary_terms_url": "",
        }

    def test_other_license_requires_spdx_id(self, base_form_data):
        """'Other' license type requires SPDX ID."""
        base_form_data["license_type"] = "other"
        base_form_data["other_license_spdx_id"] = ""

        form = ProjectForm(data=base_form_data)
        assert not form.is_valid()
        assert "other_license_spdx_id" in form.errors

    @patch("wafer_space.projects.forms.validate_spdx_id")
    def test_other_license_validates_spdx_id(self, mock_validate, base_form_data):
        """'Other' license validates SPDX ID."""
        mock_validate.side_effect = LicenseValidationError("Invalid SPDX identifier")
        base_form_data["license_type"] = "other"
        base_form_data["other_license_spdx_id"] = "INVALID-ID"

        form = ProjectForm(data=base_form_data)
        assert not form.is_valid()
        assert "Invalid SPDX identifier" in str(form.errors["other_license_spdx_id"])

    @patch("wafer_space.projects.forms.validate_spdx_id")
    def test_valid_other_license_passes(self, mock_validate, base_form_data):
        """Valid 'Other' license with SPDX ID passes."""
        # validate_spdx_id returns None on success (no error raised)
        base_form_data["license_type"] = "other"
        base_form_data["other_license_spdx_id"] = "GPL-3.0-only"

        form = ProjectForm(data=base_form_data)
        assert form.is_valid(), form.errors

    @patch("wafer_space.projects.forms.fetch_url_content")
    def test_proprietary_terms_url_fetched_and_cached(
        self, mock_fetch, base_form_data, user
    ):
        """Proprietary terms URL is fetched and content cached."""
        mock_fetch.return_value = "License terms content..."
        base_form_data["license_type"] = "proprietary"
        base_form_data["proprietary_terms_url"] = "https://example.com/terms.txt"

        form = ProjectForm(data=base_form_data)
        assert form.is_valid(), form.errors

        # Save and check cache
        form.instance.user = user
        project = form.save()
        assert project.proprietary_terms_cached == "License terms content..."
        assert project.proprietary_terms_cached_at is not None

    @patch("wafer_space.projects.forms.fetch_url_content")
    def test_proprietary_terms_url_fetch_failure_shows_error(
        self, mock_fetch, base_form_data
    ):
        """Failed fetch of proprietary terms shows error."""
        mock_fetch.side_effect = LicenseValidationError("Could not fetch")
        base_form_data["license_type"] = "proprietary"
        base_form_data["proprietary_terms_url"] = "https://example.com/bad.txt"

        form = ProjectForm(data=base_form_data)
        assert not form.is_valid()
        assert "proprietary_terms_url" in form.errors

    def test_non_other_license_clears_spdx_id(self, base_form_data):
        """Non-'other' license types clear the SPDX ID field."""
        base_form_data["license_type"] = "MIT"
        base_form_data["other_license_spdx_id"] = "should-be-cleared"

        form = ProjectForm(data=base_form_data)
        assert form.is_valid(), form.errors
        assert form.cleaned_data["other_license_spdx_id"] == ""

    def test_non_proprietary_license_clears_terms_url(self, base_form_data):
        """Non-proprietary license types clear the terms URL field."""
        base_form_data["license_type"] = "MIT"
        base_form_data["proprietary_terms_url"] = "https://example.com/terms.txt"

        form = ProjectForm(data=base_form_data)
        assert form.is_valid(), form.errors
        assert form.cleaned_data["proprietary_terms_url"] == ""

    def test_repository_url_optional(self, base_form_data):
        """Repository URL is optional."""
        base_form_data["repository_url"] = ""

        form = ProjectForm(data=base_form_data)
        assert form.is_valid(), form.errors

    def test_repository_url_accepts_valid_url(self, base_form_data):
        """Repository URL accepts valid URLs."""
        base_form_data["repository_url"] = "https://github.com/user/repo"

        form = ProjectForm(data=base_form_data)
        assert form.is_valid(), form.errors
        assert form.cleaned_data["repository_url"] == "https://github.com/user/repo"

    @patch("wafer_space.projects.forms.URLValidator.validate_hostname")
    @patch("wafer_space.projects.forms.URLValidator.validate_url_scheme")
    @patch("wafer_space.projects.forms.fetch_url_content")
    def test_proprietary_url_validates_scheme_and_hostname(
        self, mock_fetch, mock_scheme, mock_hostname, base_form_data
    ):
        """Proprietary terms URL validates scheme and hostname."""
        mock_fetch.return_value = "Terms content"
        base_form_data["license_type"] = "proprietary"
        base_form_data["proprietary_terms_url"] = "https://example.com/terms.txt"

        form = ProjectForm(data=base_form_data)
        assert form.is_valid(), form.errors

        mock_scheme.assert_called_once_with("https://example.com/terms.txt")
        mock_hostname.assert_called_once_with("https://example.com/terms.txt")

    @patch("wafer_space.projects.forms.URLValidator.validate_url_scheme")
    def test_proprietary_url_rejects_invalid_scheme(self, mock_scheme, base_form_data):
        """Proprietary terms URL rejects invalid schemes."""
        mock_scheme.side_effect = SecurityValidationError("Invalid scheme")
        base_form_data["license_type"] = "proprietary"
        base_form_data["proprietary_terms_url"] = "ftp://example.com/terms.txt"

        form = ProjectForm(data=base_form_data)
        assert not form.is_valid()
        assert "proprietary_terms_url" in form.errors

    @patch("wafer_space.projects.forms.URLValidator.validate_hostname")
    @patch("wafer_space.projects.forms.URLValidator.validate_url_scheme")
    def test_proprietary_url_rejects_private_ip(
        self, mock_scheme, mock_hostname, base_form_data
    ):
        """Proprietary terms URL rejects private IP addresses."""
        mock_hostname.side_effect = SecurityValidationError(
            "Cannot download from private IP"
        )
        base_form_data["license_type"] = "proprietary"
        base_form_data["proprietary_terms_url"] = "https://192.168.1.1/terms.txt"

        form = ProjectForm(data=base_form_data)
        assert not form.is_valid()
        assert "proprietary_terms_url" in form.errors


@pytest.mark.django_db
class TestProjectFormLicenseValidationEdit:
    """Tests for license field validation in ProjectForm when editing.

    Ensures editing existing projects has same license validation as creation.
    """

    @pytest.fixture
    def project_with_owner(self, db, user):
        """Create a project with a user owner for testing."""
        shuttle = Shuttle.objects.create(
            name="G898",
            description="Test Shuttle for User Edit Form",
            status=Shuttle.Status.OPEN,
        )
        return Project.objects.create(
            user=user,
            name="Test Project",
            description="A test project",
            shuttle=shuttle,
            project_id="EDIT",
            slot_size="1x1",
            is_public=False,
        )

    @pytest.fixture
    def base_user_form_data(self):
        """Base valid form data for user edit form."""
        return {
            "name": "Test Project",
            "description": "A test project",
            "is_public": False,
            "repository_url": "",
            "license_type": "proprietary",
            "other_license_spdx_id": "",
            "proprietary_terms_url": "",
        }

    def test_other_license_requires_spdx_id(
        self, project_with_owner, base_user_form_data
    ):
        """'Other' license type requires SPDX ID in user edit form."""
        base_user_form_data["license_type"] = "other"
        base_user_form_data["other_license_spdx_id"] = ""

        form = ProjectForm(data=base_user_form_data, instance=project_with_owner)
        assert not form.is_valid()
        assert "other_license_spdx_id" in form.errors

    @patch("wafer_space.projects.forms.validate_spdx_id")
    def test_other_license_validates_spdx_id(
        self, mock_validate, project_with_owner, base_user_form_data
    ):
        """'Other' license validates SPDX ID in user edit form."""
        mock_validate.side_effect = LicenseValidationError("Invalid SPDX identifier")
        base_user_form_data["license_type"] = "other"
        base_user_form_data["other_license_spdx_id"] = "INVALID-ID"

        form = ProjectForm(data=base_user_form_data, instance=project_with_owner)
        assert not form.is_valid()
        assert "Invalid SPDX identifier" in str(form.errors["other_license_spdx_id"])

    @patch("wafer_space.projects.forms.validate_spdx_id")
    def test_valid_other_license_passes(
        self, mock_validate, project_with_owner, base_user_form_data
    ):
        """Valid 'Other' license with SPDX ID passes in user edit form."""
        # validate_spdx_id returns None on success (no error raised)
        base_user_form_data["license_type"] = "other"
        base_user_form_data["other_license_spdx_id"] = "GPL-3.0-only"

        form = ProjectForm(data=base_user_form_data, instance=project_with_owner)
        assert form.is_valid(), form.errors

    @patch("wafer_space.projects.forms.URLValidator.validate_hostname")
    @patch("wafer_space.projects.forms.URLValidator.validate_url_scheme")
    @patch("wafer_space.projects.forms.fetch_url_content")
    def test_proprietary_terms_url_fetched_and_cached(
        self,
        mock_fetch,
        mock_scheme,
        mock_hostname,
        project_with_owner,
        base_user_form_data,
    ):
        """Proprietary terms URL is fetched and content cached in user edit form."""
        mock_fetch.return_value = "License terms content..."
        base_user_form_data["license_type"] = "proprietary"
        base_user_form_data["proprietary_terms_url"] = "https://example.com/terms.txt"

        form = ProjectForm(data=base_user_form_data, instance=project_with_owner)
        assert form.is_valid(), form.errors

        # Save and check cache
        project = form.save()
        assert project.proprietary_terms_cached == "License terms content..."
        assert project.proprietary_terms_cached_at is not None

    @patch("wafer_space.projects.forms.URLValidator.validate_hostname")
    @patch("wafer_space.projects.forms.URLValidator.validate_url_scheme")
    @patch("wafer_space.projects.forms.fetch_url_content")
    def test_proprietary_terms_url_fetch_failure_shows_error(
        self,
        mock_fetch,
        mock_scheme,
        mock_hostname,
        project_with_owner,
        base_user_form_data,
    ):
        """Failed fetch of proprietary terms shows error in user edit form."""
        mock_fetch.side_effect = LicenseValidationError("Could not fetch")
        base_user_form_data["license_type"] = "proprietary"
        base_user_form_data["proprietary_terms_url"] = "https://example.com/bad.txt"

        form = ProjectForm(data=base_user_form_data, instance=project_with_owner)
        assert not form.is_valid()
        assert "proprietary_terms_url" in form.errors

    @patch("wafer_space.projects.forms.URLValidator.validate_url_scheme")
    def test_proprietary_url_rejects_invalid_scheme(
        self, mock_scheme, project_with_owner, base_user_form_data
    ):
        """Proprietary terms URL rejects invalid schemes in user edit form."""
        mock_scheme.side_effect = SecurityValidationError("Invalid scheme")
        base_user_form_data["license_type"] = "proprietary"
        base_user_form_data["proprietary_terms_url"] = "ftp://example.com/terms.txt"

        form = ProjectForm(data=base_user_form_data, instance=project_with_owner)
        assert not form.is_valid()
        assert "proprietary_terms_url" in form.errors

    def test_non_other_license_clears_spdx_id(
        self, project_with_owner, base_user_form_data
    ):
        """Non-'other' license types clear the SPDX ID field in user edit form."""
        base_user_form_data["license_type"] = "MIT"
        base_user_form_data["other_license_spdx_id"] = "should-be-cleared"

        form = ProjectForm(data=base_user_form_data, instance=project_with_owner)
        assert form.is_valid(), form.errors
        assert form.cleaned_data["other_license_spdx_id"] == ""

    def test_non_proprietary_license_clears_terms_url(
        self, project_with_owner, base_user_form_data
    ):
        """Non-proprietary license types clear the terms URL field in user edit form."""
        base_user_form_data["license_type"] = "MIT"
        base_user_form_data["proprietary_terms_url"] = "https://example.com/terms.txt"

        form = ProjectForm(data=base_user_form_data, instance=project_with_owner)
        assert form.is_valid(), form.errors
        assert form.cleaned_data["proprietary_terms_url"] == ""

    @patch("wafer_space.projects.forms.URLValidator.validate_hostname")
    @patch("wafer_space.projects.forms.URLValidator.validate_url_scheme")
    @patch("wafer_space.projects.forms.fetch_url_content")
    def test_url_change_clears_cache_when_fetch_fails(
        self,
        mock_fetch,
        mock_scheme,
        mock_hostname,
        project_with_owner,
        base_user_form_data,
    ):
        """Changing URL clears cache when new fetch fails."""
        # Set up existing cached terms
        project_with_owner.proprietary_terms_url = "https://old.example.com/terms.txt"
        project_with_owner.proprietary_terms_cached = "Old cached content"
        project_with_owner.proprietary_terms_cached_at = timezone.now()
        project_with_owner.save()

        # Try to update to new URL that fails
        mock_fetch.side_effect = LicenseValidationError("Could not fetch")
        base_user_form_data["license_type"] = "proprietary"
        base_user_form_data["proprietary_terms_url"] = (
            "https://new.example.com/terms.txt"
        )

        form = ProjectForm(data=base_user_form_data, instance=project_with_owner)
        # Form should be invalid because fetch failed
        assert not form.is_valid()
        assert "proprietary_terms_url" in form.errors
