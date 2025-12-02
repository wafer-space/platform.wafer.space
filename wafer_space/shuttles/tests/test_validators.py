"""Tests for shuttle validators."""

import pytest
from django.core.exceptions import ValidationError

from wafer_space.shuttles.models import SHUTTLE_ID_LENGTH
from wafer_space.shuttles.models import SHUTTLE_ID_MAX_NUMBER
from wafer_space.shuttles.models import SHUTTLE_ID_MIN_NUMBER
from wafer_space.shuttles.models import validate_shuttle_id


@pytest.mark.django_db
class TestValidateShuttleId:
    """Test validate_shuttle_id function."""

    def test_valid_shuttle_id_minimum(self):
        """Test minimum valid shuttle ID (G800)."""
        validate_shuttle_id("G800")  # Should not raise

    def test_valid_shuttle_id_maximum(self):
        """Test maximum valid shuttle ID (G899)."""
        validate_shuttle_id("G899")  # Should not raise

    def test_valid_shuttle_id_middle(self):
        """Test middle range shuttle ID (G850)."""
        validate_shuttle_id("G850")  # Should not raise

    def test_invalid_shuttle_id_too_short(self):
        """Test that IDs shorter than 4 characters are invalid."""
        with pytest.raises(ValidationError) as exc_info:
            validate_shuttle_id("G80")
        assert "exactly 4 characters" in str(exc_info.value)

    def test_invalid_shuttle_id_too_long(self):
        """Test that IDs longer than 4 characters are invalid."""
        with pytest.raises(ValidationError) as exc_info:
            validate_shuttle_id("G8001")
        assert "exactly 4 characters" in str(exc_info.value)

    def test_invalid_shuttle_id_wrong_prefix_g7(self):
        """Test that prefix other than G8 is invalid (G7)."""
        with pytest.raises(ValidationError) as exc_info:
            validate_shuttle_id("G700")
        assert "must start with 'G8'" in str(exc_info.value)

    def test_invalid_shuttle_id_wrong_prefix_g9(self):
        """Test that prefix other than G8 is invalid (G9)."""
        with pytest.raises(ValidationError) as exc_info:
            validate_shuttle_id("G900")
        assert "must start with 'G8'" in str(exc_info.value)

    def test_invalid_shuttle_id_wrong_prefix_h8(self):
        """Test that prefix other than G8 is invalid (H8)."""
        with pytest.raises(ValidationError) as exc_info:
            validate_shuttle_id("H800")
        assert "must start with 'G8'" in str(exc_info.value)

    def test_invalid_shuttle_id_lowercase(self):
        """Test that lowercase prefix is invalid."""
        with pytest.raises(ValidationError) as exc_info:
            validate_shuttle_id("g800")
        assert "must start with 'G8'" in str(exc_info.value)

    def test_invalid_shuttle_id_non_numeric_suffix(self):
        """Test that non-numeric suffix is invalid."""
        with pytest.raises(ValidationError) as exc_info:
            validate_shuttle_id("G8AB")
        assert "two digits" in str(exc_info.value)

    def test_invalid_shuttle_id_one_digit_suffix(self):
        """Test that single digit suffix is invalid."""
        with pytest.raises(ValidationError) as exc_info:
            validate_shuttle_id("G85")
        assert "exactly 4 characters" in str(exc_info.value)

    def test_invalid_shuttle_id_special_character(self):
        """Test that special characters in suffix are invalid."""
        with pytest.raises(ValidationError) as exc_info:
            validate_shuttle_id("G8-0")
        assert "two digits" in str(exc_info.value)

    def test_uses_shuttle_id_constants(self):
        """Test that validator uses shuttle ID constants."""
        assert SHUTTLE_ID_LENGTH == 4
        assert SHUTTLE_ID_MIN_NUMBER == 0
        assert SHUTTLE_ID_MAX_NUMBER == 99

        # Test boundaries using constants
        min_id = f"G8{SHUTTLE_ID_MIN_NUMBER:02d}"
        max_id = f"G8{SHUTTLE_ID_MAX_NUMBER:02d}"

        validate_shuttle_id(min_id)  # Should not raise
        validate_shuttle_id(max_id)  # Should not raise
