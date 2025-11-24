"""Git version information for templates.

Provides context processor to expose git commit hash in templates
for display in page headers and footers.
"""

from __future__ import annotations

import functools
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)

# GitHub repository for commit links
GITHUB_REPO_URL = "https://github.com/wafer-space/platform.wafer.space"


@functools.lru_cache(maxsize=1)
def get_git_describe() -> str | None:
    """Get the git describe output.

    Returns a human-readable version string like "v0.0-419-gcd24a35"
    which includes the most recent tag, number of commits since,
    and abbreviated commit hash. Returns None if unavailable.
    Result is cached for the lifetime of the process.
    """
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
        logger.warning("Failed to get git describe: %s", exc)
        return None


@functools.lru_cache(maxsize=1)
def get_git_commit_hash() -> str | None:
    """Get the current git commit hash.

    Returns the full 40-character SHA hash, or None if unavailable.
    Result is cached for the lifetime of the process since
    the commit hash won't change during runtime.
    """
    # First, try reading from .git/HEAD directly (fastest, no subprocess)
    base_dir = getattr(settings, "BASE_DIR", None)
    if base_dir:
        git_head_path = Path(base_dir) / ".git" / "HEAD"
        try:
            head_content = git_head_path.read_text().strip()
        except (OSError, FileNotFoundError):
            head_content = None

        if head_content:
            if head_content.startswith("ref: "):
                # HEAD points to a branch, resolve the ref
                ref_path = Path(base_dir) / ".git" / head_content[5:]
                try:
                    return ref_path.read_text().strip()
                except (OSError, FileNotFoundError):
                    pass
            else:
                # HEAD is detached, contains the hash directly
                return head_content

    # Fallback: use git command (works in more edge cases)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
        logger.warning("Failed to get git commit hash: %s", exc)
        return None


def git_info(request: HttpRequest) -> dict[str, str | None]:
    """Context processor that provides git commit information.

    Adds to template context:
        - GIT_DESCRIBE: Human-readable version (e.g., "v0.0-419-gcd24a35")
        - GIT_COMMIT_HASH: Full 40-character SHA hash
        - GIT_COMMIT_SHORT: Short 7-character SHA hash
        - GIT_COMMIT_URL: URL to view the commit on GitHub
    """
    commit_hash = get_git_commit_hash()
    git_describe = get_git_describe()

    if commit_hash:
        return {
            "GIT_DESCRIBE": git_describe,
            "GIT_COMMIT_HASH": commit_hash,
            "GIT_COMMIT_SHORT": commit_hash[:7],
            "GIT_COMMIT_URL": f"{GITHUB_REPO_URL}/commit/{commit_hash}",
        }

    return {
        "GIT_DESCRIBE": None,
        "GIT_COMMIT_HASH": None,
        "GIT_COMMIT_SHORT": None,
        "GIT_COMMIT_URL": None,
    }
