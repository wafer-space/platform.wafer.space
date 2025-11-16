"""Tests for compliance certification forms."""

import pytest
from django.test import TestCase

from wafer_space.projects.forms import MIN_END_USE_STATEMENT_LENGTH
from wafer_space.projects.forms import ComplianceCertificationForm
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectComplianceCertification
from wafer_space.users.models import User

from .constants import TEST_PASSWORD


@pytest.mark.django_db
class TestComplianceCertificationForm(TestCase):
    """Test ComplianceCertificationForm."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project description",
        )

    def test_form_valid_with_all_fields(self):
        """Test form is valid with all required fields."""
        statement = "This chip will be used for educational research purposes."
        form_data = {
            "export_control_compliant": True,
            "not_restricted_entity": True,
            "end_use_statement": statement,
        }
        form = ComplianceCertificationForm(data=form_data)

        assert form.is_valid()
        assert form.cleaned_data["export_control_compliant"] is True
        assert form.cleaned_data["not_restricted_entity"] is True
        assert form.cleaned_data["end_use_statement"] == statement

    def test_form_invalid_without_export_control(self):
        """Test form is invalid without export control compliance."""
        form_data = {
            "export_control_compliant": False,
            "not_restricted_entity": True,
            "end_use_statement": "Educational research purposes.",
        }
        form = ComplianceCertificationForm(data=form_data)

        assert not form.is_valid()
        assert "export_control_compliant" in form.errors

    def test_form_invalid_without_restricted_entity(self):
        """Test form is invalid without restricted entity confirmation."""
        form_data = {
            "export_control_compliant": True,
            "not_restricted_entity": False,
            "end_use_statement": "Educational research purposes.",
        }
        form = ComplianceCertificationForm(data=form_data)

        assert not form.is_valid()
        assert "not_restricted_entity" in form.errors

    def test_form_invalid_with_empty_end_use_statement(self):
        """Test form is invalid with empty end-use statement."""
        form_data = {
            "export_control_compliant": True,
            "not_restricted_entity": True,
            "end_use_statement": "",
        }
        form = ComplianceCertificationForm(data=form_data)

        assert not form.is_valid()
        assert "end_use_statement" in form.errors

    def test_form_invalid_with_short_end_use_statement(self):
        """Test form is invalid with too short end-use statement."""
        form_data = {
            "export_control_compliant": True,
            "not_restricted_entity": True,
            "end_use_statement": "Short",  # Less than MIN_END_USE_STATEMENT_LENGTH
        }
        form = ComplianceCertificationForm(data=form_data)

        assert not form.is_valid()
        assert "end_use_statement" in form.errors
        error_message = form.errors["end_use_statement"][0]
        assert str(MIN_END_USE_STATEMENT_LENGTH) in error_message

    def test_form_invalid_with_whitespace_only_end_use_statement(self):
        """Test form is invalid with whitespace-only end-use statement."""
        form_data = {
            "export_control_compliant": True,
            "not_restricted_entity": True,
            "end_use_statement": "   ",
        }
        form = ComplianceCertificationForm(data=form_data)

        assert not form.is_valid()
        assert "end_use_statement" in form.errors

    def test_form_field_order(self):
        """Test that form fields are in correct order."""
        form = ComplianceCertificationForm()
        field_names = list(form.fields.keys())

        # Field order should match template presentation
        expected_order = [
            "export_control_compliant",
            "not_restricted_entity",
            "end_use_statement",
        ]
        assert field_names == expected_order

    def test_form_widgets_have_correct_classes(self):
        """Test that form widgets have correct CSS classes."""
        form = ComplianceCertificationForm()

        # Checkboxes should have form-check-input class
        export_widget = form.fields["export_control_compliant"].widget
        assert "form-check-input" in export_widget.attrs.get("class", "")

        restricted_widget = form.fields["not_restricted_entity"].widget
        assert "form-check-input" in restricted_widget.attrs.get("class", "")

        # Textarea should have form-control class
        statement_widget = form.fields["end_use_statement"].widget
        assert "form-control" in statement_widget.attrs.get("class", "")

    def test_form_saves_correctly(self):
        """Test form saves certification correctly."""
        form_data = {
            "export_control_compliant": True,
            "not_restricted_entity": True,
            "end_use_statement": "This chip will be used for commercial applications.",
        }
        form = ComplianceCertificationForm(data=form_data)

        assert form.is_valid()

        # Save with project and user
        certification = form.save(commit=False)
        certification.project = self.project
        certification.certified_by = self.user
        certification.ip_address = "192.168.1.1"
        certification.user_agent = "Test Browser"
        certification.save()

        # Verify saved correctly
        assert ProjectComplianceCertification.objects.count() == 1
        saved_cert = ProjectComplianceCertification.objects.first()
        assert saved_cert is not None
        assert saved_cert.export_control_compliant is True
        assert saved_cert.not_restricted_entity is True
        assert (
            saved_cert.end_use_statement
            == "This chip will be used for commercial applications."
        )
        assert saved_cert.project == self.project
        assert saved_cert.certified_by == self.user
        assert saved_cert.ip_address == "192.168.1.1"
        assert saved_cert.user_agent == "Test Browser"

    def test_form_pre_populates_existing_certification(self):
        """Test form pre-populates with existing certification data."""
        # Create existing certification
        existing_cert = ProjectComplianceCertification.objects.create(
            project=self.project,
            certified_by=self.user,
            export_control_compliant=True,
            not_restricted_entity=True,
            end_use_statement="Original statement for research purposes.",
            ip_address="192.168.1.1",
            user_agent="Test Browser",
        )

        # Create form with existing instance
        form = ComplianceCertificationForm(instance=existing_cert)

        # Verify form is pre-populated
        expected_statement = "Original statement for research purposes."
        assert form.initial["export_control_compliant"] is True
        assert form.initial["not_restricted_entity"] is True
        assert form.initial["end_use_statement"] == expected_statement

    def test_end_use_statement_strips_whitespace(self):
        """Test that end-use statement strips leading/trailing whitespace."""
        form_data = {
            "export_control_compliant": True,
            "not_restricted_entity": True,
            "end_use_statement": "  Educational research with extra spaces  ",
        }
        form = ComplianceCertificationForm(data=form_data)

        expected_cleaned = "Educational research with extra spaces"
        assert form.is_valid()
        assert form.cleaned_data["end_use_statement"] == expected_cleaned

    def test_help_text_present(self):
        """Test that help text is present for all fields."""
        form = ComplianceCertificationForm()

        assert form.fields["export_control_compliant"].help_text
        assert "EAR/ITAR" in form.fields["export_control_compliant"].help_text

        assert form.fields["not_restricted_entity"].help_text
        assert "restricted" in form.fields["not_restricted_entity"].help_text

        assert form.fields["end_use_statement"].help_text
        assert "use" in form.fields["end_use_statement"].help_text
