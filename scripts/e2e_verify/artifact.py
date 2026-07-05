"""Resolve E2E inputs and precheck metadata from GitHub / GHCR at runtime.

The E2E flow uploads a design from ``wafer-space/gf180mcu-project-template``.
GitHub Actions artifacts expire (~90 days), so instead of pinning a single
artifact this module resolves the newest non-expired ``<slot_size>_gds``
artifact at runtime and computes the sha256 of the extracted GDS.

The platform hashes the *extracted* layout (not the downloaded zip), so we
extract the single ``.gds`` (decompressing a ``.gds.gz`` if present) and hash
that, which matches what the platform will compute after downloading the same
artifact URL.

It also resolves two facts about the precheck itself, from its own repo
(``wafer-space/gf180mcu-precheck``):
  - the expected run time for a slot size, from the durations of the
    ``Run the Precheck (<slot>, ...)`` jobs in the latest precheck CI run; and
  - the digest of the latest published precheck container image (GHCR ``latest``
    tag), so the run can verify the platform actually ran the newest precheck.

Requires a GitHub token in ``GITHUB_TOKEN`` or ``GH_TOKEN`` (artifact downloads
require authentication even for public repos).
"""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime

import requests

TEMPLATE_REPO = "wafer-space/gf180mcu-project-template"
API = "https://api.github.com"
_TIMEOUT = 180

# Precheck repo + its published container image on GHCR.
PRECHECK_REPO = "wafer-space/gf180mcu-precheck"
PRECHECK_GHCR = f"https://ghcr.io/v2/{PRECHECK_REPO}"
_MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json,"
    "application/vnd.docker.distribution.manifest.list.v2+json,"
    "application/vnd.oci.image.manifest.v1+json,"
    "application/vnd.docker.distribution.manifest.v2+json"
)


def _headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        msg = (
            "GITHUB_TOKEN or GH_TOKEN required to fetch template artifacts "
            "(try: GH_TOKEN=$(gh auth token))"
        )
        raise RuntimeError(msg)
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_latest_artifact(slot_size: str) -> tuple[str, str]:
    """Return ``(submit_url, sha256)`` for the newest GDS artifact of ``slot_size``.

    The template repo publishes one ``<slot_size>_gds`` artifact per slot size
    (e.g. ``0p5x0p5_gds``, ``1x1_gds``). ``submit_url`` is the GitHub web URL the
    platform downloads; ``sha256`` is the hash of the extracted GDS, matching
    what the platform computes.
    """
    artifact_name = f"{slot_size}_gds"
    # Filter by name server-side: the repo accumulates thousands of artifacts of
    # many names, so a plain per_page=100 (most-recent-first, all names) can omit
    # every matching artifact once newer other-named ones fill page 1. The
    # ``name`` query param returns only exact-name matches, newest first.
    resp = requests.get(
        f"{API}/repos/{TEMPLATE_REPO}/actions/artifacts",
        headers=_headers(),
        params={"name": artifact_name, "per_page": "100"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    artifacts = [a for a in resp.json()["artifacts"] if not a["expired"]]
    if not artifacts:
        msg = f"No non-expired '{artifact_name}' artifact in {TEMPLATE_REPO}"
        raise RuntimeError(msg)

    latest = max(artifacts, key=lambda a: a["created_at"])
    run_id = latest["workflow_run"]["id"]
    artifact_id = latest["id"]
    submit_url = (
        f"https://github.com/{TEMPLATE_REPO}"
        f"/actions/runs/{run_id}/artifacts/{artifact_id}"
    )
    return submit_url, _extracted_gds_sha256(artifact_id)


def _extracted_gds_sha256(artifact_id: int) -> str:
    """Download the artifact zip and sha256 the single extracted GDS."""
    resp = requests.get(
        f"{API}/repos/{TEMPLATE_REPO}/actions/artifacts/{artifact_id}/zip",
        headers=_headers(),
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = [n for n in zf.namelist() if n.endswith((".gds", ".gds.gz"))]
        if len(names) != 1:
            msg = f"expected exactly one GDS in artifact, found: {zf.namelist()}"
            raise RuntimeError(msg)
        data = zf.read(names[0])

    if names[0].endswith(".gz"):
        data = gzip.decompress(data)
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class PrecheckIdentity:
    """How the newest published precheck image can be identified.

    The platform's version badge shows one of these forms depending on whether
    it has cataloged the image: the ``sha256:`` digest (uncataloged), the
    ``version`` label (or a tag-resolved semver derived from it), or the short
    ``git_sha``. Keeping all three lets a run recognise the latest image
    whichever form the badge happens to render.
    """

    digest: str  # full "sha256:..." of the GHCR 'latest' index
    version: str  # org.opencontainers.image.version label ("" if unset)
    git_sha: str  # org.opencontainers.image.revision label ("" if unset)


def get_latest_precheck_identity() -> PrecheckIdentity:
    """Identify the newest published precheck image (GHCR ``latest`` tag).

    Reads the same OCI labels the platform reads (``.version`` / ``.revision``)
    plus the index digest, so a run can independently confirm a check used the
    newest published precheck regardless of how the badge displays it.
    """
    tok = _ghcr_pull_token()
    index = requests.get(
        f"{PRECHECK_GHCR}/manifests/latest",
        headers={"Authorization": f"Bearer {tok}", "Accept": _MANIFEST_ACCEPT},
        timeout=_TIMEOUT,
    )
    index.raise_for_status()
    digest = index.headers.get("Docker-Content-Digest")
    if not digest:
        msg = "GHCR did not return a Docker-Content-Digest for precheck 'latest'"
        raise RuntimeError(msg)

    labels = _fetch_image_labels(tok, index.json())
    return PrecheckIdentity(
        digest=digest,
        version=labels.get("org.opencontainers.image.version", ""),
        git_sha=labels.get("org.opencontainers.image.revision", ""),
    )


def _fetch_image_labels(token: str, index_json: dict) -> dict[str, str]:
    """Return the OCI config labels for the amd64 image of a manifest index."""
    manifest_digest = "latest"
    for m in index_json.get("manifests", []):
        if m.get("platform", {}).get("architecture") == "amd64":
            manifest_digest = m["digest"]
            break

    headers = {"Authorization": f"Bearer {token}", "Accept": _MANIFEST_ACCEPT}
    manifest = requests.get(
        f"{PRECHECK_GHCR}/manifests/{manifest_digest}",
        headers=headers,
        timeout=_TIMEOUT,
    )
    manifest.raise_for_status()
    config_digest = manifest.json().get("config", {}).get("digest")
    if not config_digest:
        return {}

    config = requests.get(
        f"{PRECHECK_GHCR}/blobs/{config_digest}", headers=headers, timeout=_TIMEOUT
    )
    config.raise_for_status()
    return config.json().get("config", {}).get("Labels") or {}


def _ghcr_pull_token() -> str:
    """Anonymous GHCR pull token for the (public) precheck image."""
    resp = requests.get(
        f"https://ghcr.io/token?scope=repository:{PRECHECK_REPO}:pull",
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def get_expected_precheck_runtime(slot_size: str) -> int | None:
    """Expected precheck run time in seconds for ``slot_size``, from precheck CI.

    Averages (median) the durations of the ``Run the Precheck (<slot_size>, ...)``
    matrix jobs in the latest successful precheck CI run on ``main``. Returns
    None if no matching jobs are found.
    """
    runs = requests.get(
        f"{API}/repos/{PRECHECK_REPO}/actions/workflows/ci.yml/runs",
        headers=_headers(),
        params={"status": "success", "branch": "main", "per_page": "1"},
        timeout=_TIMEOUT,
    )
    runs.raise_for_status()
    workflow_runs = runs.json().get("workflow_runs", [])
    if not workflow_runs:
        return None

    jobs = requests.get(
        f"{API}/repos/{PRECHECK_REPO}/actions/runs/{workflow_runs[0]['id']}/jobs",
        headers=_headers(),
        params={"per_page": 100},
        timeout=_TIMEOUT,
    )
    jobs.raise_for_status()

    durations = [
        _iso_seconds(j["started_at"], j["completed_at"])
        for j in jobs.json().get("jobs", [])
        if f"({slot_size}," in j["name"] and j["started_at"] and j["completed_at"]
    ]
    if not durations:
        return None
    durations.sort()
    return durations[len(durations) // 2]  # median


def _iso_seconds(start: str, end: str) -> int:
    """Seconds between two ISO-8601 timestamps (e.g. GitHub's ...Z stamps)."""
    started = datetime.fromisoformat(start)
    completed = datetime.fromisoformat(end)
    return int((completed - started).total_seconds())
