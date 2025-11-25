# Generated manually - data migration to link existing checks to project files

from django.db import migrations


def populate_project_file(apps, schema_editor):
    """Link existing ManufacturabilityCheck records to their project's active file.

    Only links checks to files that aren't already assigned to another check.
    """
    ManufacturabilityCheck = apps.get_model("projects", "ManufacturabilityCheck")
    ProjectFile = apps.get_model("projects", "ProjectFile")

    # Get unique project IDs that have checks without project_file
    project_ids = (
        ManufacturabilityCheck.objects.filter(project_file__isnull=True)
        .values_list("project_id", flat=True)
        .distinct()
    )

    for project_id in project_ids:
        # Find the active file for this project
        active_file = ProjectFile.objects.filter(
            project_id=project_id,
            is_active=True,
        ).first()

        if not active_file:
            continue

        # Check if active file already has a check assigned
        existing_check = ManufacturabilityCheck.objects.filter(
            project_file=active_file
        ).exists()
        if existing_check:
            # File already has a check, skip
            continue

        # Get only the most recent check for this project (by started_at or id)
        most_recent_check = (
            ManufacturabilityCheck.objects.filter(
                project_id=project_id,
                project_file__isnull=True,
            )
            .order_by("-started_at", "-id")
            .first()
        )

        if most_recent_check:
            most_recent_check.project_file = active_file
            most_recent_check.save(update_fields=["project_file"])


def reverse_populate(apps, schema_editor):
    """Reverse: clear project_file on all checks."""
    ManufacturabilityCheck = apps.get_model("projects", "ManufacturabilityCheck")
    ManufacturabilityCheck.objects.update(project_file=None)


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0018_manufacturabilitycheck_project_file_and_more"),
    ]

    operations = [
        migrations.RunPython(populate_project_file, reverse_populate),
    ]
