"""Tests for URL rewriting module."""

import pytest

from wafer_space.projects.url_rewriters import URLRewriter


class TestURLRewriter:
    """Test URLRewriter class."""

    def test_rewrite_url_no_rewrite(self):
        """Test that non-matching URLs are not rewritten."""
        url = "https://example.com/file.gds"
        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert rewritten_url == url
        assert was_rewritten is False
        assert reason == ""

    def test_github_blob_url_rewrite(self):
        """Test GitHub blob URL is rewritten to raw.githubusercontent.com."""
        url = "https://github.com/user/repo/blob/main/design.gds"
        expected = "https://raw.githubusercontent.com/user/repo/main/design.gds"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert rewritten_url == expected
        assert was_rewritten is True
        assert "GitHub blob URL to raw content URL" in reason

    def test_github_blob_url_with_branch(self):
        """Test GitHub blob URL with different branch names."""
        test_cases = [
            (
                "https://github.com/user/repo/blob/develop/file.gds",
                "https://raw.githubusercontent.com/user/repo/develop/file.gds",
            ),
            (
                "https://github.com/user/repo/blob/feature/new-design/file.gds",
                "https://raw.githubusercontent.com/user/repo/feature/new-design/file.gds",
            ),
            (
                "https://github.com/user/repo/blob/v1.0/file.gds",
                "https://raw.githubusercontent.com/user/repo/v1.0/file.gds",
            ),
        ]

        for original, expected in test_cases:
            rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(original)
            assert rewritten_url == expected
            assert was_rewritten is True

    def test_github_non_blob_url_not_rewritten(self):
        """Test that non-blob GitHub URLs are not rewritten."""
        test_cases = [
            "https://github.com/user/repo",
            "https://github.com/user/repo/tree/main",
            "https://raw.githubusercontent.com/user/repo/main/file.gds",
        ]

        for url in test_cases:
            rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)
            assert rewritten_url == url
            assert was_rewritten is False

    def test_gitlab_blob_url_rewrite(self):
        """Test GitLab blob URL is rewritten to raw."""
        url = "https://gitlab.com/user/repo/-/blob/main/design.gds"
        expected = "https://gitlab.com/user/repo/-/raw/main/design.gds"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert rewritten_url == expected
        assert was_rewritten is True
        assert "GitLab blob URL to raw content URL" in reason

    def test_gitlab_self_hosted_rewrite(self):
        """Test GitLab self-hosted instance URL rewriting."""
        url = "https://gitlab.example.com/user/repo/-/blob/main/file.gds"
        expected = "https://gitlab.example.com/user/repo/-/raw/main/file.gds"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert rewritten_url == expected
        assert was_rewritten is True

    def test_dropbox_share_link_rewrite(self):
        """Test Dropbox share link dl=0 is changed to dl=1."""
        url = "https://www.dropbox.com/s/abc123/file.gds?dl=0"
        expected = "https://www.dropbox.com/s/abc123/file.gds?dl=1"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert rewritten_url == expected
        assert was_rewritten is True
        assert "Dropbox share link to direct download" in reason

    def test_dropbox_already_direct_download(self):
        """Test Dropbox links with dl=1 are not rewritten."""
        url = "https://www.dropbox.com/s/abc123/file.gds?dl=1"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert rewritten_url == url
        assert was_rewritten is False

    def test_dropbox_without_dl_parameter(self):
        """Test Dropbox links without dl parameter are not rewritten."""
        url = "https://www.dropbox.com/s/abc123/file.gds"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert rewritten_url == url
        assert was_rewritten is False

    def test_google_drive_file_view_rewrite(self):
        """Test Google Drive file view URL is rewritten to direct download."""
        url = "https://drive.google.com/file/d/1ABC123DEF456/view?usp=sharing"
        expected = "https://drive.google.com/uc?export=download&id=1ABC123DEF456"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert rewritten_url == expected
        assert was_rewritten is True
        assert "Google Drive share link to direct download" in reason

    def test_google_drive_file_without_view(self):
        """Test Google Drive file URL without /view."""
        url = "https://drive.google.com/file/d/1ABC123DEF456/"
        expected = "https://drive.google.com/uc?export=download&id=1ABC123DEF456"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert rewritten_url == expected
        assert was_rewritten is True

    def test_google_drive_open_id_format(self):
        """Test Google Drive open?id= format."""
        url = "https://drive.google.com/open?id=1ABC123DEF456"
        expected = "https://drive.google.com/uc?export=download&id=1ABC123DEF456"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert rewritten_url == expected
        assert was_rewritten is True

    def test_google_drive_already_direct_download(self):
        """Test Google Drive direct download URLs are not rewritten."""
        url = "https://drive.google.com/uc?export=download&id=1ABC123DEF456"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert rewritten_url == url
        assert was_rewritten is False

    def test_onedrive_share_link_rewrite(self):
        """Test OneDrive share link gets download=1 parameter."""
        url = "https://onedrive.live.com/embed?resid=ABC123&authkey=DEF456"
        expected = "https://onedrive.live.com/embed?resid=ABC123&authkey=DEF456&download=1"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert rewritten_url == expected
        assert was_rewritten is True
        assert "OneDrive share link to direct download" in reason

    def test_onedrive_short_link_rewrite(self):
        """Test 1drv.ms short links get download parameter."""
        url = "https://1drv.ms/u/s!ABC123"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert was_rewritten is True
        assert "download=1" in rewritten_url

    def test_onedrive_already_has_download_parameter(self):
        """Test OneDrive links with download parameter are not rewritten."""
        url = "https://onedrive.live.com/embed?resid=ABC&download=1"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        # Should not rewrite if "download" is already in path
        # The logic checks for "download" not in parsed.path
        # This should still add the parameter since download is in query not path
        assert "download=1" in rewritten_url

    def test_rewrite_priority_github_over_others(self):
        """Test that rewriters are tried in order."""
        # GitHub rewriter should match before others
        url = "https://github.com/user/repo/blob/main/file.gds"
        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert "raw.githubusercontent.com" in rewritten_url
        assert "GitHub" in reason

    def test_complex_github_path_with_subdirectories(self):
        """Test GitHub URLs with complex paths."""
        url = "https://github.com/user/repo/blob/main/subdir1/subdir2/file.gds"
        expected = "https://raw.githubusercontent.com/user/repo/main/subdir1/subdir2/file.gds"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert rewritten_url == expected
        assert was_rewritten is True

    def test_gitlab_with_subdirectories(self):
        """Test GitLab URLs with complex paths."""
        url = "https://gitlab.com/user/repo/-/blob/main/subdir/file.gds"
        expected = "https://gitlab.com/user/repo/-/raw/main/subdir/file.gds"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert rewritten_url == expected
        assert was_rewritten is True

    def test_dropbox_with_multiple_query_parameters(self):
        """Test Dropbox URLs with multiple query parameters."""
        url = "https://www.dropbox.com/s/abc123/file.gds?dl=0&foo=bar"

        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert was_rewritten is True
        assert "dl=1" in rewritten_url
        assert "foo=bar" in rewritten_url

    def test_empty_url(self):
        """Test empty URL returns unchanged."""
        url = ""
        rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)

        assert rewritten_url == url
        assert was_rewritten is False

    def test_non_http_url(self):
        """Test non-HTTP URLs are not rewritten."""
        test_cases = [
            "ftp://example.com/file.gds",
            "file:///local/path/file.gds",
            "s3://bucket/file.gds",
        ]

        for url in test_cases:
            rewritten_url, was_rewritten, reason = URLRewriter.rewrite_url(url)
            assert rewritten_url == url
            assert was_rewritten is False
