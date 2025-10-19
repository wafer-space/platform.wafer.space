"""Tests for URL handler framework and implementations."""

import base64
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from wafer_space.projects.models import Project
from wafer_space.projects.services import ProjectFileService
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

        # Register Google Source handler
        google_handler = GoogleSourceHandler()
        registry.register(google_handler)

        # Test Google Source URL
        google_url = "https://example.googlesource.com/repo/+/main/file.oas"
        found = registry.get_handler(google_url)
        assert isinstance(found, GoogleSourceHandler)

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
