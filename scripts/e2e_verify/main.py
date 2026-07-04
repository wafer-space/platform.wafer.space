"""
E2E verification script for wafer.space.

Usage:
    uv run python -m scripts.e2e_verify http://localhost:8081
    uv run python -m scripts.e2e_verify https://wafer.space
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC
from datetime import datetime

from playwright.sync_api import sync_playwright
from pyvirtualdisplay import Display

from .artifact import get_latest_artifact
from .pages import FileSubmitPage
from .pages import LoginPage
from .pages import ProjectCreatePage
from .pages import ProjectDetailPage

# ============================================================
# CONFIGURATION
# ============================================================
# Credentials come from the environment (put E2E_TEST_PASSWORD in .env).
USERNAME = os.environ.get("E2E_TEST_USERNAME", "e2e-test-user")
PASSWORD = os.environ.get("E2E_TEST_PASSWORD", "")

# The design to upload is resolved at runtime from the newest non-expired
# template-repo artifact (see artifact.py). WRONG_HASH is a deliberately bad
# hash used to exercise the platform's mismatch detection.
WRONG_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

# Timeout configuration in milliseconds
DOWNLOAD_TIMEOUT = 5 * 60 * 1000  # 5 minutes
HASH_TIMEOUT = 60 * 1000  # 1 minute
PRECHECK_START_TIMEOUT = 10 * 60 * 1000  # 10 minutes
PRECHECK_COMPLETE_TIMEOUT = 4 * 60 * 60 * 1000  # 4 hours


def log(step: int, total: int, message: str) -> None:
    """Print timestamped log message."""
    timestamp = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"[{timestamp}] Step {step}/{total}: {message}")  # noqa: T201


def run_full_flow(  # noqa: PLR0915
    base_url: str, vnc_port: int = 5901, *, headless: bool = False
) -> bool:
    """Run the complete E2E verification flow.

    Args:
        base_url: Base URL of the wafer.space instance
        vnc_port: Port for VNC server
        headless: Run without a VNC display (for CI/headless environments)

    Returns:
        True if all verifications passed, False otherwise
    """
    total_steps = 13

    # Resolve the design to upload: the newest non-expired quarter-slot GDS
    # artifact from the template repo (GitHub expires artifacts after ~90 days,
    # so we never rely on a pinned URL).
    print("Resolving latest template-repo artifact...")  # noqa: T201
    artifact_url, correct_hash = get_latest_artifact()
    print(f"  artifact: {artifact_url}")  # noqa: T201
    print(f"  sha256:   {correct_hash}")  # noqa: T201

    # Start a VNC display unless running headless
    display = None
    if not headless:
        print("=" * 60)  # noqa: T201
        print(f"  VNC server starting on port {vnc_port}")  # noqa: T201
        print(f"  Connect to watch: vncviewer localhost:{vnc_port}")  # noqa: T201
        print("=" * 60)  # noqa: T201
        print()  # noqa: T201
        display = Display(backend="xvnc", size=(1920, 1080), rfbport=vnc_port)
        display.start()

    success = False

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()

            # ========================================
            # Step 1: Login
            # ========================================
            log(1, total_steps, "Logging in...")
            login_page = LoginPage(page, base_url)
            login_page.login(USERNAME, PASSWORD)
            log(1, total_steps, "Login successful")

            # ========================================
            # Step 2: Create project with quarter slot
            # ========================================
            log(2, total_steps, "Creating project (quarter slot, CoB packaging)...")
            create_page = ProjectCreatePage(page, base_url)
            timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            project_name = f"E2E Test {timestamp}"
            project_id = create_page.create_project(
                project_name, slot_size="0p5x0p5", chip_on_board=True
            )
            log(2, total_steps, f"Project created (CoB): {project_id}")

            # Create page objects for remaining steps
            detail_page = ProjectDetailPage(page, base_url, project_id)
            file_submit = FileSubmitPage(page, base_url, project_id)

            # ========================================
            # Step 3: Submit file with WRONG hash
            # ========================================
            log(3, total_steps, "Submitting file with wrong hash...")
            file_submit.submit_file(artifact_url, sha256_hash=WRONG_HASH)
            log(3, total_steps, "File submitted")

            # ========================================
            # Step 4: Verify download OK, hash fails
            # ========================================
            log(4, total_steps, "Waiting for download to complete...")
            detail_page.wait_for_downloaded(timeout_ms=DOWNLOAD_TIMEOUT)
            log(4, total_steps, "Download completed")

            log(4, total_steps, "Verifying hash mismatch detected...")
            detail_page.wait_for_hash_mismatch(timeout_ms=HASH_TIMEOUT)
            log(4, total_steps, "Hash mismatch correctly detected")
            detail_page.screenshot("04_hash_mismatch")

            # ========================================
            # Step 5: Submit file with CORRECT hash
            # ========================================
            log(5, total_steps, "Submitting file with correct hash...")
            file_submit.submit_file(artifact_url, sha256_hash=correct_hash)
            log(5, total_steps, "File submitted")

            # ========================================
            # Step 6: Verify download + hash OK
            # ========================================
            log(6, total_steps, "Waiting for download to complete...")
            detail_page.wait_for_downloaded(timeout_ms=DOWNLOAD_TIMEOUT)
            log(6, total_steps, "Download completed")

            log(6, total_steps, "Verifying hash verification passes...")
            detail_page.wait_for_hash_verified(timeout_ms=HASH_TIMEOUT)
            log(6, total_steps, "Hash verified")
            detail_page.screenshot("06_hash_verified")

            # ========================================
            # Step 7: Verify precheck starts
            # ========================================
            log(7, total_steps, "Waiting for manufacturability check to start...")
            detail_page.wait_for_precheck_running(timeout_ms=PRECHECK_START_TIMEOUT)
            log(7, total_steps, "Precheck running")
            detail_page.screenshot("07_precheck_running")

            # ========================================
            # Step 8: Verify precheck produces logs
            # ========================================
            log(8, total_steps, "Waiting for precheck logs...")
            # Wait for any log content to appear
            detail_page.wait_for_logs_contain("", timeout_ms=60_000)
            logs = detail_page.get_precheck_logs()
            log(8, total_steps, f"Precheck logs received ({len(logs)} chars)")
            detail_page.screenshot("08_precheck_logs")

            # ========================================
            # Step 9: Cancel precheck
            # ========================================
            log(9, total_steps, "Cancelling precheck...")
            detail_page.click_cancel_precheck()
            detail_page.wait_for_precheck_cancelled()
            log(9, total_steps, "Precheck cancelled")
            detail_page.screenshot("09_precheck_cancelled")

            # ========================================
            # Step 10: Submit file again (correct hash)
            # ========================================
            log(10, total_steps, "Submitting file again with correct hash...")
            file_submit.submit_file(artifact_url, sha256_hash=correct_hash)
            log(10, total_steps, "File submitted")

            # ========================================
            # Step 11: Verify download + hash OK again
            # ========================================
            log(11, total_steps, "Waiting for download to complete...")
            detail_page.wait_for_downloaded(timeout_ms=DOWNLOAD_TIMEOUT)
            detail_page.wait_for_hash_verified(timeout_ms=HASH_TIMEOUT)
            log(11, total_steps, "Download and hash verified")

            # ========================================
            # Step 12: Verify new precheck starts
            # ========================================
            log(12, total_steps, "Waiting for new precheck to start...")
            detail_page.wait_for_precheck_running(timeout_ms=PRECHECK_START_TIMEOUT)
            log(12, total_steps, "New precheck running")

            # ========================================
            # Step 13: Wait for precheck to complete
            # ========================================
            log(
                13,
                total_steps,
                "Waiting for precheck to complete (this may take hours)...",
            )
            detail_page.wait_for_precheck_complete(timeout_ms=PRECHECK_COMPLETE_TIMEOUT)

            if detail_page.is_manufacturable():
                log(13, total_steps, "Precheck PASSED - Design is manufacturable")
            else:
                log(
                    13,
                    total_steps,
                    "Precheck completed - Design is NOT manufacturable",
                )

            detail_page.screenshot("13_precheck_complete")

            success = True

            # ========================================
            # Done!
            # ========================================
            print()  # noqa: T201
            print("=" * 60)  # noqa: T201
            print("  E2E VERIFICATION COMPLETE")  # noqa: T201
            print("=" * 60)  # noqa: T201

            browser.close()

    except Exception as e:
        print()  # noqa: T201
        print("=" * 60)  # noqa: T201
        print(f"  E2E VERIFICATION FAILED: {e}")  # noqa: T201
        print("=" * 60)  # noqa: T201
        raise

    finally:
        if display is not None:
            display.stop()

    return success


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

    success = run_full_flow(
        args.url, vnc_port=args.vnc_port, headless=args.headless
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
