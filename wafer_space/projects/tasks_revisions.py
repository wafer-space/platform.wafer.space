"""Celery tasks for precheck image revision tracking."""

from __future__ import annotations

import contextlib
import http
import logging
from datetime import datetime
from typing import Any

import requests
from celery import shared_task
from django.utils import timezone

from .models import ManufacturabilityCheck
from .models import PrecheckImageRevision

logger = logging.getLogger(__name__)


@shared_task(queue="none:ro:default")
def revisions_needs_fetching() -> dict[str, int]:
    """Find revisions needing metadata fetch, queue fetch tasks.

    Discovers docker_image_digest values from ManufacturabilityCheck that
    are not yet cataloged in PrecheckImageRevision. Creates stub records
    and queues metadata fetch tasks.

    Returns:
        {"new_revisions_queued": int}
    """
    known_digests = set(PrecheckImageRevision.objects.values_list("digest", flat=True))

    new_digests = (
        ManufacturabilityCheck.objects.exclude(docker_image_digest="")
        .exclude(docker_image_digest__in=known_digests)
        .values_list("docker_image_digest", flat=True)
        .distinct()
    )

    queued = 0
    for digest in new_digests:
        PrecheckImageRevision.objects.get_or_create(digest=digest)
        do_revision_fetch.delay(digest)
        queued += 1
        logger.info("Queued metadata fetch for new revision: %s", digest[:20])

    if queued:
        logger.info("revisions_needs_fetching: queued %d new revision(s)", queued)
    else:
        logger.info("revisions_needs_fetching: no new revisions found")

    return {"new_revisions_queued": queued}


@shared_task(queue="http:ro:metadata", bind=True, max_retries=3)
def do_revision_fetch(self, digest: str) -> dict[str, Any]:
    """Fetch metadata for a revision from GHCR.

    Retrieves OCI image labels from GitHub Container Registry and
    populates PrecheckImageRevision fields.

    Args:
        digest: The SHA256 digest to fetch metadata for

    Returns:
        {"status": str, "digest": str} or {"error": str}
    """
    try:
        revision = PrecheckImageRevision.objects.get(digest=digest)
    except PrecheckImageRevision.DoesNotExist:
        return {"error": f"Revision not found: {digest}"}

    if revision.metadata_fetched_at:
        return {"status": "already_fetched", "digest": digest}

    try:
        metadata = _fetch_ghcr_metadata(digest)
    except requests.RequestException as exc:
        logger.warning("Failed to fetch metadata for %s: %s", digest[:20], exc)
        retry_countdown = 60 * (2**self.request.retries)
        raise self.retry(exc=exc, countdown=retry_countdown) from exc

    revision.image_created_at = metadata.get("image_created_at")
    revision.git_commit_sha = metadata.get("git_commit_sha", "")
    revision.precheck_version = metadata.get("precheck_version", "")
    revision.pdk_version = metadata.get("pdk_version", "")
    revision.tool_versions = metadata.get("tool_versions", {})
    revision.metadata_fetched_at = timezone.now()
    revision.save()

    logger.info("Fetched metadata for revision: %s", digest[:20])
    return {"status": "success", "digest": digest}


def _fetch_ghcr_metadata(digest: str) -> dict[str, Any]:
    """Fetch metadata from GHCR API.

    Args:
        digest: SHA256 digest of the image (can be OCI index or manifest)

    Returns:
        Dict with image_created_at, git_commit_sha, precheck_version,
        pdk_version, tool_versions, and raw labels for debugging.
    """
    # Get anonymous token
    token_resp = requests.get(
        "https://ghcr.io/token?scope=repository:wafer-space/gf180mcu-precheck:pull",
        timeout=30,
    )
    token_resp.raise_for_status()
    token = token_resp.json()["token"]

    base_url = "https://ghcr.io/v2/wafer-space/gf180mcu-precheck"

    # First try as OCI index (multi-arch image)
    index_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.oci.image.index.v1+json",
    }
    manifest_url = f"{base_url}/manifests/{digest}"
    index_resp = requests.get(manifest_url, headers=index_headers, timeout=30)

    manifest_digest = digest
    if index_resp.status_code == http.HTTPStatus.OK:
        index_data = index_resp.json()
        # If it's an index, find the amd64 manifest
        if "manifests" in index_data:
            for m in index_data["manifests"]:
                platform = m.get("platform", {})
                if platform.get("architecture") == "amd64":
                    manifest_digest = m["digest"]
                    break

    # Get the actual manifest
    manifest_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.oci.image.manifest.v1+json",
    }
    manifest_resp = requests.get(
        f"{base_url}/manifests/{manifest_digest}", headers=manifest_headers, timeout=30
    )
    manifest_resp.raise_for_status()
    manifest = manifest_resp.json()

    # Get config blob containing labels
    config_digest = manifest.get("config", {}).get("digest")
    if not config_digest:
        return {}

    blob_url = f"{base_url}/blobs/{config_digest}"
    blob_resp = requests.get(blob_url, headers=manifest_headers, timeout=30)
    blob_resp.raise_for_status()
    config = blob_resp.json()

    labels = config.get("config", {}).get("Labels", {})

    # Parse timestamp
    created_str = labels.get("org.opencontainers.image.created")
    image_created_at = None
    if created_str:
        with contextlib.suppress(ValueError):
            image_created_at = datetime.fromisoformat(
                created_str.replace("Z", "+00:00")
            )

    # Extract tool versions from custom labels (if present)
    # Expected format: gf180mcu-precheck.tools.{toolname} = version
    tool_versions: dict[str, str] = {}
    for key, value in labels.items():
        if key.startswith("gf180mcu-precheck.tools."):
            tool_name = key.replace("gf180mcu-precheck.tools.", "")
            tool_versions[tool_name] = value

    return {
        "image_created_at": image_created_at,
        "git_commit_sha": labels.get("org.opencontainers.image.revision", ""),
        "precheck_version": labels.get("org.opencontainers.image.version", ""),
        "pdk_version": labels.get("gf180mcu-precheck.pdk_version", ""),
        "tool_versions": tool_versions,
        "labels": labels,  # Raw labels for debugging
    }
