"""Malayalam output formats: day first instead of Django's month first (#412).

Django's own Malayalam formats are month first ("11/23/2026"); this
replaces them. Month names stay Malayalam.
"""

from config.formats import DATE_FORMAT
from config.formats import DATETIME_FORMAT
from config.formats import MONTH_DAY_FORMAT
from config.formats import SHORT_DATE_FORMAT
from config.formats import SHORT_DATETIME_FORMAT
from config.formats import TIME_FORMAT
from config.formats import YEAR_MONTH_FORMAT

__all__ = [
    "DATETIME_FORMAT",
    "DATE_FORMAT",
    "MONTH_DAY_FORMAT",
    "SHORT_DATETIME_FORMAT",
    "SHORT_DATE_FORMAT",
    "TIME_FORMAT",
    "YEAR_MONTH_FORMAT",
]
