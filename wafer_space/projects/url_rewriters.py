"""URL rewriting utilities for common file hosting platforms.

Automatically converts web interface URLs to direct download URLs for:
- GitHub (blob → raw)
- GitLab (blob → raw)
- Dropbox (share → direct download)
- Google Drive (share → direct download)
- OneDrive (share → direct download)
"""

import re
from urllib.parse import parse_qs
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.parse import urlunparse


class URLRewriter:
    """Rewrite common URL patterns to direct download URLs."""

    @classmethod
    def rewrite_url(cls, url: str) -> tuple[str, bool, str]:
        """Rewrite URL to direct download link.

        Args:
            url: The original URL

        Returns:
            tuple: (rewritten_url, was_rewritten, rewrite_reason)
        """
        # Try each rewriter in order
        rewriters = [
            cls._rewrite_github_blob,
            cls._rewrite_gitlab_blob,
            cls._rewrite_dropbox_share,
            cls._rewrite_google_drive_share,
            cls._rewrite_onedrive_share,
        ]

        for rewriter in rewriters:
            new_url, rewritten, reason = rewriter(url)
            if rewritten:
                return new_url, True, reason

        return url, False, ""

    @staticmethod
    def _rewrite_github_blob(url: str) -> tuple[str, bool, str]:
        """Rewrite GitHub blob URL to raw content URL.

        Examples:
            https://github.com/user/repo/blob/main/file.gds
            → https://raw.githubusercontent.com/user/repo/main/file.gds
        """
        parsed = urlparse(url)

        if parsed.netloc == "github.com":
            match = re.match(
                r"^/([^/]+)/([^/]+)/blob/(.+)$",
                parsed.path,
            )
            if match:
                user, repo, rest = match.groups()
                new_url = f"https://raw.githubusercontent.com/{user}/{repo}/{rest}"
                return new_url, True, "Converted GitHub blob URL to raw content URL"

        return url, False, ""

    @staticmethod
    def _rewrite_gitlab_blob(url: str) -> tuple[str, bool, str]:
        """Rewrite GitLab blob URL to raw content URL.

        Examples:
            https://gitlab.com/user/repo/-/blob/main/file.gds
            → https://gitlab.com/user/repo/-/raw/main/file.gds
        """
        parsed = urlparse(url)

        if "gitlab" in parsed.netloc:
            if "/-/blob/" in parsed.path:
                new_url = url.replace("/-/blob/", "/-/raw/")
                return new_url, True, "Converted GitLab blob URL to raw content URL"

        return url, False, ""

    @staticmethod
    def _rewrite_dropbox_share(url: str) -> tuple[str, bool, str]:
        """Rewrite Dropbox share link to direct download.

        Examples:
            https://www.dropbox.com/s/abc123/file.gds?dl=0
            → https://www.dropbox.com/s/abc123/file.gds?dl=1
        """
        parsed = urlparse(url)

        if "dropbox.com" in parsed.netloc:
            # Parse query parameters
            params = parse_qs(parsed.query)

            # Change dl=0 to dl=1 for direct download
            if "dl" in params and params["dl"][0] == "0":
                params["dl"] = ["1"]
                new_query = urlencode(params, doseq=True)
                new_url = urlunparse((
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    new_query,
                    parsed.fragment,
                ))
                return new_url, True, "Converted Dropbox share link to direct download"

        return url, False, ""

    @staticmethod
    def _rewrite_google_drive_share(url: str) -> tuple[str, bool, str]:
        """Rewrite Google Drive share link to direct download.

        Examples:
            https://drive.google.com/file/d/FILE_ID/view?usp=sharing
            → https://drive.google.com/uc?export=download&id=FILE_ID
        """
        parsed = urlparse(url)

        if "drive.google.com" in parsed.netloc:
            # Check if already in direct download format
            params = parse_qs(parsed.query)
            is_direct_download = (
                parsed.path == "/uc"
                and "export" in params
                and "download" in params.get("export", [])
            )
            if is_direct_download:
                # Already a direct download URL
                return url, False, ""

            # Extract file ID from various Google Drive URL formats
            file_id = None

            # Format 1: /file/d/FILE_ID/
            match = re.search(r"/file/d/([^/]+)", parsed.path)
            if match:
                file_id = match.group(1)

            # Format 2: /open?id=FILE_ID
            if not file_id and "id" in params:
                file_id = params["id"][0]

            if file_id:
                new_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                return (
                    new_url,
                    True,
                    "Converted Google Drive share link to direct download",
                )


        return url, False, ""

    @staticmethod
    def _rewrite_onedrive_share(url: str) -> tuple[str, bool, str]:
        """Rewrite OneDrive/SharePoint share link to direct download.

        Examples:
            https://onedrive.live.com/...?e=abc123
            → https://onedrive.live.com/download?...&download=1
        """
        parsed = urlparse(url)

        if "onedrive.live.com" in parsed.netloc or "1drv.ms" in parsed.netloc:
            # OneDrive direct download format
            if "download" not in parsed.path:
                # Add download parameter
                params = parse_qs(parsed.query)
                params["download"] = ["1"]
                new_query = urlencode(params, doseq=True)
                new_url = urlunparse((
                    parsed.scheme,
                    parsed.netloc,
                    parsed.path,
                    parsed.params,
                    new_query,
                    parsed.fragment,
                ))
                return new_url, True, "Converted OneDrive share link to direct download"

        return url, False, ""
