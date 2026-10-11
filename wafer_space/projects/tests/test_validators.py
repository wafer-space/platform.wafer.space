"""Tests for project validators."""

import pytest
from django.core.exceptions import ValidationError

from wafer_space.projects.models import PROJECT_ID_LENGTH
from wafer_space.projects.models import validate_project_id


@pytest.mark.django_db
class TestValidateProjectId:
    """Test validate_project_id function."""

    def test_valid_project_id_uppercase_letters(self):
        """Test that uppercase letters are valid."""
        validate_project_id("ABCD")  # Should not raise

    def test_valid_project_id_numbers(self):
        """Test that numbers are valid."""
        validate_project_id("1234")  # Should not raise

    def test_valid_project_id_mixed(self):
        """Test that mixed alphanumeric is valid."""
        validate_project_id("A1B2")  # Should not raise

    def test_invalid_project_id_too_short(self):
        """Test that IDs shorter than 4 characters are invalid."""
        with pytest.raises(ValidationError) as exc_info:
            validate_project_id("ABC")
        assert "exactly 4 characters" in str(exc_info.value)

    def test_invalid_project_id_too_long(self):
        """Test that IDs longer than 4 characters are invalid."""
        with pytest.raises(ValidationError) as exc_info:
            validate_project_id("ABCDE")
        assert "exactly 4 characters" in str(exc_info.value)

    def test_invalid_project_id_lowercase(self):
        """Test that lowercase letters are invalid."""
        with pytest.raises(ValidationError) as exc_info:
            validate_project_id("abcd")
        assert "uppercase" in str(exc_info.value)

    def test_invalid_project_id_special_characters(self):
        """Test that special characters are invalid."""
        with pytest.raises(ValidationError) as exc_info:
            validate_project_id("AB-D")
        assert "alphanumeric" in str(exc_info.value)

    def test_invalid_project_id_non_ascii_alphanumeric(self):
        """Test that non-ASCII alphanumerics are invalid.

        "ÀBCD" satisfies str.isalnum() and is left unchanged by str.upper(),
        so it passed both the alphanumeric and uppercase checks. It has no
        place in the ASCII-only canonical project URL: storing one made every
        page that links the project raise NoReverseMatch.
        """
        with pytest.raises(ValidationError) as exc_info:
            validate_project_id("ÀBCD")
        assert "alphanumeric" in str(exc_info.value)

    def test_invalid_project_id_spaces(self):
        """Test that spaces are invalid."""
        with pytest.raises(ValidationError) as exc_info:
            validate_project_id("AB D")
        assert "alphanumeric" in str(exc_info.value)

    def test_invalid_project_id_empty_string(self):
        """Test that empty string is invalid."""
        with pytest.raises(ValidationError) as exc_info:
            validate_project_id("")
        assert "exactly 4 characters" in str(exc_info.value)

    def test_uses_project_id_length_constant(self):
        """Test that validator uses PROJECT_ID_LENGTH constant."""
        # If constant changes, validator should reflect it
        test_id = "A" * PROJECT_ID_LENGTH
        validate_project_id(test_id)  # Should not raise
