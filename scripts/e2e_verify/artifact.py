"""Resolve the latest quarter-slot GDS artifact from the project template repo.

The E2E flow uploads a design from ``wafer-space/gf180mcu-project-template``.
GitHub Actions artifacts expire (~90 days), so instead of pinning a single
artifact this module resolves the newest non-expired ``0p5x0p5_gds`` artifact
at runtime and computes the sha256 of the extracted GDS.

The platform hashes the *extracted* layout (not the downloaded zip), so we
extract the single ``.gds`` (decompressing a ``.gds.gz`` if present) and hash
that, which matches what the platform will compute after downloading the same
artifact URL.

Requires a GitHub token in ``GITHUB_TOKEN`` or ``GH_TOKEN`` (artifact downloads
require authentication even for public repos).
"""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import zipfile

import requests

TEMPLATE_REPO = "wafer-space/gf180mcu-project-template"
ARTIFACT_NAME = "0p5x0p5_gds"
API = "https://api.github.com"
_TIMEOUT = 180


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
