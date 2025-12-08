"""Utility functions for the legal app."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import frontmatter

if TYPE_CHECKING:
    from frontmatter import Post


def get_tos_versions_directory() -> Path:
    """Get the directory where TOS version files are stored.

    Returns:
        Path to the tos_versions directory.
    """
    return Path(__file__).parent / "tos_versions"


def dump_frontmatter_post(post: Post) -> str:
    """Dump a frontmatter post to a string with consistent formatting.

    This function ensures consistent output by always including a trailing
    newline. This prevents spurious file modifications during test runs
    (see GitHub issue #153).

    Args:
        post: A frontmatter Post object.

    Returns:
        String representation with YAML frontmatter and content,
        always ending with a single newline.
    """
    content = frontmatter.dumps(post)
    # Ensure exactly one trailing newline for consistency
    return content.rstrip() + "\n"


def write_frontmatter_file(file_path: Path, post: Post) -> bool:
    """Write a frontmatter post to a file, only if content changed.

    This function avoids unnecessary file modifications by comparing
    the new content with existing file content before writing.
    This prevents spurious git changes during test runs.

    Args:
        file_path: Path to the markdown file.
        post: A frontmatter Post object to write.

    Returns:
        True if file was written, False if content was unchanged.
    """
    new_content = dump_frontmatter_post(post)

    # Check if file exists and content is unchanged
    if file_path.exists():
        existing_content = file_path.read_text(encoding="utf-8")
        if existing_content == new_content:
            return False

    # Write the file
    file_path.write_text(new_content, encoding="utf-8")
    return True
