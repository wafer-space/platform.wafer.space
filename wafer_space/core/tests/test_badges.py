"""Tests for the badge system."""

from __future__ import annotations

import dataclasses

import pytest

from wafer_space.core.badges import BadgeInfo
from wafer_space.core.badges import BadgeType
from wafer_space.core.badges import render_badge_html


class TestBadgeType:
    """Tests for BadgeType enum."""

    def test_badge_type_has_success(self) -> None:
        assert BadgeType.SUCCESS.value == "success"

    def test_badge_type_has_danger(self) -> None:
        assert BadgeType.DANGER.value == "danger"

    def test_badge_type_has_warning(self) -> None:
        assert BadgeType.WARNING.value == "warning"

    def test_badge_type_has_info(self) -> None:
        assert BadgeType.INFO.value == "info"

    def test_badge_type_has_processing(self) -> None:
        assert BadgeType.PROCESSING.value == "processing"

    def test_badge_type_has_neutral(self) -> None:
        assert BadgeType.NEUTRAL.value == "neutral"


class TestBadgeInfo:
    """Tests for BadgeInfo dataclass."""

    def test_badge_info_creation(self) -> None:
        badge = BadgeInfo(text="Test", badge_type=BadgeType.SUCCESS)
        assert badge.text == "Test"
        assert badge.badge_type == BadgeType.SUCCESS
        assert badge.icon is None

    def test_badge_info_with_icon(self) -> None:
        badge = BadgeInfo(
            text="Downloaded",
            badge_type=BadgeType.SUCCESS,
            icon="bi-check-circle",
        )
        assert badge.icon == "bi-check-circle"

    def test_badge_info_is_frozen(self) -> None:
        badge = BadgeInfo(text="Test", badge_type=BadgeType.SUCCESS)
        # Attribute name held in a variable so the frozen-dataclass
        # assignment is exercised at runtime rather than rejected by mypy
        attr_name = "text"
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(badge, attr_name, "Changed")

    def test_badge_info_to_dict(self) -> None:
        badge = BadgeInfo(
            text="Downloaded",
            badge_type=BadgeType.SUCCESS,
            icon="bi-check-circle",
        )
        result = badge.to_dict()
        assert result == {
            "text": "Downloaded",
            "badge_type": "success",
            "icon": "bi-check-circle",
        }

    def test_badge_info_to_dict_without_icon(self) -> None:
        badge = BadgeInfo(text="Pending", badge_type=BadgeType.NEUTRAL)
        result = badge.to_dict()
        assert result == {
            "text": "Pending",
            "badge_type": "neutral",
            "icon": None,
        }


class TestRenderBadgeHtml:
    """Tests for render_badge_html helper function."""

    def test_render_badge_html_returns_html_string(self) -> None:
        badge = BadgeInfo(
            text="Downloaded",
            badge_type=BadgeType.SUCCESS,
            icon="bi-check-circle",
        )
        result = render_badge_html(badge)

        assert '<span class="badge bg-success">' in result
        assert "Downloaded" in result
        assert "bi-check-circle" in result

    def test_render_badge_html_processing_has_spinner(self) -> None:
        badge = BadgeInfo(text="Downloading", badge_type=BadgeType.PROCESSING)
        result = render_badge_html(badge)

        assert "spinner-border" in result
        assert "Downloading" in result

    def test_render_badge_html_warning_has_text_dark(self) -> None:
        badge = BadgeInfo(text="Warning", badge_type=BadgeType.WARNING)
        result = render_badge_html(badge)

        assert "bg-warning" in result
        assert "text-dark" in result
