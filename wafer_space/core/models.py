"""Models for the core app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import IntegrityError
from django.db import models
from django.db import transaction

if TYPE_CHECKING:
    from datetime import datetime
    from datetime import timedelta

# Tries to claim a slot whose row another process deleted in between, before
# taking the slot anyway: a deleted row means that process lost its email
CLAIM_ATTEMPTS = 2


class AdminEmailClaimManager(models.Manager["AdminEmailClaim"]):
    """Claims on ADMINS email slots, shared by every process (issue #450)."""

    def claim(
        self,
        signature: str,
        *,
        now: datetime,
        window: timedelta,
    ) -> datetime | None:
        """Take ``signature``'s slot at ``now``, unless it was taken within ``window``.

        Returns None when the caller took it and should send the email;
        otherwise when the slot was taken, so the caller can ask again
        once the window ends. Atomic: of two processes that ask at once,
        exactly one takes the slot. Run it in autocommit mode, on a
        connection of its own: inside a transaction, the row stays locked
        until that transaction ends.
        """
        for _attempt in range(CLAIM_ATTEMPTS):
            try:
                with transaction.atomic():
                    self.create(signature=signature, sent_at=now)
            except IntegrityError:
                pass
            else:
                return None
            # The row exists: take it over if its window has ended
            if self.filter(signature=signature, sent_at__lte=now - window).update(
                sent_at=now
            ):
                return None
            sent_at = (
                self.filter(signature=signature)
                .values_list("sent_at", flat=True)
                .first()
            )
            if sent_at is not None:
                return sent_at
        return None

    def release(self, signature: str, *, sent_at: datetime) -> None:
        """Give back the slot taken at ``sent_at``: its email was lost."""
        self.filter(signature=signature, sent_at=sent_at).delete()


class AdminEmailClaim(models.Model):
    """When an ADMINS email was last sent for one error signature (issue #450).

    RateLimitedAdminEmailHandler sends at most one email per signature per
    hour. Each process used to keep that in its own LocMem cache, so every
    process that logged the same error sent its own email. A row here is
    shared by all of them. There is one row per signature, updated in place.
    """

    # sha256 hex digest of "logger:level:unformatted message"
    signature = models.CharField(max_length=64, unique=True)
    sent_at = models.DateTimeField()

    objects = AdminEmailClaimManager()

    class Meta:
        verbose_name = "ADMINS email claim"

    def __str__(self) -> str:
        return f"{self.signature[:12]} sent at {self.sent_at.isoformat()}"
