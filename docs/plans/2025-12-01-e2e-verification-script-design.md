# E2E Verification Script Design

**Date:** 2025-12-01
**Status:** Draft

## Overview

A standalone Python script that verifies the primary user flow works correctly on a live wafer.space deployment. The script uses Playwright for browser automation and runs inside a VNC server so operators can connect and watch progress.

## Goals

1. Verify the complete user journey: login → create project → upload file → download → hash verification → manufacturability precheck
2. Run against any environment (local, staging, production) via URL parameter
3. Allow operators to connect via VNC to watch the test in real-time
4. Handle long-running operations (precheck can take hours)

## Non-Goals

- Not a replacement for existing pytest browser tests
- Not a CI/CD integration (runs manually in tmux)
- No configuration files - edit the script directly

## Technology Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Browser automation | **Playwright** | Modern, auto-wait, faster than Selenium, role-based locators |
| Virtual display | **PyVirtualDisplay** (xvnc backend) | VNC-accessible, allows remote viewing |
| Python version | 3.11+ | Match existing project |

## Architecture

```
scripts/
└── e2e_verify/
    ├── __init__.py
    ├── __main__.py          # Entry point for `python -m e2e_verify`
    ├── main.py              # CLI and main flow orchestration
    └── pages/               # Page Object Models
        ├── __init__.py
        ├── base.py          # BasePage with common methods
        ├── login.py         # LoginPage
        ├── project_create.py
        ├── project_detail.py
        └── file_submit.py
```

### Page Object Model

Playwright officially recommends the Page Object Model pattern. Each page class:
- Encapsulates locators using role-based selectors (`get_by_role`, `get_by_label`, `get_by_text`)
- Uses `expect()` with timeouts for waiting (auto-retries)
- Provides high-level methods for user actions

### VNC Server

The script automatically starts a VNC server before launching the browser:

```python
from pyvirtualdisplay import Display

display = Display(backend="xvnc", size=(1920, 1080), rfbport=5901)
display.start()
# Browser runs visibly inside VNC
# User connects with: vncviewer localhost:5901
```

## Test Flow (13 Steps)

| Step | Action | Verification |
|------|--------|--------------|
| 1 | Login | Redirects away from login page |
| 2 | Create project (quarter slot) | Project UUID in URL |
| 3 | Submit file with **wrong** hash | Form submits |
| 4 | Wait for download | "Downloaded" badge + "Hash Mismatch" badge |
| 5 | Submit file with **correct** hash | Form submits |
| 6 | Wait for download | "Downloaded" badge + "Hash Verified" badge |
| 7 | Wait for precheck to start | "Checking..." badge visible |
| 8 | Check logs appear | `#processing-logs` contains text |
| 9 | Cancel precheck | "Check Cancelled" badge |
| 10 | Submit file again (correct hash) | Form submits |
| 11 | Wait for download + hash | Badges visible |
| 12 | Wait for precheck to start | "Checking..." badge |
| 13 | Wait for precheck to complete | "Manufacturable" or "Not Manufacturable" badge |

## Usage

```bash
# Install dependencies
uv add playwright pyvirtualdisplay
playwright install chromium

# System dependencies (Ubuntu/Debian)
sudo apt-get install tigervnc-standalone-server

# Run against local
uv run python -m e2e_verify http://localhost:8081

# Run against production
uv run python -m e2e_verify https://wafer.space

# Custom VNC port
uv run python -m e2e_verify https://wafer.space --vnc-port 5902
```

## Configuration

Edit constants at the top of `main.py`:

```python
USERNAME = "e2e-test-user"
PASSWORD = "changeme"

ARTIFACT_URL = "https://github.com/wafer-space/gf180mcu-project-template/actions/runs/19704603402/artifacts/4686122452"
CORRECT_HASH = "sha256:ddce4c192bef84b45eec11e539e9f98345c16e89e8da4546c35dfe1ad663a616"
WRONG_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

# Timeouts (milliseconds)
DOWNLOAD_TIMEOUT = 5 * 60 * 1000        # 5 minutes
PRECHECK_COMPLETE_TIMEOUT = 4 * 60 * 60 * 1000  # 4 hours
```

## Timeouts

| Operation | Default Timeout | Rationale |
|-----------|-----------------|-----------|
| Download | 5 minutes | GitHub artifacts can be slow |
| Hash verification | 1 minute | Quick operation |
| Precheck queue wait | 10 minutes | Queue may have other jobs |
| Precheck completion | 4 hours | Manufacturing checks are slow |

## Output

- Timestamped console logs for each step
- Screenshots saved to `screenshots/` at key points
- Final pass/fail summary

Example output:
```
============================================================
  VNC server starting on port 5901
  Connect to watch: vncviewer localhost:5901
============================================================

[14:32:01] Step 1/13: Logging in...
[14:32:05] Step 1/13: Login successful ✓
[14:32:05] Step 2/13: Creating project with quarter slot size...
[14:32:08] Step 2/13: Project created: a1b2c3d4-... ✓
...
[18:45:23] Step 13/13: Precheck PASSED - Design is manufacturable ✓

============================================================
  E2E VERIFICATION COMPLETE
============================================================
```

## Dependencies

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
e2e = [
    "playwright>=1.40",
    "pyvirtualdisplay>=3.0",
]
```

## Future Enhancements

- Add `--scenario` flag to run specific scenarios (e.g., just wrong hash test)
- JSON output for integration with monitoring systems
- Slack/email notifications on failure
- Multiple test users for parallel testing
