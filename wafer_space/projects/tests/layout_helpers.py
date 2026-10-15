"""Layout files for top-cell tests, written with gdstk (#78)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gdstk

if TYPE_CHECKING:
    from pathlib import Path

# Deeper than Python's default recursion limit of 1000.
DEEP_LEVELS = 2000


def chain(length: int) -> dict[str, list[str]]:
    """C0 references C1, which references C2, ... down to C<length - 1>."""
    hierarchy: dict[str, list[str]] = {
        f"C{i}": [f"C{i + 1}"] for i in range(length - 1)
    }
    hierarchy[f"C{length - 1}"] = []
    return hierarchy


def write_layout(
    path: Path,
    hierarchy: dict[str, list[str]],
) -> Path:
    """Write a layout whose cells reference each other as `hierarchy` says.

    Each key is a cell; its list names the cells it references. Every cell
    also gets one rectangle, so no cell is empty. The format follows the
    suffix of `path` (.gds or .oas).
    """
    cells = {name: gdstk.Cell(name) for name in hierarchy}
    for name, children in hierarchy.items():
        cells[name].add(gdstk.rectangle((0, 0), (1, 1)))
        for child in children:
            cells[name].add(gdstk.Reference(cells[child]))
    library = gdstk.Library()
    library.add(*cells.values())
    if path.suffix == ".oas":
        library.write_oas(str(path))
    else:
        library.write_gds(str(path))
    return path
