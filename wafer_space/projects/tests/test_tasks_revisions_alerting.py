"""Precheck metadata-fetch failures are loud: ERROR, ADMINS email, recorded (#293).

In June-July 2026 every new precheck image failed its metadata fetch (the
PDK_TAG -> PDK_COMMIT change) and nobody was told for a month. These tests
pin down that each failure path now logs an ERROR that reaches ADMINS
through the rate-limited handler prod uses, and records the problem on the
PrecheckImageRevision row.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import requests
from django.core import mail
from django.core.cache import cache
from django.utils import timezone

from wafer_space.core.log import RateLimitedAdminEmailHandler
from wafer_space.projects.models import MAX_METADATA_FETCH_ATTEMPTS
from wafer_space.projects.models import PrecheckImageRevision
from wafer_space.projects.tasks_revisions import _fetch_ghcr_metadata
from wafer_space.projects.tasks_revisions import do_revision_fetch
from wafer_space.projects.tasks_revisions import revisions_needs_fetching
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.core.mail import EmailMessage

pytestmark = pytest.mark.django_db

DIGEST = "sha256:" + "b" * 64
FETCH = "wafer_space.projects.tasks_revisions._fetch_ghcr_metadata"


@pytest.fixture
def admin_mail() -> Iterator[list[EmailMessage]]:
    """Route wafer_space.* ERRORs to ADMINS email, as prod and stage LOGGING do."""
    cache.clear()
    handler = RateLimitedAdminEmailHandler()
    handler.setLevel(logging.ERROR)  # "level": "ERROR" in prod LOGGING
    app_logger = logging.getLogger("wafer_space")
    app_logger.addHandler(handler)
    yield mail.outbox
    app_logger.removeHandler(handler)
    cache.clear()


def _metadata(**overrides: object) -> dict[str, object]:
    """Metadata dict shaped like _fetch_ghcr_metadata's return value."""
    metadata: dict[str, object] = {
        "image_created_at": timezone.now(),
        "git_commit_sha": "59207bbebaf2f5e5bb5f3e9441199a71948b1fdc",
        "precheck_version": "1.7.2",
        "pdk_version": "1.0.604",
        "tool_versions": {"nix-eda": "6.24.0 @ ebee72ea7826"},
        "commit_message": "Merge pull request #46",
        "commit_date": timezone.now(),
        "problems": [],
    }
    metadata.update(overrides)
    return metadata


def _email_text(outbox: list[EmailMessage]) -> str:
    return "\n".join(f"{m.subject}\n{m.body}" for m in outbox)


def test_full_metadata_sends_no_email(admin_mail: list[EmailMessage]) -> None:
    PrecheckImageRevision.objects.create(digest=DIGEST)

    with patch(FETCH, return_value=_metadata()):
        do_revision_fetch(DIGEST)

    assert admin_mail == []


def test_unresolved_pdk_version_emails_admins(
    admin_mail: list[EmailMessage],
) -> None:
    """The July incident: the PDK version could not be determined."""
    PrecheckImageRevision.objects.create(digest=DIGEST)

    with patch(FETCH, return_value=_metadata(pdk_version="")):
        do_revision_fetch(DIGEST)

    assert len(admin_mail) == 1
    assert "pdk_version unresolved" in _email_text(admin_mail)


def test_unresolved_pdk_version_is_recorded_on_the_revision() -> None:
    revision = PrecheckImageRevision.objects.create(digest=DIGEST)

    with patch(FETCH, return_value=_metadata(pdk_version="")):
        result = do_revision_fetch(DIGEST)

    revision.refresh_from_db()
    assert (result["status"], revision.metadata_fetch_last_error) == (
        "partial",
        "pdk_version unresolved",
    )


def test_unresolved_precheck_version_emails_admins(
    admin_mail: list[EmailMessage],
) -> None:
    """A branch name such as "main" is not a precheck version (#295)."""
    revision = PrecheckImageRevision.objects.create(digest=DIGEST)

    with patch(FETCH, return_value=_metadata(precheck_version="main")):
        result = do_revision_fetch(DIGEST)

    revision.refresh_from_db()
    assert result["status"] == "partial"
    assert "precheck_version unresolved ('main')" in (
        revision.metadata_fetch_last_error
    )
    assert len(admin_mail) == 1


def test_tag_lookup_failure_is_a_problem_not_a_silent_fallback() -> None:
    labels = {
        "org.opencontainers.image.version": "main",
        "org.opencontainers.image.revision": "",
        "gf180mcu-precheck.pdk_version": "1.0.604",
    }
    with (
        patch(
            "wafer_space.projects.tasks_revisions._fetch_container_labels",
            return_value=labels,
        ),
        patch(
            "wafer_space.projects.tasks_revisions._resolve_version_from_tags",
            side_effect=requests.RequestException("tags/list returned 502"),
        ),
    ):
        metadata = _fetch_ghcr_metadata(DIGEST)

    assert metadata["problems"] == ["tag lookup failed: tags/list returned 502"]


def test_tag_lookup_failure_emails_admins_once(
    admin_mail: list[EmailMessage],
) -> None:
    """One fetch with two problems is one ERROR line, so one email."""
    revision = PrecheckImageRevision.objects.create(digest=DIGEST)
    metadata = _metadata(
        precheck_version="main",
        problems=["tag lookup failed: tags/list returned 502"],
    )

    with patch(FETCH, return_value=metadata):
        do_revision_fetch(DIGEST)

    revision.refresh_from_db()
    assert revision.metadata_fetch_last_error == (
        "tag lookup failed: tags/list returned 502; "
        "precheck_version unresolved ('main')"
    )
    assert len(admin_mail) == 1


def test_invalid_registry_data_gives_up_at_once() -> None:
    """Malformed data for an immutable digest will not fix itself."""
    revision = PrecheckImageRevision.objects.create(digest=DIGEST)

    with patch(FETCH, side_effect=ValueError("manifest has no config")):
        result = do_revision_fetch(DIGEST)

    revision.refresh_from_db()
    assert result["gave_up"] is True
    assert revision.metadata_fetch_attempts == MAX_METADATA_FETCH_ATTEMPTS
    assert revision.metadata_fetch_last_error == "manifest has no config"


def test_invalid_registry_data_emails_admins(
    admin_mail: list[EmailMessage],
) -> None:
    PrecheckImageRevision.objects.create(digest=DIGEST)

    with patch(FETCH, side_effect=ValueError("manifest has no config")):
        do_revision_fetch(DIGEST)

    assert len(admin_mail) == 1
    assert "manifest has no config" in _email_text(admin_mail)


def test_invalid_registry_data_is_not_requeued() -> None:
    ManufacturabilityCheckFactory(docker_image_digest=DIGEST)
    PrecheckImageRevision.objects.create(digest=DIGEST)
    with patch(FETCH, side_effect=ValueError("manifest has no config")):
        do_revision_fetch(DIGEST)

    with patch(
        "wafer_space.projects.tasks_revisions.do_revision_fetch.delay",
    ) as delay:
        result = revisions_needs_fetching()

    assert (result["new_revisions_queued"], delay.call_count) == (0, 0)


def test_giving_up_after_network_failures_emails_admins(
    admin_mail: list[EmailMessage],
) -> None:
    PrecheckImageRevision.objects.create(
        digest=DIGEST,
        metadata_fetch_attempts=MAX_METADATA_FETCH_ATTEMPTS - 1,
    )

    with patch(FETCH, side_effect=requests.ConnectionError("ghcr unreachable")):
        do_revision_fetch(DIGEST)

    assert len(admin_mail) == 1
    assert "ghcr unreachable" in _email_text(admin_mail)
