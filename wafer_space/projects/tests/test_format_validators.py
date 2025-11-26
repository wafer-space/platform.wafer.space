"""Tests for format validators."""

from pathlib import Path

import pytest

from wafer_space.projects.format_validators import GDSValidator
from wafer_space.projects.format_validators import OASISValidator
from wafer_space.projects.format_validators import validate_output_format


class TestGDSValidator:
    """Tests for GDSValidator."""

    def test_gds_validator_valid_file(self, tmp_path: Path) -> None:
        """Test GDSValidator accepts valid GDSII file."""
        # Create valid GDS file with correct magic bytes
        gds_file = tmp_path / "test.gds"
        gds_file.write_bytes(b"\x00\x06\x00\x02" + b"\x00\x05" + b"\x00" * 100)

        validator = GDSValidator()
        assert validator.is_valid(gds_file)
        assert validator.get_format_name() == "GDSII"

    def test_gds_validator_invalid_magic_bytes(self, tmp_path: Path) -> None:
        """Test GDSValidator rejects file with wrong magic bytes."""
        # Create file with wrong magic bytes
        invalid_file = tmp_path / "invalid.gds"
        invalid_file.write_bytes(b"\x00\x00\x00\x00" + b"\x00" * 100)

        validator = GDSValidator()
        assert not validator.is_valid(invalid_file)

    def test_gds_validator_empty_file(self, tmp_path: Path) -> None:
        """Test GDSValidator handles empty file."""
        empty_file = tmp_path / "empty.gds"
        empty_file.write_bytes(b"")

        validator = GDSValidator()
        assert not validator.is_valid(empty_file)

    def test_gds_validator_partial_file(self, tmp_path: Path) -> None:
        """Test GDSValidator handles file shorter than magic bytes."""
        partial_file = tmp_path / "partial.gds"
        partial_file.write_bytes(b"\x00\x06")  # Only 2 bytes

        validator = GDSValidator()
        assert not validator.is_valid(partial_file)

    def test_gds_validator_nonexistent_file(self, tmp_path: Path) -> None:
        """Test GDSValidator handles nonexistent file."""
        nonexistent = tmp_path / "nonexistent.gds"

        validator = GDSValidator()
        assert not validator.is_valid(nonexistent)

    def test_gds_validator_minimal_valid_file(self, tmp_path: Path) -> None:
        """Test GDSValidator accepts minimal valid file (just magic bytes)."""
        minimal_file = tmp_path / "minimal.gds"
        minimal_file.write_bytes(b"\x00\x06\x00\x02")

        validator = GDSValidator()
        assert validator.is_valid(minimal_file)


class TestOASISValidator:
    """Tests for OASISValidator."""

    def test_oasis_validator_valid_file(self, tmp_path: Path) -> None:
        """Test OASISValidator accepts valid OASIS file."""
        # Create valid OASIS file with correct magic string
        oasis_file = tmp_path / "test.oas"
        oasis_file.write_bytes(b"%SEMI-OASIS\r\n" + b"\x00" * 100)

        validator = OASISValidator()
        assert validator.is_valid(oasis_file)
        assert validator.get_format_name() == "OASIS"

    def test_oasis_validator_invalid_magic_string(self, tmp_path: Path) -> None:
        """Test OASISValidator rejects file with wrong magic string."""
        # Create file with wrong magic string
        invalid_file = tmp_path / "invalid.oas"
        invalid_file.write_bytes(b"%WRONG-FORMAT\r\n" + b"\x00" * 100)

        validator = OASISValidator()
        assert not validator.is_valid(invalid_file)

    def test_oasis_validator_empty_file(self, tmp_path: Path) -> None:
        """Test OASISValidator handles empty file."""
        empty_file = tmp_path / "empty.oas"
        empty_file.write_bytes(b"")

        validator = OASISValidator()
        assert not validator.is_valid(empty_file)

    def test_oasis_validator_partial_file(self, tmp_path: Path) -> None:
        """Test OASISValidator handles file shorter than magic string."""
        partial_file = tmp_path / "partial.oas"
        partial_file.write_bytes(b"%SEMI")  # Only 5 bytes

        validator = OASISValidator()
        assert not validator.is_valid(partial_file)

    def test_oasis_validator_nonexistent_file(self, tmp_path: Path) -> None:
        """Test OASISValidator handles nonexistent file."""
        nonexistent = tmp_path / "nonexistent.oas"

        validator = OASISValidator()
        assert not validator.is_valid(nonexistent)

    def test_oasis_validator_minimal_valid_file(self, tmp_path: Path) -> None:
        """Test OASISValidator accepts minimal valid file (just magic string)."""
        minimal_file = tmp_path / "minimal.oas"
        minimal_file.write_bytes(b"%SEMI-OASIS\r\n")

        validator = OASISValidator()
        assert validator.is_valid(minimal_file)

    def test_oasis_validator_wrong_line_ending(self, tmp_path: Path) -> None:
        """Test OASISValidator rejects OASIS with Unix line ending."""
        # OASIS spec requires CR+LF, not just LF
        wrong_ending = tmp_path / "wrong_ending.oas"
        wrong_ending.write_bytes(b"%SEMI-OASIS\n" + b"\x00" * 100)

        validator = OASISValidator()
        assert not validator.is_valid(wrong_ending)


class TestValidateOutputFormat:
    """Tests for validate_output_format function."""

    def test_validate_output_format_gds(self, tmp_path: Path) -> None:
        """Test validate_output_format identifies GDSII file."""
        gds_file = tmp_path / "design.gds"
        gds_file.write_bytes(b"\x00\x06\x00\x02" + b"\x00\x05" + b"\x00" * 100)

        result = validate_output_format(gds_file)
        assert result == "GDSII"

    def test_validate_output_format_oasis(self, tmp_path: Path) -> None:
        """Test validate_output_format identifies OASIS file."""
        oasis_file = tmp_path / "design.oas"
        oasis_file.write_bytes(b"%SEMI-OASIS\r\n" + b"\x00" * 100)

        result = validate_output_format(oasis_file)
        assert result == "OASIS"

    def test_validate_output_format_invalid(self, tmp_path: Path) -> None:
        """Test validate_output_format raises error for invalid file."""
        invalid_file = tmp_path / "design.txt"
        invalid_file.write_bytes(b"This is not a valid GDS or OASIS file")

        with pytest.raises(ValueError, match="not a valid GDS or OASIS file"):
            validate_output_format(invalid_file)

    def test_validate_output_format_empty(self, tmp_path: Path) -> None:
        """Test validate_output_format raises error for empty file."""
        empty_file = tmp_path / "empty.gds"
        empty_file.write_bytes(b"")

        with pytest.raises(ValueError, match="not a valid GDS or OASIS file"):
            validate_output_format(empty_file)

    def test_validate_output_format_error_message(self, tmp_path: Path) -> None:
        """Test validate_output_format error message includes expected formats."""
        invalid_file = tmp_path / "invalid.bin"
        invalid_file.write_bytes(b"\xff\xff\xff\xff")

        expected_pattern = (
            r"Expected GDSII format \(00 06 00 02\) "
            r"or OASIS format \(%SEMI-OASIS\)"
        )
        with pytest.raises(ValueError, match=expected_pattern):
            validate_output_format(invalid_file)

    def test_validate_output_format_includes_filename(self, tmp_path: Path) -> None:
        """Test validate_output_format error message includes filename."""
        invalid_file = tmp_path / "my_design.gds"
        invalid_file.write_bytes(b"invalid content")

        with pytest.raises(ValueError, match=r"my_design\.gds"):
            validate_output_format(invalid_file)


class TestValidatorEdgeCases:
    """Tests for edge cases and error handling."""

    def test_gds_validator_with_permission_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test GDSValidator handles permission errors gracefully."""
        gds_file = tmp_path / "test.gds"
        gds_file.write_bytes(b"\x00\x06\x00\x02")

        # Mock file open to raise PermissionError
        def mock_open(*args, **kwargs):
            msg = "Access denied"
            raise PermissionError(msg)

        monkeypatch.setattr(Path, "open", mock_open)

        validator = GDSValidator()
        assert not validator.is_valid(gds_file)

    def test_oasis_validator_with_io_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test OASISValidator handles IO errors gracefully."""
        oasis_file = tmp_path / "test.oas"
        oasis_file.write_bytes(b"%SEMI-OASIS\r\n")

        # Mock file open to raise OSError
        def mock_open(*args, **kwargs):
            msg = "Disk error"
            raise OSError(msg)

        monkeypatch.setattr(Path, "open", mock_open)

        validator = OASISValidator()
        assert not validator.is_valid(oasis_file)

    def test_validators_with_binary_garbage(self, tmp_path: Path) -> None:
        """Test validators reject binary garbage data."""
        garbage_file = tmp_path / "garbage.bin"
        # Create 1KB of random-looking binary data
        garbage_data = bytes(range(256)) * 4
        garbage_file.write_bytes(garbage_data)

        gds_validator = GDSValidator()
        oasis_validator = OASISValidator()

        assert not gds_validator.is_valid(garbage_file)
        assert not oasis_validator.is_valid(garbage_file)

    def test_validators_with_text_file(self, tmp_path: Path) -> None:
        """Test validators reject plain text files."""
        text_file = tmp_path / "readme.txt"
        text_file.write_text("This is a plain text file\n")

        gds_validator = GDSValidator()
        oasis_validator = OASISValidator()

        assert not gds_validator.is_valid(text_file)
        assert not oasis_validator.is_valid(text_file)

    def test_gds_validator_with_almost_correct_magic(self, tmp_path: Path) -> None:
        """Test GDSValidator rejects file with almost correct magic bytes."""
        # Off by one byte
        almost_file = tmp_path / "almost.gds"
        almost_file.write_bytes(b"\x00\x06\x00\x03" + b"\x00" * 100)

        validator = GDSValidator()
        assert not validator.is_valid(almost_file)

    def test_oasis_validator_with_case_variation(self, tmp_path: Path) -> None:
        """Test OASISValidator rejects case variations of magic string."""
        # OASIS spec is case-sensitive
        lowercase_file = tmp_path / "lowercase.oas"
        lowercase_file.write_bytes(b"%semi-oasis\r\n" + b"\x00" * 100)

        validator = OASISValidator()
        assert not validator.is_valid(lowercase_file)
