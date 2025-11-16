"""Forms for project management."""

from django import forms
from django.core.exceptions import ValidationError

from .models import Project
from .models import ProjectComplianceCertification

# Hash length constants
MD5_HASH_LENGTH = 32
SHA1_HASH_LENGTH = 40

# Compliance form validation constants
MIN_END_USE_STATEMENT_LENGTH = 10


class ProjectForm(forms.ModelForm):
    """Form for creating and editing projects."""

    class Meta:
        model = Project
        fields = ["name", "description"]
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
        }
        help_texts = {
            "name": "A descriptive name for your project",
            "description": "Optional details about your design",
        }


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
        max_length=32,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "abc123def456...",
                "pattern": "[a-fA-F0-9]{32}",
            },
        ),
        help_text="MD5 checksum for file integrity verification (32 hex characters)",
    )

    expected_hash_sha1 = forms.CharField(
        label="SHA1 Hash",
        max_length=40,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "abc123def456...",
                "pattern": "[a-fA-F0-9]{40}",
            },
        ),
        help_text="SHA1 checksum for file integrity verification (40 hex characters)",
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
        """Validate MD5 hash format."""
        md5_hash = self.cleaned_data.get("expected_hash_md5", "").strip()

        if not md5_hash:
            return ""

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
        """Validate SHA1 hash format."""
        sha1_hash = self.cleaned_data.get("expected_hash_sha1", "").strip()

        if not sha1_hash:
            return ""

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

    def clean(self):
        """Validate that at least one hash is provided."""
        cleaned_data = super().clean()
        if cleaned_data is None:
            return cleaned_data

        md5_hash = cleaned_data.get("expected_hash_md5", "").strip()
        sha1_hash = cleaned_data.get("expected_hash_sha1", "").strip()

        # Require at least one hash
        if not md5_hash and not sha1_hash:
            msg = (
                "At least one checksum (MD5 or SHA1) is required for file "
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
