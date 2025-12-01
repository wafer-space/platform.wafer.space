# E2E Verification Script Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a standalone Playwright script that verifies the complete user flow (login → create project → upload file → hash verification → manufacturability precheck) against a live wafer.space deployment.

**Architecture:** Standalone CLI script using Playwright for browser automation, PyVirtualDisplay for VNC server, and Page Object Model for maintainability. Runs in a VNC session so operators can connect and watch.

**Tech Stack:** Python 3.11+, Playwright, PyVirtualDisplay (xvnc), argparse

---

## Task 1: Add Dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add playwright and pyvirtualdisplay to dev dependencies**

In `pyproject.toml`, add to `[project.optional-dependencies]` or `[dependency-groups]`:

```toml
[dependency-groups]
dev = [
    # ... existing deps ...
    "playwright>=1.40",
    "pyvirtualdisplay>=3.0",
]
```

**Step 2: Sync dependencies**

Run: `uv sync`
Expected: Dependencies install successfully

**Step 3: Install Playwright browsers**

Run: `uv run playwright install chromium`
Expected: Chromium browser downloaded

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add playwright and pyvirtualdisplay dependencies"
```

---

## Task 2: Create Package Structure

**Files:**
- Create: `scripts/e2e_verify/__init__.py`
- Create: `scripts/e2e_verify/__main__.py`
- Create: `scripts/e2e_verify/pages/__init__.py`

**Step 1: Create directory structure**

Run: `mkdir -p scripts/e2e_verify/pages`

**Step 2: Create `scripts/e2e_verify/__init__.py`**

```python
"""E2E verification script for wafer.space."""
```

**Step 3: Create `scripts/e2e_verify/__main__.py`**

```python
"""Entry point for `python -m e2e_verify`."""

from .main import main

if __name__ == "__main__":
    main()
```

**Step 4: Create `scripts/e2e_verify/pages/__init__.py`**

```python
"""Page Object Models for E2E tests."""

from .base import BasePage
from .login import LoginPage
from .project_create import ProjectCreatePage
from .project_detail import ProjectDetailPage
from .file_submit import FileSubmitPage

__all__ = [
    "BasePage",
    "LoginPage",
    "ProjectCreatePage",
    "ProjectDetailPage",
    "FileSubmitPage",
]
```

**Step 5: Commit**

```bash
git add scripts/e2e_verify/
git commit -m "feat(e2e): create package structure"
```

---

## Task 3: Implement BasePage

**Files:**
- Create: `scripts/e2e_verify/pages/base.py`

**Step 1: Create BasePage class**

```python
"""Base Page Object Model for all pages."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page


class BasePage:
    """Base page class with common Playwright helpers."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url.rstrip("/")

    def navigate(self, path: str = "") -> None:
        """Navigate to a path relative to base_url."""
        url = f"{self.base_url}{path}"
        self.page.goto(url)

    def screenshot(self, name: str) -> Path:
        """Take a screenshot and save to screenshots/ directory."""
        screenshots_dir = Path("screenshots")
        screenshots_dir.mkdir(exist_ok=True)
        filepath = screenshots_dir / f"{name}.png"
        self.page.screenshot(path=str(filepath))
        return filepath

    def get_current_path(self) -> str:
        """Get the current URL path (without base_url)."""
        url = self.page.url
        if url.startswith(self.base_url):
            return url[len(self.base_url) :]
        return url
```

**Step 2: Verify syntax**

Run: `uv run python -c "from scripts.e2e_verify.pages.base import BasePage; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add scripts/e2e_verify/pages/base.py
git commit -m "feat(e2e): implement BasePage"
```

---

## Task 4: Implement LoginPage

**Files:**
- Create: `scripts/e2e_verify/pages/login.py`

**Step 1: Create LoginPage class**

```python
"""Login page interactions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class LoginPage(BasePage):
    """Page Object for the login page."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def login(self, username: str, password: str) -> None:
        """Log in with username and password.

        Args:
            username: Email or username
            password: Password
        """
        self.navigate("/accounts/login/")

        # Fill login form - using name attributes from allauth
        self.page.fill('input[name="login"]', username)
        self.page.fill('input[name="password"]', password)

        # Click sign in button
        self.page.click('button[type="submit"]')

        # Wait for redirect away from login page
        expect(self.page).not_to_have_url(re.compile(r".*/accounts/login/.*"))
```

**Step 2: Verify syntax**

Run: `uv run python -c "from scripts.e2e_verify.pages.login import LoginPage; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add scripts/e2e_verify/pages/login.py
git commit -m "feat(e2e): implement LoginPage"
```

---

## Task 5: Implement ProjectCreatePage

**Files:**
- Create: `scripts/e2e_verify/pages/project_create.py`

**Step 1: Create ProjectCreatePage class**

```python
"""Project creation page interactions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class ProjectCreatePage(BasePage):
    """Page Object for project creation."""

    def __init__(self, page: Page, base_url: str) -> None:
        super().__init__(page, base_url)

    def create_project(self, name: str, slot_size: str = "0p5x0p5") -> str:
        """Create a new project.

        Args:
            name: Project name
            slot_size: Slot size value (0p5x0p5, 1x1, 0p5x1, 1x0p5)

        Returns:
            Project UUID from the redirect URL
        """
        self.navigate("/projects/create/")

        # Fill project form
        self.page.fill('input[name="name"]', name)
        self.page.select_option('select[name="slot_size"]', slot_size)

        # Submit form
        self.page.click('button[type="submit"]')

        # Wait for redirect to project detail page
        expect(self.page).to_have_url(re.compile(r"/projects/[\w-]+/$"))

        # Extract project UUID from URL
        match = re.search(r"/projects/([\w-]+)/", self.page.url)
        if match:
            return match.group(1)
        msg = f"Could not extract project ID from URL: {self.page.url}"
        raise ValueError(msg)
```

**Step 2: Verify syntax**

Run: `uv run python -c "from scripts.e2e_verify.pages.project_create import ProjectCreatePage; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add scripts/e2e_verify/pages/project_create.py
git commit -m "feat(e2e): implement ProjectCreatePage"
```

---

## Task 6: Implement FileSubmitPage

**Files:**
- Create: `scripts/e2e_verify/pages/file_submit.py`

**Step 1: Create FileSubmitPage class**

```python
"""File URL submission page interactions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class FileSubmitPage(BasePage):
    """Page Object for file URL submission."""

    def __init__(self, page: Page, base_url: str, project_id: str) -> None:
        super().__init__(page, base_url)
        self.project_id = project_id

    def submit_file(self, url: str, sha256_hash: str | None = None) -> None:
        """Submit a file URL for download.

        Args:
            url: URL to download file from
            sha256_hash: Optional SHA256 hash for verification (without 'sha256:' prefix)
        """
        self.navigate(f"/projects/{self.project_id}/submit-url/")

        # Fill URL field
        self.page.fill('input[name="url"]', url)

        # Fill SHA256 hash if provided
        if sha256_hash:
            # Remove prefix if present
            hash_value = sha256_hash
            if hash_value.startswith("sha256:"):
                hash_value = hash_value[7:]
            self.page.fill('input[name="expected_hash_sha256"]', hash_value)

        # Submit form
        self.page.click('button[type="submit"]')

        # Wait for redirect back to project detail
        expect(self.page).to_have_url(
            re.compile(rf"/projects/{self.project_id}/")
        )
```

**Step 2: Verify syntax**

Run: `uv run python -c "from scripts.e2e_verify.pages.file_submit import FileSubmitPage; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add scripts/e2e_verify/pages/file_submit.py
git commit -m "feat(e2e): implement FileSubmitPage"
```

---

## Task 7: Implement ProjectDetailPage

**Files:**
- Create: `scripts/e2e_verify/pages/project_detail.py`

**Step 1: Create ProjectDetailPage class**

```python
"""Project detail page interactions."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playwright.sync_api import expect

from .base import BasePage

if TYPE_CHECKING:
    from playwright.sync_api import Page


class ProjectDetailPage(BasePage):
    """Page Object for project detail page with status monitoring."""

    # Default timeouts (milliseconds)
    DOWNLOAD_TIMEOUT = 5 * 60 * 1000  # 5 minutes
    HASH_TIMEOUT = 60 * 1000  # 1 minute
    PRECHECK_START_TIMEOUT = 10 * 60 * 1000  # 10 minutes
    PRECHECK_COMPLETE_TIMEOUT = 4 * 60 * 60 * 1000  # 4 hours

    def __init__(self, page: Page, base_url: str, project_id: str) -> None:
        super().__init__(page, base_url)
        self.project_id = project_id

    def go(self) -> None:
        """Navigate to this project's detail page."""
        self.navigate(f"/projects/{self.project_id}/")

    def refresh(self) -> None:
        """Refresh the page."""
        self.page.reload()

    # ========================================
    # Download status
    # ========================================

    def wait_for_downloading(self, timeout_ms: int | None = None) -> None:
        """Wait for download to start."""
        timeout = timeout_ms or self.DOWNLOAD_TIMEOUT
        expect(self.page.get_by_text("Downloading")).to_be_visible(timeout=timeout)

    def wait_for_downloaded(self, timeout_ms: int | None = None) -> None:
        """Wait for download to complete."""
        timeout = timeout_ms or self.DOWNLOAD_TIMEOUT
        expect(self.page.get_by_text("Downloaded")).to_be_visible(timeout=timeout)

    # ========================================
    # Hash verification status
    # ========================================

    def wait_for_hash_verified(self, timeout_ms: int | None = None) -> None:
        """Wait for hash verification to pass."""
        timeout = timeout_ms or self.HASH_TIMEOUT
        expect(self.page.get_by_text("Hash Verified")).to_be_visible(timeout=timeout)

    def wait_for_hash_mismatch(self, timeout_ms: int | None = None) -> None:
        """Wait for hash mismatch to be detected."""
        timeout = timeout_ms or self.HASH_TIMEOUT
        expect(self.page.get_by_text("Hash Mismatch")).to_be_visible(timeout=timeout)

    # ========================================
    # Manufacturability precheck status
    # ========================================

    def wait_for_precheck_queued(self, timeout_ms: int | None = None) -> None:
        """Wait for precheck to be queued."""
        timeout = timeout_ms or self.PRECHECK_START_TIMEOUT
        expect(self.page.get_by_text("Check Queued")).to_be_visible(timeout=timeout)

    def wait_for_precheck_running(self, timeout_ms: int | None = None) -> None:
        """Wait for precheck to start running."""
        timeout = timeout_ms or self.PRECHECK_START_TIMEOUT
        expect(self.page.get_by_text("Checking...")).to_be_visible(timeout=timeout)

    def wait_for_precheck_complete(self, timeout_ms: int | None = None) -> None:
        """Wait for precheck to finish (either pass or fail)."""
        timeout = timeout_ms or self.PRECHECK_COMPLETE_TIMEOUT
        # Match either "Manufacturable" or "Not Manufacturable"
        expect(
            self.page.get_by_text(re.compile(r"^Manufacturable|^Not Manufacturable"))
        ).to_be_visible(timeout=timeout)

    def wait_for_precheck_cancelled(self, timeout_ms: int | None = None) -> None:
        """Wait for precheck cancellation to be confirmed."""
        timeout = timeout_ms or 30_000
        expect(self.page.get_by_text("Check Cancelled")).to_be_visible(timeout=timeout)

    def is_manufacturable(self) -> bool:
        """Check if the design passed manufacturability check.

        Call after wait_for_precheck_complete().
        """
        # Check for "Manufacturable" but not "Not Manufacturable"
        manufacturable = self.page.get_by_text("Manufacturable").first
        not_manufacturable = self.page.get_by_text("Not Manufacturable").first

        if not_manufacturable.is_visible():
            return False
        return manufacturable.is_visible()

    # ========================================
    # Actions
    # ========================================

    def click_cancel_precheck(self) -> None:
        """Click the cancel button for the manufacturability check."""
        # Set up dialog handler before clicking
        self.page.on("dialog", lambda dialog: dialog.accept())

        # Find and click the Cancel button
        self.page.get_by_role("button", name="Cancel").click()

    # ========================================
    # Logs
    # ========================================

    def get_precheck_logs(self) -> str:
        """Get the current precheck processing logs."""
        logs_element = self.page.locator("#processing-logs")
        if logs_element.is_visible():
            return logs_element.text_content() or ""
        return ""

    def wait_for_logs_contain(self, text: str, timeout_ms: int = 60_000) -> None:
        """Wait for precheck logs to contain specific text."""
        expect(self.page.locator("#processing-logs")).to_contain_text(
            text, timeout=timeout_ms
        )
```

**Step 2: Verify syntax**

Run: `uv run python -c "from scripts.e2e_verify.pages.project_detail import ProjectDetailPage; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add scripts/e2e_verify/pages/project_detail.py
git commit -m "feat(e2e): implement ProjectDetailPage"
```

---

## Task 8: Implement Main Script

**Files:**
- Create: `scripts/e2e_verify/main.py`

**Step 1: Create main.py with CLI and flow orchestration**

```python
"""
E2E verification script for wafer.space.

Usage:
    uv run python -m scripts.e2e_verify http://localhost:8081
    uv run python -m scripts.e2e_verify https://wafer.space
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright
from pyvirtualdisplay import Display

from .pages import (
    FileSubmitPage,
    LoginPage,
    ProjectCreatePage,
    ProjectDetailPage,
)

# ============================================================
# CONFIGURATION - Edit these values directly
# ============================================================
USERNAME = "e2e-test-user"
PASSWORD = "changeme"  # TODO: Set this or use os.environ.get("E2E_PASSWORD")

ARTIFACT_URL = (
    "https://github.com/wafer-space/gf180mcu-project-template"
    "/actions/runs/19704603402/artifacts/4686122452"
)
CORRECT_HASH = "sha256:ddce4c192bef84b45eec11e539e9f98345c16e89e8da4546c35dfe1ad663a616"
WRONG_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

# Timeouts (milliseconds)
DOWNLOAD_TIMEOUT = 5 * 60 * 1000  # 5 minutes
HASH_TIMEOUT = 60 * 1000  # 1 minute
PRECHECK_START_TIMEOUT = 10 * 60 * 1000  # 10 minutes
PRECHECK_COMPLETE_TIMEOUT = 4 * 60 * 60 * 1000  # 4 hours


def log(step: int, total: int, message: str) -> None:
    """Print timestamped log message."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] Step {step}/{total}: {message}")


def run_full_flow(base_url: str, vnc_port: int = 5901) -> bool:
    """Run the complete E2E verification flow.

    Args:
        base_url: Base URL of the wafer.space instance
        vnc_port: Port for VNC server

    Returns:
        True if all verifications passed, False otherwise
    """
    total_steps = 13

    # Start VNC server
    print("=" * 60)
    print(f"  VNC server starting on port {vnc_port}")
    print(f"  Connect to watch: vncviewer localhost:{vnc_port}")
    print("=" * 60)
    print()

    display = Display(backend="xvnc", size=(1920, 1080), rfbport=vnc_port)
    display.start()

    success = False

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)  # Visible in VNC
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
            log(2, total_steps, "Creating project with quarter slot size...")
            create_page = ProjectCreatePage(page, base_url)
            project_name = f"E2E Test {datetime.now().strftime('%Y%m%d-%H%M%S')}"
            project_id = create_page.create_project(project_name, slot_size="0p5x0p5")
            log(2, total_steps, f"Project created: {project_id}")

            # Create page objects for remaining steps
            detail_page = ProjectDetailPage(page, base_url, project_id)
            file_submit = FileSubmitPage(page, base_url, project_id)

            # ========================================
            # Step 3: Submit file with WRONG hash
            # ========================================
            log(3, total_steps, "Submitting file with wrong hash...")
            file_submit.submit_file(ARTIFACT_URL, sha256_hash=WRONG_HASH)
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
            file_submit.submit_file(ARTIFACT_URL, sha256_hash=CORRECT_HASH)
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
            file_submit.submit_file(ARTIFACT_URL, sha256_hash=CORRECT_HASH)
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
            log(13, total_steps, "Waiting for precheck to complete (this may take hours)...")
            detail_page.wait_for_precheck_complete(timeout_ms=PRECHECK_COMPLETE_TIMEOUT)

            if detail_page.is_manufacturable():
                log(13, total_steps, "Precheck PASSED - Design is manufacturable")
            else:
                log(13, total_steps, "Precheck completed - Design is NOT manufacturable")

            detail_page.screenshot("13_precheck_complete")

            success = True

            # ========================================
            # Done!
            # ========================================
            print()
            print("=" * 60)
            print("  E2E VERIFICATION COMPLETE")
            print("=" * 60)

            browser.close()

    except Exception as e:
        print()
        print("=" * 60)
        print(f"  E2E VERIFICATION FAILED: {e}")
        print("=" * 60)
        raise

    finally:
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
    args = parser.parse_args()

    success = run_full_flow(args.url, vnc_port=args.vnc_port)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
```

**Step 2: Verify syntax**

Run: `uv run python -c "from scripts.e2e_verify.main import main; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add scripts/e2e_verify/main.py
git commit -m "feat(e2e): implement main script with full 13-step flow"
```

---

## Task 9: Run Lint and Type Check

**Files:**
- Modify: Various (fix any issues)

**Step 1: Run linting**

Run: `make lint-fix`
Expected: Auto-fixes applied or no issues

**Step 2: Run type check**

Run: `make type-check`
Expected: No type errors

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "style: fix lint and type issues in e2e_verify"
```

---

## Task 10: Test Script Starts (Smoke Test)

**Files:**
- None (verification only)

**Step 1: Verify script can be imported**

Run: `uv run python -c "from scripts.e2e_verify import main; print('Import OK')"`
Expected: `Import OK`

**Step 2: Verify CLI help works**

Run: `uv run python -m scripts.e2e_verify --help`
Expected: Help text showing URL argument and --vnc-port option

**Step 3: Document in README or design doc**

The script is ready. To run:

```bash
# Install system dependency (Ubuntu/Debian)
sudo apt-get install tigervnc-standalone-server

# Run against local
uv run python -m scripts.e2e_verify http://localhost:8081

# Run against production
uv run python -m scripts.e2e_verify https://wafer.space
```

**Step 4: Final commit**

```bash
git add -A
git commit -m "docs: add e2e verification script usage instructions"
```

---

## Summary

After completing all tasks, you will have:

1. **Dependencies**: Playwright and PyVirtualDisplay added to project
2. **Package structure**: `scripts/e2e_verify/` with proper `__init__.py` and `__main__.py`
3. **Page Objects**: 5 page classes (Base, Login, ProjectCreate, FileSubmit, ProjectDetail)
4. **Main script**: Full 13-step flow with logging, screenshots, and VNC support
5. **CLI**: Simple `python -m scripts.e2e_verify <url>` interface

Total estimated tasks: 10
Total estimated commits: ~10
