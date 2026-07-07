"""Read-size instrumentation helpers for streaming tests.

These wrappers record the ``size`` argument of every ``read()`` call so
tests can assert that large files are processed in bounded chunks instead
of being read fully into memory (the pattern fixed for precheck output
extraction in #275, applied here to the download pipeline).

Note: ``RecordingPath`` only observes reads made through ``Path.open()``.
Code that opens the path via ``os.fspath()`` (e.g. ``zipfile.ZipFile``,
``tarfile.open``) bypasses the recorder, so a bounded-reads assertion
covers our own file handling, not the stdlib archive internals.
"""

from __future__ import annotations

from pathlib import Path
from typing import IO
from typing import Any
from typing import Self


class ReadSizeRecorder:
    """Wrap a binary file object and record every read() size argument."""

    def __init__(self, inner: IO[bytes], read_sizes: list[int]) -> None:
        self._inner = inner
        self._read_sizes = read_sizes

    def read(self, size: int = -1) -> bytes:
        self._read_sizes.append(size)
        return self._inner.read(size)

    def write(self, data: bytes) -> int:
        return self._inner.write(data)

    def seek(self, *args: int) -> int:
        return self._inner.seek(*args)

    def tell(self) -> int:
        return self._inner.tell()

    def close(self) -> None:
        self._inner.close()

    @property
    def closed(self) -> bool:
        return self._inner.closed

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._inner.close()


class RecordingPath(Path):
    """Path whose open() wraps the file in a ReadSizeRecorder.

    Attach the target list after construction::

        path = RecordingPath(real_path)
        path.read_sizes = sizes
    """

    read_sizes: list[int]

    def open(self, *args: Any, **kwargs: Any) -> Any:
        inner = super().open(*args, **kwargs)
        return ReadSizeRecorder(inner, self.read_sizes)
