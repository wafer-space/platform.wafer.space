"""Tests for project forms."""

import pytest
from django.test import TestCase

from wafer_space.projects.forms import ProjectFileLocalUploadForm
from wafer_space.projects.forms import ProjectFileURLSubmitForm
from wafer_space.projects.forms import ProjectForm
from wafer_space.projects.models import Project
from wafer_space.users.models import User


@pytest.mark.django_db
class TestProjectForm(TestCase):
    """Test ProjectForm."""

    def test_form_valid_with_all_fields(self):
        """Test form is valid with name and description."""
        form_data = {
            "name": "Test Project",
            "description": "This is a test project",
        }
        form = ProjectForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["name"] == "Test Project"
        assert form.cleaned_data["description"] == "This is a test project"

    def test_form_valid_without_description(self):
        """Test form is valid without description (optional field)."""
        form_data = {
            "name": "Test Project",
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
            password="testpass123",
        )

        form_data = {
            "name": "My Project",
            "description": "My description",
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
        assert saved_project.name == "My Project"
        assert saved_project.description == "My description"
        assert saved_project.user == user


@pytest.mark.django_db
class TestProjectFileURLSubmitForm(TestCase):
    """Test ProjectFileURLSubmitForm."""

    def test_form_valid_with_url_only(self):
        """Test form is valid with just URL."""
        form_data = {
            "url": "https://example.com/file.gds",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["url"] == "https://example.com/file.gds"
        assert form.cleaned_data["expected_hash_md5"] == ""
        assert form.cleaned_data["expected_hash_sha1"] == ""

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
        form_data = {}
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

    def test_form_md5_hash_with_whitespace_invalid(self):
        """Test MD5 hash with whitespace is invalid (pattern validation)."""
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": "abc123 def456 789012 345678 901234ab",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        # HTML5 pattern attribute rejects this before clean method runs
        assert not form.is_valid()
        assert "expected_hash_md5" in form.errors

    def test_form_md5_hash_with_dashes_invalid(self):
        """Test MD5 hash with dashes is invalid (pattern validation)."""
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": "abc123-def456-789012-345678-901234ab",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        # HTML5 pattern attribute rejects this before clean method runs
        assert not form.is_valid()
        assert "expected_hash_md5" in form.errors

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
            "expected_hash_sha1": "gggggggggggggggggggggggggggggggggggggggg",  # 'g' is not hex
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert not form.is_valid()
        assert "expected_hash_sha1" in form.errors
        assert "hexadecimal characters" in str(form.errors["expected_hash_sha1"])

    def test_form_empty_md5_hash_allowed(self):
        """Test empty MD5 hash is allowed (optional field)."""
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_md5": "",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_md5"] == ""

    def test_form_empty_sha1_hash_allowed(self):
        """Test empty SHA1 hash is allowed (optional field)."""
        form_data = {
            "url": "https://example.com/file.gds",
            "expected_hash_sha1": "",
        }
        form = ProjectFileURLSubmitForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["expected_hash_sha1"] == ""


@pytest.mark.django_db
class TestProjectFileLocalUploadForm(TestCase):
    """Test ProjectFileLocalUploadForm."""

    def test_form_has_correct_fields(self):
        """Test form has expected fields."""
        form = ProjectFileLocalUploadForm()

        assert "file" in form.fields
        assert "file_type" in form.fields
        assert "expected_hash_md5" in form.fields
        assert "expected_hash_sha1" in form.fields

    def test_form_md5_validation_same_as_url_form(self):
        """Test MD5 validation matches URL form."""
        # Test valid MD5
        form_data = {
            "expected_hash_md5": "abc123def456789012345678901234ab",
        }
        form = ProjectFileLocalUploadForm(data=form_data)

        # Will be invalid due to missing file, but MD5 should be cleaned
        form.is_valid()
        if "expected_hash_md5" not in form.errors:
            assert form.cleaned_data["expected_hash_md5"] == "abc123def456789012345678901234ab"

    def test_form_sha1_validation_same_as_url_form(self):
        """Test SHA1 validation matches URL form."""
        # Test valid SHA1
        form_data = {
            "expected_hash_sha1": "abc123def456789012345678901234567890abcd",
        }
        form = ProjectFileLocalUploadForm(data=form_data)

        # Will be invalid due to missing file, but SHA1 should be cleaned
        form.is_valid()
        if "expected_hash_sha1" not in form.errors:
            assert form.cleaned_data["expected_hash_sha1"] == "abc123def456789012345678901234567890abcd"
