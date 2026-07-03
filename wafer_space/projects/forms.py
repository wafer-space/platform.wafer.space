"""Forms for project management."""

from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from wafer_space.core.enums import SlotSize
from wafer_space.shuttles.models import Shuttle

from .models import PROJECT_ID_LENGTH
from .models import LicenseType
from .models import Project
from .models import ProjectComplianceCertification
from .security import SecurityValidationError
from .security import URLValidator
from .services.license_service import LicenseValidationError
from .services.license_service import fetch_url_content
from .services.license_service import validate_spdx_id

# Hash length constants
MD5_HASH_LENGTH = 32
SHA1_HASH_LENGTH = 40
SHA256_HASH_LENGTH = 64

# Compliance form validation constants
MIN_END_USE_STATEMENT_LENGTH = 10


class LicenseValidationMixin:
    """Mixin for forms that validate license fields.

    Provides shared validation logic for license type, SPDX ID validation,
    URL security validation, and proprietary terms caching.

    This mixin is designed to be used with forms.ModelForm subclasses.
    """

    _proprietary_terms_content: str | None = None

    def _add_field_error(self, field: str, message: str) -> None:
        """Add an error to a form field.

        Wrapper around add_error for type-safe access in mixin.
        """
        if hasattr(self, "add_error"):
            self.add_error(field, message)

    def _validate_license_fields(self, cleaned_data: dict) -> dict:
        """Validate license fields and fetch proprietary terms.

        Args:
            cleaned_data: The form's cleaned_data dict to validate

        Returns:
            dict: The validated cleaned_data with fields cleared as needed
        """
        license_type = cleaned_data.get("license_type")
        other_spdx_id = cleaned_data.get("other_license_spdx_id", "").strip()
        terms_url = cleaned_data.get("proprietary_terms_url", "").strip()

        # Validate "other" license type requires valid SPDX ID
        if license_type == LicenseType.OTHER:
            if not other_spdx_id:
                self._add_field_error(
                    "other_license_spdx_id",
                    "SPDX identifier is required for 'Other' license type",
                )
            else:
                try:
                    validate_spdx_id(other_spdx_id)
                except LicenseValidationError as e:
                    self._add_field_error("other_license_spdx_id", str(e))
        else:
            # Clear other_license_spdx_id if not "other" type
            cleaned_data["other_license_spdx_id"] = ""

        # Clear proprietary_terms_url if not proprietary
        if license_type != LicenseType.PROPRIETARY:
            cleaned_data["proprietary_terms_url"] = ""
        elif terms_url:
            # Validate URL security (scheme and hostname)
            try:
                URLValidator.validate_url_scheme(terms_url)
                URLValidator.validate_hostname(terms_url)
            except SecurityValidationError as e:
                self._add_field_error("proprietary_terms_url", str(e))
                return cleaned_data

            # Fetch and cache proprietary terms
            try:
                # Store for use in save()
                self._proprietary_terms_content = fetch_url_content(terms_url)
            except LicenseValidationError as e:
                self._add_field_error("proprietary_terms_url", str(e))

        return cleaned_data

    def _save_license_fields(self, instance: Project) -> None:
        """Update cached proprietary terms on the instance.

        Handles cache invalidation when URL changes or license type changes.

        Args:
            instance: The Project instance to update
        """
        # Check if proprietary_terms_url has changed (for existing instances).
        # Use _state.adding instead of pk check because Project uses UUID pk
        # which is auto-generated at instance creation, not at save time.
        url_changed = False
        if not instance._state.adding:  # noqa: SLF001
            # Use _loaded_values captured by from_db() instead of extra DB query.
            # If _loaded_values is missing, validation should have already failed.
            loaded = getattr(instance, "_loaded_values", None)
            if loaded is None:
                msg = (
                    f"Cannot check URL change for project {instance.pk}: "
                    "instance was not loaded via QuerySet (missing _loaded_values)."
                )
                raise RuntimeError(msg)
            old_url = loaded.get("proprietary_terms_url", "")
            url_changed = old_url != instance.proprietary_terms_url

        # Update cached terms if we fetched them during validation
        if self._proprietary_terms_content:
            instance.proprietary_terms_cached = self._proprietary_terms_content
            instance.proprietary_terms_cached_at = timezone.now()
        elif instance.license_type != LicenseType.PROPRIETARY:
            # Clear cache if no longer proprietary
            instance.proprietary_terms_cached = ""
            instance.proprietary_terms_cached_at = None
        elif not instance.proprietary_terms_url or url_changed:
            # Clear cache if URL removed or changed (and fetch failed/not attempted)
            instance.proprietary_terms_cached = ""
            instance.proprietary_terms_cached_at = None


class ProjectForm(LicenseValidationMixin, forms.ModelForm):
    """Unified form for creating and editing projects.

    Adapts field availability based on:
    - Whether this is a new project (creation) or existing (edit)
    - Whether the user is staff

    Core fields (shuttle, project_id, slot_size):
    - Editable during creation
    - Editable by staff on existing projects
    - Disabled for non-staff on existing projects

    User fields (name, description, etc.):
    - Always editable by project owner
    """

    # Override license_type to make it not required (model has default)
    license_type = forms.ChoiceField(
        choices=LicenseType.choices,
        required=False,
        widget=forms.Select(attrs={"class": "form-control", "id": "id_license_type"}),
        help_text="License under which this project is released",
    )

    shuttle = forms.ModelChoiceField(
        # Use callable so queryset is evaluated fresh each time, not at class definition
        queryset=Shuttle.objects.none(),  # Overridden in __init__
        widget=forms.Select(attrs={"class": "form-control", "id": "id_shuttle"}),
        help_text="Select the shuttle run for this project",
        empty_label=None,  # Remove "--------" option since we always have a default
    )

    project_id = forms.CharField(
        max_length=PROJECT_ID_LENGTH,
        min_length=PROJECT_ID_LENGTH,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "id": "id_project_id",
                "placeholder": "ABCD",
                "maxlength": str(PROJECT_ID_LENGTH),
                "minlength": str(PROJECT_ID_LENGTH),
                "pattern": f"[A-Z0-9]{{{PROJECT_ID_LENGTH}}}",
                "style": "text-transform: uppercase;",
                "data-bs-toggle": "popover",
                "data-bs-trigger": "focus",
                "data-bs-placement": "right",
                "data-bs-content": (
                    f"Enter a unique {PROJECT_ID_LENGTH}-character project ID using "
                    "uppercase letters (A-Z) and numbers (0-9). "
                    "Example: ABCD, TEST, 1234, A1B2"
                ),
                "title": "Project ID Requirements",
            },
        ),
        help_text=f"{PROJECT_ID_LENGTH}-character alphanumeric identifier (A-Z, 0-9)",
    )

    class Meta:
        model = Project
        fields = [
            # Core fields (immutable after creation except by staff)
            "shuttle",
            "project_id",
            "slot_size",
            # User fields (always editable)
            "name",
            "description",
            "is_public",
            "chip_on_board",
            "repository_url",
            "crowd_supply_order_id",
            "license_type",
            "other_license_spdx_id",
            "proprietary_terms_url",
        ]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "My Chip Design Project",
                },
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Description of your design project...",
                },
            ),
            "slot_size": forms.Select(
                attrs={
                    "class": "form-control",
                    "id": "id_slot_size",
                },
            ),
            "is_public": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "chip_on_board": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "repository_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://github.com/username/repo",
                },
            ),
            "crowd_supply_order_id": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "327373",
                    "inputmode": "numeric",
                },
            ),
            "other_license_spdx_id": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "GPL-3.0-only",
                },
            ),
            "proprietary_terms_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://example.com/license-terms",
                },
            ),
        }
        help_texts = {
            "name": "A descriptive name for your project",
            "description": "Optional details about your design",
            "slot_size": "Select the die slot size for your design",
            "is_public": "Make this design publicly visible on the platform",
            # chip_on_board: help_text inherited from the model field
            "repository_url": "URL to the project's source repository",
            "crowd_supply_order_id": (
                "CrowdSupply order number, e.g. 327373 (optional)."
            ),
            "other_license_spdx_id": (
                "SPDX identifier (e.g., GPL-3.0-only, LGPL-2.1-or-later)"
            ),
            "proprietary_terms_url": "URL to your proprietary license terms",
        }

    def __init__(self, *args, user=None, **kwargs):
        """Initialize form with user context for field configuration.

        Args:
            user: The user submitting the form. Required for determining
                which fields should be editable and for model-level
                immutability validation.

        Note:
            We set `instance._current_user` immediately after super().__init__()
            because Django's ModelForm calls model.full_clean() during is_valid(),
            BEFORE save() is called. The model's clean() method needs to know
            the current user to allow staff to modify core fields while blocking
            non-staff users. Without this early assignment, model validation
            would fail for staff users editing core fields.
        """
        super().__init__(*args, **kwargs)
        self.user = user
        # Must set before is_valid() - see docstring above
        self.instance._current_user = user  # noqa: SLF001

        # Set shuttle queryset fresh each time (not at class definition time).
        # This is critical for tests where shuttles are created after import.
        shuttle_field = self.fields["shuttle"]
        if isinstance(shuttle_field, forms.ModelChoiceField):
            shuttle_field.queryset = Shuttle.objects.filter(
                status=Shuttle.Status.OPEN,
            ).order_by("name")

        self._configure_fields()
        self._set_defaults()

    def _configure_fields(self):
        """Configure field editability based on user and instance state.

        Core fields are disabled for non-staff users editing existing projects.

        Note: We use _state.adding instead of pk is None because the Project
        model uses a UUID primary key that's auto-generated at instance creation,
        not at save time.
        """
        is_new = self.instance._state.adding  # noqa: SLF001
        is_staff = self.user and self.user.is_staff

        for field_name in Project.CORE_FIELDS:
            if field_name not in self.fields:
                continue

            if is_new or is_staff:
                # Editable - keep field as-is
                pass
            else:
                # Disable for non-staff editing existing project
                self.fields[field_name].disabled = True

    def _set_defaults(self):
        """Set default values for new projects."""
        # Use _state.adding instead of pk is None (Project uses UUID pk)
        if not self.instance._state.adding:  # noqa: SLF001
            return

        # Set default shuttle to oldest open shuttle (by created_at)
        default_shuttle = (
            Shuttle.objects.filter(status=Shuttle.Status.OPEN)
            .order_by("created_at")
            .first()
        )
        if default_shuttle:
            self.fields["shuttle"].initial = default_shuttle

        # Set default license_type for new projects
        self.fields["license_type"].initial = LicenseType.PROPRIETARY

        # Use full labels for slot_size dropdown (includes dimensions)
        slot_size_field = self.fields["slot_size"]
        if isinstance(slot_size_field, forms.TypedChoiceField):
            slot_size_field.choices = [
                (size.value, size.full_label) for size in SlotSize
            ]

    def clean(self):
        """Validate license fields and cache proprietary terms."""
        cleaned_data = super().clean()
        if cleaned_data is None:
            return cleaned_data
        return self._validate_license_fields(cleaned_data)

    def clean_crowd_supply_order_id(self) -> str:
        """Strip whitespace and a leading '#' so a pasted '#327373' is accepted."""
        value = self.cleaned_data.get("crowd_supply_order_id", "")
        return value.strip().lstrip("#").strip()

    def clean_project_id(self):
        """Validate and normalize project_id field."""
        project_id = self.cleaned_data.get("project_id", "").upper().strip()

        # Validate format (backup to model validator)
        if not project_id:
            msg = "Project ID is required"
            raise ValidationError(msg)

        if not project_id.isalnum():
            msg = "Project ID must be alphanumeric (A-Z, 0-9)"
            raise ValidationError(msg)

        if len(project_id) != PROJECT_ID_LENGTH:
            msg = f"Project ID must be exactly {PROJECT_ID_LENGTH} characters"
            raise ValidationError(msg)

        # Check uniqueness within shuttle
        shuttle = self.cleaned_data.get("shuttle")
        if shuttle:
            # Exclude current instance if editing
            queryset = Project.objects.filter(
                shuttle=shuttle,
                project_id=project_id,
            )
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                msg = (
                    f"Project ID '{project_id}' is already used in "
                    f"shuttle {shuttle.name}"
                )
                raise ValidationError(msg)

        return project_id

    def save(self, commit: bool = True) -> Project:  # noqa: FBT001, FBT002
        """Save form and update cached proprietary terms."""
        instance = super().save(commit=False)
        self._save_license_fields(instance)
        if commit:
            instance.save()
        return instance


class ProjectFileURLSubmitForm(forms.Form):
    """Form for submitting a file URL for download."""

    url = forms.URLField(
        label="File URL",
        max_length=2048,
        assume_scheme="https",
        widget=forms.URLInput(
            attrs={
                "class": "form-control",
                "placeholder": "https://github.com/user/repo/blob/main/design.gds",
            },
        ),
        help_text=(
            "URL to your GDS/OASIS file (up to 100GB). "
            "Accepted formats: .gds, .gdsii, .gds2, .oas, .oasis "
            "(optionally compressed: .gz, .zip, .bz2, .xz). "
            "Supports GitHub, GitLab, Dropbox, Google Drive, OneDrive."
        ),
    )

    expected_hash_md5 = forms.CharField(
        label="MD5 Hash",
        max_length=64,  # Increased to allow for prefix like "sha256:"
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "abc123def456... or md5:abc123def456...",
            },
        ),
        help_text=(
            "MD5 checksum for file integrity verification (32 hex characters). "
            "Optional prefix like 'md5:' will be stripped."
        ),
    )

    expected_hash_sha1 = forms.CharField(
        label="SHA1 Hash",
        max_length=64,  # Increased to allow for prefix like "sha256:"
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "abc123def456... or sha1:abc123def456...",
            },
        ),
        help_text=(
            "SHA1 checksum for file integrity verification (40 hex characters). "
            "Optional prefix like 'sha1:' will be stripped."
        ),
    )

    expected_hash_sha256 = forms.CharField(
        label="SHA256 Hash",
        max_length=96,  # Increased to allow for prefix like "sha256:"
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "abc123def456... or sha256:abc123def456...",
            },
        ),
        help_text=(
            "SHA256 checksum for file integrity verification (64 hex characters). "
            "Optional prefix like 'sha256:' will be stripped."
        ),
    )

    def clean_url(self):
        """Validate and clean URL field."""
        url = self.cleaned_data.get("url")

        if not url:
            msg = "URL is required"
            raise ValidationError(msg)

        # Strip whitespace
        url = url.strip()

        if not url:
            msg = "URL cannot be empty"
            raise ValidationError(msg)

        return url

    def clean_expected_hash_md5(self):
        """Validate MD5 hash format.

        Supports hash values with or without type prefix.
        Examples: "md5:abc123..." or "abc123..."
        """
        md5_hash = self.cleaned_data.get("expected_hash_md5", "").strip()

        if not md5_hash:
            return ""

        # Strip hash type prefix if present (e.g., "md5:", "sha256:", etc.)
        if ":" in md5_hash:
            # Take the part after the first colon
            md5_hash = md5_hash.split(":", 1)[1].strip()

        # Remove any whitespace or dashes
        md5_hash = md5_hash.replace(" ", "").replace("-", "")

        # Validate length
        if len(md5_hash) != MD5_HASH_LENGTH:
            msg = f"MD5 hash must be exactly {MD5_HASH_LENGTH} hexadecimal characters"
            raise ValidationError(msg)

        # Validate hex characters
        try:
            int(md5_hash, 16)
        except ValueError as e:
            msg = "MD5 hash must contain only hexadecimal characters (0-9, a-f)"
            raise ValidationError(msg) from e

        return md5_hash.lower()

    def clean_expected_hash_sha1(self):
        """Validate SHA1 hash format.

        Supports hash values with or without type prefix.
        Examples: "sha1:abc123..." or "abc123..."
        """
        sha1_hash = self.cleaned_data.get("expected_hash_sha1", "").strip()

        if not sha1_hash:
            return ""

        # Strip hash type prefix if present (e.g., "sha1:", "sha256:", etc.)
        if ":" in sha1_hash:
            # Take the part after the first colon
            sha1_hash = sha1_hash.split(":", 1)[1].strip()

        # Remove any whitespace or dashes
        sha1_hash = sha1_hash.replace(" ", "").replace("-", "")

        # Validate length
        if len(sha1_hash) != SHA1_HASH_LENGTH:
            msg = f"SHA1 hash must be exactly {SHA1_HASH_LENGTH} hexadecimal characters"
            raise ValidationError(msg)

        # Validate hex characters
        try:
            int(sha1_hash, 16)
        except ValueError as e:
            msg = "SHA1 hash must contain only hexadecimal characters (0-9, a-f)"
            raise ValidationError(msg) from e

        return sha1_hash.lower()

    def clean_expected_hash_sha256(self):
        """Validate SHA256 hash format.

        Supports hash values with or without type prefix.
        Examples: "sha256:abc123..." or "abc123..."
        """
        sha256_hash = self.cleaned_data.get("expected_hash_sha256", "").strip()

        if not sha256_hash:
            return ""

        # Strip hash type prefix if present (e.g., "sha256:", "md5:", etc.)
        if ":" in sha256_hash:
            # Take the part after the first colon
            sha256_hash = sha256_hash.split(":", 1)[1].strip()

        # Remove any whitespace or dashes
        sha256_hash = sha256_hash.replace(" ", "").replace("-", "")

        # Validate length
        if len(sha256_hash) != SHA256_HASH_LENGTH:
            msg = (
                f"SHA256 hash must be exactly {SHA256_HASH_LENGTH} "
                "hexadecimal characters"
            )
            raise ValidationError(msg)

        # Validate hex characters
        try:
            int(sha256_hash, 16)
        except ValueError as e:
            msg = "SHA256 hash must contain only hexadecimal characters (0-9, a-f)"
            raise ValidationError(msg) from e

        return sha256_hash.lower()

    def clean(self):
        """Validate that at least one hash is provided."""
        cleaned_data = super().clean()
        if cleaned_data is None:
            return cleaned_data

        md5_hash = cleaned_data.get("expected_hash_md5", "").strip()
        sha1_hash = cleaned_data.get("expected_hash_sha1", "").strip()
        sha256_hash = cleaned_data.get("expected_hash_sha256", "").strip()

        # Require at least one hash
        if not md5_hash and not sha1_hash and not sha256_hash:
            msg = (
                "At least one checksum (MD5, SHA1, or SHA256) is required for file "
                "verification. This ensures file integrity during download."
            )
            raise ValidationError(msg)

        return cleaned_data


class ComplianceCertificationForm(forms.ModelForm):
    """Form for export compliance certification."""

    class Meta:
        model = ProjectComplianceCertification
        fields = [
            "export_control_compliant",
            "not_restricted_entity",
            "end_use_statement",
        ]
        widgets = {
            "export_control_compliant": forms.CheckboxInput(
                attrs={"class": "form-check-input", "required": True},
            ),
            "not_restricted_entity": forms.CheckboxInput(
                attrs={"class": "form-check-input", "required": True},
            ),
            "end_use_statement": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": (
                        "Describe the intended use of this chip (e.g., research, "
                        "commercial product, educational demonstration)"
                    ),
                    "required": True,
                },
            ),
        }
        help_texts = {
            "export_control_compliant": (
                "I confirm this design complies with U.S. Export Control "
                "Regulations (EAR/ITAR)"
            ),
            "not_restricted_entity": (
                "I confirm I am not from a restricted country or sanctioned entity"
            ),
            "end_use_statement": (
                "Provide a clear description of how this chip will be used"
            ),
        }

    def clean_export_control_compliant(self):
        """Ensure export control compliance is confirmed."""
        value = self.cleaned_data.get("export_control_compliant")
        if not value:
            msg = "You must confirm compliance with export control regulations"
            raise ValidationError(msg)
        return value

    def clean_not_restricted_entity(self):
        """Ensure not restricted entity confirmation."""
        value = self.cleaned_data.get("not_restricted_entity")
        if not value:
            msg = (
                "You must confirm you are not from a restricted country "
                "or sanctioned entity"
            )
            raise ValidationError(msg)
        return value

    def clean_end_use_statement(self):
        """Validate end-use statement."""
        value = self.cleaned_data.get("end_use_statement", "").strip()
        if not value:
            msg = "End-use statement is required"
            raise ValidationError(msg)
        if len(value) < MIN_END_USE_STATEMENT_LENGTH:
            msg = (
                f"Please provide a more detailed end-use statement "
                f"(at least {MIN_END_USE_STATEMENT_LENGTH} characters)"
            )
            raise ValidationError(msg)
        return value
