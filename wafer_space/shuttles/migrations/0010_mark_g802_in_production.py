# Data migration marking G802 as sent to manufacturing.
#
# GDS for GF180MCU Run #2 was delivered to GlobalFoundries on 24 Jul 2026
# (the shuttle's production_start_date), so the run is now in production
# and no longer accepts submissions. New projects target G803 (Run #3).

import logging
from typing import ClassVar

from django.db import migrations

logger = logging.getLogger(__name__)


def mark_g802_in_production(apps, _schema_editor):
    """Set G802's status to "production" (In Production).

    Update-only: shuttles are never created here. G802 exists in the
    deployed databases but not in test databases, where creating it would
    collide with ShuttleFactory's G8XX name sequence (see 0009).
    """
    Shuttle = apps.get_model("shuttles", "Shuttle")

    updated = Shuttle.objects.filter(name="G802").update(status="production")
    logger.info("Marked %d G802 shuttle(s) as In Production", updated)


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("shuttles", "0009_update_g801_g802_schedule"),
    ]

    operations: ClassVar[list[migrations.RunPython]] = [
        migrations.RunPython(mark_g802_in_production, migrations.RunPython.noop),
    ]
