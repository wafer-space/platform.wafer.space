"""Tests for badge methods on notification models."""

from __future__ import annotations

import pytest

from wafer_space.core.badges import BadgeType
from wafer_space.notifications.models import Notification
from wafer_space.users.models import User


class TestNotificationTypeBadge:
    """Tests for Notification.get_type_badge() method."""

    @pytest.fixture(autouse=True)
    def setup(self, db):
        """Set up test fixtures."""
        # No password needed - these tests never authenticate
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
        )

    def test_download_complete_returns_success_badge(self) -> None:
        notification = Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_COMPLETE,
            title="Download Complete",
            message="Your file download is complete.",
        )
        badge = notification.get_type_badge()

        assert badge.badge_type == BadgeType.SUCCESS
        assert badge.text == "Download Complete"
        assert badge.icon == "bi-check-circle"

    def test_download_failed_returns_danger_badge(self) -> None:
        notification = Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_FAILED,
            title="Download Failed",
            message="Your file download has failed.",
        )
        badge = notification.get_type_badge()

        assert badge.badge_type == BadgeType.DANGER
        assert badge.text == "Download Failed"
        assert badge.icon == "bi-exclamation-triangle"

    def test_checksum_verified_returns_success_badge(self) -> None:
        notification = Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.CHECKSUM_VERIFIED,
            title="Checksum Verified",
            message="File checksum has been verified.",
        )
        badge = notification.get_type_badge()

        assert badge.badge_type == BadgeType.SUCCESS
        assert badge.text == "Checksum Verified"
        assert badge.icon == "bi-shield-check"

    def test_checksum_mismatch_returns_warning_badge(self) -> None:
        notification = Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.CHECKSUM_MISMATCH,
            title="Checksum Mismatch",
            message="File checksum does not match expected value.",
        )
        badge = notification.get_type_badge()

        assert badge.badge_type == BadgeType.WARNING
        assert badge.text == "Checksum Mismatch"
        assert badge.icon == "bi-shield-x"

    def test_manufacturing_complete_returns_success_badge(self) -> None:
        notification = Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.MANUFACTURING_COMPLETE,
            title="Manufacturing Complete",
            message="Your manufacturing order is complete.",
        )
        badge = notification.get_type_badge()

        assert badge.badge_type == BadgeType.SUCCESS
        assert badge.text == "Manufacturing Complete"
        assert badge.icon == "bi-box-seam"

    def test_tos_update_returns_info_badge(self) -> None:
        notification = Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.TOS_UPDATE,
            title="Terms of Service Update",
            message="Our terms of service have been updated.",
        )
        badge = notification.get_type_badge()

        assert badge.badge_type == BadgeType.INFO
        assert badge.text == "Terms of Service Update"
        assert badge.icon == "bi-file-text"

    def test_unknown_type_returns_neutral_badge_with_display_name(self) -> None:
        # Create notification with a valid type first
        notification = Notification.objects.create(
            user=self.user,
            notification_type=Notification.Type.DOWNLOAD_COMPLETE,
            title="Test",
            message="Test message",
        )

        # Manually override the notification_type to an invalid value
        # This simulates what would happen if a new type was added but
        # get_type_badge() wasn't updated
        notification.notification_type = "unknown_type"
        notification.save()

        badge = notification.get_type_badge()

        assert badge.badge_type == BadgeType.NEUTRAL
        assert badge.text == "unknown_type"
        assert badge.icon is None
