"""Tests for ManufacturabilityCheck status metadata."""

import pytest
from django.utils.safestring import SafeString

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


class TestStatusBadgeHtml:
    """Tests for status_badge_html() method."""

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
    def test_badge_includes_color_class(self, pending_check):
        """Badge HTML includes Bootstrap color class."""
        html = pending_check.status_badge_html()
        assert "bg-warning" in html

    @pytest.mark.django_db
    def test_badge_includes_icon(self, pending_check):
        """Badge HTML includes icon when defined."""
        html = pending_check.status_badge_html()
        assert "bi-clock" in html

    @pytest.mark.django_db
    def test_badge_includes_label(self, pending_check):
        """Badge HTML includes status label."""
        html = pending_check.status_badge_html()
        assert "Pending" in html

    @pytest.mark.django_db
    def test_badge_includes_spinner_when_active(self, running_check):
        """Badge HTML includes spinner for active statuses."""
        html = running_check.status_badge_html()
        assert "spinner-border" in html

    @pytest.mark.django_db
    def test_badge_no_spinner_when_inactive(self, pending_check):
        """Badge HTML excludes spinner for inactive statuses."""
        html = pending_check.status_badge_html()
        assert "spinner-border" not in html

    @pytest.mark.django_db
    def test_badge_is_marked_safe(self, pending_check):
        """Badge HTML is marked safe for template rendering."""
        html = pending_check.status_badge_html()
        assert isinstance(html, SafeString)


class TestFinishedStatusBadge:
    """Tests for finished status badge showing all three manufacturable states."""

    @pytest.fixture
    def manufacturable_clean_check(self):
        """Create a finished check that is manufacturable with no warnings."""
        return ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
            warnings=[],
        )

    @pytest.fixture
    def manufacturable_with_warnings_check(self):
        """Create a finished check that is manufacturable but has warnings."""
        return ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
            warnings=["Warning 1", "Warning 2"],
        )

    @pytest.fixture
    def not_manufacturable_check(self):
        """Create a finished check that is not manufacturable."""
        return ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=False,
        )

    # --- Manufacturable (Clean) tests ---

    @pytest.mark.django_db
    def test_manufacturable_clean_shows_success_color(self, manufacturable_clean_check):
        """Manufacturable clean check shows success (green) badge."""
        html = manufacturable_clean_check.status_badge_html()
        assert "bg-success" in html

    @pytest.mark.django_db
    def test_manufacturable_clean_shows_check_icon(self, manufacturable_clean_check):
        """Manufacturable clean check shows check-circle icon."""
        html = manufacturable_clean_check.status_badge_html()
        assert "bi-check-circle" in html

    @pytest.mark.django_db
    def test_manufacturable_clean_shows_label(self, manufacturable_clean_check):
        """Manufacturable clean check shows 'Manufacturable' label."""
        html = manufacturable_clean_check.status_badge_html()
        assert "Manufacturable" in html
        assert "Warnings" not in html

    # --- Manufacturable (with warnings) tests ---

    @pytest.mark.django_db
    def test_manufacturable_warnings_shows_warning_color(
        self, manufacturable_with_warnings_check
    ):
        """Manufacturable with warnings shows warning (yellow) badge."""
        html = manufacturable_with_warnings_check.status_badge_html()
        assert "bg-warning" in html

    @pytest.mark.django_db
    def test_manufacturable_warnings_shows_warning_icon(
        self, manufacturable_with_warnings_check
    ):
        """Manufacturable with warnings shows exclamation-triangle icon."""
        html = manufacturable_with_warnings_check.status_badge_html()
        assert "bi-exclamation-triangle" in html

    @pytest.mark.django_db
    def test_manufacturable_warnings_shows_label(
        self, manufacturable_with_warnings_check
    ):
        """Manufacturable with warnings shows appropriate label."""
        html = manufacturable_with_warnings_check.status_badge_html()
        assert "Manufacturable" in html
        assert "Warnings" in html

    # --- Not Manufacturable tests ---

    @pytest.mark.django_db
    def test_not_manufacturable_badge_shows_danger_color(
        self, not_manufacturable_check
    ):
        """Not manufacturable check shows danger (red) badge."""
        html = not_manufacturable_check.status_badge_html()
        assert "bg-danger" in html

    @pytest.mark.django_db
    def test_not_manufacturable_badge_shows_x_icon(self, not_manufacturable_check):
        """Not manufacturable check shows x-circle icon."""
        html = not_manufacturable_check.status_badge_html()
        assert "bi-x-circle" in html

    @pytest.mark.django_db
    def test_not_manufacturable_badge_shows_not_manufacturable_label(
        self, not_manufacturable_check
    ):
        """Not manufacturable check shows 'Not Manufacturable' label."""
        html = not_manufacturable_check.status_badge_html()
        assert "Not Manufacturable" in html
