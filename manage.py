#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os  # noqa: F401 - used by commented-out setdefault below
import sys
from pathlib import Path


def main():
    """Run administrative tasks."""
    # Disabled: fail fast if DJANGO_SETTINGS_MODULE not set, don't silently use SQLite.
    # https://github.com/wafer-space/platform.wafer.space/issues/152
    # os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")  # noqa: ERA001, E501

    try:
        from django.core.management import execute_from_command_line  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(  # noqa: TRY003
            "Couldn't import Django. Are you sure it's installed and "  # noqa: EM101
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?",
        ) from exc

    # This allows easy placement of apps within the interior
    # wafer_space directory.
    current_path = Path(__file__).parent.resolve()
    sys.path.append(str(current_path / "wafer_space"))

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
