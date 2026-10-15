"""Extract top-level cell name from GDS and OASIS files."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import gdstk

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class LayoutHierarchyError(Exception):
    """The layout's cell hierarchy is broken, and only the user can fix it.

    Deliberately not a ValueError: extract_top_cell turns ValueError into
    None, and this message must reach the user instead.
    """


class CircularCellReferenceError(LayoutHierarchyError):
    """A cell references itself, directly or through other cells."""

    def __init__(self, cycle: list[str]) -> None:
        """Name the cells of the cycle, first cell repeated at the end."""
        self.cycle = cycle
        path = " → ".join(cycle)
        msg = (
            f"The design has a circular cell reference ({path}). "
            "Fix the circular reference in your layout and upload it again."
        )
        super().__init__(msg)


class MissingCellReferenceError(LayoutHierarchyError):
    """A cell references a cell that the file does not contain."""

    def __init__(self, parent: str, missing: str) -> None:
        """Name the referencing cell and the missing one."""
        self.parent = parent
        self.missing = missing
        msg = (
            f"The design references a cell that is not in the file "
            f"({parent} references {missing}). "
            "Add the missing cell to your layout and upload it again."
        )
        super().__init__(msg)


def _children_by_cell(cells: list[gdstk.Cell]) -> dict[str, list[str]]:
    """Map each cell's name to the names of the cells it references.

    A reference to a cell that isn't in the file is kept by gdstk as the
    plain name (a str), so it is listed by name too; _top_cells rejects it.
    """
    return {
        cell.name: [
            target if isinstance(target := ref.cell, str) else target.name
            for ref in cell.references
        ]
        for cell in cells
    }


def _top_cells(children: dict[str, list[str]]) -> set[str]:
    """Return the cells that no other cell references.

    Raises:
        MissingCellReferenceError: If a reference names a cell that isn't in
            the file.
    """
    referenced: set[str] = set()
    for names in children.values():
        referenced.update(names)
    if missing := referenced - children.keys():
        parent, child = next(
            (parent, child)
            for parent, names in children.items()
            for child in names
            if child in missing
        )
        raise MissingCellReferenceError(parent, child)
    return children.keys() - referenced


def hierarchy_depths(children: dict[str, list[str]]) -> dict[str, int]:
    """Return every cell's hierarchical depth (0 for a leaf cell).

    A depth-first walk with an explicit stack, so neither a deep hierarchy
    nor a cycle can exhaust Python's recursion limit. Every cell is
    walked, including cells no top cell reaches. Every name in `children`'s
    lists must be one of its keys.

    Raises:
        CircularCellReferenceError: If any cell references itself, directly
            or through other cells.
    """
    depths: dict[str, int] = {}
    for root, root_children in children.items():
        if root in depths:
            continue
        # The cells on the current path, the position of each on it, an
        # iterator over the children each has yet to visit, and the deepest
        # child depth each has seen so far.
        path = [root]
        position = {root: 0}
        pending = [iter(root_children)]
        deepest = [-1]
        while pending:
            for child in pending[-1]:
                depth = depths.get(child)
                if depth is not None:
                    deepest[-1] = max(deepest[-1], depth)
                    continue
                if child in position:
                    raise CircularCellReferenceError(
                        [*path[position[child] :], child],
                    )
                position[child] = len(path)
                path.append(child)
                pending.append(iter(children[child]))
                deepest.append(-1)
                break
            else:
                # Every child visited: this cell's depth is final.
                done = path.pop()
                pending.pop()
                del position[done]
                depths[done] = deepest.pop() + 1
                if deepest:
                    deepest[-1] = max(deepest[-1], depths[done])
    return depths


class TopCellExtractor:
    """Extract top-level cell name from GDS/OASIS layout files.

    The top-level cell is the cell that is not instantiated by any other cell.
    If there are multiple top-level cells, returns the one with the most
    hierarchical depth (most nested instantiations).
    """

    # Supported file extensions
    GDS_EXTENSIONS = {".gds", ".gdsii", ".gds2"}
    OAS_EXTENSIONS = {".oas", ".oasis"}
    SUPPORTED_EXTENSIONS = GDS_EXTENSIONS | OAS_EXTENSIONS

    def can_extract(self, file_path: Path) -> bool:
        """Check if file is a supported GDS/OASIS format.

        Args:
            file_path: Path to the layout file

        Returns:
            True if file extension is supported
        """
        suffix = file_path.suffix.lower()
        return suffix in self.SUPPORTED_EXTENSIONS

    def _load_library(self, file_path: Path) -> gdstk.Library:
        """Load GDS or OASIS file into a gdstk Library.

        Args:
            file_path: Path to the layout file

        Returns:
            gdstk.Library object

        Raises:
            ValueError: If file format is unsupported or file is corrupted
        """
        suffix = file_path.suffix.lower()

        if suffix in self.GDS_EXTENSIONS:
            return self._read_gds_safe(file_path)
        if suffix in self.OAS_EXTENSIONS:
            return self._read_oas_safe(file_path)
        msg = f"Unsupported file format: {suffix}"
        raise ValueError(msg)

    def _read_gds_safe(self, file_path: Path) -> gdstk.Library:
        """Read GDS file with error handling."""
        try:
            return gdstk.read_gds(str(file_path))
        except Exception as e:
            msg = f"Failed to read GDS file: {e}"
            raise ValueError(msg) from e

    def _read_oas_safe(self, file_path: Path) -> gdstk.Library:
        """Read OASIS file with error handling."""
        try:
            return gdstk.read_oas(str(file_path))
        except Exception as e:
            msg = f"Failed to read OASIS file: {e}"
            raise ValueError(msg) from e

    def _select_top_cell(
        self,
        top_cells: list[str],
        depths: dict[str, int],
    ) -> str:
        """Select the best top-level cell when several exist.

        Selection criteria:
        1. Cell with the deepest hierarchy (most nested instantiations)
        2. If tied, alphabetically first name

        Args:
            top_cells: Names of the cells no other cell references, sorted
            depths: Hierarchical depth of every cell

        Returns:
            Name of the selected top-level cell
        """
        if len(top_cells) == 1:
            return top_cells[0]

        # Sort by depth (descending), then by name (ascending)
        selected = min(top_cells, key=lambda name: (-depths[name], name))
        logger.info(
            "Multiple top-level cells found: %s. Selected '%s' (depth=%d)",
            top_cells,
            selected,
            depths[selected],
        )
        return selected

    def extract(self, file_path: Path) -> str:
        """Extract the top-level cell name from a GDS/OASIS file.

        Args:
            file_path: Path to the layout file

        Returns:
            Name of the top-level cell

        Raises:
            ValueError: If file cannot be read or has no cells
            LayoutHierarchyError: If the cell hierarchy has a cycle or a
                reference to a missing cell
        """
        logger.info("Extracting top cell from: %s", file_path.name)

        library = self._load_library(file_path)

        # Only Cell objects (not RawCell, which has no references)
        cells = [c for c in library.cells if isinstance(c, gdstk.Cell)]
        if not cells:
            msg = f"Layout file contains no cells: {file_path.name}"
            raise ValueError(msg)

        children = _children_by_cell(cells)
        top_cells = sorted(_top_cells(children))
        depths = hierarchy_depths(children)
        # Never empty once hierarchy_depths has ruled out cycles: a finite
        # acyclic hierarchy always has a cell that nothing references.
        selected = self._select_top_cell(top_cells, depths)
        logger.info("Top cell identified: %s", selected)

        return selected


def extract_top_cell(file_path: Path) -> str | None:
    """Convenience function to extract top cell from a layout file.

    Args:
        file_path: Path to GDS/OASIS file

    Returns:
        Top cell name, or None if extraction fails

    Raises:
        LayoutHierarchyError: If the design's cell hierarchy is broken. The
            message is for the user, so it is not turned into None.
    """
    extractor = TopCellExtractor()

    if not extractor.can_extract(file_path):
        logger.debug("File %s is not a supported layout format", file_path.name)
        return None

    try:
        return extractor.extract(file_path)
    except ValueError as e:
        logger.warning("Failed to extract top cell from %s: %s", file_path.name, e)
        return None
