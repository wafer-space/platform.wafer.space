"""Names shared by the request log middleware and its admin (#379)."""

from __future__ import annotations

import re

# Logged for every visitor, logged in or not: a failed or redirected fetch
# of a file is still an attempt to fetch it.
FILE_VIEW_NAMES = frozenset(
    {
        "projects:check_artifact",
        "projects:check_log",
        "projects:file_download",
    }
)

# nginx's $request_id format, and the format of ids generated here.
REQUEST_ID_RE = re.compile(r"[0-9a-f]{32}")
