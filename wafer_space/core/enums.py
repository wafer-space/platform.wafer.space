"""Shared enums used across wafer_space applications."""

from django.db import models


class SlotSize(models.TextChoices):
    """Available slot sizes for manufacturing.

    Each slot represents a portion of the die area:
    - 1x1: Full slot (3.88mm x 5.07mm = 19.67mm²)
    - 0p5x1: Half width (1.94mm x 5.07mm = 9.84mm²)
    - 1x0p5: Half height (3.88mm x 2.535mm = 9.84mm²)
    - 0p5x0p5: Quarter slot (1.94mm x 2.535mm = 4.92mm²)
    """

    FULL = "1x1", "1×1 - Full Slot (3.88mm × 5.07mm = 19.67mm²)"
    HALF_WIDTH = "0p5x1", "0.5×1 - Half Width (1.94mm × 5.07mm = 9.84mm²)"
    HALF_HEIGHT = "1x0p5", "1×0.5 - Half Height (3.88mm × 2.535mm = 9.84mm²)"
    QUARTER = "0p5x0p5", "0.5×0.5 - Quarter Slot (1.94mm × 2.535mm = 4.92mm²)"
