"""The precheck version behind each verdict on the projects list (#235).

Each verdict on the list (Manufacturable, Not manufacturable, Submitted)
says which precheck version gave it, and whether that is the latest one:
the digest of the most recently started check, as on the check pages.
"""

from __future__ import annotations

from datetime import timedelta
from html.parser import HTMLParser
from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import PrecheckImageRevision
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.users.tests.factories import UserFactory

from .factories import ManufacturabilityCheckFactory
from .factories import ProjectFactory
from .factories import make_downloaded_file

if TYPE_CHECKING:
    from django.test import Client

    from wafer_space.users.models import User

pytestmark = pytest.mark.django_db

OLD = "sha256:" + "a" * 64
NEW = "sha256:" + "b" * 64
FINISHED = ManufacturabilityCheck.Status.FINISHED


class _VersionLines(HTMLParser):
    """(row pk, version key, text) for each precheck version line."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[tuple[str, str, str]] = []
        self._row = ""
        self._in_line = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if "data-project-row" in found:
            self._row = found["data-project-row"] or ""
        if "data-precheck-version" in found:
            key = found["data-precheck-version"] or ""
            self.lines.append((self._row, key, ""))
            self._in_line = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "small":
            self._in_line = False

    def handle_data(self, data: str) -> None:
        if self._in_line:
            row, key, text = self.lines[-1]
            self.lines[-1] = (row, key, " ".join(f"{text} {data}".split()))


def version_lines(client: Client, user: User, project: Project) -> list[tuple]:
    """(version key, text) of each version line in ``project``'s row."""
    client.force_login(user)
    parser = _VersionLines()
    parser.feed(client.get(reverse("projects:list")).content.decode())
    return [(key, text) for row, key, text in parser.lines if row == str(project.pk)]


def checked_revision(project: Project, digest: str, *, verdict: bool) -> ProjectFile:
    """A new active revision of ``project`` with one finished check."""
    project.files.update(is_active=False)
    revision = make_downloaded_file(project)
    ManufacturabilityCheckFactory(
        project=project,
        project_file=revision,
        status=FINISHED,
        is_manufacturable=verdict,
        docker_image_digest=digest,
        container_started_at=timezone.now(),
    )
    return revision


def newer_check_elsewhere(digest: str) -> None:
    """A check of another project, started last, that sets the latest digest."""
    ManufacturabilityCheckFactory(
        status=FINISHED,
        is_manufacturable=True,
        docker_image_digest=digest,
        container_started_at=timezone.now() + timedelta(minutes=5),
    )


def test_latest_version_is_marked_latest(client: Client) -> None:
    user = UserFactory()
    project = ProjectFactory(user=user)
    PrecheckImageRevision.objects.create(digest=NEW, precheck_version="1.6.0")
    checked_revision(project, NEW, verdict=True)

    assert version_lines(client, user, project) == [("latest", "precheck 1.6.0")]


def test_older_version_is_marked_outdated(client: Client) -> None:
    user = UserFactory()
    project = ProjectFactory(user=user)
    PrecheckImageRevision.objects.create(digest=OLD, precheck_version="1.5.2")
    checked_revision(project, OLD, verdict=False)
    newer_check_elsewhere(NEW)

    assert version_lines(client, user, project) == [("outdated", "precheck 1.5.2")]


def test_uncatalogued_digest_shows_the_short_digest(client: Client) -> None:
    """As on the check pages, when no PrecheckImageRevision describes it."""
    user = UserFactory()
    project = ProjectFactory(user=user)
    checked_revision(project, NEW, verdict=True)

    assert version_lines(client, user, project) == [
        ("latest", "precheck sha256:bbbbbbbbbbbb..."),
    ]


def test_commit_sha_when_no_version_is_catalogued(client: Client) -> None:
    user = UserFactory()
    project = ProjectFactory(user=user)
    PrecheckImageRevision.objects.create(digest=NEW, git_commit_sha="0123456789ab")
    checked_revision(project, NEW, verdict=True)

    assert version_lines(client, user, project) == [("latest", "precheck 0123456")]


def test_check_without_a_digest_shows_no_version(client: Client) -> None:
    user = UserFactory()
    project = ProjectFactory(user=user)
    checked_revision(project, "", verdict=True)

    assert version_lines(client, user, project) == []


def test_unfinished_check_shows_no_version(client: Client) -> None:
    """Only a verdict has a version; Checking has none yet."""
    user = UserFactory()
    project = ProjectFactory(user=user)
    revision = make_downloaded_file(project)
    ManufacturabilityCheckFactory(
        project=project,
        project_file=revision,
        status=ManufacturabilityCheck.Status.RUNNING,
        docker_image_digest=NEW,
        container_started_at=timezone.now(),
    )

    assert version_lines(client, user, project) == []


def test_submitted_and_newer_revision_each_show_their_own(client: Client) -> None:
    """Each line names the revision it describes (CLAUDE.md, #354)."""
    user = UserFactory()
    project = ProjectFactory(user=user)
    project.submitted_file = checked_revision(project, OLD, verdict=True)
    project.save()
    checked_revision(project, NEW, verdict=True)

    assert version_lines(client, user, project) == [
        ("outdated", "precheck sha256:aaaaaaaaaaaa..."),
        ("latest", "precheck sha256:bbbbbbbbbbbb..."),
    ]


def test_query_count_does_not_grow_with_versions(client: Client) -> None:
    """Versions are annotated: no query per row or per digest."""
    user = UserFactory()
    client.force_login(user)

    def list_queries() -> int:
        with CaptureQueriesContext(connection) as queries:
            client.get(reverse("projects:list"))
        return len(queries)

    checked_revision(ProjectFactory(user=user), OLD, verdict=True)
    one_project = list_queries()
    for n in range(6):
        digest = f"sha256:{n:064d}"
        PrecheckImageRevision.objects.create(digest=digest, precheck_version=f"1.{n}")
        checked_revision(ProjectFactory(user=user), digest, verdict=True)

    assert list_queries() == one_project
