"""
E2E verification script for wafer.space.

Usage:
    uv run python -m scripts.e2e_verify http://localhost:8081
    uv run python -m scripts.e2e_verify https://wafer.space
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import TYPE_CHECKING

from playwright.sync_api import sync_playwright
from pyvirtualdisplay import Display

from .artifact import PrecheckIdentity
from .artifact import get_expected_precheck_runtime
from .artifact import get_latest_artifact
from .artifact import get_latest_precheck_identity
from .pages import FileSubmitPage
from .pages import LoginPage
from .pages import ProjectCreatePage
from .pages import ProjectDetailPage
from .pages import ProjectListPage

if TYPE_CHECKING:
    from playwright.sync_api import Page

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunInputs:
    """Resolved inputs for a run: the design to upload + precheck metadata."""

    artifact_url: str
    correct_hash: str
    expected_runtime_s: int | None
    precheck_identity: PrecheckIdentity


# ============================================================
# CONFIGURATION
# ============================================================
# Credentials come from the environment (put E2E_TEST_PASSWORD in .env).
USERNAME = os.environ.get("E2E_TEST_USERNAME", "e2e-test-user")
PASSWORD = os.environ.get("E2E_TEST_PASSWORD", "")

# Slot size to test (quarter slot). Used both for project creation and to look
# up the matching precheck CI job's expected run time.
SLOT_SIZE = "0p5x0p5"
TOTAL_STEPS = 13

# The design to upload is resolved at runtime from the newest non-expired
# template-repo artifact (see artifact.py). WRONG_HASH is a deliberately bad
# hash used to exercise the platform's mismatch detection.
WRONG_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

# Timeout configuration in milliseconds
DOWNLOAD_TIMEOUT = 5 * 60 * 1000  # 5 minutes
HASH_TIMEOUT = 60 * 1000  # 1 minute
PRECHECK_START_TIMEOUT = 10 * 60 * 1000  # 10 minutes
PRECHECK_COMPLETE_TIMEOUT = 4 * 60 * 60 * 1000  # 4 hours
LOGS_TIMEOUT = 90 * 1000  # 1.5 minutes


def configure_logging() -> None:
    """Send this package's logs to stdout as ``[HH:MM:SS] message``.

    A StreamHandler on stdout flushes on every record, so progress is visible
    in real time even when stdout is redirected to a file or pipe.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(message)s", datefmt="%H:%M:%S")
    )
    package_logger = logging.getLogger(__package__ or "scripts.e2e_verify")
    package_logger.handlers.clear()
    package_logger.addHandler(handler)
    package_logger.setLevel(logging.INFO)
    package_logger.propagate = False


def log(step: int, message: str) -> None:
    """Log a step-progress line (the timestamp is added by the formatter)."""
    logger.info("Step %d/%d: %s", step, TOTAL_STEPS, message)


def _verify_latest_precheck(token: str | None, identity: PrecheckIdentity) -> str:
    """Return a status message; raise if the check isn't the latest precheck.

    ``token`` is the version the platform shows for the running check -- a
    ``sha256:`` digest, a semver/git-describe string, or a short git sha --
    and ``identity`` is how GHCR's ``latest`` image identifies itself. The
    token matches the latest image if it corresponds to any of those forms.
    """
    if token is None:
        msg = "Could not read the precheck version from the page to verify it"
        raise RuntimeError(msg)

    latest_hex = identity.digest.split(":")[-1]
    git7 = identity.git_sha[:7]
    token_l = token.lower()

    matches_digest = "sha256:" in token_l and latest_hex.startswith(
        token_l.rsplit("sha256:", 1)[-1]
    )
    matches_version = bool(identity.version) and identity.version in token
    matches_git = bool(git7) and git7 in token_l
    if matches_digest or matches_version or matches_git:
        return f"Precheck version is latest ({token})"

    msg = (
        f"Precheck is NOT the latest published image: check shows {token!r}, "
        f"but GHCR 'latest' is sha256:{latest_hex[:12]}... "
        f"(version={identity.version!r}, git={git7})"
    )
    raise RuntimeError(msg)


def _resolve_inputs() -> RunInputs:
    """Resolve the artifact + precheck metadata, logging what was found."""
    logger.info("Resolving latest template-repo artifact + precheck metadata...")
    artifact_url, correct_hash = get_latest_artifact()
    inputs = RunInputs(
        artifact_url=artifact_url,
        correct_hash=correct_hash,
        expected_runtime_s=get_expected_precheck_runtime(SLOT_SIZE),
        precheck_identity=get_latest_precheck_identity(),
    )
    runtime = (
        f"~{inputs.expected_runtime_s}s (~{inputs.expected_runtime_s // 60}m)"
        if inputs.expected_runtime_s
        else "unknown"
    )
    logger.info("  artifact:         %s", inputs.artifact_url)
    logger.info("  sha256:           %s", inputs.correct_hash)
    logger.info("  latest precheck:  %s", inputs.precheck_identity.digest)
    logger.info("  expected runtime: %s", runtime)
    return inputs


def _start_display(vnc_port: int, *, headless: bool) -> Display | None:
    """Start an Xvnc display for headed runs; return None when headless."""
    if headless:
        return None
    logger.info("=" * 60)
    logger.info("  VNC server starting on port %d", vnc_port)
    logger.info("  Connect to watch: vncviewer localhost:%d", vnc_port)
    logger.info("=" * 60)
    display = Display(backend="xvnc", size=(1920, 1080), rfbport=vnc_port)
    display.start()
    return display


def _login_and_preflight(page: Page, base_url: str) -> None:
    """Step 1: log in, then cancel any of the user's in-progress checks.

    Cancelling first gives the run a clean slate and frees test-platform's
    limited concurrent-check capacity so this run's check is not queued behind
    leftover checks from earlier runs.
    """
    log(1, "Logging in...")
    LoginPage(page, base_url).login(USERNAME, PASSWORD)
    log(1, "Login successful")

    log(1, "Preflight: cancelling any running checks...")
    project_ids = ProjectListPage(page, base_url).project_ids()
    log(1, f"Preflight: scanning {len(project_ids)} project(s)")
    for pid in project_ids:
        if ProjectDetailPage(page, base_url, pid).cancel_check_if_running():
            log(1, f"Preflight: cancelled check on {pid}")
    log(1, "Preflight complete")


def _create_project(
    page: Page, base_url: str
) -> tuple[ProjectDetailPage, FileSubmitPage]:
    """Step 2: create a quarter-slot chip-on-board project."""
    log(2, "Creating project (quarter slot, CoB packaging)...")
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    project_id = ProjectCreatePage(page, base_url).create_project(
        f"E2E Test {timestamp}", slot_size=SLOT_SIZE, chip_on_board=True
    )
    log(2, f"Project created (CoB): {project_id}")
    return (
        ProjectDetailPage(page, base_url, project_id),
        FileSubmitPage(page, base_url, project_id),
    )


def _verify_upload_and_hash(
    detail_page: ProjectDetailPage,
    file_submit: FileSubmitPage,
    inputs: RunInputs,
) -> None:
    """Steps 3-6: wrong hash is rejected, correct hash is verified."""
    log(3, "Submitting file with wrong hash...")
    file_submit.submit_file(inputs.artifact_url, sha256_hash=WRONG_HASH)
    log(3, "File submitted")

    log(4, "Waiting for download to complete...")
    detail_page.wait_for_downloaded(timeout_ms=DOWNLOAD_TIMEOUT)
    log(4, "Download completed")
    log(4, "Verifying hash mismatch detected...")
    detail_page.wait_for_hash_mismatch(timeout_ms=HASH_TIMEOUT)
    log(4, "Hash mismatch correctly detected")
    detail_page.screenshot("04_hash_mismatch")

    log(5, "Submitting file with correct hash...")
    file_submit.submit_file(inputs.artifact_url, sha256_hash=inputs.correct_hash)
    log(5, "File submitted")

    log(6, "Waiting for download to complete...")
    detail_page.wait_for_downloaded(timeout_ms=DOWNLOAD_TIMEOUT)
    log(6, "Download completed")
    log(6, "Verifying hash verification passes...")
    detail_page.wait_for_hash_verified(timeout_ms=HASH_TIMEOUT)
    log(6, "Hash verified")
    detail_page.screenshot("06_hash_verified")


def _run_and_cancel_precheck(detail_page: ProjectDetailPage) -> None:
    """Steps 7-9: the precheck starts, produces logs, and can be cancelled."""
    log(7, "Waiting for manufacturability check to start...")
    detail_page.wait_for_precheck_running(timeout_ms=PRECHECK_START_TIMEOUT)
    log(7, "Precheck running")
    detail_page.screenshot("07_precheck_running")

    log(8, "Waiting for precheck logs...")
    # Logs are best-effort: the platform persists check.processing_logs with
    # some delay, so it may have none while the check is early in its run.
    try:
        detail_page.wait_for_logs_contain("", timeout_ms=LOGS_TIMEOUT)
    except TimeoutError:
        log(8, "No precheck logs yet (continuing)")
    logs = detail_page.get_precheck_logs()
    log(8, f"Precheck logs received ({len(logs)} chars)")
    detail_page.screenshot("08_precheck_logs")

    log(9, "Cancelling precheck...")
    detail_page.click_cancel_precheck()
    detail_page.wait_for_precheck_cancelled()
    log(9, "Precheck cancelled")
    detail_page.screenshot("09_precheck_cancelled")


def _rerun_and_await_verdict(
    detail_page: ProjectDetailPage,
    file_submit: FileSubmitPage,
    inputs: RunInputs,
) -> None:
    """Steps 10-13: resubmit, verify the precheck version, await the verdict."""
    log(10, "Submitting file again with correct hash...")
    file_submit.submit_file(inputs.artifact_url, sha256_hash=inputs.correct_hash)
    log(10, "File submitted")

    log(11, "Waiting for download to complete...")
    detail_page.wait_for_downloaded(timeout_ms=DOWNLOAD_TIMEOUT)
    detail_page.wait_for_hash_verified(timeout_ms=HASH_TIMEOUT)
    log(11, "Download and hash verified")

    log(12, "Waiting for new precheck to start...")
    detail_page.wait_for_precheck_running(timeout_ms=PRECHECK_START_TIMEOUT)
    log(12, "New precheck running")
    # Verify the platform ran the *latest* published precheck image. Poll until
    # the version is shown (it only appears once the image has been pulled).
    token = detail_page.wait_for_check_version_token()
    log(12, _verify_latest_precheck(token, inputs.precheck_identity))

    log(13, "Waiting for precheck to complete (this may take hours)...")
    detail_page.wait_for_precheck_complete(
        timeout_ms=PRECHECK_COMPLETE_TIMEOUT, expected_s=inputs.expected_runtime_s
    )
    if detail_page.is_manufacturable():
        log(13, "Precheck PASSED - Design is manufacturable")
    else:
        log(13, "Precheck completed - Design is NOT manufacturable")
    detail_page.screenshot("13_precheck_complete")


def run_full_flow(
    base_url: str, vnc_port: int = 5901, *, headless: bool = False
) -> bool:
    """Run the complete E2E verification flow.

    Args:
        base_url: Base URL of the wafer.space instance
        vnc_port: Port for VNC server
        headless: Run without a VNC display (for CI/headless environments)

    Returns:
        True if all verifications passed, False otherwise.
    """
    inputs = _resolve_inputs()
    display = _start_display(vnc_port, headless=headless)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()
            # Auto-accept confirmation dialogs (e.g. cancel-check confirms).
            # Registered once here so it doesn't accumulate per cancel click.
            page.on("dialog", lambda dialog: dialog.accept())

            _login_and_preflight(page, base_url)
            detail_page, file_submit = _create_project(page, base_url)
            _verify_upload_and_hash(detail_page, file_submit, inputs)
            _run_and_cancel_precheck(detail_page)
            _rerun_and_await_verdict(detail_page, file_submit, inputs)

            logger.info("=" * 60)
            logger.info("  E2E VERIFICATION COMPLETE")
            logger.info("=" * 60)
            browser.close()
    except Exception:
        logger.exception("E2E VERIFICATION FAILED")
        return False
    else:
        return True
    finally:
        if display is not None:
            display.stop()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="E2E verification for wafer.space",
        epilog="Connect to VNC to watch: vncviewer localhost:5901",
    )
    parser.add_argument("url", help="Base URL (e.g., https://wafer.space)")
    parser.add_argument(
        "--vnc-port", type=int, default=5901, help="VNC port (default: 5901)"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without a VNC display (for CI/headless environments)",
    )
    args = parser.parse_args()

    if not PASSWORD:
        parser.error(
            "E2E_TEST_PASSWORD environment variable is required (add it to .env)"
        )

    configure_logging()
    success = run_full_flow(args.url, vnc_port=args.vnc_port, headless=args.headless)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
