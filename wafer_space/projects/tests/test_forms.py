"""Tests for project forms."""

import pytest
from django.test import TestCase

from wafer_space.projects.forms import ProjectFileURLSubmitForm
from wafer_space.projects.forms import ProjectForm
from wafer_space.projects.models import Project
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
            name="G800",
            description="Test Shuttle",
            status=Shuttle.Status.OPEN,
            max_slots=10,
            available_slots=10,
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

    def test_form_saves_correctly(self):
        """Test form saves project correctly."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
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
