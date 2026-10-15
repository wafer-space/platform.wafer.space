"""Tests for the top-cell extractor (wafer_space/projects/processors)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gdstk
import pytest

from wafer_space.projects.processors.top_cell_extractor import TopCellExtractor
from wafer_space.projects.processors.top_cell_extractor import extract_top_cell

if TYPE_CHECKING:
    from pathlib import Path


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


@pytest.mark.parametrize("suffix", [".gds", ".oas"])
def test_single_top_cell_is_returned(tmp_path: Path, suffix: str) -> None:
    """The one cell nothing references is the top cell."""
    path = write_layout(
        tmp_path / f"design{suffix}",
        {"TOP": ["MID"], "MID": ["LEAF"], "LEAF": []},
    )

    assert TopCellExtractor().extract(path) == "TOP"


def test_deepest_of_several_top_cells_wins(tmp_path: Path) -> None:
    """With several top cells, the one with the deepest hierarchy wins."""
    path = write_layout(
        tmp_path / "design.gds",
        {
            "A_SHALLOW": ["LEAF"],
            "Z_DEEP": ["MID"],
            "MID": ["LEAF"],
            "LEAF": [],
        },
    )

    assert TopCellExtractor().extract(path) == "Z_DEEP"


def test_tied_top_cells_pick_the_first_name(tmp_path: Path) -> None:
    """Top cells of equal depth are broken by name, alphabetically."""
    path = write_layout(
        tmp_path / "design.gds",
        {"B_TOP": ["LEAF"], "A_TOP": ["LEAF"], "LEAF": []},
    )

    assert TopCellExtractor().extract(path) == "A_TOP"


def test_flat_cells_pick_the_first_name(tmp_path: Path) -> None:
    """Unrelated leaf cells all have depth 0, so the first name wins."""
    path = write_layout(tmp_path / "design.gds", {"ZED": [], "ALPHA": []})

    assert TopCellExtractor().extract(path) == "ALPHA"


def test_shared_subcell_counts_its_deepest_path(tmp_path: Path) -> None:
    """A cell reached by two paths gets the depth of the longer one."""
    path = write_layout(
        tmp_path / "design.gds",
        {
            "TOP_A": ["X", "LEAF"],
            "X": ["Y"],
            "Y": ["LEAF"],
            "LEAF": [],
            "TOP_B": ["P"],
            "P": ["LEAF"],
        },
    )

    assert TopCellExtractor().extract(path) == "TOP_A"


def test_library_without_cells_is_rejected(tmp_path: Path) -> None:
    """An empty layout has no top cell to name."""
    path = tmp_path / "empty.gds"
    gdstk.Library().write_gds(str(path))

    with pytest.raises(ValueError, match="contains no cells"):
        TopCellExtractor().extract(path)


def test_unreadable_file_is_a_value_error(tmp_path: Path) -> None:
    """A file that isn't GDS fails as ValueError, which callers handle."""
    path = tmp_path / "broken.gds"
    path.write_bytes(b"this is not a GDS file")

    with pytest.raises(ValueError, match="Failed to read GDS file"):
        TopCellExtractor().extract(path)


def test_extract_top_cell_ignores_unsupported_extensions(tmp_path: Path) -> None:
    """A file that isn't GDS or OASIS has no top cell: None."""
    path = tmp_path / "notes.txt"
    path.write_text("hello")

    assert extract_top_cell(path) is None


def test_extract_top_cell_returns_none_for_unreadable_file(tmp_path: Path) -> None:
    """A read failure is logged and returned as None."""
    path = tmp_path / "broken.gds"
    path.write_bytes(b"this is not a GDS file")

    assert extract_top_cell(path) is None
