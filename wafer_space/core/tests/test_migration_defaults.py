"""A new NOT NULL column needs a database default (issue #433).

A deploy runs migrate first, then restarts the services one at a time, so
for minutes workers run the old code against the new schema. The old code
doesn't know a new column, so its INSERT leaves it out. Without a database
default PostgreSQL puts NULL there and a NOT NULL column refuses it: on
16 Oct 2026 an old do_analyzing failed that way on
projects_historicalproject.submission_override_reason (migration 0062).

Django's AddField uses a field's default only to fill the existing rows,
then drops it, so a NOT NULL column needs db_default to keep one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.db import migrations
from django.db import models
from django.db.migrations.loader import MigrationLoader
from django.db.models.fields import NOT_PROVIDED

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.db.migrations import Migration
    from django.db.migrations.operations.base import Operation

# Each app's newest migration when this check was added. They and every
# migration before them are exempt: 61 columns were added that way, and the
# rows those migrations added are long since in place. The three columns
# that broke a deploy got a database default in projects 0063.
CHECKED_AFTER = {
    "coupons": "0001_initial",
    "legal": "0002_remove_content_field_use_markdown",
    "notifications": "0001_initial",
    "projects": "0062_submission_override",
    "referrals": "0001_initial",
    "shuttles": "0014_drop_non_gds_shuttle_dates",
    "sites": "0004_alter_options_ordering_domain",
    "users": "0002_remove_linkedin_oauth2_socialapp",
}
OUR_MIGRATIONS = "wafer_space."


def columns_without_a_database_default(migration: Migration) -> list[str]:
    """The NOT NULL columns ``migration`` adds with no db_default."""
    return [
        f"{operation.model_name}.{operation.name}"
        for operation in migration.operations
        if isinstance(operation, migrations.AddField)
        and not operation.field.null
        and not operation.field.many_to_many
        and operation.field.db_default is NOT_PROVIDED
    ]


def migrations_to_check(loader: MigrationLoader) -> Iterable[Migration]:
    """Our migrations that come after CHECKED_AFTER, in any app."""
    exempt: set[tuple[str, str]] = set()
    for app, name in CHECKED_AFTER.items():
        exempt.update(loader.graph.forwards_plan((app, name)))
    for key, migration in loader.disk_migrations.items():
        if migration.__module__.startswith(OUR_MIGRATIONS) and key not in exempt:
            yield migration


def a_migration(*operations: Operation) -> Migration:
    """A migration holding ``operations``, as a migration file declares them."""
    example = type("Migration", (migrations.Migration,), {"operations": operations})
    return example("0999_example", "projects")


class TestNewMigrations:
    def test_no_new_not_null_column_lacks_a_database_default(self) -> None:
        loader = MigrationLoader(None, ignore_no_migrations=True)

        offending = {
            f"{migration.app_label}.{migration.name}": columns
            for migration in migrations_to_check(loader)
            if (columns := columns_without_a_database_default(migration))
        }

        assert offending == {}, (
            "Give each column db_default (e.g. TextField(blank=True, "
            'default="", db_default="")): during a deploy, workers still on '
            "the old code insert rows without it (issue #433)."
        )

    def test_every_app_with_migrations_has_a_starting_point(self) -> None:
        """A new app's migrations are checked from its first one."""
        loader = MigrationLoader(None, ignore_no_migrations=True)
        apps = {
            app
            for (app, _name), migration in loader.disk_migrations.items()
            if migration.__module__.startswith(OUR_MIGRATIONS)
        }

        assert apps <= set(CHECKED_AFTER)

    def test_the_fix_for_0062_is_checked(self) -> None:
        loader = MigrationLoader(None, ignore_no_migrations=True)

        names = {migration.name for migration in migrations_to_check(loader)}

        assert "0063_db_default_for_rolling_restarts" in names


class TestWhatTheCheckFlags:
    def test_a_not_null_column_with_only_a_default(self) -> None:
        """0062's case: default="" fills existing rows, then is dropped."""
        migration = a_migration(
            migrations.AddField(
                "project", "reason", models.TextField(blank=True, default="")
            )
        )

        assert columns_without_a_database_default(migration) == ["project.reason"]

    @pytest.mark.parametrize(
        "field",
        [
            models.TextField(blank=True, default="", db_default=""),
            models.TextField(null=True, blank=True),
            models.ManyToManyField("users.User"),
        ],
        ids=["db_default", "nullable", "many_to_many"],
    )
    def test_columns_old_code_can_leave_out(self, field: models.Field) -> None:
        migration = a_migration(migrations.AddField("project", "extra", field))

        assert columns_without_a_database_default(migration) == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("projects_project", "submission_override_reason"),
        ("projects_historicalproject", "submission_override_reason"),
        ("projects_projectaccesslog", "details"),
    ],
)
def test_0062s_columns_have_a_database_default(table: str, column: str) -> None:
    """An INSERT from older code that leaves them out now gets ''."""
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table)

    defaults = {info.name: info.default for info in description}
    assert defaults[column] == "''"
