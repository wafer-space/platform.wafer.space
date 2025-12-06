"""Tests for multi-algorithm hash calculation utilities."""

from __future__ import annotations

import hashlib
import io
from typing import TYPE_CHECKING

import pytest

from wafer_space.projects.hashing import MultiHasher

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# Test constants for bytes processed assertions
HELLO_LEN = 5  # len(b"hello")
HELLO_WORLD_LEN = 11  # len(b"hello world")
LARGE_FILE_SIZE = 100_000  # Size for chunked file tests


class TestMultiHasherInit:
    """Test MultiHasher initialization."""

    def test_uses_default_algorithms(self) -> None:
        """Uses MD5, SHA1, SHA256 by default."""
        hasher = MultiHasher()
        assert hasher.algorithms == ("md5", "sha1", "sha256")

    def test_accepts_custom_algorithms_tuple(self) -> None:
        """Accepts custom algorithm tuple."""
        hasher = MultiHasher(algorithms=("sha256", "sha512"))
        assert hasher.algorithms == ("sha256", "sha512")

    def test_accepts_custom_algorithms_list(self) -> None:
        """Accepts custom algorithm list."""
        hasher = MultiHasher(algorithms=["sha256"])
        assert hasher.algorithms == ("sha256",)

    def test_starts_with_zero_bytes_processed(self) -> None:
        """Starts with zero bytes processed."""
        hasher = MultiHasher()
        assert hasher.bytes_processed == 0


class TestMultiHasherUpdate:
    """Test MultiHasher update method."""

    def test_updates_all_algorithms(self) -> None:
        """Updates all configured algorithms with data."""
        hasher = MultiHasher(algorithms=["md5", "sha256"])
        data = b"hello world"
        hasher.update(data)

        digests = hasher.hexdigests()
        assert digests["md5"] == hashlib.md5(data, usedforsecurity=False).hexdigest()
        assert digests["sha256"] == hashlib.sha256(data).hexdigest()

    def test_tracks_bytes_processed(self) -> None:
        """Tracks total bytes processed."""
        hasher = MultiHasher()
        hasher.update(b"hello")
        assert hasher.bytes_processed == HELLO_LEN
        hasher.update(b" world")
        assert hasher.bytes_processed == HELLO_WORLD_LEN

    def test_incremental_updates_match_single_update(self) -> None:
        """Multiple updates produce same hash as single update."""
        data = b"hello world"

        hasher1 = MultiHasher(algorithms=["sha256"])
        hasher1.update(data)

        hasher2 = MultiHasher(algorithms=["sha256"])
        hasher2.update(b"hello")
        hasher2.update(b" ")
        hasher2.update(b"world")

        assert hasher1.hexdigest("sha256") == hasher2.hexdigest("sha256")


class TestMultiHasherHexdigests:
    """Test MultiHasher hexdigest methods."""

    def test_hexdigests_returns_all_algorithms(self) -> None:
        """hexdigests() returns dict with all algorithm results."""
        hasher = MultiHasher()
        hasher.update(b"test")

        digests = hasher.hexdigests()
        assert "md5" in digests
        assert "sha1" in digests
        assert "sha256" in digests

    def test_hexdigest_returns_single_algorithm(self) -> None:
        """hexdigest(algorithm) returns just that hash."""
        hasher = MultiHasher()
        hasher.update(b"test")

        sha256 = hasher.hexdigest("sha256")
        assert sha256 == hashlib.sha256(b"test").hexdigest()

    def test_hexdigest_raises_for_unknown_algorithm(self) -> None:
        """hexdigest() raises KeyError for unconfigured algorithm."""
        hasher = MultiHasher(algorithms=["sha256"])

        with pytest.raises(KeyError):
            hasher.hexdigest("md5")


class TestMultiHasherMatchesHashlib:
    """Test that MultiHasher produces identical results to hashlib."""

    def test_matches_hashlib_md5(self) -> None:
        """MD5 matches hashlib.md5."""
        data = b"The quick brown fox jumps over the lazy dog"
        hasher = MultiHasher(algorithms=["md5"])
        hasher.update(data)

        expected = hashlib.md5(data, usedforsecurity=False).hexdigest()
        assert hasher.hexdigest("md5") == expected

    def test_matches_hashlib_sha1(self) -> None:
        """SHA1 matches hashlib.sha1."""
        data = b"The quick brown fox jumps over the lazy dog"
        hasher = MultiHasher(algorithms=["sha1"])
        hasher.update(data)

        expected = hashlib.sha1(data, usedforsecurity=False).hexdigest()
        assert hasher.hexdigest("sha1") == expected

    def test_matches_hashlib_sha256(self) -> None:
        """SHA256 matches hashlib.sha256."""
        data = b"The quick brown fox jumps over the lazy dog"
        hasher = MultiHasher(algorithms=["sha256"])
        hasher.update(data)

        assert hasher.hexdigest("sha256") == hashlib.sha256(data).hexdigest()

    def test_empty_data_produces_correct_hashes(self) -> None:
        """Empty input produces correct empty-string hashes."""
        hasher = MultiHasher()
        # No update calls - empty input

        expected_md5 = hashlib.md5(b"", usedforsecurity=False).hexdigest()
        assert hasher.hexdigest("md5") == expected_md5
        assert hasher.hexdigest("sha256") == hashlib.sha256(b"").hexdigest()


class TestMultiHasherFromFile:
    """Test MultiHasher.from_file class method."""

    def test_hashes_file_contents(self, tmp_path: Path) -> None:
        """Hashes file contents correctly."""
        content = b"file content for hashing"
        file_path = tmp_path / "test.txt"
        file_path.write_bytes(content)

        hasher = MultiHasher.from_file(file_path)

        assert hasher.hexdigest("sha256") == hashlib.sha256(content).hexdigest()
        assert hasher.bytes_processed == len(content)

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        """Accepts string path argument."""
        content = b"string path test"
        file_path = tmp_path / "test.txt"
        file_path.write_bytes(content)

        hasher = MultiHasher.from_file(str(file_path))

        assert hasher.hexdigest("sha256") == hashlib.sha256(content).hexdigest()

    def test_uses_custom_algorithms(self, tmp_path: Path) -> None:
        """Respects algorithms parameter."""
        content = b"custom algorithms"
        file_path = tmp_path / "test.txt"
        file_path.write_bytes(content)

        hasher = MultiHasher.from_file(file_path, algorithms=["sha512"])

        assert hasher.algorithms == ("sha512",)
        assert hasher.hexdigest("sha512") == hashlib.sha512(content).hexdigest()

    def test_handles_large_files_in_chunks(self, tmp_path: Path) -> None:
        """Correctly hashes files larger than chunk size."""
        # Create content larger than default chunk size (64KB)
        content = b"x" * LARGE_FILE_SIZE
        file_path = tmp_path / "large.bin"
        file_path.write_bytes(content)

        hasher = MultiHasher.from_file(file_path, chunk_size=1024)

        assert hasher.hexdigest("sha256") == hashlib.sha256(content).hexdigest()
        assert hasher.bytes_processed == LARGE_FILE_SIZE


class TestMultiHasherFromStream:
    """Test MultiHasher.from_stream class method."""

    def test_hashes_stream_contents(self) -> None:
        """Hashes stream contents correctly."""
        content = b"stream content"
        stream = io.BytesIO(content)

        hasher = MultiHasher.from_stream(stream)

        assert hasher.hexdigest("sha256") == hashlib.sha256(content).hexdigest()
        assert hasher.bytes_processed == len(content)

    def test_uses_custom_algorithms(self) -> None:
        """Respects algorithms parameter."""
        content = b"stream with sha512"
        stream = io.BytesIO(content)

        hasher = MultiHasher.from_stream(stream, algorithms=["sha512"])

        assert hasher.algorithms == ("sha512",)
        assert hasher.hexdigest("sha512") == hashlib.sha512(content).hexdigest()

    def test_handles_empty_stream(self) -> None:
        """Handles empty stream correctly."""
        stream = io.BytesIO(b"")

        hasher = MultiHasher.from_stream(stream)

        assert hasher.bytes_processed == 0
        assert hasher.hexdigest("sha256") == hashlib.sha256(b"").hexdigest()


class TestMultiHasherFromIterator:
    """Test MultiHasher.from_iterator class method."""

    def test_hashes_iterator_contents(self) -> None:
        """Hashes all chunks from iterator."""
        chunks = [b"hello", b" ", b"world"]

        hasher = MultiHasher.from_iterator(iter(chunks))

        expected = hashlib.sha256(b"hello world").hexdigest()
        assert hasher.hexdigest("sha256") == expected
        assert hasher.bytes_processed == HELLO_WORLD_LEN

    def test_uses_custom_algorithms(self) -> None:
        """Respects algorithms parameter."""
        chunks = [b"chunk1", b"chunk2"]

        hasher = MultiHasher.from_iterator(iter(chunks), algorithms=["md5"])

        assert hasher.algorithms == ("md5",)
        expected = hashlib.md5(b"chunk1chunk2", usedforsecurity=False).hexdigest()
        assert hasher.hexdigest("md5") == expected

    def test_handles_empty_iterator(self) -> None:
        """Handles empty iterator correctly."""

        def empty_gen() -> Iterator[bytes]:
            return iter([])

        hasher = MultiHasher.from_iterator(empty_gen())

        assert hasher.bytes_processed == 0
        assert hasher.hexdigest("sha256") == hashlib.sha256(b"").hexdigest()

    def test_handles_generator(self) -> None:
        """Works with generator functions."""

        def chunk_generator() -> Iterator[bytes]:
            yield b"first"
            yield b"second"
            yield b"third"

        hasher = MultiHasher.from_iterator(chunk_generator())

        expected = hashlib.sha256(b"firstsecondthird").hexdigest()
        assert hasher.hexdigest("sha256") == expected
