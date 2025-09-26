import secrets
import string

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Coupon(models.Model):
    """Discount coupons for shuttle purchases."""

    class CouponType(models.TextChoices):
        FIXED_AMOUNT = "fixed", "Fixed Amount"
        PERCENTAGE = "percentage", "Percentage"
        FREE_SLOT = "free_slot", "Free Slot"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        EXPIRED = "expired", "Expired"
        EXHAUSTED = "exhausted", "Exhausted"
        DISABLED = "disabled", "Disabled"

    code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Unique coupon code",
    )
    name = models.CharField(
        max_length=100,
        help_text="Descriptive name for the coupon",
    )
    description = models.TextField(blank=True)

    coupon_type = models.CharField(
        max_length=20,
        choices=CouponType.choices,
        default=CouponType.FIXED_AMOUNT,
    )

    # Discount values
    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Fixed discount amount (for fixed_amount type)",
    )
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Percentage discount (for percentage type)",
    )

    # Usage limits
    usage_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum number of times this coupon can be used (null = unlimited)",
    )
    usage_count = models.PositiveIntegerField(default=0)
    per_user_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum uses per user (null = unlimited per user)",
    )

    # Validity dates
    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Expiration date (null = never expires)",
    )

    # Minimum purchase requirements
    minimum_purchase_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Minimum purchase amount required to use this coupon",
    )

    # Creation info
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_coupons",
    )

    # Referral program integration
    from_referral_earnings = models.BooleanField(
        default=False,
        help_text="True if this coupon was generated from referral earnings",
    )
    source_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_coupons",
        help_text="User who generated this coupon (for referral-based coupons)",
    )

    class Meta:
        verbose_name = "Coupon"
        verbose_name_plural = "Coupons"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["valid_from", "valid_until"]),
            models.Index(fields=["from_referral_earnings", "source_user"]),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def status(self):
        """Calculate current status of the coupon."""
        now = timezone.now()

        # Check if expired
        if self.valid_until and now > self.valid_until:
            return self.Status.EXPIRED

        # Check if not yet valid
        if now < self.valid_from:
            return self.Status.DISABLED

        # Check if usage limit reached
        if self.usage_limit and self.usage_count >= self.usage_limit:
            return self.Status.EXHAUSTED

        return self.Status.ACTIVE

    def is_valid(self, user=None, purchase_amount=None):
        """Check if coupon is valid for use."""
        # Check basic status
        if self.status != self.Status.ACTIVE:
            return False, f"Coupon is {self.status}"

        # Check minimum purchase amount
        if (
            self.minimum_purchase_amount
            and purchase_amount
            and purchase_amount < self.minimum_purchase_amount
        ):
            return False, f"Minimum purchase amount is ${self.minimum_purchase_amount}"

        # Check per-user limit
        if user and self.per_user_limit:
            user_usage_count = self.usages.filter(user=user).count()
            if user_usage_count >= self.per_user_limit:
                return False, "You have reached the usage limit for this coupon"

        return True, "Valid"

    def calculate_discount(self, purchase_amount):
        """Calculate discount amount for a given purchase."""
        if self.coupon_type == self.CouponType.FIXED_AMOUNT:
            return min(self.discount_amount or 0, purchase_amount)
        if self.coupon_type == self.CouponType.PERCENTAGE:
            return purchase_amount * (self.discount_percentage or 0) / 100
        if self.coupon_type == self.CouponType.FREE_SLOT:
            # This would need to be handled in the business logic
            # as it depends on slot pricing
            return 0
        return 0

    @classmethod
    def generate_code(cls, prefix="", length=8):
        """Generate a unique coupon code."""
        while True:
            code = prefix + "".join(
                secrets.choice(string.ascii_uppercase + string.digits)
                for _ in range(length)
            )
            if not cls.objects.filter(code=code).exists():
                return code

    def use(self, user, purchase_amount=None, order_reference=""):
        """Record usage of this coupon."""
        is_valid, message = self.is_valid(user, purchase_amount)
        if not is_valid:
            raise ValueError(message)

        discount_amount = self.calculate_discount(purchase_amount or 0)

        usage = CouponUsage.objects.create(
            coupon=self,
            user=user,
            purchase_amount=purchase_amount or 0,
            discount_amount=discount_amount,
            order_reference=order_reference,
        )

        # Update usage count
        self.usage_count += 1
        self.save()

        return usage


class CouponUsage(models.Model):
    """Track usage of coupons by users."""

    coupon = models.ForeignKey(
        Coupon,
        on_delete=models.CASCADE,
        related_name="usages",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="coupon_usages",
    )

    # Usage details
    used_at = models.DateTimeField(auto_now_add=True)
    purchase_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    order_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Reference to the order where this coupon was used",
    )

    class Meta:
        verbose_name = "Coupon Usage"
        verbose_name_plural = "Coupon Usages"
        ordering = ["-used_at"]
        indexes = [
            models.Index(fields=["coupon", "user"]),
            models.Index(fields=["user", "used_at"]),
        ]

    def __str__(self):
        return (
            f"{self.coupon.code} used by {self.user.username} - "
            f"${self.discount_amount} discount"
        )


class CouponBatch(models.Model):
    """Batch generation of coupons for campaigns or referral programs."""

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    # Batch settings
    coupon_count = models.PositiveIntegerField()
    code_prefix = models.CharField(max_length=10, blank=True)

    # Coupon template settings
    coupon_type = models.CharField(
        max_length=20,
        choices=Coupon.CouponType.choices,
        default=Coupon.CouponType.FIXED_AMOUNT,
    )
    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    discount_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    usage_limit = models.PositiveIntegerField(null=True, blank=True)
    per_user_limit = models.PositiveIntegerField(null=True, blank=True)
    valid_from = models.DateTimeField(default=timezone.now)
    valid_until = models.DateTimeField(null=True, blank=True)
    minimum_purchase_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )

    # Batch info
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    generated = models.BooleanField(default=False)
    generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Coupon Batch"
        verbose_name_plural = "Coupon Batches"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.coupon_count} coupons)"

    def generate_coupons(self):
        """Generate all coupons in this batch."""
        if self.generated:
            msg = "Coupons for this batch have already been generated"
            raise ValueError(msg)

        coupons_created = []
        for i in range(self.coupon_count):
            coupon = Coupon.objects.create(
                code=Coupon.generate_code(self.code_prefix),
                name=f"{self.name} #{i + 1}",
                description=self.description,
                coupon_type=self.coupon_type,
                discount_amount=self.discount_amount,
                discount_percentage=self.discount_percentage,
                usage_limit=self.usage_limit,
                per_user_limit=self.per_user_limit,
                valid_from=self.valid_from,
                valid_until=self.valid_until,
                minimum_purchase_amount=self.minimum_purchase_amount,
                created_by=self.created_by,
            )
            coupons_created.append(coupon)

        self.generated = True
        self.generated_at = timezone.now()
        self.save()

        return coupons_created
