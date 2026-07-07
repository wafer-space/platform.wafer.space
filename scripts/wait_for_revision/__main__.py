"""CLI: wait until a deployed site's footer revision matches an expected value.

Examples::

    uv run python -m scripts.wait_for_revision --expected 6feb497
    uv run python -m scripts.wait_for_revision https://test-platform.wafer.space \
        --expected pull/290/head --interval 5

Polls the site footer every ``--interval`` seconds, printing a flushed status
line each time (wall-clock, elapsed wait, current revision). HTTP error pages
(404/403/503/...) are reported but do not stop the watch. Exits 0 on match, 1 on
timeout.
"""

from __future__ import annotations

import argparse
import sys

from .watcher import DEFAULT_INTERVAL_S
from .watcher import DEFAULT_URL
from .watcher import wait_for_revision


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Wait for a deployed revision by polling the site footer.",
    )
    parser.add_argument(
        "url", nargs="?", default=DEFAULT_URL, help=f"Site URL (default: {DEFAULT_URL})"
    )
    parser.add_argument(
        "-e",
        "--expected",
        required=True,
        help=(
            "Revision to wait for: a commit sha (full or short prefix), a "
            "git-describe string, or a ref like 'pull/290/head'."
        ),
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_S,
        help=f"Seconds between checks (default: {DEFAULT_INTERVAL_S}).",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        default=None,
        help="Give up after this many seconds (default: wait indefinitely).",
    )
    args = parser.parse_args()

    matched = wait_for_revision(
        args.url,
        args.expected,
        interval=args.interval,
        timeout=args.timeout,
    )
    sys.exit(0 if matched else 1)


if __name__ == "__main__":
    main()
