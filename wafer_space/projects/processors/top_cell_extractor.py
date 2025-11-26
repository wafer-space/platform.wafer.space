"""Extract top-level cell name from GDS and OASIS files."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import gdstk

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


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

    def _find_top_cells(self, library: gdstk.Library) -> list[gdstk.Cell]:
        """Find all top-level cells (cells not instantiated by others).

        Args:
            library: gdstk Library object

        Returns:
            List of top-level cells
        """
        # Filter to only Cell objects (not RawCell which has no references)
        cells = [c for c in library.cells if isinstance(c, gdstk.Cell)]

        # Get all cell names that are referenced by other cells
        referenced_cells: set[str] = set()
        for cell in cells:
            for ref in cell.references:
                referenced_cells.add(ref.cell.name)

        # Top-level cells are those not referenced by any other cell
        return [cell for cell in cells if cell.name not in referenced_cells]

    def _calculate_depth(self, cell: gdstk.Cell, memo: dict[str, int]) -> int:
        """Calculate hierarchical depth of a cell.

        Args:
            cell: gdstk Cell object
            memo: Memoization dict to avoid recalculation

        Returns:
            Maximum depth of cell hierarchy (0 for leaf cells)
        """
        if cell.name in memo:
            return memo[cell.name]

        if not cell.references:
            memo[cell.name] = 0
            return 0

        max_child_depth = 0
        for ref in cell.references:
            child_depth = self._calculate_depth(ref.cell, memo)
            max_child_depth = max(max_child_depth, child_depth)

        depth = max_child_depth + 1
        memo[cell.name] = depth
        return depth

    def _select_top_cell(self, top_cells: list[gdstk.Cell]) -> gdstk.Cell:
        """Select the best top-level cell when multiple exist.

        Selection criteria:
        1. Cell with the deepest hierarchy (most nested instantiations)
        2. If tied, alphabetically first name

        Args:
            top_cells: List of top-level cells

        Returns:
            The selected top-level cell

        Raises:
            ValueError: If no cells provided
        """
        if not top_cells:
            msg = "No cells found in layout file"
            raise ValueError(msg)

        if len(top_cells) == 1:
            return top_cells[0]

        # Calculate depth for each cell
        memo: dict[str, int] = {}
        cells_with_depth = [
            (cell, self._calculate_depth(cell, memo)) for cell in top_cells
        ]

        # Sort by depth (descending), then by name (ascending)
        cells_with_depth.sort(key=lambda x: (-x[1], x[0].name))

        selected = cells_with_depth[0][0]
        logger.info(
            "Multiple top-level cells found: %s. Selected '%s' (depth=%d)",
            [c.name for c in top_cells],
            selected.name,
            cells_with_depth[0][1],
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
        """
        logger.info("Extracting top cell from: %s", file_path.name)

        library = self._load_library(file_path)

        if not library.cells:
            msg = f"Layout file contains no cells: {file_path.name}"
            raise ValueError(msg)

        top_cells = self._find_top_cells(library)

        if not top_cells:
            # If no clear top-level cell, use the first cell in the library
            # This can happen with flat designs
            logger.warning(
                "No clear top-level cell found (all cells are referenced). "
                "Using first cell: %s",
                library.cells[0].name,
            )
            return library.cells[0].name

        selected = self._select_top_cell(top_cells)
        logger.info("Top cell identified: %s", selected.name)

        return selected.name


def extract_top_cell(file_path: Path) -> str | None:
    """Convenience function to extract top cell from a layout file.

    Args:
        file_path: Path to GDS/OASIS file

    Returns:
        Top cell name, or None if extraction fails
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
