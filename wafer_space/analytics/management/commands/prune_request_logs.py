"""Delete request log rows older than a given age (#379).

Nothing schedules this: rows are kept indefinitely until a retention limit
is decided. See docs/request_analytics.md.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser
from django.utils import timezone

from wafer_space.analytics.models import RequestLog

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Delete request log rows older than --older-than DAYS."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--older-than",
            type=int,
            required=True,
            metavar="DAYS",
            help="Delete rows created more than DAYS days ago.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        days: int = options["older_than"]
        if days < 1:
            # 0 or less puts the cutoff at or after now: every row would go.
            msg = f"--older-than must be at least 1 day, not {days}"
            raise CommandError(msg)
        cutoff = timezone.now() - datetime.timedelta(days=days)
        deleted, _ = RequestLog.objects.filter(created_at__lt=cutoff).delete()
        logger.info("Deleted %d request log rows older than %d days", deleted, days)
        self.stdout.write(f"Deleted {deleted} request log rows older than {days} days")
