# Generated manually for clean slate restructure
# Implements DownloadAttempt model and updates FK relationships

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0013_projectfile_processed_filename_and_more"),
    ]

    operations = [
        # CLEAN SLATE STRATEGY: Drop old tables to eliminate legacy data
        # This is acceptable during active development (no production data)
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS projects_projectfilechunk CASCADE;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS projects_fileprocessingerror CASCADE;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Create new DownloadAttempt model
        migrations.CreateModel(
            name="DownloadAttempt",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "attempt_number",
                    models.IntegerField(
                        help_text="Sequential attempt number (1, 2, 3...)",
                    ),
                ),
                (
                    "started_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="When this attempt was created",
                    ),
                ),
                (
                    "completed_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When this attempt finished (success or failure)",
                        null=True,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("downloading", "Downloading"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                        ],
                        default="pending",
                        help_text="Current status of this download attempt",
                        max_length=20,
                    ),
                ),
                (
                    "download_started_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When download actually started (after task setup)",
                        null=True,
                    ),
                ),
                (
                    "download_completed_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="When download finished (success or failure)",
                        null=True,
                    ),
                ),
                (
                    "download_error",
                    models.TextField(
                        blank=True,
                        help_text="Error message if download failed",
                    ),
                ),
                (
                    "download_duration_seconds",
                    models.FloatField(
                        blank=True,
                        help_text="Total download duration in seconds",
                        null=True,
                    ),
                ),
                (
                    "bytes_downloaded",
                    models.BigIntegerField(
                        default=0,
                        help_text="Total bytes downloaded in this attempt",
                    ),
                ),
                (
                    "last_activity",
                    models.DateTimeField(
                        auto_now=True,
                        help_text="Last update to this attempt (for staleness detection)",
                    ),
                ),
                (
                    "project_file",
                    models.ForeignKey(
                        help_text="The file this download attempt belongs to",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="download_attempts",
                        to="projects.projectfile",
                    ),
                ),
            ],
            options={
                "ordering": ["-attempt_number"],
                "indexes": [
                    models.Index(
                        fields=["project_file", "-attempt_number"],
                        name="projects_do_project_1b0e8d_idx",
                    ),
                    models.Index(
                        fields=["status"],
                        name="projects_do_status_5f4c9a_idx",
                    ),
                    models.Index(
                        fields=["last_activity"],
                        name="projects_do_last_ac_8a3d2e_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=["project_file", "attempt_number"],
                        name="unique_attempt_per_file",
                    ),
                ],
            },
        ),
        # Recreate ProjectFileChunk with FK to DownloadAttempt
        migrations.CreateModel(
            name="ProjectFileChunk",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "timestamp",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="When this checkpoint was recorded",
                    ),
                ),
                (
                    "bytes_downloaded",
                    models.BigIntegerField(
                        help_text="Cumulative bytes downloaded at this checkpoint",
                    ),
                ),
                (
                    "chunk_number",
                    models.IntegerField(
                        help_text="Sequential chunk number for ordering",
                    ),
                ),
                (
                    "download_attempt",
                    models.ForeignKey(
                        help_text="The download attempt this checkpoint belongs to",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunks",
                        to="projects.downloadattempt",
                    ),
                ),
            ],
            options={
                "ordering": ["chunk_number"],
                "indexes": [
                    models.Index(
                        fields=["download_attempt", "chunk_number"],
                        name="projects_pr_downloa_4f8e3a_idx",
                    ),
                    models.Index(
                        fields=["download_attempt", "timestamp"],
                        name="projects_pr_downloa_9c2d1b_idx",
                    ),
                ],
            },
        ),
        # Recreate FileProcessingError with FK to DownloadAttempt
        migrations.CreateModel(
            name="FileProcessingError",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "error_type",
                    models.CharField(
                        choices=[
                            ("download", "Download Error"),
                            ("extraction", "Extraction Error"),
                            ("validation", "Validation Error"),
                            ("pipeline", "Pipeline Error"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "error_message",
                    models.TextField(help_text="User-friendly error message"),
                ),
                (
                    "error_detail",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Technical details: stack trace, context, etc. (superuser only)",
                    ),
                ),
                (
                    "occurred_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "download_attempt",
                    models.ForeignKey(
                        help_text="The download attempt this error belongs to",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="errors",
                        to="projects.downloadattempt",
                    ),
                ),
            ],
            options={
                "ordering": ["-occurred_at"],
                "indexes": [
                    models.Index(
                        fields=["download_attempt", "-occurred_at"],
                        name="projects_fi_downloa_7a6f2c_idx",
                    ),
                    models.Index(
                        fields=["error_type", "-occurred_at"],
                        name="projects_fi_error_t_4ec9f5_idx",
                    ),
                ],
            },
        ),
    ]
