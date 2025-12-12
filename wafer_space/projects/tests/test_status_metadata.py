"""Tests for ManufacturabilityCheck status metadata."""

import pytest
from django.utils.safestring import SafeString

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory


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
