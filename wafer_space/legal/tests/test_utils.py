"""Tests for legal app utility functions."""

import tempfile
from pathlib import Path

import frontmatter

from wafer_space.legal.utils import dump_frontmatter_post
from wafer_space.legal.utils import write_frontmatter_file


class TestDumpFrontmatterPost:
    """Tests for dump_frontmatter_post function."""

    def test_ensures_trailing_newline(self):
        """Verify output always ends with exactly one newline."""
        post = frontmatter.Post("Test content")
        post.metadata["version"] = "1.0.0"

        result = dump_frontmatter_post(post)

        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_strips_extra_trailing_newlines(self):
        """Verify multiple trailing newlines are normalized to one."""
        # Content with trailing newlines
        post = frontmatter.Post("Test content\n\n\n")
        post.metadata["version"] = "1.0.0"

        result = dump_frontmatter_post(post)

        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_with_empty_content(self):
        """Verify handling of empty content."""
        post = frontmatter.Post("")
        post.metadata["version"] = "1.0.0"

        result = dump_frontmatter_post(post)

        assert result.endswith("\n")
        assert "version: 1.0.0" in result

    def test_preserves_frontmatter_metadata(self):
        """Verify all metadata is preserved in output."""
        post = frontmatter.Post("# Test\n\nContent here.")
        post.metadata["version"] = "2.0.0"
        post.metadata["is_active"] = True
        post.metadata["description"] = "Test description"

        result = dump_frontmatter_post(post)

        assert "version: 2.0.0" in result
        assert "is_active: true" in result
        assert "description: Test description" in result
        assert "# Test" in result
        assert "Content here." in result


class TestWriteFrontmatterFile:
    """Tests for write_frontmatter_file function."""

    def test_creates_new_file(self):
        """Verify new file is created when it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.md"
            post = frontmatter.Post("Test content")
            post.metadata["version"] = "1.0.0"

            result = write_frontmatter_file(file_path, post)

            assert result is True
            assert file_path.exists()
            content = file_path.read_text(encoding="utf-8")
            assert "version: 1.0.0" in content
            assert "Test content" in content

    def test_returns_false_when_content_unchanged(self):
        """Verify returns False when file content matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.md"
            post = frontmatter.Post("Test content")
            post.metadata["version"] = "1.0.0"

            # First write
            write_frontmatter_file(file_path, post)

            # Second write with same content
            result = write_frontmatter_file(file_path, post)

            assert result is False

    def test_returns_true_when_content_changed(self):
        """Verify returns True when file content differs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.md"
            post = frontmatter.Post("Test content")
            post.metadata["version"] = "1.0.0"
            post.metadata["is_active"] = True

            # First write
            write_frontmatter_file(file_path, post)

            # Change content
            post.metadata["is_active"] = False
            result = write_frontmatter_file(file_path, post)

            assert result is True

    def test_updates_file_when_content_changed(self):
        """Verify file is updated when content changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.md"
            post = frontmatter.Post("Original content")
            post.metadata["version"] = "1.0.0"

            write_frontmatter_file(file_path, post)

            # Update content
            post = frontmatter.Post("Updated content")
            post.metadata["version"] = "1.0.0"
            write_frontmatter_file(file_path, post)

            content = file_path.read_text(encoding="utf-8")
            assert "Updated content" in content
            assert "Original content" not in content

    def test_file_ends_with_newline(self):
        """Verify written file ends with newline."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.md"
            post = frontmatter.Post("Test content")
            post.metadata["version"] = "1.0.0"

            write_frontmatter_file(file_path, post)

            content = file_path.read_text(encoding="utf-8")
            assert content.endswith("\n")

    def test_handles_unicode_content(self):
        """Verify UTF-8 content is handled correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.md"
            post = frontmatter.Post("Contenu français avec des accents: é, è, à, ç")
            post.metadata["description"] = "日本語テスト"

            result = write_frontmatter_file(file_path, post)

            assert result is True
            content = file_path.read_text(encoding="utf-8")
            assert "Contenu français" in content
            assert "日本語テスト" in content
