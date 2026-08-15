"""Infrastructure endpoints that do not belong to any user-facing app."""

from __future__ import annotations

from django.db import transaction
from django.http import HttpRequest
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


@never_cache
@require_safe
@transaction.non_atomic_requests
def health(request: HttpRequest) -> HttpResponse:
    """Liveness probe for nginx and deployment tooling (issue #336).

    Deliberately database-free (``non_atomic_requests`` opts out of
    ``ATOMIC_REQUESTS``) so it keeps answering while the database is down.
    """
    return HttpResponse("ok", content_type="text/plain")
