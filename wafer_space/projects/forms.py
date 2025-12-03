"""Forms for project management."""

from django import forms
from django.core.exceptions import ValidationError

from wafer_space.shuttles.models import Shuttle

from .models import PROJECT_ID_LENGTH
from .models import Project
from .models import ProjectComplianceCertification

# Hash length constants
MD5_HASH_LENGTH = 32
SHA1_HASH_LENGTH = 40
SHA256_HASH_LENGTH = 64

# Compliance form validation constants
MIN_END_USE_STATEMENT_LENGTH = 10


class ProjectForm(forms.ModelForm):
    """Form for creating and editing projects."""

    shuttle = forms.ModelChoiceField(
        queryset=Shuttle.objects.filter(
            status__in=[Shuttle.Status.PLANNING, Shuttle.Status.OPEN],
        ).order_by("name"),
        widget=forms.Select(attrs={"class": "form-control", "id": "id_shuttle"}),
        help_text="Select the shuttle run for this project",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set default shuttle to oldest open shuttle (by created_at)
        if not self.instance.pk:  # Only for new projects
            default_shuttle = (
                Shuttle.objects.filter(
                    status=Shuttle.Status.OPEN,
                )
                .order_by("created_at")
                .first()
            )
            if default_shuttle:
                self.fields["shuttle"].initial = default_shuttle

    project_id = forms.CharField(
        max_length=PROJECT_ID_LENGTH,
        min_length=PROJECT_ID_LENGTH,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "id": "id_project_id",
                "placeholder": "ABCD",
                "maxlength": "4",
                "minlength": "4",
                "pattern": "[A-Z0-9]{4}",
                "style": "text-transform: uppercase;",
                "data-bs-toggle": "popover",
                "data-bs-trigger": "focus",
                "data-bs-placement": "right",
                "data-bs-content": (
                    "Enter a unique 4-character project ID using uppercase letters "
                    "(A-Z) and numbers (0-9). Example: ABCD, TEST, 1234, A1B2"
                ),
                "title": "Project ID Requirements",
            },
        ),
        help_text="4-character alphanumeric identifier (A-Z, 0-9)",
    )

    class Meta:
        model = Project
        fields = ["name", "description", "shuttle", "project_id", "slot_size"]
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
        }
        help_texts = {
            "name": "A descriptive name for your project",
            "description": "Optional details about your design",
            "slot_size": "Select the die slot size for your design",
        }

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
            msg = "Project ID must be exactly 4 characters"
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
