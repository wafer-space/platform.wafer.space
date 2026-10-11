"""Send a private user file to a client that a view has already authorised.

User files (stored layouts, check logs and artifacts) live under MEDIA_ROOT
and nothing serves MEDIA_URL: a file is reachable only through a view that
has checked the requester may see the project. Such a view returns
``protected_file_response(...)``.

Deployed, nginx sends the bytes: the response carries an X-Accel-Redirect
to MEDIA_X_ACCEL_REDIRECT_PREFIX, an nginx ``internal`` location aliasing
MEDIA_ROOT that clients cannot request directly. gunicorn's worker is free
at once, and nginx handles Range requests. In dev and tests there is no
nginx, so Django streams the file itself.

Read-only, as the web process must be.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import FileResponse
from django.http import Http404
from django.http import HttpResponse
from django.utils.http import content_disposition_header

if TYPE_CHECKING:
    from django.db.models.fields.files import FieldFile
    from django.http.response import HttpResponseBase

DEFAULT_CONTENT_TYPE = "application/octet-stream"


def stored_file_exists(field_file: FieldFile) -> bool:
    """Whether the field names a file that is present in its storage."""
    name = field_file.name
    if not name:
        return False
    return field_file.storage.exists(name)


def protected_file_response(
    field_file: FieldFile,
    *,
    filename: str,
    content_type: str = DEFAULT_CONTENT_TYPE,
) -> HttpResponseBase:
    """Return a response that downloads ``field_file`` as ``filename``.

    The caller must already have checked permission. Raises Http404 when
    the field is empty or its file is missing, so a stale row is a 404 and
    not a 500 (or an nginx 404 with no explanation in Django's log).
    The type defaults to octet-stream: these are attachments, and guessing
    from the host's mime.types differs between machines (it calls an OASIS
    layout "application/vnd.fujitsu.oasys").
    """
    name = field_file.name
    if not name or not field_file.storage.exists(name):
        msg = "This file is not stored on the platform"
        raise Http404(msg)

    prefix = settings.MEDIA_X_ACCEL_REDIRECT_PREFIX
    if prefix is None:
        response: HttpResponseBase = FileResponse(
            field_file.open("rb"),
            as_attachment=True,
            filename=filename,
            content_type=content_type,
        )
    else:
        disposition = content_disposition_header(as_attachment=True, filename=filename)
        if disposition is None:
            # Django returns None only for an inline response with no name.
            msg = f"No Content-Disposition for {filename!r}"
            raise ValueError(msg)
        response = HttpResponse(content_type=content_type)
        response["X-Accel-Redirect"] = prefix + quote(
            _media_relative_name(field_file, name)
        )
        response["Content-Disposition"] = disposition
    # Private data: no shared cache may keep a copy.
    response["Cache-Control"] = "private, no-store"
    return response


def _media_relative_name(field_file: FieldFile, name: str) -> str:
    """The file's path relative to MEDIA_ROOT, which nginx aliases.

    The nginx location maps onto MEDIA_ROOT, so a storage rooted anywhere
    else would send the wrong file: refuse loudly. ``storage.path()``
    rejects names that escape the storage root (SuspiciousFileOperation).
    """
    storage = field_file.storage
    media_root = Path(settings.MEDIA_ROOT).absolute()
    location = getattr(storage, "location", None)
    if location is None or Path(location) != media_root:
        msg = (
            f"{type(storage).__name__} for {name!r} is not rooted at "
            "MEDIA_ROOT, so nginx's protected-media alias cannot serve it"
        )
        raise ImproperlyConfigured(msg)
    return Path(storage.path(name)).relative_to(media_root).as_posix()
