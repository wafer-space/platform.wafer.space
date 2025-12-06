"""Multi-algorithm hash calculation utilities."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import BinaryIO


class MultiHasher:
    """Calculate multiple hash algorithms simultaneously from a byte stream.

    This class provides a hashlib-compatible interface that calculates
    multiple hashes in a single pass through the data, avoiding the need
    to read large files multiple times.

    Example:
        # Calculate hashes while streaming to disk
        hasher = MultiHasher()
        with open("output.tar", "wb") as f:
            for chunk in docker_stream:
                hasher.update(chunk)
                f.write(chunk)
        hashes = hasher.hexdigests()
        # {"md5": "...", "sha1": "...", "sha256": "..."}

        # Single hash mode
        hasher = MultiHasher(algorithms=["sha256"])
        hashes = hasher.hexdigests()
        # {"sha256": "..."}
    """

    DEFAULT_ALGORITHMS: tuple[str, ...] = ("md5", "sha1", "sha256")
    DEFAULT_CHUNK_SIZE: int = 65536  # 64KB

    def __init__(
        self,
        algorithms: tuple[str, ...] | list[str] | None = None,
    ) -> None:
        """Initialize with specified hash algorithms.

        Args:
            algorithms: Hash algorithm names (e.g., ["sha256"] or
                ["md5", "sha1", "sha256"]). Defaults to MD5 + SHA1 + SHA256
                for compatibility with ProjectFile.
        """
        if algorithms is None:
            algorithms = self.DEFAULT_ALGORITHMS
        self._hashers = {alg: hashlib.new(alg) for alg in algorithms}
        self._bytes_processed = 0

    def update(self, data: bytes) -> None:
        """Update all hash algorithms with new data.

        Args:
            data: Bytes to hash
        """
        for hasher in self._hashers.values():
            hasher.update(data)
        self._bytes_processed += len(data)

    def hexdigests(self) -> dict[str, str]:
        """Return hex digests for all algorithms.

        Returns:
            Dict mapping algorithm name to hex digest string
        """
        return {alg: hasher.hexdigest() for alg, hasher in self._hashers.items()}

    def hexdigest(self, algorithm: str) -> str:
        """Return hex digest for a specific algorithm.

        Args:
            algorithm: Algorithm name (e.g., "sha256")

        Returns:
            Hex digest string

        Raises:
            KeyError: If algorithm not in configured algorithms
        """
        return self._hashers[algorithm].hexdigest()

    @property
    def bytes_processed(self) -> int:
        """Total bytes processed so far."""
        return self._bytes_processed

    @property
    def algorithms(self) -> tuple[str, ...]:
        """Configured algorithm names."""
        return tuple(self._hashers.keys())

    @classmethod
    def from_file(
        cls,
        file_path: Path | str,
        algorithms: tuple[str, ...] | list[str] | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> MultiHasher:
        """Create hasher and process entire file.

        Args:
            file_path: Path to file to hash
            algorithms: Hash algorithms to use
            chunk_size: Read buffer size

        Returns:
            MultiHasher with computed hashes
        """
        hasher = cls(algorithms=algorithms)
        path = Path(file_path) if not isinstance(file_path, Path) else file_path
        with path.open("rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher

    @classmethod
    def from_stream(
        cls,
        stream: BinaryIO,
        algorithms: tuple[str, ...] | list[str] | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> MultiHasher:
        """Create hasher and process entire stream.

        Args:
            stream: Binary stream to read from
            algorithms: Hash algorithms to use
            chunk_size: Read buffer size

        Returns:
            MultiHasher with computed hashes
        """
        hasher = cls(algorithms=algorithms)
        while chunk := stream.read(chunk_size):
            hasher.update(chunk)
        return hasher

    @classmethod
    def from_iterator(
        cls,
        iterator: Iterator[bytes],
        algorithms: tuple[str, ...] | list[str] | None = None,
    ) -> MultiHasher:
        """Create hasher and process byte chunks from iterator.

        Args:
            iterator: Iterator yielding byte chunks
            algorithms: Hash algorithms to use

        Returns:
            MultiHasher with computed hashes
        """
        hasher = cls(algorithms=algorithms)
        for chunk in iterator:
            hasher.update(chunk)
        return hasher
