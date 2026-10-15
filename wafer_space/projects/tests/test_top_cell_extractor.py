"""Tests for the top-cell extractor (wafer_space/projects/processors)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gdstk
import pytest

from wafer_space.projects.processors.top_cell_extractor import (
    CircularCellReferenceError,
)
from wafer_space.projects.processors.top_cell_extractor import MissingCellReferenceError
from wafer_space.projects.processors.top_cell_extractor import TopCellExtractor
from wafer_space.projects.processors.top_cell_extractor import extract_top_cell
from wafer_space.projects.processors.top_cell_extractor import hierarchy_depths

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


# Circular and missing references (#78)

# Deeper than Python's default recursion limit of 1000.
DEEP_LEVELS = 2000


def chain(length: int) -> dict[str, list[str]]:
    """C0 references C1, which references C2, ... down to C<length - 1>."""
    hierarchy: dict[str, list[str]] = {
        f"C{i}": [f"C{i + 1}"] for i in range(length - 1)
    }
    hierarchy[f"C{length - 1}"] = []
    return hierarchy


@pytest.mark.parametrize("suffix", [".gds", ".oas"])
def test_two_cell_cycle_names_its_cells(tmp_path: Path, suffix: str) -> None:
    """A references B and B references A: the error names A, B, A."""
    path = write_layout(
        tmp_path / f"design{suffix}",
        {"TOP": ["A"], "A": ["B"], "B": ["A"], "OTHER": []},
    )

    with pytest.raises(CircularCellReferenceError) as excinfo:
        TopCellExtractor().extract(path)

    assert excinfo.value.cycle == ["A", "B", "A"]


def test_cycle_message_tells_the_user_what_to_do(tmp_path: Path) -> None:
    """The message is what the user reads, word for word."""
    path = write_layout(
        tmp_path / "design.gds",
        {"TOP": ["A"], "A": ["B"], "B": ["A"]},
    )

    with pytest.raises(CircularCellReferenceError) as excinfo:
        TopCellExtractor().extract(path)

    assert str(excinfo.value) == (
        "The design has a circular cell reference (A → B → A). "
        "Fix the circular reference in your layout and upload it again."
    )


@pytest.mark.parametrize("suffix", [".gds", ".oas"])
def test_self_reference_is_a_cycle(tmp_path: Path, suffix: str) -> None:
    """A cell that references itself, under a single top cell."""
    path = write_layout(
        tmp_path / f"design{suffix}",
        {"TOP": ["A"], "A": ["A"]},
    )

    with pytest.raises(CircularCellReferenceError) as excinfo:
        TopCellExtractor().extract(path)

    assert excinfo.value.cycle == ["A", "A"]


def test_cycle_with_no_top_cell_is_rejected(tmp_path: Path) -> None:
    """Every cell referenced: once this fell back to the first cell, "A"."""
    path = write_layout(tmp_path / "design.gds", {"A": ["B"], "B": ["A"]})

    with pytest.raises(CircularCellReferenceError):
        TopCellExtractor().extract(path)


def test_cycle_unreachable_from_the_top_cell_is_rejected(tmp_path: Path) -> None:
    """A cycle among cells the top cell never uses still fails the file."""
    path = write_layout(
        tmp_path / "design.gds",
        {"TOP": ["LEAF"], "LEAF": [], "X": ["Y"], "Y": ["X"]},
    )

    with pytest.raises(CircularCellReferenceError) as excinfo:
        TopCellExtractor().extract(path)

    assert excinfo.value.cycle == ["X", "Y", "X"]


def test_long_cycle_lists_every_cell_once(tmp_path: Path) -> None:
    """A cycle through four cells names all four, first repeated last."""
    path = write_layout(
        tmp_path / "design.gds",
        {"TOP": ["P"], "P": ["Q"], "Q": ["R"], "R": ["S"], "S": ["Q"]},
    )

    with pytest.raises(CircularCellReferenceError) as excinfo:
        TopCellExtractor().extract(path)

    assert excinfo.value.cycle == ["Q", "R", "S", "Q"]


@pytest.mark.parametrize("suffix", [".gds", ".oas"])
def test_2000_deep_hierarchy_is_walked(tmp_path: Path, suffix: str) -> None:
    """2000 levels, past the recursion limit, with a second top cell.

    The second top cell makes the extractor compare depths, which once
    recursed once per level.
    """
    hierarchy = chain(DEEP_LEVELS + 1)
    hierarchy["OTHER"] = []
    path = write_layout(tmp_path / f"deep{suffix}", hierarchy)

    assert TopCellExtractor().extract(path) == "C0"


def test_2000_deep_hierarchy_has_depth_2000() -> None:
    """Depth counts levels below the cell: 2001 cells in a chain is 2000."""
    assert hierarchy_depths(chain(DEEP_LEVELS + 1))["C0"] == DEEP_LEVELS


def test_depths_of_a_diamond() -> None:
    """Every cell's depth, where two paths of different length meet."""
    depths = hierarchy_depths(
        {"TOP": ["LONG", "LEAF"], "LONG": ["MID"], "MID": ["LEAF"], "LEAF": []},
    )

    assert depths == {"TOP": 3, "LONG": 2, "MID": 1, "LEAF": 0}


def test_extract_top_cell_passes_the_cycle_error_on(tmp_path: Path) -> None:
    """The cycle error reaches the caller instead of becoming None."""
    path = write_layout(tmp_path / "design.gds", {"TOP": ["A"], "A": ["A"]})

    with pytest.raises(CircularCellReferenceError):
        extract_top_cell(path)


def test_reference_to_a_missing_cell_names_both_cells(tmp_path: Path) -> None:
    """gdstk keeps a reference to a cell that isn't in the file as a str."""
    top, ghost = gdstk.Cell("TOP"), gdstk.Cell("GHOST")
    top.add(gdstk.Reference(ghost))
    library = gdstk.Library()
    library.add(top)  # GHOST is left out of the file
    path = tmp_path / "design.gds"
    library.write_gds(str(path))

    with (
        pytest.warns(RuntimeWarning, match="Missing reference"),
        pytest.raises(MissingCellReferenceError) as excinfo,
    ):
        TopCellExtractor().extract(path)

    assert str(excinfo.value) == (
        "The design references a cell that is not in the file "
        "(TOP references GHOST). "
        "Add the missing cell to your layout and upload it again."
    )
