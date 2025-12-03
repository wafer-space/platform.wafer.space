"""Django admin configuration for referrals app."""

from django.contrib import admin

from wafer_space.referrals.models import PayoutRequest
from wafer_space.referrals.models import ReferralCode
from wafer_space.referrals.models import ReferralEarning


@admin.register(ReferralCode)
class ReferralCodeAdmin(admin.ModelAdmin):
    """Admin interface for ReferralCode model."""

    list_display = [
        "code",
        "user",
        "usage_count",
        "is_active",
        "created_at",
    ]
    list_filter = ["is_active", "created_at"]
    search_fields = ["code", "user__username", "user__email"]
    readonly_fields = ["created_at", "usage_count"]
    raw_id_fields = ["user"]


@admin.register(ReferralEarning)
class ReferralEarningAdmin(admin.ModelAdmin):
    """Admin interface for ReferralEarning model."""

    list_display = [
        "referrer",
        "referred_user",
        "amount",
        "status",
        "order_reference",
        "created_at",
    ]
    list_filter = ["status", "created_at"]
    search_fields = [
        "referrer__username",
        "referred_user__username",
        "order_reference",
    ]
    readonly_fields = ["created_at", "confirmed_at", "paid_at"]
    raw_id_fields = ["referrer", "referred_user", "referral_code"]


@admin.register(PayoutRequest)
class PayoutRequestAdmin(admin.ModelAdmin):
    """Admin interface for PayoutRequest model."""

    list_display = [
        "user",
        "amount",
        "payout_method",
        "status",
        "created_at",
        "processed_at",
    ]
    list_filter = ["status", "payout_method", "created_at"]
    search_fields = ["user__username", "user__email", "notes"]
    readonly_fields = ["created_at", "processed_at", "completed_at"]
    raw_id_fields = ["user"]
