# Project Metadata Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add repository URL and license tracking fields to the Project model, enabling users to document their project's source code location and licensing terms.

**Architecture:** Extend the existing Project model with 6 new fields (repository_url, license_type, other_license_spdx_id, proprietary_terms_url, proprietary_terms_cached, proprietary_terms_cached_at). Forms validate SPDX identifiers via HTTP fetch and cache proprietary license terms on save. JavaScript handles conditional field visibility.

**Tech Stack:** Django 5.2+, django-simple-history (already integrated), httpx for HTTP fetching, pytest for testing

---

## Task 1: Add LicenseType Enum

**Files:**
- Modify: `wafer_space/projects/models.py:1-50` (add enum near top after imports)

**Step 1: Add the LicenseType enum**

Add after the existing imports and before the `Project` class:

```python
class LicenseType(models.TextChoices):
    """License types for projects.

    Uses SPDX identifiers where applicable for standard open source licenses.
    """

    PROPRIETARY = "proprietary", "Proprietary (All Rights Reserved)"
    APACHE_2_0 = "Apache-2.0", "Apache License 2.0"
    MIT = "MIT", "MIT License"
    BSD_3_CLAUSE = "BSD-3-Clause", "BSD 3-Clause License"
    ISC = "ISC", "ISC License"
    CERN_OHL_P = "CERN-OHL-P-2.0", "CERN Open Hardware License (Permissive)"
    SOLDERPAD_2_0 = "SHL-2.0", "Solderpad Hardware License 2.0"
    SOLDERPAD_2_1 = "SHL-2.1", "Solderpad Hardware License 2.1"
    CC0 = "CC0-1.0", "CC0 1.0 (Public Domain)"
    CC_BY = "CC-BY-4.0", "Creative Commons Attribution 4.0"
    OTHER = "other", "Other Open Source License"
```

**Step 2: Run lint to verify syntax**

Run: `make lint`
Expected: PASS (no errors related to new code)

**Step 3: Commit**

```bash
git add wafer_space/projects/models.py
git commit -m "feat(projects): add LicenseType enum for license tracking"
```

---

## Task 2: Add New Fields to Project Model

**Files:**
- Modify: `wafer_space/projects/models.py` (add fields to Project class)

**Step 1: Add the 6 new fields to Project model**

Add these fields after the existing `is_public` field in the Project class:

```python
    # Repository URL (Issue #137)
    repository_url = models.URLField(
        blank=True,
        max_length=500,
        help_text="URL to the project's source repository",
    )

    # License tracking (Issue #193)
    license_type = models.CharField(
        max_length=50,
        choices=LicenseType.choices,
        default=LicenseType.PROPRIETARY,
        help_text="License under which this project is released",
    )
    other_license_spdx_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="SPDX identifier when license_type is 'Other'",
    )
    proprietary_terms_url = models.URLField(
        blank=True,
        max_length=500,
        help_text="URL to proprietary license terms",
    )
    proprietary_terms_cached = models.TextField(
        blank=True,
        help_text="Cached content from proprietary_terms_url",
    )
    proprietary_terms_cached_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When proprietary terms were last cached",
    )
```

**Step 2: Run lint and type-check**

Run: `make lint && make type-check`
Expected: PASS

**Step 3: Commit**

```bash
git add wafer_space/projects/models.py
git commit -m "feat(projects): add repository_url and license tracking fields"
```

---

## Task 3: Create and Apply Migration

**Files:**
- Create: `wafer_space/projects/migrations/XXXX_add_project_metadata_fields.py` (auto-generated)

**Step 1: Generate migration**

Run: `uv run python manage.py makemigrations projects --name add_project_metadata_fields`
Expected: Creates migration file with 6 new fields

**Step 2: Review migration**

Run: `cat wafer_space/projects/migrations/*add_project_metadata_fields.py`
Expected: Migration adds repository_url, license_type, other_license_spdx_id, proprietary_terms_url, proprietary_terms_cached, proprietary_terms_cached_at

**Step 3: Apply migration**

Run: `uv run python manage.py migrate`
Expected: Migration applies successfully

**Step 4: Commit**

```bash
git add wafer_space/projects/migrations/
git commit -m "feat(projects): add migration for project metadata fields"
```

---

## Task 4: Write Model Tests for License Fields

**Files:**
- Modify: `wafer_space/projects/tests/test_models.py`

**Step 1: Write the failing tests**

Add to the existing test file:

```python
class TestProjectLicenseFields:
    """Tests for project license tracking fields."""

    def test_default_license_type_is_proprietary(self, user):
        """New projects default to proprietary license."""
        project = Project.objects.create(
            user=user,
            name="Test Project",
            project_id="TEST",
        )
        assert project.license_type == LicenseType.PROPRIETARY

    def test_license_type_choices_include_common_licenses(self):
        """LicenseType enum includes expected common licenses."""
        license_values = [choice[0] for choice in LicenseType.choices]
        assert "MIT" in license_values
        assert "Apache-2.0" in license_values
        assert "proprietary" in license_values
        assert "other" in license_values

    def test_repository_url_is_optional(self, user):
        """Projects can be created without repository_url."""
        project = Project.objects.create(
            user=user,
            name="Test Project",
            project_id="TEST",
        )
        assert project.repository_url == ""

    def test_repository_url_can_be_set(self, user):
        """Repository URL can be set on project."""
        project = Project.objects.create(
            user=user,
            name="Test Project",
            project_id="TEST",
            repository_url="https://github.com/user/repo",
        )
        assert project.repository_url == "https://github.com/user/repo"

    def test_other_license_spdx_id_is_optional(self, user):
        """other_license_spdx_id is optional."""
        project = Project.objects.create(
            user=user,
            name="Test Project",
            project_id="TEST",
            license_type=LicenseType.MIT,
        )
        assert project.other_license_spdx_id == ""

    def test_proprietary_terms_fields_are_optional(self, user):
        """Proprietary terms fields are optional."""
        project = Project.objects.create(
            user=user,
            name="Test Project",
            project_id="TEST",
        )
        assert project.proprietary_terms_url == ""
        assert project.proprietary_terms_cached == ""
        assert project.proprietary_terms_cached_at is None
```

**Step 2: Add import for LicenseType**

Add to imports at top of test file:

```python
from wafer_space.projects.models import LicenseType
```

**Step 3: Run tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_models.py::TestProjectLicenseFields -v`
Expected: All 6 tests PASS

**Step 4: Commit**

```bash
git add wafer_space/projects/tests/test_models.py
git commit -m "test(projects): add model tests for license tracking fields"
```

---

## Task 5: Add License Validation Service

**Files:**
- Create: `wafer_space/projects/services/license_service.py`
- Create: `wafer_space/projects/services/__init__.py` (if not exists)

**Step 1: Create services directory if needed**

Run: `mkdir -p wafer_space/projects/services && touch wafer_space/projects/services/__init__.py`

**Step 2: Create the license service**

Create `wafer_space/projects/services/license_service.py`:

```python
"""Service for license validation and caching."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from django.utils import timezone

if TYPE_CHECKING:
    from wafer_space.projects.models import Project

logger = logging.getLogger(__name__)

# Timeout for HTTP requests (seconds)
HTTP_TIMEOUT = 10.0

# SPDX license text base URL
SPDX_LICENSE_TEXT_URL = "https://raw.githubusercontent.com/spdx/license-list-data/main/text/{spdx_id}.txt"


class LicenseValidationError(Exception):
    """Raised when license validation fails."""

    pass


def validate_spdx_id(spdx_id: str) -> bool:
    """Validate that an SPDX identifier exists.

    Args:
        spdx_id: The SPDX license identifier to validate.

    Returns:
        True if valid, False otherwise.

    Raises:
        LicenseValidationError: If the SPDX ID is invalid or unreachable.
    """
    url = SPDX_LICENSE_TEXT_URL.format(spdx_id=spdx_id)
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.head(url, follow_redirects=True)
            if response.status_code == 200:
                return True
            msg = f"Invalid SPDX identifier: {spdx_id}"
            raise LicenseValidationError(msg)
    except httpx.TimeoutException as e:
        msg = f"Timeout validating SPDX identifier: {spdx_id}"
        raise LicenseValidationError(msg) from e
    except httpx.HTTPError as e:
        msg = f"Error validating SPDX identifier: {spdx_id}"
        raise LicenseValidationError(msg) from e


def fetch_url_content(url: str) -> str:
    """Fetch content from a URL.

    Args:
        url: The URL to fetch.

    Returns:
        The content as a string.

    Raises:
        LicenseValidationError: If the URL is unreachable or returns an error.
    """
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(url, follow_redirects=True)
            response.raise_for_status()
            return response.text
    except httpx.TimeoutException as e:
        msg = f"Timeout fetching URL: {url}"
        raise LicenseValidationError(msg) from e
    except httpx.HTTPStatusError as e:
        msg = f"Error fetching URL ({e.response.status_code}): {url}"
        raise LicenseValidationError(msg) from e
    except httpx.HTTPError as e:
        msg = f"Error fetching URL: {url}"
        raise LicenseValidationError(msg) from e


def cache_proprietary_terms(project: Project, terms_url: str) -> None:
    """Fetch and cache proprietary license terms.

    Args:
        project: The project to update.
        terms_url: The URL to fetch terms from.

    Raises:
        LicenseValidationError: If the URL cannot be fetched.
    """
    content = fetch_url_content(terms_url)
    project.proprietary_terms_cached = content
    project.proprietary_terms_cached_at = timezone.now()
```

**Step 3: Update services __init__.py**

Add to `wafer_space/projects/services/__init__.py`:

```python
from .license_service import LicenseValidationError
from .license_service import cache_proprietary_terms
from .license_service import fetch_url_content
from .license_service import validate_spdx_id

__all__ = [
    "LicenseValidationError",
    "cache_proprietary_terms",
    "fetch_url_content",
    "validate_spdx_id",
]
```

**Step 4: Run lint**

Run: `make lint-fix && make lint && make type-check`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/services/
git commit -m "feat(projects): add license validation service"
```

---

## Task 6: Write Tests for License Service

**Files:**
- Create: `wafer_space/projects/tests/test_license_service.py`

**Step 1: Write the tests**

Create `wafer_space/projects/tests/test_license_service.py`:

```python
"""Tests for license validation service."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest
from django.utils import timezone

from wafer_space.projects.services.license_service import HTTP_TIMEOUT
from wafer_space.projects.services.license_service import LicenseValidationError
from wafer_space.projects.services.license_service import cache_proprietary_terms
from wafer_space.projects.services.license_service import fetch_url_content
from wafer_space.projects.services.license_service import validate_spdx_id


class TestValidateSpdxId:
    """Tests for validate_spdx_id function."""

    def test_valid_spdx_id_returns_true(self):
        """Valid SPDX ID returns True."""
        with patch("wafer_space.projects.services.license_service.httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.return_value.__enter__.return_value.head.return_value = mock_response

            result = validate_spdx_id("MIT")
            assert result is True

    def test_invalid_spdx_id_raises_error(self):
        """Invalid SPDX ID raises LicenseValidationError."""
        with patch("wafer_space.projects.services.license_service.httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_client.return_value.__enter__.return_value.head.return_value = mock_response

            with pytest.raises(LicenseValidationError, match="Invalid SPDX identifier"):
                validate_spdx_id("NOT-A-REAL-LICENSE")

    def test_timeout_raises_error(self):
        """Timeout raises LicenseValidationError."""
        with patch("wafer_space.projects.services.license_service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.head.side_effect = httpx.TimeoutException("timeout")

            with pytest.raises(LicenseValidationError, match="Timeout"):
                validate_spdx_id("MIT")


class TestFetchUrlContent:
    """Tests for fetch_url_content function."""

    def test_successful_fetch_returns_content(self):
        """Successful fetch returns content."""
        with patch("wafer_space.projects.services.license_service.httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.text = "License text content"
            mock_response.raise_for_status = MagicMock()
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response

            result = fetch_url_content("https://example.com/license.txt")
            assert result == "License text content"

    def test_http_error_raises_validation_error(self):
        """HTTP error raises LicenseValidationError."""
        with patch("wafer_space.projects.services.license_service.httpx.Client") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 404
            error = httpx.HTTPStatusError("Not found", request=MagicMock(), response=mock_response)
            mock_response.raise_for_status.side_effect = error
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response

            with pytest.raises(LicenseValidationError, match="Error fetching URL"):
                fetch_url_content("https://example.com/nonexistent.txt")

    def test_timeout_raises_validation_error(self):
        """Timeout raises LicenseValidationError."""
        with patch("wafer_space.projects.services.license_service.httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = httpx.TimeoutException("timeout")

            with pytest.raises(LicenseValidationError, match="Timeout"):
                fetch_url_content("https://example.com/slow.txt")


class TestCacheProprietaryTerms:
    """Tests for cache_proprietary_terms function."""

    def test_caches_content_and_timestamp(self):
        """Caches content and sets timestamp."""
        with patch("wafer_space.projects.services.license_service.fetch_url_content") as mock_fetch:
            mock_fetch.return_value = "Proprietary license terms..."

            mock_project = MagicMock()
            mock_project.proprietary_terms_cached = ""
            mock_project.proprietary_terms_cached_at = None

            cache_proprietary_terms(mock_project, "https://example.com/terms.txt")

            assert mock_project.proprietary_terms_cached == "Proprietary license terms..."
            assert mock_project.proprietary_terms_cached_at is not None

    def test_fetch_failure_propagates_error(self):
        """Fetch failure propagates LicenseValidationError."""
        with patch("wafer_space.projects.services.license_service.fetch_url_content") as mock_fetch:
            mock_fetch.side_effect = LicenseValidationError("Could not fetch")

            mock_project = MagicMock()

            with pytest.raises(LicenseValidationError):
                cache_proprietary_terms(mock_project, "https://example.com/bad.txt")
```

**Step 2: Run tests**

Run: `uv run pytest wafer_space/projects/tests/test_license_service.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add wafer_space/projects/tests/test_license_service.py
git commit -m "test(projects): add tests for license validation service"
```

---

## Task 7: Update ProjectForm with New Fields

**Files:**
- Modify: `wafer_space/projects/forms.py`

**Step 1: Add imports**

Add to imports at top of file:

```python
from wafer_space.projects.models import LicenseType
from wafer_space.projects.services.license_service import LicenseValidationError
from wafer_space.projects.services.license_service import cache_proprietary_terms
from wafer_space.projects.services.license_service import validate_spdx_id
```

**Step 2: Add shared widget/help_text constants**

Add after the existing `IS_PUBLIC_*` constants:

```python
# Shared license field configuration
LICENSE_TYPE_WIDGET = forms.Select(attrs={"class": "form-control", "id": "id_license_type"})
LICENSE_TYPE_HELP_TEXT = "License under which this project is released"

REPOSITORY_URL_WIDGET = forms.URLInput(
    attrs={
        "class": "form-control",
        "placeholder": "https://github.com/username/repo",
    }
)
REPOSITORY_URL_HELP_TEXT = "URL to the project's source repository"

OTHER_LICENSE_WIDGET = forms.TextInput(
    attrs={
        "class": "form-control",
        "placeholder": "GPL-3.0-only",
    }
)
OTHER_LICENSE_HELP_TEXT = "SPDX identifier (e.g., GPL-3.0-only, LGPL-2.1-or-later)"

PROPRIETARY_TERMS_URL_WIDGET = forms.URLInput(
    attrs={
        "class": "form-control",
        "placeholder": "https://example.com/license-terms",
    }
)
PROPRIETARY_TERMS_URL_HELP_TEXT = "URL to your proprietary license terms"
```

**Step 3: Update ProjectForm.Meta.fields**

Update the `fields` list in `ProjectForm.Meta`:

```python
        fields = [
            "name",
            "description",
            "shuttle",
            "project_id",
            "slot_size",
            "is_public",
            "repository_url",
            "license_type",
            "other_license_spdx_id",
            "proprietary_terms_url",
        ]
```

**Step 4: Update ProjectForm.Meta.widgets**

Add to the `widgets` dict:

```python
            "repository_url": REPOSITORY_URL_WIDGET,
            "license_type": LICENSE_TYPE_WIDGET,
            "other_license_spdx_id": OTHER_LICENSE_WIDGET,
            "proprietary_terms_url": PROPRIETARY_TERMS_URL_WIDGET,
```

**Step 5: Update ProjectForm.Meta.help_texts**

Add to the `help_texts` dict:

```python
            "repository_url": REPOSITORY_URL_HELP_TEXT,
            "license_type": LICENSE_TYPE_HELP_TEXT,
            "other_license_spdx_id": OTHER_LICENSE_HELP_TEXT,
            "proprietary_terms_url": PROPRIETARY_TERMS_URL_HELP_TEXT,
```

**Step 6: Add clean method to ProjectForm**

Add this method to the `ProjectForm` class:

```python
    def clean(self):
        """Validate license fields and cache proprietary terms."""
        cleaned_data = super().clean()
        if cleaned_data is None:
            return cleaned_data

        license_type = cleaned_data.get("license_type")
        other_spdx_id = cleaned_data.get("other_license_spdx_id", "").strip()
        terms_url = cleaned_data.get("proprietary_terms_url", "").strip()

        # Validate "other" license type requires valid SPDX ID
        if license_type == LicenseType.OTHER:
            if not other_spdx_id:
                self.add_error(
                    "other_license_spdx_id",
                    "SPDX identifier is required for 'Other' license type",
                )
            else:
                try:
                    validate_spdx_id(other_spdx_id)
                except LicenseValidationError as e:
                    self.add_error("other_license_spdx_id", str(e))
        else:
            # Clear other_license_spdx_id if not "other" type
            cleaned_data["other_license_spdx_id"] = ""

        # Clear proprietary_terms_url if not proprietary
        if license_type != LicenseType.PROPRIETARY:
            cleaned_data["proprietary_terms_url"] = ""
        elif terms_url:
            # Validate and cache proprietary terms URL
            try:
                # Store for use in save()
                self._proprietary_terms_content = None
                from wafer_space.projects.services.license_service import fetch_url_content
                self._proprietary_terms_content = fetch_url_content(terms_url)
            except LicenseValidationError as e:
                self.add_error("proprietary_terms_url", str(e))

        return cleaned_data

    def save(self, commit=True):
        """Save form and update cached proprietary terms."""
        instance = super().save(commit=False)

        # Update cached terms if we fetched them during validation
        if hasattr(self, "_proprietary_terms_content") and self._proprietary_terms_content:
            from django.utils import timezone
            instance.proprietary_terms_cached = self._proprietary_terms_content
            instance.proprietary_terms_cached_at = timezone.now()
        elif instance.license_type != LicenseType.PROPRIETARY or not instance.proprietary_terms_url:
            # Clear cache if no longer proprietary or no URL
            instance.proprietary_terms_cached = ""
            instance.proprietary_terms_cached_at = None

        if commit:
            instance.save()
        return instance
```

**Step 7: Run lint**

Run: `make lint-fix && make lint && make type-check`
Expected: PASS

**Step 8: Commit**

```bash
git add wafer_space/projects/forms.py
git commit -m "feat(projects): add license and repository fields to ProjectForm"
```

---

## Task 8: Update ProjectUserEditForm

**Files:**
- Modify: `wafer_space/projects/forms.py`

**Step 1: Update ProjectUserEditForm.Meta.fields**

Change from:

```python
        fields = ["is_public"]
```

To:

```python
        fields = [
            "is_public",
            "repository_url",
            "license_type",
            "other_license_spdx_id",
            "proprietary_terms_url",
        ]
```

**Step 2: Update ProjectUserEditForm.Meta.widgets**

Change from:

```python
        widgets = {"is_public": IS_PUBLIC_WIDGET}
```

To:

```python
        widgets = {
            "is_public": IS_PUBLIC_WIDGET,
            "repository_url": REPOSITORY_URL_WIDGET,
            "license_type": LICENSE_TYPE_WIDGET,
            "other_license_spdx_id": OTHER_LICENSE_WIDGET,
            "proprietary_terms_url": PROPRIETARY_TERMS_URL_WIDGET,
        }
```

**Step 3: Update ProjectUserEditForm.Meta.help_texts**

Change from:

```python
        help_texts = {"is_public": IS_PUBLIC_HELP_TEXT}
```

To:

```python
        help_texts = {
            "is_public": IS_PUBLIC_HELP_TEXT,
            "repository_url": REPOSITORY_URL_HELP_TEXT,
            "license_type": LICENSE_TYPE_HELP_TEXT,
            "other_license_spdx_id": OTHER_LICENSE_HELP_TEXT,
            "proprietary_terms_url": PROPRIETARY_TERMS_URL_HELP_TEXT,
        }
```

**Step 4: Add clean and save methods to ProjectUserEditForm**

Add to the class (same validation logic as ProjectForm):

```python
    def clean(self):
        """Validate license fields and cache proprietary terms."""
        cleaned_data = super().clean()
        if cleaned_data is None:
            return cleaned_data

        license_type = cleaned_data.get("license_type")
        other_spdx_id = cleaned_data.get("other_license_spdx_id", "").strip()
        terms_url = cleaned_data.get("proprietary_terms_url", "").strip()

        # Validate "other" license type requires valid SPDX ID
        if license_type == LicenseType.OTHER:
            if not other_spdx_id:
                self.add_error(
                    "other_license_spdx_id",
                    "SPDX identifier is required for 'Other' license type",
                )
            else:
                try:
                    validate_spdx_id(other_spdx_id)
                except LicenseValidationError as e:
                    self.add_error("other_license_spdx_id", str(e))
        else:
            # Clear other_license_spdx_id if not "other" type
            cleaned_data["other_license_spdx_id"] = ""

        # Clear proprietary_terms_url if not proprietary
        if license_type != LicenseType.PROPRIETARY:
            cleaned_data["proprietary_terms_url"] = ""
        elif terms_url:
            # Validate and cache proprietary terms URL
            try:
                self._proprietary_terms_content = None
                from wafer_space.projects.services.license_service import fetch_url_content
                self._proprietary_terms_content = fetch_url_content(terms_url)
            except LicenseValidationError as e:
                self.add_error("proprietary_terms_url", str(e))

        return cleaned_data

    def save(self, commit=True):
        """Save form and update cached proprietary terms."""
        instance = super().save(commit=False)

        # Update cached terms if we fetched them during validation
        if hasattr(self, "_proprietary_terms_content") and self._proprietary_terms_content:
            from django.utils import timezone
            instance.proprietary_terms_cached = self._proprietary_terms_content
            instance.proprietary_terms_cached_at = timezone.now()
        elif instance.license_type != LicenseType.PROPRIETARY or not instance.proprietary_terms_url:
            # Clear cache if no longer proprietary or no URL
            instance.proprietary_terms_cached = ""
            instance.proprietary_terms_cached_at = None

        if commit:
            instance.save()
        return instance
```

**Step 5: Run lint**

Run: `make lint-fix && make lint && make type-check`
Expected: PASS

**Step 6: Commit**

```bash
git add wafer_space/projects/forms.py
git commit -m "feat(projects): add license and repository fields to ProjectUserEditForm"
```

---

## Task 9: Write Form Tests

**Files:**
- Modify: `wafer_space/projects/tests/test_forms.py`

**Step 1: Add imports**

Add to imports:

```python
from unittest.mock import patch

from wafer_space.projects.models import LicenseType
from wafer_space.projects.services.license_service import LicenseValidationError
```

**Step 2: Write tests for license validation**

Add new test class:

```python
class TestProjectFormLicenseValidation:
    """Tests for license field validation in ProjectForm."""

    @pytest.fixture
    def base_form_data(self, open_shuttle):
        """Base valid form data."""
        return {
            "name": "Test Project",
            "description": "A test project",
            "shuttle": open_shuttle.pk,
            "project_id": "TEST",
            "slot_size": "1x1",
            "is_public": False,
            "repository_url": "",
            "license_type": "proprietary",
            "other_license_spdx_id": "",
            "proprietary_terms_url": "",
        }

    def test_other_license_requires_spdx_id(self, base_form_data):
        """'Other' license type requires SPDX ID."""
        base_form_data["license_type"] = "other"
        base_form_data["other_license_spdx_id"] = ""

        form = ProjectForm(data=base_form_data)
        assert not form.is_valid()
        assert "other_license_spdx_id" in form.errors

    @patch("wafer_space.projects.forms.validate_spdx_id")
    def test_other_license_validates_spdx_id(self, mock_validate, base_form_data):
        """'Other' license validates SPDX ID."""
        mock_validate.side_effect = LicenseValidationError("Invalid SPDX identifier")
        base_form_data["license_type"] = "other"
        base_form_data["other_license_spdx_id"] = "INVALID-ID"

        form = ProjectForm(data=base_form_data)
        assert not form.is_valid()
        assert "Invalid SPDX identifier" in str(form.errors["other_license_spdx_id"])

    @patch("wafer_space.projects.forms.validate_spdx_id")
    def test_valid_other_license_passes(self, mock_validate, base_form_data):
        """Valid 'Other' license with SPDX ID passes."""
        mock_validate.return_value = True
        base_form_data["license_type"] = "other"
        base_form_data["other_license_spdx_id"] = "GPL-3.0-only"

        form = ProjectForm(data=base_form_data)
        assert form.is_valid(), form.errors

    @patch("wafer_space.projects.forms.fetch_url_content")
    def test_proprietary_terms_url_fetched_and_cached(self, mock_fetch, base_form_data, user):
        """Proprietary terms URL is fetched and content cached."""
        mock_fetch.return_value = "License terms content..."
        base_form_data["license_type"] = "proprietary"
        base_form_data["proprietary_terms_url"] = "https://example.com/terms.txt"

        form = ProjectForm(data=base_form_data)
        assert form.is_valid(), form.errors

        # Save and check cache
        form.instance.user = user
        project = form.save()
        assert project.proprietary_terms_cached == "License terms content..."
        assert project.proprietary_terms_cached_at is not None

    @patch("wafer_space.projects.forms.fetch_url_content")
    def test_proprietary_terms_url_fetch_failure_shows_error(self, mock_fetch, base_form_data):
        """Failed fetch of proprietary terms shows error."""
        mock_fetch.side_effect = LicenseValidationError("Could not fetch")
        base_form_data["license_type"] = "proprietary"
        base_form_data["proprietary_terms_url"] = "https://example.com/bad.txt"

        form = ProjectForm(data=base_form_data)
        assert not form.is_valid()
        assert "proprietary_terms_url" in form.errors

    def test_non_other_license_clears_spdx_id(self, base_form_data):
        """Non-'other' license types clear the SPDX ID field."""
        base_form_data["license_type"] = "MIT"
        base_form_data["other_license_spdx_id"] = "should-be-cleared"

        form = ProjectForm(data=base_form_data)
        assert form.is_valid(), form.errors
        assert form.cleaned_data["other_license_spdx_id"] == ""

    def test_non_proprietary_license_clears_terms_url(self, base_form_data):
        """Non-proprietary license types clear the terms URL field."""
        base_form_data["license_type"] = "MIT"
        base_form_data["proprietary_terms_url"] = "https://example.com/terms.txt"

        form = ProjectForm(data=base_form_data)
        assert form.is_valid(), form.errors
        assert form.cleaned_data["proprietary_terms_url"] == ""

    def test_repository_url_optional(self, base_form_data):
        """Repository URL is optional."""
        base_form_data["repository_url"] = ""

        form = ProjectForm(data=base_form_data)
        assert form.is_valid(), form.errors

    def test_repository_url_accepts_valid_url(self, base_form_data):
        """Repository URL accepts valid URLs."""
        base_form_data["repository_url"] = "https://github.com/user/repo"

        form = ProjectForm(data=base_form_data)
        assert form.is_valid(), form.errors
        assert form.cleaned_data["repository_url"] == "https://github.com/user/repo"
```

**Step 3: Run tests**

Run: `uv run pytest wafer_space/projects/tests/test_forms.py::TestProjectFormLicenseValidation -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add wafer_space/projects/tests/test_forms.py
git commit -m "test(projects): add form tests for license validation"
```

---

## Task 10: Update Project Detail Template

**Files:**
- Modify: `wafer_space/templates/projects/project_detail.html`

**Step 1: Add license and repository display**

Find the section showing "Visibility" (around line 50-57) and add after it:

```html
            <p>
              <strong>License:</strong>
              {% if project.license_type == "proprietary" %}
                <span class="badge bg-secondary">Proprietary</span>
                {% if project.proprietary_terms_url %}
                  <a href="{{ project.proprietary_terms_url }}" target="_blank" rel="noopener">
                    <i class="bi bi-box-arrow-up-right"></i> View Terms
                  </a>
                {% endif %}
              {% elif project.license_type == "other" %}
                <span class="badge bg-info">{{ project.other_license_spdx_id }}</span>
                <a href="https://spdx.org/licenses/{{ project.other_license_spdx_id }}.html" target="_blank" rel="noopener">
                  <i class="bi bi-box-arrow-up-right"></i> View License
                </a>
              {% else %}
                <span class="badge bg-success">{{ project.get_license_type_display }}</span>
                <a href="https://spdx.org/licenses/{{ project.license_type }}.html" target="_blank" rel="noopener">
                  <i class="bi bi-box-arrow-up-right"></i> View License
                </a>
              {% endif %}
            </p>
            {% if project.repository_url %}
              <p>
                <strong>Repository:</strong>
                <a href="{{ project.repository_url }}" target="_blank" rel="noopener">
                  <i class="bi bi-github"></i> {{ project.repository_url }}
                </a>
              </p>
            {% endif %}
```

**Step 2: Run template lint**

Run: `uv run djlint wafer_space/templates/projects/project_detail.html --check`
Expected: PASS (or minor formatting issues to fix)

**Step 3: Commit**

```bash
git add wafer_space/templates/projects/project_detail.html
git commit -m "feat(projects): display license and repository on project detail page"
```

---

## Task 11: Add JavaScript for Conditional Fields

**Files:**
- Modify: `wafer_space/templates/projects/project_form.html`

**Step 1: Add JavaScript for conditional field visibility**

Add at the bottom of the template, before `{% endblock %}`:

```html
{% block extra_js %}
{{ block.super }}
<script>
  document.addEventListener('DOMContentLoaded', function() {
    const licenseTypeField = document.getElementById('id_license_type');
    const otherSpdxIdRow = document.getElementById('id_other_license_spdx_id')?.closest('.mb-3');
    const proprietaryTermsRow = document.getElementById('id_proprietary_terms_url')?.closest('.mb-3');

    function updateFieldVisibility() {
      const licenseType = licenseTypeField?.value;

      if (otherSpdxIdRow) {
        otherSpdxIdRow.style.display = licenseType === 'other' ? '' : 'none';
      }
      if (proprietaryTermsRow) {
        proprietaryTermsRow.style.display = licenseType === 'proprietary' ? '' : 'none';
      }
    }

    if (licenseTypeField) {
      licenseTypeField.addEventListener('change', updateFieldVisibility);
      updateFieldVisibility();  // Set initial state
    }
  });
</script>
{% endblock %}
```

**Step 2: Commit**

```bash
git add wafer_space/templates/projects/project_form.html
git commit -m "feat(projects): add JavaScript for conditional license field visibility"
```

---

## Task 12: Update Admin

**Files:**
- Modify: `wafer_space/projects/admin.py`

**Step 1: Update ProjectAdmin.list_display**

Add to the list:

```python
    list_display = [
        "name",
        "user",
        "shuttle",
        "project_id",
        "full_id",
        "slot_size",
        "status",
        "is_public",
        "license_type",  # ADD
        "created_at",
        "updated_at",
    ]
```

**Step 2: Update ProjectAdmin.list_filter**

Add to the list:

```python
    list_filter = [
        "status",
        "shuttle",
        "slot_size",
        "is_public",
        "license_type",  # ADD
        "created_at",
        "updated_at",
    ]
```

**Step 3: Update ProjectAdmin.search_fields**

Add to the list:

```python
    search_fields = [
        "name",
        "description",
        "user__username",
        "project_id",
        "shuttle__name",
        "repository_url",  # ADD
        "other_license_spdx_id",  # ADD
    ]
```

**Step 4: Run lint**

Run: `make lint-fix && make lint`
Expected: PASS

**Step 5: Commit**

```bash
git add wafer_space/projects/admin.py
git commit -m "feat(projects): add license fields to admin interface"
```

---

## Task 13: Run Full Test Suite

**Step 1: Run all project tests**

Run: `uv run pytest wafer_space/projects/tests/ -v`
Expected: All tests PASS

**Step 2: Run full test suite**

Run: `make test`
Expected: All tests PASS

**Step 3: Run all checks**

Run: `make check-all`
Expected: All checks PASS

---

## Task 14: Final Commit and Summary

**Step 1: Verify git log**

Run: `git log --oneline -15`
Expected: Shows all commits from this implementation

**Step 2: Push branch**

Run: `git push -u origin feature/project-metadata`

---

## Summary

This plan implements:
- **Issue #137**: Repository URL field
- **Issue #193**: License tracking with SPDX validation and proprietary terms caching

Total: 14 tasks, ~45-60 minutes estimated implementation time.
