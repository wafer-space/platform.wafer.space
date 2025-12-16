"""Celery tasks for precheck image revision tracking."""

from __future__ import annotations

import contextlib
import http
import logging
import re
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
    except ValueError as exc:
        logger.exception("Validation error for %s", digest[:20])
        return {"error": str(exc), "digest": digest}

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
    """Fetch metadata from GHCR API and GitHub.

    Args:
        digest: SHA256 digest of the image (can be OCI index or manifest)

    Returns:
        Dict with image_created_at, git_commit_sha, precheck_version,
        pdk_version, tool_versions, commit info, and raw labels.

    Raises:
        ValueError: If required fields (pdk_version) cannot be determined.
    """
    labels = _fetch_container_labels(digest)
    result = _parse_container_labels(labels)

    # Fetch additional info from GitHub
    git_commit_sha = result["git_commit_sha"]
    if git_commit_sha:
        github_info = _fetch_github_info(git_commit_sha)
        result["commit_message"] = github_info.get("commit_message", "")
        result["commit_date"] = github_info.get("commit_date")
        if not result["pdk_version"]:
            result["pdk_version"] = github_info.get("pdk_version", "")
        if not result["tool_versions"]:
            result["tool_versions"] = github_info.get("tool_versions", {})

    # Validate required fields
    if not result["pdk_version"]:
        msg = f"Could not determine PDK version for digest {digest[:20]}"
        raise ValueError(msg)

    return result


def _fetch_container_labels(digest: str) -> dict[str, str]:
    """Fetch container labels from GHCR.

    Args:
        digest: SHA256 digest (can be OCI index or manifest)

    Returns:
        Dict of container labels
    """
    # Get anonymous token
    token_resp = requests.get(
        "https://ghcr.io/token?scope=repository:wafer-space/gf180mcu-precheck:pull",
        timeout=30,
    )
    token_resp.raise_for_status()
    token = token_resp.json()["token"]

    base_url = "https://ghcr.io/v2/wafer-space/gf180mcu-precheck"
    manifest_digest = _resolve_manifest_digest(base_url, token, digest)

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

    return config.get("config", {}).get("Labels", {})


def _resolve_manifest_digest(base_url: str, token: str, digest: str) -> str:
    """Resolve OCI index to amd64 manifest digest if needed.

    Args:
        base_url: GHCR base URL
        token: Bearer token
        digest: Original digest (may be OCI index)

    Returns:
        Manifest digest for amd64 architecture
    """
    index_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.oci.image.index.v1+json",
    }
    index_resp = requests.get(
        f"{base_url}/manifests/{digest}", headers=index_headers, timeout=30
    )

    if index_resp.status_code == http.HTTPStatus.OK:
        index_data = index_resp.json()
        if "manifests" in index_data:
            for m in index_data["manifests"]:
                platform = m.get("platform", {})
                if platform.get("architecture") == "amd64":
                    return m["digest"]

    return digest


def _parse_container_labels(labels: dict[str, str]) -> dict[str, Any]:
    """Parse container labels into metadata dict.

    Args:
        labels: Raw container labels

    Returns:
        Parsed metadata dict
    """
    # Parse timestamp
    created_str = labels.get("org.opencontainers.image.created")
    image_created_at = None
    if created_str:
        with contextlib.suppress(ValueError):
            image_created_at = datetime.fromisoformat(
                created_str.replace("Z", "+00:00")
            )

    # Extract tool versions from custom labels
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
        "commit_message": "",
        "commit_date": None,
        "labels": labels,
    }


GITHUB_REPO = "wafer-space/gf180mcu-precheck"


def _fetch_github_info(commit_sha: str) -> dict[str, Any]:
    """Fetch commit info and version data from GitHub.

    Args:
        commit_sha: Git commit SHA to fetch info for

    Returns:
        Dict with commit_message, commit_date, pdk_version, tool_versions
    """
    result: dict[str, Any] = {}

    # Fetch commit info
    commit_url = f"https://api.github.com/repos/{GITHUB_REPO}/commits/{commit_sha}"
    try:
        commit_resp = requests.get(commit_url, timeout=30)
        if commit_resp.status_code == http.HTTPStatus.OK:
            commit_data = commit_resp.json()
            result["commit_message"] = (
                commit_data.get("commit", {}).get("message", "").split("\n")[0]
            )
            commit_date_str = (
                commit_data.get("commit", {}).get("committer", {}).get("date")
            )
            if commit_date_str:
                with contextlib.suppress(ValueError):
                    result["commit_date"] = datetime.fromisoformat(
                        commit_date_str.replace("Z", "+00:00")
                    )
    except requests.RequestException:
        logger.warning("Failed to fetch commit info for %s", commit_sha[:12])

    # Fetch flake.lock for version info
    flake_lock_url = (
        f"https://raw.githubusercontent.com/{GITHUB_REPO}/{commit_sha}/flake.lock"
    )
    try:
        flake_resp = requests.get(flake_lock_url, timeout=30)
        if flake_resp.status_code == http.HTTPStatus.OK:
            flake_data = flake_resp.json()
            tool_versions = _parse_flake_lock(flake_data)
            if tool_versions:
                result["tool_versions"] = tool_versions
    except (requests.RequestException, ValueError):
        logger.warning("Failed to fetch flake.lock for %s", commit_sha[:12])

    # Fetch Makefile for PDK version
    makefile_url = (
        f"https://raw.githubusercontent.com/{GITHUB_REPO}/{commit_sha}/Makefile"
    )
    try:
        makefile_resp = requests.get(makefile_url, timeout=30)
        if makefile_resp.status_code == http.HTTPStatus.OK:
            pdk_version = _parse_makefile_pdk_version(makefile_resp.text)
            if pdk_version:
                result["pdk_version"] = pdk_version
    except requests.RequestException:
        logger.warning("Failed to fetch Makefile for %s", commit_sha[:12])

    return result


def _parse_flake_lock(flake_data: dict[str, Any]) -> dict[str, str]:
    """Parse flake.lock to extract version info.

    Args:
        flake_data: Parsed flake.lock JSON

    Returns:
        Dict mapping tool/input names to versions
    """
    versions: dict[str, str] = {}
    nodes = flake_data.get("nodes", {})

    for name, node in nodes.items():
        if name == "root":
            continue

        locked = node.get("locked", {})
        original = node.get("original", {})

        if locked.get("type") == "github":
            # Use ref (tag/branch) if available, otherwise short rev
            ref = locked.get("ref") or original.get("ref", "")
            if ref:
                versions[name] = ref
            elif locked.get("rev"):
                versions[name] = locked["rev"][:12]

    return versions


def _parse_makefile_pdk_version(makefile_content: str) -> str:
    """Parse Makefile to extract PDK_TAG version.

    Args:
        makefile_content: Raw Makefile text

    Returns:
        PDK version string or empty string if not found
    """
    # Look for PDK_TAG ?= X.Y.Z or PDK_TAG = X.Y.Z
    match = re.search(r"^PDK_TAG\s*\??=\s*(.+)$", makefile_content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return ""
