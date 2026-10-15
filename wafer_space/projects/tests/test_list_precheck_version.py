"""The precheck version behind each verdict on the projects list (#235).

Each verdict on the list (Manufacturable, Not manufacturable, Submitted)
says which precheck version gave it, and whether that is the latest one:
the digest of the most recently started check, as on the check pages.
"""

from __future__ import annotations

import re
from datetime import timedelta
from html.parser import HTMLParser
from http import HTTPStatus
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
SHORT_NEW = "sha256:bbbbbbbbbbbb..."
IMAGE_LINE = re.compile(r"<small[^>]*data-precheck-image[^>]*><code>([^<]*)</code>")
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


def checked_revision(
    project: Project, digest: str, *, verdict: bool, stamped: str = ""
) -> ProjectFile:
    """A new active revision of ``project`` with one finished check.

    ``stamped`` is the precheck version do_analyzing stamped on the check.
    """
    project.files.update(is_active=False)
    revision = make_downloaded_file(project)
    ManufacturabilityCheckFactory(
        project=project,
        project_file=revision,
        status=FINISHED,
        is_manufacturable=verdict,
        docker_image_digest=digest,
        precheck_version=stamped,
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

    assert version_lines(client, user, project) == [
        ("latest", "precheck 1.6.0 (latest)"),
    ]


def test_older_version_is_marked_outdated(client: Client) -> None:
    user = UserFactory()
    project = ProjectFactory(user=user)
    PrecheckImageRevision.objects.create(digest=OLD, precheck_version="1.5.2")
    checked_revision(project, OLD, verdict=False)
    newer_check_elsewhere(NEW)

    assert version_lines(client, user, project) == [
        ("outdated", "precheck 1.5.2 (older version)"),
    ]


def test_catalog_version_comes_before_the_stamped_one(client: Client) -> None:
    """Rule 1 of #421: the catalog's version, whatever the check stamped."""
    user = UserFactory()
    project = ProjectFactory(user=user)
    PrecheckImageRevision.objects.create(digest=NEW, precheck_version="1.6.0")
    checked_revision(project, NEW, verdict=True, stamped="1.5.9")

    assert version_lines(client, user, project) == [
        ("latest", "precheck 1.6.0 (latest)"),
    ]


@pytest.mark.parametrize("catalogued", [False, True])
def test_stamped_version_when_the_catalog_has_none(
    client: Client, *, catalogued: bool
) -> None:
    """Rule 2 of #421: the check's own stamped version, before any commit."""
    user = UserFactory()
    project = ProjectFactory(user=user)
    if catalogued:
        PrecheckImageRevision.objects.create(digest=NEW, git_commit_sha="0123456789ab")
    checked_revision(project, NEW, verdict=True, stamped="1.5.2")

    assert version_lines(client, user, project) == [
        ("latest", "precheck 1.5.2 (latest)"),
    ]


def test_uncatalogued_image_is_version_not_yet_known(client: Client) -> None:
    """Rule 4 of #421: no raw digest as the version (the fetch is to come)."""
    user = UserFactory()
    project = ProjectFactory(user=user)
    checked_revision(project, NEW, verdict=True)

    assert version_lines(client, user, project) == [
        ("latest", "precheck version not yet known (latest)"),
    ]


def test_catalog_row_without_metadata_is_version_not_yet_known(
    client: Client,
) -> None:
    """A catalogued image whose metadata fetch has not succeeded yet."""
    user = UserFactory()
    project = ProjectFactory(user=user)
    PrecheckImageRevision.objects.create(digest=NEW)
    checked_revision(project, NEW, verdict=True)

    assert version_lines(client, user, project) == [
        ("latest", "precheck version not yet known (latest)"),
    ]


def test_version_not_yet_known_names_the_image_in_its_title(client: Client) -> None:
    user = UserFactory()
    project = ProjectFactory(user=user)
    checked_revision(project, NEW, verdict=True)
    client.force_login(user)

    content = client.get(reverse("projects:list")).content.decode()

    assert f'its version is not known yet: image {NEW}"' in content


def image_lines(client: Client, user: User) -> list[str]:
    """The staff-only digest lines on the list, as shown."""
    client.force_login(user)
    content = client.get(reverse("projects:list")).content.decode()
    return IMAGE_LINE.findall(content)


@pytest.mark.parametrize(("viewer", "shown"), [("owner", []), ("staff", [SHORT_NEW])])
def test_only_staff_see_the_digest_line(
    client: Client, viewer: str, shown: list[str]
) -> None:
    """Rule 4 of #421: owners have the digest only in the title."""
    owner = UserFactory()
    checked_revision(ProjectFactory(user=owner), NEW, verdict=True)
    user = owner if viewer == "owner" else UserFactory(is_staff=True)

    assert image_lines(client, user) == shown


def test_no_digest_line_when_the_version_is_known(client: Client) -> None:
    PrecheckImageRevision.objects.create(digest=NEW, precheck_version="1.6.0")
    checked_revision(ProjectFactory(), NEW, verdict=True)

    assert image_lines(client, UserFactory(is_staff=True)) == []


def test_commit_sha_when_no_version_is_catalogued(client: Client) -> None:
    user = UserFactory()
    project = ProjectFactory(user=user)
    PrecheckImageRevision.objects.create(digest=NEW, git_commit_sha="0123456789ab")
    checked_revision(project, NEW, verdict=True)

    assert version_lines(client, user, project) == [
        ("latest", "precheck 0123456 (latest)"),
    ]


def test_latest_unknown_when_no_check_has_started(client: Client) -> None:
    """A digest without any started check (a duplicated check, say)."""
    user = UserFactory()
    project = ProjectFactory(user=user)
    revision = checked_revision(project, NEW, verdict=True)
    revision.manufacturability_checks.update(container_started_at=None)

    assert version_lines(client, user, project) == [
        ("unknown", "precheck version not yet known (latest version unknown)"),
    ]


def test_check_without_a_digest_shows_image_not_recorded(client: Client) -> None:
    """Rule 6 of #421: checks before 16 Nov 2025 recorded no digest."""
    user = UserFactory()
    project = ProjectFactory(user=user)
    checked_revision(project, "", verdict=True)

    assert version_lines(client, user, project) == [
        ("unrecorded", "precheck image not recorded (version unknown)"),
    ]


def test_newer_revision_without_a_digest_shows_image_not_recorded(
    client: Client,
) -> None:
    """Rule 6 of #421 under the newer-revision line too."""
    user = UserFactory()
    project = ProjectFactory(user=user)
    PrecheckImageRevision.objects.create(digest=NEW, precheck_version="1.6.0")
    project.submitted_file = checked_revision(project, NEW, verdict=True)
    project.save()
    checked_revision(project, "", verdict=True)

    assert version_lines(client, user, project) == [
        ("latest", "precheck 1.6.0 (latest)"),
        ("unrecorded", "precheck image not recorded (version unknown)"),
    ]


def test_unknown_digest_never_becomes_the_latest(client: Client) -> None:
    """A newest check that stored "unknown" leaves real images latest (#421)."""
    user = UserFactory()
    project = ProjectFactory(user=user)
    PrecheckImageRevision.objects.create(digest=NEW, precheck_version="1.6.0")
    checked_revision(project, NEW, verdict=True)
    newer_check_elsewhere("unknown")

    assert version_lines(client, user, project) == [
        ("latest", "precheck 1.6.0 (latest)"),
    ]


@pytest.mark.parametrize("viewer", ["owner", "staff"])
def test_unknown_digest_does_not_break_the_list(client: Client, viewer: str) -> None:
    """do_dispatching stores "unknown" when a pulled image has no RepoDigests.

    That digest reached PrecheckImageRevision.short_digest, whose assert
    failed and made the whole list a 500 (#421).
    """
    owner = UserFactory()
    project = ProjectFactory(user=owner)
    checked_revision(project, "unknown", verdict=True)
    user = owner if viewer == "owner" else UserFactory(is_staff=True)
    client.force_login(user)

    response = client.get(reverse("projects:list"))

    assert response.status_code == HTTPStatus.OK
    assert version_lines(client, user, project) == [
        ("unrecorded", "precheck image not recorded (version unknown)"),
    ]


def test_unknown_digest_with_its_catalog_stub(client: Client) -> None:
    """revisions_needs_fetching catalogues "unknown" too, with no version."""
    user = UserFactory()
    project = ProjectFactory(user=user)
    PrecheckImageRevision.objects.create(digest="unknown")
    checked_revision(project, "unknown", verdict=True)

    assert version_lines(client, user, project) == [
        ("unrecorded", "precheck image not recorded (version unknown)"),
    ]


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
        ("outdated", "precheck version not yet known (older version)"),
        ("latest", "precheck version not yet known (latest)"),
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
