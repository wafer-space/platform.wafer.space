"""Forms for project management."""

from django import forms
from django.core.exceptions import ValidationError

from .models import Project
from .models import ProjectFile

# Hash length constants
MD5_HASH_LENGTH = 32
SHA1_HASH_LENGTH = 40


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
            "URL to your GDS file (up to 100GB). "
            "Supports GitHub, GitLab, Dropbox, Google Drive, OneDrive."
        ),
    )

    expected_hash_md5 = forms.CharField(
        label="MD5 Hash (Optional)",
        max_length=32,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "abc123def456...",
                "pattern": "[a-fA-F0-9]{32}",
            },
        ),
        help_text="Optional: MD5 hash for verification (32 hex characters)",
    )

    expected_hash_sha1 = forms.CharField(
        label="SHA1 Hash (Optional)",
        max_length=40,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "abc123def456...",
                "pattern": "[a-fA-F0-9]{40}",
            },
        ),
        help_text="Optional: SHA1 hash for verification (40 hex characters)",
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


class ProjectFileLocalUploadForm(forms.ModelForm):
    """Form for uploading a file directly (not from URL)."""

    class Meta:
        model = ProjectFile
        fields = ["file", "file_type", "expected_hash_md5", "expected_hash_sha1"]
        widgets = {
            "file": forms.FileInput(
                attrs={
                    "class": "form-control",
                },
            ),
            "file_type": forms.Select(
                attrs={
                    "class": "form-select",
                },
            ),
            "expected_hash_md5": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "abc123def456... (optional)",
                    "pattern": "[a-fA-F0-9]{32}",
                },
            ),
            "expected_hash_sha1": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "abc123def456... (optional)",
                    "pattern": "[a-fA-F0-9]{40}",
                },
            ),
        }
        help_texts = {
            "file": "Upload your design file directly",
            "file_type": "Type of design file",
            "expected_hash_md5": "Optional: MD5 hash for verification",
            "expected_hash_sha1": "Optional: SHA1 hash for verification",
        }

    def clean_expected_hash_md5(self):
        """Validate MD5 hash format."""
        md5_hash = self.cleaned_data.get("expected_hash_md5", "").strip()

        if not md5_hash:
            return ""

        # Remove any whitespace or dashes
        md5_hash = md5_hash.replace(" ", "").replace("-", "")

        if len(md5_hash) != MD5_HASH_LENGTH:
            msg = f"MD5 hash must be exactly {MD5_HASH_LENGTH} hexadecimal characters"
            raise ValidationError(msg)

        try:
            int(md5_hash, 16)
        except ValueError as e:
            msg = "MD5 hash must contain only hexadecimal characters"
            raise ValidationError(msg) from e

        return md5_hash.lower()

    def clean_expected_hash_sha1(self):
        """Validate SHA1 hash format."""
        sha1_hash = self.cleaned_data.get("expected_hash_sha1", "").strip()

        if not sha1_hash:
            return ""

        # Remove any whitespace or dashes
        sha1_hash = sha1_hash.replace(" ", "").replace("-", "")

        if len(sha1_hash) != SHA1_HASH_LENGTH:
            msg = f"SHA1 hash must be exactly {SHA1_HASH_LENGTH} hexadecimal characters"
            raise ValidationError(msg)

        try:
            int(sha1_hash, 16)
        except ValueError as e:
            msg = "SHA1 hash must contain only hexadecimal characters"
            raise ValidationError(msg) from e

        return sha1_hash.lower()
