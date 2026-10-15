"""Day-first and ISO 8601 date output formats (#412).

Dates are never shown month first: the platform's users are worldwide and
"10/03/2026" or "Oct 3, 2026" read differently in different places.

``LocaleMiddleware`` picks formats from the visitor's ``Accept-Language``.
Two kinds of locale would otherwise render month first:

- English (``en``, ``en-us``) and Malayalam (``ml``): Django's own formats
  for them are month first.
  ``FORMAT_MODULE_PATH`` points at ``config.formats``, so
  ``config/formats/<locale>/formats.py`` replaces them.
- Locales with no format of their own fall back to the global settings,
  whose Django defaults are month first. ``config/settings/base.py`` sets
  them from these values.

Locales whose own formats are day first or year first (fr, de, en-GB, ja,
...) keep them. Only output formats are set; input formats are Django's.
"""

DATE_FORMAT = "j M Y"  # 3 Oct 2026
DATETIME_FORMAT = "j M Y, H:i"  # 3 Oct 2026, 14:05
TIME_FORMAT = "H:i"  # 14:05
YEAR_MONTH_FORMAT = "F Y"  # October 2026
MONTH_DAY_FORMAT = "j F"  # 3 October
SHORT_DATE_FORMAT = "Y-m-d"  # 2026-10-03
SHORT_DATETIME_FORMAT = "Y-m-d H:i"  # 2026-10-03 14:05
