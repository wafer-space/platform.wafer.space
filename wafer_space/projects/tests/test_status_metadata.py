"""Tests for ManufacturabilityCheck status metadata."""

from wafer_space.projects.models import ManufacturabilityCheck


class TestStatusMetadata:
    """Tests for status metadata completeness and consistency."""

    def test_all_statuses_have_metadata(self):
        """Every status choice must have metadata defined."""
        for status_value, _label in ManufacturabilityCheck.Status.choices:
            meta = ManufacturabilityCheck.get_status_metadata(status_value)
            assert meta is not None, f"Missing metadata for status: {status_value}"
            assert "color" in meta, f"Missing 'color' for status: {status_value}"
            assert "icon" in meta, f"Missing 'icon' for status: {status_value}"
            assert "label" in meta, f"Missing 'label' for status: {status_value}"
            assert "show_spinner" in meta, f"Missing 'show_spinner' for: {status_value}"

    def test_colors_are_valid_bootstrap(self):
        """Colors must be valid Bootstrap contextual colors."""
        valid_colors = {"primary", "secondary", "success", "danger", "warning", "info"}
        for status_value, _label in ManufacturabilityCheck.Status.choices:
            meta = ManufacturabilityCheck.get_status_metadata(status_value)
            assert meta["color"] in valid_colors, (
                f"Invalid color '{meta['color']}' for status: {status_value}"
            )

    def test_icons_are_bootstrap_icons(self):
        """Icons must be valid Bootstrap icon classes."""
        for status_value, _label in ManufacturabilityCheck.Status.choices:
            meta = ManufacturabilityCheck.get_status_metadata(status_value)
            # Icons should start with "bi-" or be empty for spinner-only
            icon = meta["icon"]
            assert isinstance(icon, str), (
                f"Icon must be string for status: {status_value}"
            )
            assert icon == "" or icon.startswith("bi-"), (
                f"Invalid icon '{icon}' for status: {status_value}"
            )

    def test_show_spinner_is_boolean(self):
        """show_spinner must be a boolean."""
        for status_value, _label in ManufacturabilityCheck.Status.choices:
            meta = ManufacturabilityCheck.get_status_metadata(status_value)
            assert isinstance(meta["show_spinner"], bool), (
                f"show_spinner must be bool for status: {status_value}"
            )
