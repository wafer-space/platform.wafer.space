# Data migration linking past shuttle runs to their wafer.space run pages
# (issue #350; Tim, 11 Oct 2026: "The platform should also show past
# shuttles as closed and link to https://wafer.space/ws-run1/ and
# https://wafer.space/ws-run2/"). Run 3 has no page yet (404 on 11 Oct 2026).

import logging
from typing import ClassVar

from django.db import migrations

logger = logging.getLogger(__name__)

RUN_PAGES = {
    "G801": "https://wafer.space/ws-run1/",
    "G802": "https://wafer.space/ws-run2/",
}


def set_run_page_urls(apps, _schema_editor):
    """Set the run-page URL on G801/G802.

    Update-only: shuttles are never created here. G802 exists in the
    deployed databases but not in test databases, where creating it would
    collide with ShuttleFactory's G8XX name sequence (see 0009).
    """
    Shuttle = apps.get_model("shuttles", "Shuttle")
    for name, url in RUN_PAGES.items():
        updated = Shuttle.objects.filter(name=name).update(website_url=url)
        logger.info("Set run page URL on %d %s shuttle(s)", updated, name)


class Migration(migrations.Migration):

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("shuttles", "0011_shuttle_website_url"),
    ]

    operations: ClassVar[list[migrations.RunPython]] = [
        migrations.RunPython(set_run_page_urls, migrations.RunPython.noop),
    ]
