"""e2e_verify's template artifact: its name and its not-found error (#428).

The template's CI names each GDS artifact ``<slot>_<voltage>_gds``. No
network: ``requests.get`` is replaced by a fake GitHub API.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from dataclasses import field
from typing import Any

import pytest

from scripts.e2e_verify import artifact
from scripts.e2e_verify import main

API = f"{artifact.API}/repos/{artifact.TEMPLATE_REPO}/actions"
GDS_BYTES = b"GDS layout"
RUN_URL = f"https://github.com/{artifact.TEMPLATE_REPO}/actions/runs/7"
# The only runs query whose answer lists the run's artifacts
SUCCESSFUL_MAIN_RUNS = {"branch": "main", "status": "success", "per_page": "1"}


@dataclass
class FakeResponse:
    payload: Any = None
    content: bytes = b""

    def raise_for_status(self) -> None:
        """Every fake response is a 200."""

    def json(self) -> Any:
        return self.payload


@dataclass
class FakeGitHub:
    """The template repo's artifacts API, answering from ``artifacts``."""

    artifacts: list[dict[str, Any]]
    latest_run_names: list[str] = field(default_factory=list)
    has_successful_run: bool = True
    requests: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def get(
        self, url: str, *, params: dict[str, str] | None = None, **_: object
    ) -> FakeResponse:
        self.requests.append((url, params or {}))
        if url == f"{API}/artifacts":
            name = (params or {})["name"]
            return FakeResponse(
                {"artifacts": [a for a in self.artifacts if a["name"] == name]}
            )
        if url == f"{API}/workflows/ci.yml/runs":
            runs = [{"id": 7, "html_url": RUN_URL}]
            wanted = params == SUCCESSFUL_MAIN_RUNS and self.has_successful_run
            return FakeResponse({"workflow_runs": runs if wanted else []})
        if url == f"{API}/runs/7/artifacts":
            return FakeResponse(
                {"artifacts": [{"name": n} for n in self.latest_run_names]}
            )
        if url.endswith("/zip"):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as zf:
                zf.writestr("chip_top.gds", GDS_BYTES)
            return FakeResponse(content=buffer.getvalue())
        msg = f"unexpected request {url}"
        raise AssertionError(msg)


def gds_artifact(artifact_id: int, name: str, created_at: str) -> dict[str, Any]:
    return {
        "id": artifact_id,
        "name": name,
        "expired": False,
        "created_at": created_at,
        "workflow_run": {"id": 100 + artifact_id},
    }


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    fake = FakeGitHub(artifacts=[])
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setattr(artifact.requests, "get", fake.get)
    return fake


@pytest.mark.parametrize(
    ("slot", "voltage", "name"),
    [("0p5x0p5", "3v3", "0p5x0p5_3v3_gds"), ("1x1", "5v", "1x1_5v_gds")],
)
def test_artifact_name_has_the_voltage(slot: str, voltage: str, name: str) -> None:
    assert artifact.gds_artifact_name(slot, voltage) == name


def test_unknown_voltage_is_refused() -> None:
    with pytest.raises(ValueError, match="voltage must be one of"):
        artifact.gds_artifact_name("1x1", "1v8")


def test_default_voltage_is_3v3() -> None:
    assert main.DEFAULT_VOLTAGE == "3v3"
    assert main.DEFAULT_VOLTAGE in artifact.VOLTAGES


def test_latest_artifact_of_the_voltage_is_submitted(github: FakeGitHub) -> None:
    github.artifacts = [
        gds_artifact(1, "0p5x0p5_3v3_gds", "2026-10-14T00:00:00Z"),
        gds_artifact(2, "0p5x0p5_3v3_gds", "2026-10-15T00:00:00Z"),
        gds_artifact(3, "0p5x0p5_5v_gds", "2026-10-16T00:00:00Z"),
    ]

    submit_url, sha256 = artifact.get_latest_artifact("0p5x0p5", "3v3")

    assert github.requests[0][1]["name"] == "0p5x0p5_3v3_gds"
    assert submit_url == (
        f"https://github.com/{artifact.TEMPLATE_REPO}/actions/runs/102/artifacts/2"
    )
    assert sha256 == hashlib.sha256(GDS_BYTES).hexdigest()


def test_missing_artifact_lists_what_the_latest_run_has(github: FakeGitHub) -> None:
    github.artifacts = [gds_artifact(1, "0p5x0p5_3v3_gds", "2026-10-15T00:00:00Z")]
    github.latest_run_names = ["0p5x0p5_3v3_gds", "0p5x0p5_3v3_image", "1x1_5v_gds"]

    with pytest.raises(RuntimeError) as raised:
        artifact.get_latest_artifact("0p5x0p5", "5v")

    assert str(raised.value) == (
        f"No non-expired '0p5x0p5_5v_gds' artifact in {artifact.TEMPLATE_REPO}. "
        f"Its latest successful main CI run ({RUN_URL}) has: "
        "0p5x0p5_3v3_gds, 0p5x0p5_3v3_image, 1x1_5v_gds"
    )


def test_expired_artifact_is_not_submitted(github: FakeGitHub) -> None:
    expired = gds_artifact(1, "1x1_3v3_gds", "2026-10-15T00:00:00Z")
    expired["expired"] = True
    github.artifacts = [expired]

    with pytest.raises(RuntimeError, match="No non-expired '1x1_3v3_gds'"):
        artifact.get_latest_artifact("1x1", "3v3")


def test_missing_artifact_without_a_successful_run_says_so(
    github: FakeGitHub,
) -> None:
    github.has_successful_run = False

    with pytest.raises(RuntimeError) as raised:
        artifact.get_latest_artifact("1x1", "3v3")

    assert str(raised.value).endswith("The template has no successful CI run on main.")
