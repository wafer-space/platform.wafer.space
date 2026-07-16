"""Wait for a deployed revision by polling a site footer.

Run as ``python -m scripts.wait_for_revision --expected <rev>``.
"""

from __future__ import annotations

from .watcher import Revision
from .watcher import fetch_revision
from .watcher import parse_revision
from .watcher import wait_for_revision

__all__ = ["Revision", "fetch_revision", "parse_revision", "wait_for_revision"]
