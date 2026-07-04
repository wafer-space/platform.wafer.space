"""Resolve E2E inputs and precheck metadata from GitHub / GHCR at runtime.

The E2E flow uploads a design from ``wafer-space/gf180mcu-project-template``.
GitHub Actions artifacts expire (~90 days), so instead of pinning a single
artifact this module resolves the newest non-expired ``0p5x0p5_gds`` artifact
at runtime and computes the sha256 of the extracted GDS.

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
from datetime import datetime

import requests

TEMPLATE_REPO = "wafer-space/gf180mcu-project-template"
ARTIFACT_NAME = "0p5x0p5_gds"
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


def get_latest_artifact() -> tuple[str, str]:
    """Return ``(submit_url, sha256)`` for the newest quarter-slot GDS artifact.

    ``submit_url`` is the GitHub web URL the platform downloads; ``sha256`` is
    the hash of the extracted GDS, matching what the platform computes.
    """
    resp = requests.get(
        f"{API}/repos/{TEMPLATE_REPO}/actions/artifacts",
        headers=_headers(),
        params={"per_page": 100},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    artifacts = [
        a
        for a in resp.json()["artifacts"]
        if a["name"] == ARTIFACT_NAME and not a["expired"]
    ]
    if not artifacts:
        msg = f"No non-expired '{ARTIFACT_NAME}' artifact in {TEMPLATE_REPO}"
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


def get_latest_precheck_digest() -> str:
    """Return the digest of the newest published precheck image.

    Resolves the GHCR ``latest`` tag of the precheck container to its
    ``sha256:...`` digest. This is what the platform pulls to run a check, so
    the run can confirm a check used the newest published precheck.
    """
    tok = _ghcr_pull_token()
    resp = requests.get(
        f"{PRECHECK_GHCR}/manifests/latest",
        headers={"Authorization": f"Bearer {tok}", "Accept": _MANIFEST_ACCEPT},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    digest = resp.headers.get("Docker-Content-Digest")
    if not digest:
        msg = "GHCR did not return a Docker-Content-Digest for precheck 'latest'"
        raise RuntimeError(msg)
    return digest


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
        params={"status": "success", "branch": "main", "per_page": 1},
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
