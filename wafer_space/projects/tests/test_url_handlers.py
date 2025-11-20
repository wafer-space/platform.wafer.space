"""Tests for URL handler framework and implementations."""

import base64
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.services import ProjectFileService
from wafer_space.projects.url_handlers import GitHubArtifactHandler
from wafer_space.projects.url_handlers import GoogleSourceHandler
from wafer_space.projects.url_handlers import URLHandler
from wafer_space.projects.url_handlers import URLHandlerRegistry


class TestURLHandler:
    """Test the abstract URLHandler base class."""

    def test_url_handler_is_abstract(self):
        """URLHandler cannot be instantiated directly."""
        # URLHandler is abstract and should not be instantiable
        # We test this by ensuring it has abstract methods
        assert hasattr(URLHandler, "can_handle")
        assert hasattr(URLHandler, "process_url")
        assert hasattr(URLHandler, "post_download")


class TestGoogleSourceHandler:
    """Test GoogleSourceHandler implementation."""

    def test_can_handle_googlesource_urls(self):
        """GoogleSourceHandler detects googlesource.com URLs."""
        handler = GoogleSourceHandler()

        # Valid googlesource.com URLs
        assert handler.can_handle(
            "https://foss-eda-tools.googlesource.com/project/+/main/file.oas",
        )
        assert handler.can_handle(
            "https://example.googlesource.com/repo/+/refs/heads/main/file.gds",
        )
        assert handler.can_handle(
            "https://chromium.googlesource.com/chromium/src/+/main/DEPS",
        )

    def test_can_handle_rejects_non_googlesource_urls(self):
        """GoogleSourceHandler rejects non-googlesource URLs."""
        handler = GoogleSourceHandler()

        # Non-googlesource URLs
        assert not handler.can_handle("https://github.com/user/repo/blob/main/file.gds")
        assert not handler.can_handle(
            "https://gitlab.com/user/repo/-/blob/main/file.oas"
        )
        assert not handler.can_handle("https://google.com/search")
        assert not handler.can_handle("https://example.com/file.gds")

    def test_process_url_adds_format_text_parameter(self):
        """GoogleSourceHandler adds ?format=TEXT to URL."""
        handler = GoogleSourceHandler()

        url = (
            "https://foss-eda-tools.googlesource.com/third_party/shuttle/"
            "gf180mcu/mpw-000/slot-001/+/refs/heads/main/"
            "tapeout/outputs/oas/caravel_18006079.oas"
        )

        result = handler.process_url(url)

        assert "url" in result
        assert "metadata" in result
        assert result["url"] == f"{url}?format=TEXT"
        assert result["metadata"]["handler"] == "GoogleSourceHandler"
        assert result["metadata"]["base64_encoded"] is True

    def test_process_url_preserves_existing_format_text(self):
        """GoogleSourceHandler doesn't add ?format=TEXT if already present."""
        handler = GoogleSourceHandler()

        url = "https://example.googlesource.com/repo/+/main/file.oas?format=TEXT"
        result = handler.process_url(url)

        # Should not add duplicate ?format=TEXT
        assert result["url"] == url
        assert result["url"].count("format=TEXT") == 1

    def test_process_url_with_existing_query_params(self):
        """GoogleSourceHandler appends format=TEXT to existing parameters."""
        handler = GoogleSourceHandler()

        url = "https://example.googlesource.com/repo/+/main/file.oas?foo=bar"
        result = handler.process_url(url)

        # Should append with & not ?
        assert result["url"] == f"{url}&format=TEXT"
        assert "foo=bar" in result["url"]
        assert "format=TEXT" in result["url"]

    def test_post_download_base64_decodes_content(self):
        """GoogleSourceHandler base64 decodes downloaded content."""
        handler = GoogleSourceHandler()

        # Create base64-encoded test data
        original_content = b"This is a test file content with binary data \x00\x01\x02"
        encoded_content = base64.b64encode(original_content)

        metadata = {
            "handler": "GoogleSourceHandler",
            "base64_encoded": True,
        }

        result = handler.post_download(encoded_content, metadata)

        assert result == original_content

    def test_post_download_handles_empty_content(self):
        """GoogleSourceHandler handles empty content correctly."""
        handler = GoogleSourceHandler()

        encoded_content = base64.b64encode(b"")
        metadata = {"handler": "GoogleSourceHandler", "base64_encoded": True}

        result = handler.post_download(encoded_content, metadata)

        assert result == b""

    def test_post_download_handles_large_content(self):
        """GoogleSourceHandler handles large base64-encoded content."""
        handler = GoogleSourceHandler()

        # Create 1MB of random-ish data
        original_content = b"x" * (1024 * 1024)
        encoded_content = base64.b64encode(original_content)

        metadata = {"handler": "GoogleSourceHandler", "base64_encoded": True}

        result = handler.post_download(encoded_content, metadata)

        assert result == original_content
        assert len(result) == 1024 * 1024


class TestGitHubArtifactHandler:
    """Test GitHubArtifactHandler implementation."""

    def test_can_handle_github_actions_urls(self):
        """GitHubArtifactHandler detects GitHub Actions run URLs."""
        handler = GitHubArtifactHandler()

        # Valid GitHub Actions URLs
        assert handler.can_handle("https://github.com/owner/repo/actions/runs/12345678")
        assert handler.can_handle(
            "https://github.com/wafer-space/platform/actions/runs/987654321"
        )
        assert handler.can_handle(
            "https://github.com/user-name/repo-name/actions/runs/1"
        )
        # With trailing path segments
        assert handler.can_handle(
            "https://github.com/owner/repo/actions/runs/12345678/attempts/1"
        )
        # Using HTTP protocol instead of HTTPS
        assert handler.can_handle("http://github.com/owner/repo/actions/runs/12345678")

    def test_can_handle_rejects_invalid_urls(self):
        """GitHubArtifactHandler rejects non-Actions URLs."""
        handler = GitHubArtifactHandler()

        # GitHub but not Actions runs
        assert not handler.can_handle("https://github.com/owner/repo")
        assert not handler.can_handle(
            "https://github.com/owner/repo/blob/main/file.txt"
        )
        assert not handler.can_handle("https://github.com/owner/repo/issues/123")
        assert not handler.can_handle("https://github.com/owner/repo/actions")
        assert not handler.can_handle(
            "https://github.com/owner/repo/actions/workflows/test.yml"
        )

        # Missing run_id
        assert not handler.can_handle("https://github.com/owner/repo/actions/runs/")
        assert not handler.can_handle("https://github.com/owner/repo/actions/runs/abc")

        # Other platforms
        assert not handler.can_handle(
            "https://gitlab.com/owner/repo/-/jobs/12345678/artifacts"
        )
        assert not handler.can_handle(
            "https://example.googlesource.com/repo/+/main/file.txt"
        )
        assert not handler.can_handle("https://example.com/file.zip")

    def test_process_url_extracts_metadata(self):
        """GitHubArtifactHandler extracts owner/repo/run_id from URL."""
        handler = GitHubArtifactHandler()

        url = "https://github.com/wafer-space/platform/actions/runs/12345678"
        result = handler.process_url(url)

        assert "url" in result
        assert "metadata" in result

        # URL should be unchanged (download task handles API calls)
        assert result["url"] == url

        # Metadata should contain extracted info
        metadata = result["metadata"]
        assert metadata["handler"] == "GitHubArtifactHandler"
        assert metadata["owner"] == "wafer-space"
        assert metadata["repo"] == "platform"
        assert metadata["run_id"] == "12345678"
        assert metadata["requires_github_auth"] is True

    def test_process_url_with_different_owners_repos(self):
        """GitHubArtifactHandler correctly parses various owner/repo combinations."""
        handler = GitHubArtifactHandler()

        test_cases = [
            (
                "https://github.com/single/simple/actions/runs/111",
                "single",
                "simple",
                "111",
            ),
            (
                "https://github.com/user-name/repo-name/actions/runs/222",
                "user-name",
                "repo-name",
                "222",
            ),
            (
                "https://github.com/org_name/repo.name/actions/runs/333",
                "org_name",
                "repo.name",
                "333",
            ),
        ]

        for url, expected_owner, expected_repo, expected_run_id in test_cases:
            result = handler.process_url(url)
            metadata = result["metadata"]
            assert metadata["owner"] == expected_owner
            assert metadata["repo"] == expected_repo
            assert metadata["run_id"] == expected_run_id

    def test_process_url_with_trailing_path(self):
        """GitHubArtifactHandler handles URLs with trailing path segments."""
        handler = GitHubArtifactHandler()

        # URL with /attempts/1 suffix
        url = "https://github.com/owner/repo/actions/runs/12345678/attempts/1"
        result = handler.process_url(url)

        # Should extract run_id correctly and ignore trailing segments
        metadata = result["metadata"]
        assert metadata["run_id"] == "12345678"
        assert metadata["owner"] == "owner"
        assert metadata["repo"] == "repo"

    def test_process_url_raises_on_invalid_format(self):
        """GitHubArtifactHandler raises ValueError for invalid URLs."""
        handler = GitHubArtifactHandler()

        # URL that doesn't match pattern
        invalid_url = "https://github.com/owner/repo/blob/main/file.txt"

        with pytest.raises(ValueError, match="Invalid GitHub Actions URL format"):
            handler.process_url(invalid_url)

    def test_post_download_passes_through_content(self):
        """GitHubArtifactHandler returns ZIP content unchanged."""
        handler = GitHubArtifactHandler()

        # Simulate ZIP file content
        fake_zip_content = b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + b"test ZIP content"

        metadata = {
            "handler": "GitHubArtifactHandler",
            "owner": "owner",
            "repo": "repo",
            "run_id": "12345678",
            "requires_github_auth": True,
        }

        result = handler.post_download(fake_zip_content, metadata)

        # Content should be unchanged
        assert result == fake_zip_content

    def test_post_download_handles_empty_content(self):
        """GitHubArtifactHandler handles empty ZIP files."""
        handler = GitHubArtifactHandler()

        metadata = {"handler": "GitHubArtifactHandler"}
        result = handler.post_download(b"", metadata)

        assert result == b""

    def test_post_download_handles_large_content(self):
        """GitHubArtifactHandler handles large artifact files."""
        handler = GitHubArtifactHandler()

        # Create 5MB of data
        large_content = b"x" * (5 * 1024 * 1024)
        metadata = {"handler": "GitHubArtifactHandler"}

        result = handler.post_download(large_content, metadata)

        assert result == large_content
        assert len(result) == 5 * 1024 * 1024


class TestURLHandlerRegistry:
    """Test URLHandlerRegistry functionality."""

    def test_register_handler(self):
        """Registry can register and store handlers."""
        registry = URLHandlerRegistry()
        handler = GoogleSourceHandler()

        registry.register(handler)

        # Should be able to get the handler back
        url = "https://example.googlesource.com/repo/+/main/file.oas"
        found_handler = registry.get_handler(url)

        assert found_handler is not None
        assert isinstance(found_handler, GoogleSourceHandler)

    def test_get_handler_returns_first_matching(self):
        """Registry returns first handler that can handle URL."""
        registry = URLHandlerRegistry()
        handler = GoogleSourceHandler()
        registry.register(handler)

        url = "https://foss-eda-tools.googlesource.com/project/+/main/file.oas"
        found_handler = registry.get_handler(url)

        assert found_handler is handler

    def test_get_handler_returns_none_for_no_match(self):
        """Registry returns None when no handler matches URL."""
        registry = URLHandlerRegistry()
        handler = GoogleSourceHandler()
        registry.register(handler)

        url = "https://github.com/user/repo/blob/main/file.gds"
        found_handler = registry.get_handler(url)

        assert found_handler is None

    def test_multiple_handlers_registration(self):
        """Registry can handle multiple registered handlers."""
        registry = URLHandlerRegistry()

        # Register both handlers
        google_handler = GoogleSourceHandler()
        github_handler = GitHubArtifactHandler()
        registry.register(google_handler)
        registry.register(github_handler)

        # Test Google Source URL
        google_url = "https://example.googlesource.com/repo/+/main/file.oas"
        found = registry.get_handler(google_url)
        assert isinstance(found, GoogleSourceHandler)

        # Test GitHub Actions URL
        github_url = "https://github.com/owner/repo/actions/runs/12345678"
        found = registry.get_handler(github_url)
        assert isinstance(found, GitHubArtifactHandler)

        # Test non-matching URL
        other_url = "https://example.com/file.gds"
        found = registry.get_handler(other_url)
        assert found is None


@pytest.mark.django_db
class TestGoogleSourceHandlerIntegration:
    """Integration tests for GoogleSourceHandler with real URL patterns."""

    def test_full_googlesource_url_workflow(self):
        """Test complete workflow: URL processing and content decoding."""
        handler = GoogleSourceHandler()

        # Step 1: Check handler recognizes URL
        original_url = (
            "https://foss-eda-tools.googlesource.com/third_party/shuttle/"
            "gf180mcu/mpw-000/slot-001/+/refs/heads/main/"
            "tapeout/outputs/oas/caravel_18006079.oas"
        )
        assert handler.can_handle(original_url)

        # Step 2: Process URL to add format=TEXT
        result = handler.process_url(original_url)
        processed_url = result["url"]
        metadata = result["metadata"]

        assert processed_url.endswith("?format=TEXT")
        assert metadata["handler"] == "GoogleSourceHandler"
        assert metadata["base64_encoded"] is True

        # Step 3: Simulate download and decode
        # Google Source returns base64-encoded content
        fake_file_content = b"GDS FILE CONTENT HERE"
        fake_response = base64.b64encode(fake_file_content)

        decoded_content = handler.post_download(fake_response, metadata)

        assert decoded_content == fake_file_content

    def test_registry_integration_with_googlesource(self):
        """Test registry integration with GoogleSourceHandler."""
        registry = URLHandlerRegistry()
        registry.register(GoogleSourceHandler())

        url = (
            "https://chromium.googlesource.com/chromium/src/+/main/"
            "chrome/browser/resources/file.oas"
        )

        # Get handler from registry
        handler = registry.get_handler(url)
        assert handler is not None

        # Process URL
        result = handler.process_url(url)
        assert "?format=TEXT" in result["url"]

        # Decode content
        original = b"test content"
        encoded = base64.b64encode(original)
        decoded = handler.post_download(encoded, result["metadata"])
        assert decoded == original


@pytest.mark.django_db
class TestGitHubArtifactHandlerIntegration:
    """Integration tests for GitHubArtifactHandler with real URL patterns."""

    def test_full_github_artifact_url_workflow(self):
        """Test complete workflow: URL detection, parsing, and pass-through."""
        handler = GitHubArtifactHandler()

        # Step 1: Check handler recognizes URL
        original_url = "https://github.com/wafer-space/platform/actions/runs/987654321"
        assert handler.can_handle(original_url)

        # Step 2: Process URL to extract metadata
        result = handler.process_url(original_url)
        processed_url = result["url"]
        metadata = result["metadata"]

        # URL should be unchanged (download task will handle API calls)
        assert processed_url == original_url
        assert metadata["handler"] == "GitHubArtifactHandler"
        assert metadata["owner"] == "wafer-space"
        assert metadata["repo"] == "platform"
        assert metadata["run_id"] == "987654321"
        assert metadata["requires_github_auth"] is True

        # Step 3: Simulate download and verify pass-through
        # GitHub artifacts come as ZIP files
        fake_artifact_zip = b"PK\x03\x04" + b"fake artifact content"
        processed_content = handler.post_download(fake_artifact_zip, metadata)

        # Content should be unchanged (no transformation like base64 decode)
        assert processed_content == fake_artifact_zip

    def test_registry_integration_with_github_artifacts(self):
        """Test registry integration with GitHubArtifactHandler."""
        registry = URLHandlerRegistry()
        registry.register(GitHubArtifactHandler())

        url = "https://github.com/owner/repo/actions/runs/12345678"

        # Get handler from registry
        handler = registry.get_handler(url)
        assert handler is not None
        assert isinstance(handler, GitHubArtifactHandler)

        # Process URL
        result = handler.process_url(url)
        assert result["url"] == url  # Unchanged
        assert result["metadata"]["owner"] == "owner"
        assert result["metadata"]["repo"] == "repo"
        assert result["metadata"]["run_id"] == "12345678"
        assert result["metadata"]["requires_github_auth"] is True

        # Pass through content
        content = b"test artifact"
        processed = handler.post_download(content, result["metadata"])
        assert processed == content

    def test_registry_distinguishes_handlers(self):
        """Test registry can distinguish between different handler types."""
        registry = URLHandlerRegistry()
        registry.register(GoogleSourceHandler())
        registry.register(GitHubArtifactHandler())

        # GitHub URL should get GitHub handler
        github_url = "https://github.com/owner/repo/actions/runs/12345678"
        handler = registry.get_handler(github_url)
        assert isinstance(handler, GitHubArtifactHandler)

        # Google Source URL should get Google handler
        google_url = "https://example.googlesource.com/repo/+/main/file.oas"
        handler = registry.get_handler(google_url)
        assert isinstance(handler, GoogleSourceHandler)


@pytest.mark.django_db
class TestServiceIntegrationWithHandlers:
    """Test ProjectFileService integration with URL handlers."""

    def test_submit_googlesource_url_stores_handler_metadata(self, user):
        """Test that submitting a googlesource.com URL stores handler metadata."""
        project = Project.objects.create(
            user=user,
            name="Test Project",
            description="Test project for handler integration",
        )

        googlesource_url = (
            "https://foss-eda-tools.googlesource.com/third_party/shuttle/"
            "gf180mcu/mpw-000/slot-001/+/refs/heads/main/"
            "tapeout/outputs/oas/caravel_18006079.oas"
        )

        # Mock both URL validation and Celery task
        with (
            patch(
                "wafer_space.projects.services.URLValidator.validate_url"
            ) as mock_validate,
            patch(
                "wafer_space.projects.services.download_project_file.delay"
            ) as mock_task,
        ):
            mock_validate.return_value = {
                "file_size": 1024,
                "content_type": "application/octet-stream",
                "supports_range": False,
            }
            mock_task.return_value = MagicMock(id="test-task-id")

            project_file, metadata = ProjectFileService.submit_file_from_url(
                project=project,
                url=googlesource_url,
                expected_hash_md5="d41d8cd98f00b204e9800998ecf8427e",
                expected_hash_sha1="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            )

        # Verify handler was detected
        assert metadata["handler_used"] == "GoogleSourceHandler"

        # Verify URL was rewritten
        assert project_file.source_url.endswith("?format=TEXT")

        # Verify handler metadata was stored
        assert project_file.handler_metadata["handler"] == "GoogleSourceHandler"
        assert project_file.handler_metadata["base64_encoded"] is True

    def test_submit_regular_url_no_handler_metadata(self, user):
        """Test that regular URLs don't get handler metadata."""
        project = Project.objects.create(
            user=user,
            name="Test Project",
            description="Test project for handler integration",
        )

        regular_url = "https://example.com/file.gds"

        # Mock both URL validation and Celery task
        with (
            patch(
                "wafer_space.projects.services.URLValidator.validate_url"
            ) as mock_validate,
            patch(
                "wafer_space.projects.services.download_project_file.delay"
            ) as mock_task,
        ):
            mock_validate.return_value = {
                "file_size": 1024,
                "content_type": "application/octet-stream",
                "supports_range": False,
            }
            mock_task.return_value = MagicMock(id="test-task-id")

            project_file, metadata = ProjectFileService.submit_file_from_url(
                project=project,
                url=regular_url,
                expected_hash_md5="d41d8cd98f00b204e9800998ecf8427e",
                expected_hash_sha1="da39a3ee5e6b4b0d3255bfef95601890afd80709",
            )

        # Verify no handler was used
        assert metadata["handler_used"] is None

        # Verify handler metadata is empty
        assert project_file.handler_metadata == {}

    def test_submit_github_artifact_url_skips_validation(self, user):
        """Test that GitHub artifact URLs skip validation and store auth metadata.

        This is a regression test for the issue where GitHub artifact URLs
        failed validation with 404 errors because they require authentication.

        Real-world example URL from TinyTapeout:
        https://github.com/TinyTapeout/tinytapeout-gf-0p2/actions/runs/19443235082/artifacts/4593571166
        """
        project = Project.objects.create(
            user=user,
            name="Test Project",
            description="Test project for GitHub artifact",
        )

        # Use the actual TinyTapeout URL from the bug report
        github_artifact_url = (
            "https://github.com/TinyTapeout/tinytapeout-gf-0p2/"
            "actions/runs/19443235082/artifacts/4593571166"
        )

        # Mock only the Celery task (URLValidator.validate_url should NOT be called)
        with patch(
            "wafer_space.projects.services.download_project_file.delay"
        ) as mock_task:
            mock_task.return_value = MagicMock(id="test-task-id")

            project_file, metadata = ProjectFileService.submit_file_from_url(
                project=project,
                url=github_artifact_url,
                expected_hash_md5="abc123def456",
                expected_hash_sha1="7df059597099bb7dcf25d2a9aedfaf4465f72d8d",
            )

        # Verify handler was used
        assert metadata["handler_used"] == "GitHubArtifactHandler"

        # Verify handler metadata was stored with correct values
        assert project_file.handler_metadata["handler"] == "GitHubArtifactHandler"
        assert project_file.handler_metadata["owner"] == "TinyTapeout"
        assert project_file.handler_metadata["repo"] == "tinytapeout-gf-0p2"
        assert project_file.handler_metadata["run_id"] == "19443235082"
        assert project_file.handler_metadata["requires_github_auth"] is True

        # Verify file was created and marked for download
        assert project_file.download_status == ProjectFile.DownloadStatus.PENDING
        assert project_file.is_active is True

        # Verify download task was started
        mock_task.assert_called_once_with(str(project.id))

        # Verify expected hashes were stored
        assert project_file.expected_hash_md5 == "abc123def456"
        expected_sha1 = "7df059597099bb7dcf25d2a9aedfaf4465f72d8d"
        assert project_file.expected_hash_sha1 == expected_sha1
