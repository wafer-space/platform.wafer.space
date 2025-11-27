"""Hostname information for templates.

Provides context processor to expose server hostname in templates
for display in page headers and footers. Useful for identifying
which server is serving requests in multi-server deployments.
"""

from __future__ import annotations

import functools
import logging
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def get_hostname() -> str | None:
    """Get the server hostname using hostname -A.

    Returns the raw output from `hostname -A`, stripped of leading/trailing
    whitespace. Returns None if unavailable. Result is cached for the
    lifetime of the process since the hostname won't change during runtime.
    """
    try:
        result = subprocess.run(
            ["hostname", "-A"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
        logger.warning("Failed to get hostname: %s", exc)
        return None
    else:
        output = result.stdout.strip()
        return output if output else None


def hostname_info(_request: HttpRequest) -> dict[str, str | None]:
    """Context processor that provides hostname information.

    Adds to template context:
        - SERVER_HOSTNAME: The FQDN of the server, or None if unavailable
    """
    return {
        "SERVER_HOSTNAME": get_hostname(),
    }
