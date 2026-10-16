"""Tests for AdminEmailClaim, the ADMINS email slots every process shares (#450)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from wafer_space.core.models import AdminEmailClaim

SIGNATURE = "a" * 64
OTHER_SIGNATURE = "b" * 64
WINDOW = timedelta(hours=1)
TWO_ROWS = 2

pytestmark = pytest.mark.django_db


class TestClaim:
    def test_a_new_signature_is_taken(self) -> None:
        now = timezone.now()

        assert AdminEmailClaim.objects.claim(SIGNATURE, now=now, window=WINDOW) is None
        assert AdminEmailClaim.objects.get(signature=SIGNATURE).sent_at == now

    def test_a_slot_taken_within_the_window_is_refused(self) -> None:
        sent_at = timezone.now() - timedelta(minutes=10)
        AdminEmailClaim.objects.create(signature=SIGNATURE, sent_at=sent_at)

        refused = AdminEmailClaim.objects.claim(
            SIGNATURE, now=timezone.now(), window=WINDOW
        )

        assert refused == sent_at
        assert AdminEmailClaim.objects.get(signature=SIGNATURE).sent_at == sent_at

    def test_a_slot_whose_window_ended_is_taken_in_place(self) -> None:
        AdminEmailClaim.objects.create(
            signature=SIGNATURE, sent_at=timezone.now() - timedelta(hours=2)
        )
        now = timezone.now()

        assert AdminEmailClaim.objects.claim(SIGNATURE, now=now, window=WINDOW) is None
        assert list(AdminEmailClaim.objects.values_list("sent_at", flat=True)) == [now]

    def test_signatures_have_slots_of_their_own(self) -> None:
        now = timezone.now()
        AdminEmailClaim.objects.claim(SIGNATURE, now=now, window=WINDOW)

        taken = AdminEmailClaim.objects.claim(OTHER_SIGNATURE, now=now, window=WINDOW)

        assert taken is None

    def test_one_row_per_signature_however_often_it_is_claimed(self) -> None:
        start = timezone.now()
        for hour in range(5):
            AdminEmailClaim.objects.claim(
                SIGNATURE, now=start + timedelta(hours=hour), window=WINDOW
            )

        assert AdminEmailClaim.objects.count() == 1

    def test_other_signatures_rows_past_their_window_are_deleted(self) -> None:
        """An f-string message's one row per value doesn't pile up."""
        now = timezone.now()
        AdminEmailClaim.objects.create(
            signature=OTHER_SIGNATURE, sent_at=now - timedelta(hours=2)
        )

        AdminEmailClaim.objects.claim(SIGNATURE, now=now, window=WINDOW)

        assert list(AdminEmailClaim.objects.values_list("signature", flat=True)) == [
            SIGNATURE
        ]

    def test_other_signatures_rows_within_their_window_are_kept(self) -> None:
        now = timezone.now()
        AdminEmailClaim.objects.create(
            signature=OTHER_SIGNATURE, sent_at=now - timedelta(minutes=10)
        )

        AdminEmailClaim.objects.claim(SIGNATURE, now=now, window=WINDOW)

        assert AdminEmailClaim.objects.count() == TWO_ROWS


class TestRelease:
    def test_the_lost_emails_slot_is_given_back(self) -> None:
        now = timezone.now()
        AdminEmailClaim.objects.claim(SIGNATURE, now=now, window=WINDOW)

        AdminEmailClaim.objects.release(SIGNATURE, sent_at=now)

        assert not AdminEmailClaim.objects.exists()

    def test_a_later_claim_is_kept(self) -> None:
        """A late release never frees a slot another process took since."""
        lost_at = timezone.now() - timedelta(hours=2)
        later = timezone.now()
        AdminEmailClaim.objects.create(signature=SIGNATURE, sent_at=later)

        AdminEmailClaim.objects.release(SIGNATURE, sent_at=lost_at)

        assert AdminEmailClaim.objects.get(signature=SIGNATURE).sent_at == later
