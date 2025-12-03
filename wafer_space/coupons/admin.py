"""Django admin configuration for coupons app."""

from django.contrib import admin

from wafer_space.coupons.models import Coupon
from wafer_space.coupons.models import CouponBatch
from wafer_space.coupons.models import CouponUsage


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    """Admin interface for Coupon model."""

    list_display = [
        "code",
        "name",
        "coupon_type",
        "discount_display",
        "usage_count",
        "usage_limit",
        "status",
        "valid_from",
        "valid_until",
    ]
    list_filter = ["coupon_type", "from_referral_earnings", "valid_from", "created_at"]
    search_fields = ["code", "name", "description"]
    readonly_fields = ["created_at", "usage_count", "status"]
    raw_id_fields = ["created_by", "source_user"]
    fieldsets = [
        (None, {"fields": ["code", "name", "description", "coupon_type"]}),
        (
            "Discount",
            {"fields": ["discount_amount", "discount_percentage"]},
        ),
        (
            "Limits",
            {"fields": ["usage_limit", "usage_count", "per_user_limit"]},
        ),
        (
            "Validity",
            {"fields": ["valid_from", "valid_until", "minimum_purchase_amount"]},
        ),
        (
            "Referral Program",
            {
                "fields": ["from_referral_earnings", "source_user"],
                "classes": ["collapse"],
            },
        ),
        (
            "Metadata",
            {"fields": ["created_at", "created_by"]},
        ),
    ]

    @admin.display(description="Discount")
    def discount_display(self, obj):
        """Display discount value based on coupon type."""
        if obj.coupon_type == Coupon.CouponType.FIXED_AMOUNT:
            return f"${obj.discount_amount}"
        if obj.coupon_type == Coupon.CouponType.PERCENTAGE:
            return f"{obj.discount_percentage}%"
        if obj.coupon_type == Coupon.CouponType.FREE_SLOT:
            return "Free Slot"
        return "-"


@admin.register(CouponUsage)
class CouponUsageAdmin(admin.ModelAdmin):
    """Admin interface for CouponUsage model."""

    list_display = [
        "coupon",
        "user",
        "purchase_amount",
        "discount_amount",
        "order_reference",
        "used_at",
    ]
    list_filter = ["used_at"]
    search_fields = [
        "coupon__code",
        "user__username",
        "order_reference",
    ]
    readonly_fields = ["used_at"]
    raw_id_fields = ["coupon", "user"]


@admin.register(CouponBatch)
class CouponBatchAdmin(admin.ModelAdmin):
    """Admin interface for CouponBatch model."""

    list_display = [
        "name",
        "coupon_count",
        "coupon_type",
        "generated",
        "created_at",
        "generated_at",
    ]
    list_filter = ["generated", "coupon_type", "created_at"]
    search_fields = ["name", "description", "code_prefix"]
    readonly_fields = ["created_at", "generated", "generated_at"]
    raw_id_fields = ["created_by"]
