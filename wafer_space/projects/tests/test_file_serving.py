"""User files are sent only after a permission check (coord-10).

``protected_file_response`` streams in dev and tests and answers with an
X-Accel-Redirect to nginx's internal location when deployed; nothing
serves MEDIA_URL.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.http import FileResponse
from django.http import Http404
from django.test import override_settings
from django.urls import clear_url_caches
from django.views.static import serve

from config import urls as root_urls
from wafer_space.projects.file_serving import protected_file_response

from .factories import ProjectFileFactory

if TYPE_CHECKING:
    from django.db.models.fields.files import FieldFile
    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db

CONTENT = b"layout bytes"
PREFIX = "/protected-media/"


def stored(name: str = "chip_top.gds") -> FieldFile:
    """A stored input layout, saved under MEDIA_ROOT by its upload_to."""
    revision = ProjectFileFactory()
    revision.file.save(name, ContentFile(CONTENT), save=True)
    return revision.file


class TestWithoutNginx:
    """MEDIA_X_ACCEL_REDIRECT_PREFIX unset (dev, tests): Django streams."""

    def test_streams_the_file(self) -> None:
        response = protected_file_response(stored(), filename="chip_top.gds")
        assert isinstance(response, FileResponse)
        assert b"".join(response.streaming_content) == CONTENT

    def test_is_an_attachment_with_the_given_name(self) -> None:
        response = protected_file_response(stored(), filename="out.gds")
        assert response["Content-Disposition"] == 'attachment; filename="out.gds"'

    def test_no_shared_cache_may_keep_it(self) -> None:
        response = protected_file_response(stored(), filename="chip_top.gds")
        assert response["Cache-Control"] == "private, no-store"


class TestBehindNginx:
    """Deployed: nginx sends the bytes from its internal location."""

    @pytest.fixture(autouse=True)
    def _prefix(self, settings: SettingsWrapper) -> None:
        settings.MEDIA_X_ACCEL_REDIRECT_PREFIX = PREFIX

    def test_redirects_to_the_file_under_the_internal_location(self) -> None:
        field_file = stored()
        response = protected_file_response(field_file, filename="chip_top.gds")
        assert response["X-Accel-Redirect"] == PREFIX + field_file.name

    def test_django_sends_no_body(self) -> None:
        response = protected_file_response(stored(), filename="chip_top.gds")
        assert (response.streaming, response.content) == (False, b"")

    def test_keeps_attachment_name_and_type(self) -> None:
        response = protected_file_response(
            stored(), filename="run.log", content_type="text/plain; charset=utf-8"
        )
        assert (response["Content-Disposition"], response["Content-Type"]) == (
            'attachment; filename="run.log"',
            "text/plain; charset=utf-8",
        )

    def test_type_defaults_to_octet_stream_not_html(self) -> None:
        """nginx keeps the upstream Content-Type; Django's default is HTML."""
        response = protected_file_response(stored(), filename="chip_top.oas")
        assert response["Content-Type"] == "application/octet-stream"

    def test_no_shared_cache_may_keep_it(self) -> None:
        response = protected_file_response(stored(), filename="chip_top.gds")
        assert response["Cache-Control"] == "private, no-store"

    def test_unsafe_characters_in_the_name_are_percent_encoded(self) -> None:
        """Names carry the user's file name and top cell; nginx decodes %XX.

        An unencoded '?' would end the path at nginx and '#' or '%' would
        corrupt it.
        """
        field_file = stored()
        unsafe = Path(field_file.name).parent / "my chip?#%ü.gds"
        field_file.storage.save(str(unsafe), ContentFile(CONTENT))
        field_file.name = str(unsafe)
        response = protected_file_response(field_file, filename="x.gds")
        redirect = response["X-Accel-Redirect"]
        directory, _, encoded = redirect.rpartition("/")
        assert (directory + "/", encoded) == (
            PREFIX + str(Path(field_file.name).parent) + "/",
            "my%20chip%3F%23%25%C3%BC.gds",
        )

    def test_non_ascii_download_name_is_rfc_5987_encoded(self) -> None:
        response = protected_file_response(stored(), filename="puce_ü.gds")
        assert "filename*=utf-8''puce_%C3%BC.gds" in response["Content-Disposition"]

    def test_storage_outside_media_root_is_refused_loudly(
        self, tmp_path: Path
    ) -> None:
        """nginx aliases MEDIA_ROOT, so another root would send the wrong file."""
        elsewhere = FileSystemStorage(location=tmp_path / "elsewhere")
        elsewhere.save("chip_top.gds", ContentFile(CONTENT))
        field_file = stored()
        field_file.storage = elsewhere
        field_file.name = "chip_top.gds"
        with pytest.raises(ImproperlyConfigured, match="not rooted at MEDIA_ROOT"):
            protected_file_response(field_file, filename="chip_top.gds")


class TestMissingFiles:
    """A row that names no file, or a file that is gone, is a 404."""

    @pytest.mark.parametrize("prefix", [None, PREFIX])
    def test_empty_field_is_404(
        self, settings: SettingsWrapper, prefix: str | None
    ) -> None:
        settings.MEDIA_X_ACCEL_REDIRECT_PREFIX = prefix
        revision = ProjectFileFactory(file=None)
        with pytest.raises(Http404):
            protected_file_response(revision.file, filename="chip_top.gds")

    @pytest.mark.parametrize("prefix", [None, PREFIX])
    def test_file_gone_from_disk_is_404(
        self, settings: SettingsWrapper, prefix: str | None
    ) -> None:
        settings.MEDIA_X_ACCEL_REDIRECT_PREFIX = prefix
        field_file = stored()
        field_file.storage.delete(field_file.name)
        with pytest.raises(Http404):
            protected_file_response(field_file, filename="chip_top.gds")


def test_media_url_is_not_served_even_in_debug() -> None:
    """Dev must not hide a link that would 404 (or leak) once deployed."""
    try:
        with override_settings(DEBUG=True):
            clear_url_caches()
            importlib.reload(root_urls)
            callbacks = [getattr(p, "callback", None) for p in root_urls.urlpatterns]
    finally:
        clear_url_caches()
        importlib.reload(root_urls)
    assert serve not in callbacks
