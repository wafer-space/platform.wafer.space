"""Tests for ManufacturabilityCheck status metadata."""

import pytest

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory


class TestStatusClassMethods:
    """Tests for Status class helper methods completeness."""

    def test_all_matches_choices_length(self):
        """Status.all() must have same length as choices."""
        assert len(ManufacturabilityCheck.Status.all()) == len(
            ManufacturabilityCheck.Status.choices
        )

    def test_all_contains_all_choices(self):
        """Status.all() must contain all status values from choices."""
        all_statuses = set(ManufacturabilityCheck.Status.all())
        choice_values = {choice[0] for choice in ManufacturabilityCheck.Status.choices}
        assert all_statuses == choice_values

    def test_display_order_matches_choices_length(self):
        """Status.display_order() must have same length as choices."""
        assert len(ManufacturabilityCheck.Status.display_order()) == len(
            ManufacturabilityCheck.Status.choices
        )

    def test_display_order_contains_all_choices(self):
        """Status.display_order() must contain all status values from choices."""
        display_statuses = set(ManufacturabilityCheck.Status.display_order())
        choice_values = {choice[0] for choice in ManufacturabilityCheck.Status.choices}
        assert display_statuses == choice_values

    def test_terminal_plus_non_terminal_equals_all(self):
        """Terminal and non-terminal statuses must cover all statuses."""
        terminal = set(ManufacturabilityCheck.Status.terminal())
        non_terminal = set(ManufacturabilityCheck.Status.non_terminal())
        all_statuses = set(ManufacturabilityCheck.Status.all())
        assert terminal | non_terminal == all_statuses
        assert terminal & non_terminal == set()  # No overlap


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

    def test_invalid_status_raises_key_error(self):
        """get_status_metadata raises KeyError for invalid status."""
        with pytest.raises(KeyError) as exc_info:
            ManufacturabilityCheck.get_status_metadata("invalid_status")
        assert "invalid_status" in str(exc_info.value)


class TestStatusProperties:
    """Tests for ManufacturabilityCheck status properties."""

    @pytest.fixture
    def pending_check(self):
        """Create a check in pending status."""
        return ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.PENDING
        )

    @pytest.fixture
    def running_check(self):
        """Create a check in running status."""
        return ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING
        )

    @pytest.mark.django_db
    def test_status_color_property(self, pending_check):
        """status_color returns the Bootstrap color for current status."""
        assert pending_check.status_color == "warning"

    @pytest.mark.django_db
    def test_status_icon_property(self, pending_check):
        """status_icon returns the Bootstrap icon class for current status."""
        assert pending_check.status_icon == "bi-clock"

    @pytest.mark.django_db
    def test_status_label_property(self, pending_check):
        """status_label returns the human-readable label."""
        assert pending_check.status_label == "Pending"

    @pytest.mark.django_db
    def test_status_show_spinner_false(self, pending_check):
        """status_show_spinner returns False for non-active statuses."""
        assert pending_check.status_show_spinner is False

    @pytest.mark.django_db
    def test_status_show_spinner_true(self, running_check):
        """status_show_spinner returns True for active statuses."""
        assert running_check.status_show_spinner is True
