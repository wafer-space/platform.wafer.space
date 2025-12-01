"""Add created_at field to ManufacturabilityCheck."""

import django.utils.timezone
from django.db import migrations
from django.db import models


class Migration(migrations.Migration):
    """Add created_at timestamp to ManufacturabilityCheck."""

    dependencies = [
        ("projects", "0036_migrate_status_values"),
    ]

    operations = [
        migrations.AddField(
            model_name="manufacturabilitycheck",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
                help_text="When this check record was created",
            ),
            preserve_default=False,
        ),
    ]
