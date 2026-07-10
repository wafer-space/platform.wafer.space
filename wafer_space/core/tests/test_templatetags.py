"""Tests for badge template tags."""

from __future__ import annotations

import pytest
from django.template import Context
from django.template import Template

from wafer_space.core.badges import BadgeInfo
from wafer_space.core.badges import BadgeType


class TestRenderBadgeTag:
    """Tests for the render_badge template tag."""

    @pytest.mark.django_db
    def test_render_badge_success(self) -> None:
        template = Template("{% load badges %}{% render_badge badge %}")
        badge = BadgeInfo(text="Downloaded", badge_type=BadgeType.SUCCESS)
        context = Context({"badge": badge})
        result = template.render(context)

        assert "bg-success" in result
        assert "Downloaded" in result

    @pytest.mark.django_db
    def test_render_badge_danger(self) -> None:
        template = Template("{% load badges %}{% render_badge badge %}")
        badge = BadgeInfo(text="Failed", badge_type=BadgeType.DANGER)
        context = Context({"badge": badge})
        result = template.render(context)

        assert "bg-danger" in result
        assert "Failed" in result

    @pytest.mark.django_db
    def test_render_badge_with_icon(self) -> None:
        template = Template("{% load badges %}{% render_badge badge %}")
        badge = BadgeInfo(
            text="Verified",
            badge_type=BadgeType.SUCCESS,
            icon="bi-shield-check",
        )
        context = Context({"badge": badge})
        result = template.render(context)

        assert "bi-shield-check" in result

    @pytest.mark.django_db
    def test_render_badge_processing_has_spinner(self) -> None:
        template = Template("{% load badges %}{% render_badge badge %}")
        badge = BadgeInfo(text="Checking...", badge_type=BadgeType.PROCESSING)
        context = Context({"badge": badge})
        result = template.render(context)

        assert "spinner-border" in result
        assert "bg-primary" in result

    @pytest.mark.django_db
    def test_render_badge_warning_has_text_dark(self) -> None:
        template = Template("{% load badges %}{% render_badge badge %}")
        badge = BadgeInfo(text="Unverified", badge_type=BadgeType.WARNING)
        context = Context({"badge": badge})
        result = template.render(context)

        assert "bg-warning" in result
        assert "text-dark" in result
