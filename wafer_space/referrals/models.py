from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from django.utils import timezone
import secrets
import string


class ReferralCode(models.Model):
    """Referral codes generated for users in the referral program."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='referral_code'
    )
    code = models.CharField(
        max_length=20,
        unique=True,
        help_text="Unique referral code for this user"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    usage_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Referral Code"
        verbose_name_plural = "Referral Codes"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.code}"

    @classmethod
    def generate_code(cls, length=8):
        """Generate a unique referral code."""
        while True:
            code = ''.join(secrets.choice(string.ascii_uppercase + string.digits)
                          for _ in range(length))
            if not cls.objects.filter(code=code).exists():
                return code


class ReferralEarning(models.Model):
    """Track earnings from referral program usage."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        CONFIRMED = 'confirmed', 'Confirmed'
        PAID = 'paid', 'Paid'
        CANCELLED = 'cancelled', 'Cancelled'

    referrer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='referral_earnings'
    )
    referred_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='referred_from'
    )
    referral_code = models.ForeignKey(
        ReferralCode,
        on_delete=models.CASCADE,
        related_name='earnings'
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    order_reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Reference to the order that generated this earning"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Referral Earning"
        verbose_name_plural = "Referral Earnings"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['referrer', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"{self.referrer.username} earned ${self.amount} from {self.referred_user.username}"

    def confirm(self):
        """Mark earning as confirmed."""
        self.status = self.Status.CONFIRMED
        self.confirmed_at = timezone.now()
        self.save()


class PayoutRequest(models.Model):
    """User requests for referral earning payouts."""

    class PayoutMethod(models.TextChoices):
        USD_PAYMENT = 'usd', 'USD Payment'
        SHUTTLE_COUPON = 'coupon', 'Shuttle Coupon'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='payout_requests'
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    payout_method = models.CharField(
        max_length=20,
        choices=PayoutMethod.choices
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )
    payment_details = models.JSONField(
        default=dict,
        help_text="Payment method specific details (email, address, etc.)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Payout Request"
        verbose_name_plural = "Payout Requests"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"{self.user.username} - ${self.amount} via {self.get_payout_method_display()}"
