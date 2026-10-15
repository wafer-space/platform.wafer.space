"""Template filters for check artifact files."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import template

if TYPE_CHECKING:
    from django.db.models.fields.files import FieldFile

register = template.Library()


@register.filter
def stored_size(field_file: FieldFile) -> int | None:
    """Return the size in bytes of a saved artifact, or None if it is not on disk.

    ``FieldFile.size`` asks the storage for the file named in the database
    row and raises ``FileNotFoundError`` when that file is gone (a manual
    clean-up, a restore that copied the database but not every media file,
    a failed partial save). Rendering that inside a template turned the
    whole project page into a 500 (issue #378), so the page asks here and
    shows "File missing" instead. This only reads (one ``stat``); nothing is
    written under MEDIA_ROOT from the web process.

    An empty field (no file name in the row) also returns None; templates
    test the field itself first to tell "never saved" from "missing".
    """
    if not field_file:
        return None
    try:
        return field_file.size
    except FileNotFoundError:
        return None
