"""Tests for compliance certification views."""

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.test import RequestFactory
from django.test import TestCase
from django.urls import reverse

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectComplianceCertification
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.views_compliance import get_client_ip
from wafer_space.users.models import User

from .constants import HTTP_FOUND
from .constants import HTTP_NOT_FOUND
from .constants import HTTP_OK
from .constants import TEST_PASSWORD


@pytest.mark.django_db
class TestGetClientIP(TestCase):
    """Test get_client_ip helper function."""

    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()

    def test_extracts_ip_from_remote_addr(self):
        """Test extracting IP from REMOTE_ADDR when no X-Forwarded-For."""
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "192.168.1.100"

        ip = get_client_ip(request)
        assert ip == "192.168.1.100"

    def test_extracts_ip_from_x_forwarded_for(self):
        """Test extracting IP from X-Forwarded-For header."""
        request = self.factory.get("/")
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.195, 192.168.1.1"
        request.META["REMOTE_ADDR"] = "192.168.1.1"

        ip = get_client_ip(request)
        assert ip == "203.0.113.195"

    def test_strips_whitespace_from_x_forwarded_for(self):
        """Test that whitespace is stripped from X-Forwarded-For IP."""
        request = self.factory.get("/")
        request.META["HTTP_X_FORWARDED_FOR"] = "  203.0.113.195  , 192.168.1.1"
        request.META["REMOTE_ADDR"] = "192.168.1.1"

        ip = get_client_ip(request)
        assert ip == "203.0.113.195"

    def test_validates_ipv4_address(self):
        """Test that IPv4 addresses are validated."""
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "192.168.1.100"

        ip = get_client_ip(request)
        assert ip == "192.168.1.100"

    def test_validates_ipv6_address(self):
        """Test that IPv6 addresses are validated."""
        request = self.factory.get("/")
        request.META["REMOTE_ADDR"] = "2001:0db8:85a3:0000:0000:8a2e:0370:7334"

        ip = get_client_ip(request)
        assert ip == "2001:0db8:85a3:0000:0000:8a2e:0370:7334"

    def test_falls_back_to_remote_addr_on_invalid_x_forwarded_for(self):
        """Test fallback to REMOTE_ADDR when X-Forwarded-For is invalid."""
        request = self.factory.get("/")
        request.META["HTTP_X_FORWARDED_FOR"] = "invalid-ip-address"
        request.META["REMOTE_ADDR"] = "192.168.1.1"

        ip = get_client_ip(request)
        # Falls back to REMOTE_ADDR which is validated and returned
        assert ip == "192.168.1.1"

    def test_returns_fallback_ip_when_x_forwarded_for_invalid(self):
        """Test returns fallback REMOTE_ADDR when X-Forwarded-For is invalid."""
        request = self.factory.get("/")
        # Invalid X-Forwarded-For should trigger fallback
        request.META["HTTP_X_FORWARDED_FOR"] = "not-an-ip"
        request.META["REMOTE_ADDR"] = "10.0.0.1"

        ip = get_client_ip(request)
        # Should fall back to REMOTE_ADDR
        assert ip == "10.0.0.1"

    def test_handles_empty_x_forwarded_for(self):
        """Test handling when X-Forwarded-For is empty."""
        request = self.factory.get("/")
        request.META["HTTP_X_FORWARDED_FOR"] = ""
        request.META["REMOTE_ADDR"] = "192.168.1.1"

        # Should fall back to REMOTE_ADDR
        ip = get_client_ip(request)
        assert ip == "192.168.1.1"


@pytest.mark.django_db
class TestComplianceCertificationCreateView(TestCase):
    """Test compliance_certify view."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password=TEST_PASSWORD,
        )
        self.other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password=TEST_PASSWORD,
        )

        # Create project with manufacturable check
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project description",
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            source_url="https://example.com/test.gds",
            is_active=True,
        )
        self.check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse(
            "projects:compliance_certify",
            kwargs={"pk": self.project.pk},
        )
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        assert "/accounts/login/" in response["Location"]

    def test_requires_project_ownership(self):
        """Test that view requires project ownership."""
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse(
            "projects:compliance_certify",
            kwargs={"pk": self.project.pk},
        )
        response = self.client.get(url)

        # Should return 404 (project doesn't belong to this user)
        assert response.status_code == HTTP_NOT_FOUND

    def test_redirects_if_no_manufacturability_check(self):
        """Test that view redirects if project has no manufacturability check."""
        # Create project without check
        project_without_check = Project.objects.create(
            user=self.user,
            name="Unchecked Project",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:compliance_certify",
            kwargs={"pk": project_without_check.pk},
        )
        response = self.client.get(url)

        # Should redirect to project detail
        assert response.status_code == HTTP_FOUND
        assert f"/projects/{project_without_check.pk}/" in response["Location"]

        # Check error message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "manufacturability" in str(messages[0]).lower()

    def test_redirects_if_not_manufacturable(self):
        """Test that view redirects if project is not manufacturable."""
        # Update check to not manufacturable
        self.check.is_manufacturable = False
        self.check.errors = [{"error": "Test error"}]
        self.check.save()

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:compliance_certify",
            kwargs={"pk": self.project.pk},
        )
        response = self.client.get(url)

        # Should redirect to project detail
        assert response.status_code == HTTP_FOUND
        assert f"/projects/{self.project.pk}/" in response["Location"]

        # Check error message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "manufacturability" in str(messages[0]).lower()

    def test_redirects_if_latest_revision_unchecked(self):
        """A passing check on an older revision must not open the gate.

        Manufacturability is per file revision
        (docs/manufacturable_vs_submitted.md): a new latest revision with
        no checks means the gate must close, even though an older revision
        passed.
        """
        self.project_file.is_active = False
        self.project_file.save()
        ProjectFile.objects.create(
            project=self.project,
            original_filename="test_v2.gds",
            source_url="https://example.com/test_v2.gds",
            is_active=True,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:compliance_certify",
            kwargs={"pk": self.project.pk},
        )
        response = self.client.get(url)

        assert response.status_code == HTTP_FOUND
        assert f"/projects/{self.project.pk}/" in response["Location"]
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "manufacturability" in str(messages[0]).lower()

    def test_get_shows_form(self):
        """Test GET request shows certification form."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:compliance_certify",
            kwargs={"pk": self.project.pk},
        )
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "form" in response.context
        assert "project" in response.context
        assert response.context["project"] == self.project

    def test_get_shows_info_message_if_already_certified(self):
        """Test GET shows info message if project already certified."""
        # Create existing certification
        ProjectComplianceCertification.objects.create(
            project=self.project,
            certified_by=self.user,
            export_control_compliant=True,
            not_restricted_entity=True,
            end_use_statement="Original certification statement.",
            ip_address="192.168.1.1",
            user_agent="Test Browser",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:compliance_certify",
            kwargs={"pk": self.project.pk},
        )
        response = self.client.get(url)

        assert response.status_code == HTTP_OK

        # Check info message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "already been certified" in str(messages[0])

    def test_get_prepopulates_form_if_already_certified(self):
        """Test GET pre-populates form with existing certification data."""
        # Create existing certification
        ProjectComplianceCertification.objects.create(
            project=self.project,
            certified_by=self.user,
            export_control_compliant=True,
            not_restricted_entity=True,
            end_use_statement="Original certification statement.",
            ip_address="192.168.1.1",
            user_agent="Test Browser",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:compliance_certify",
            kwargs={"pk": self.project.pk},
        )
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        form = response.context["form"]

        # Form should be pre-populated
        assert form.initial["export_control_compliant"] is True
        assert form.initial["not_restricted_entity"] is True
        assert form.initial["end_use_statement"] == "Original certification statement."

    def test_post_creates_new_certification(self):
        """Test POST creates new certification."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:compliance_certify",
            kwargs={"pk": self.project.pk},
        )

        form_data = {
            "export_control_compliant": True,
            "not_restricted_entity": True,
            "end_use_statement": "This chip will be used for educational research.",
        }
        response = self.client.post(url, data=form_data)

        # Should redirect to project detail
        assert response.status_code == HTTP_FOUND
        expected_url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        assert response["Location"] == expected_url

        # Check success message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "successfully" in str(messages[0]).lower()

        # Verify certification created
        assert ProjectComplianceCertification.objects.count() == 1
        cert = ProjectComplianceCertification.objects.first()
        assert cert is not None
        expected_statement = "This chip will be used for educational research."
        assert cert.project == self.project
        assert cert.certified_by == self.user
        assert cert.export_control_compliant is True
        assert cert.not_restricted_entity is True
        assert cert.end_use_statement == expected_statement

    def test_post_captures_ip_address(self):
        """Test POST captures client IP address."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:compliance_certify",
            kwargs={"pk": self.project.pk},
        )

        form_data = {
            "export_control_compliant": True,
            "not_restricted_entity": True,
            "end_use_statement": "Educational research purposes.",
        }

        # Set REMOTE_ADDR to simulate client IP
        response = self.client.post(
            url,
            data=form_data,
            REMOTE_ADDR="203.0.113.195",
        )

        assert response.status_code == HTTP_FOUND

        # Verify IP captured
        cert = ProjectComplianceCertification.objects.first()
        assert cert is not None
        assert cert.ip_address == "203.0.113.195"

    def test_post_captures_user_agent(self):
        """Test POST captures user agent."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:compliance_certify",
            kwargs={"pk": self.project.pk},
        )

        form_data = {
            "export_control_compliant": True,
            "not_restricted_entity": True,
            "end_use_statement": "Educational research purposes.",
        }

        # Set HTTP_USER_AGENT
        response = self.client.post(
            url, data=form_data, headers={"user-agent": "Mozilla/5.0 Test Browser"}
        )

        assert response.status_code == HTTP_FOUND

        # Verify user agent captured
        cert = ProjectComplianceCertification.objects.first()
        assert cert is not None
        assert cert.user_agent == "Mozilla/5.0 Test Browser"

    def test_post_updates_existing_certification(self):
        """Test POST updates existing certification instead of creating duplicate."""
        # Create existing certification
        existing_cert = ProjectComplianceCertification.objects.create(
            project=self.project,
            certified_by=self.user,
            export_control_compliant=True,
            not_restricted_entity=True,
            end_use_statement="Original statement.",
            ip_address="192.168.1.1",
            user_agent="Old Browser",
        )
        original_certified_at = existing_cert.certified_at

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:compliance_certify",
            kwargs={"pk": self.project.pk},
        )

        form_data = {
            "export_control_compliant": True,
            "not_restricted_entity": True,
            "end_use_statement": "Updated statement for commercial use.",
        }
        response = self.client.post(
            url,
            data=form_data,
            REMOTE_ADDR="203.0.113.195",
            headers={"user-agent": "New Browser"},
        )

        assert response.status_code == HTTP_FOUND

        # Should still be only one certification
        assert ProjectComplianceCertification.objects.count() == 1

        # Verify certification updated
        cert = ProjectComplianceCertification.objects.first()
        assert cert is not None
        assert cert.id == existing_cert.id
        assert cert.end_use_statement == "Updated statement for commercial use."
        assert cert.ip_address == "203.0.113.195"
        assert cert.user_agent == "New Browser"
        assert cert.certified_at == original_certified_at  # Should not change

    def test_post_invalid_form_shows_errors(self):
        """Test POST with invalid form shows errors."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:compliance_certify",
            kwargs={"pk": self.project.pk},
        )

        # Missing required fields
        form_data = {
            "export_control_compliant": False,  # Invalid
            "not_restricted_entity": True,
            "end_use_statement": "Short",  # Too short
        }
        response = self.client.post(url, data=form_data)

        assert response.status_code == HTTP_OK
        assert "form" in response.context
        assert not response.context["form"].is_valid()

        # Check error message
        messages = list(get_messages(response.wsgi_request))
        assert any("correct the errors" in str(msg).lower() for msg in messages)

        # No certification should be created
        assert ProjectComplianceCertification.objects.count() == 0

    def test_context_includes_certification_if_exists(self):
        """Test that context includes existing certification."""
        # Create existing certification
        existing_cert = ProjectComplianceCertification.objects.create(
            project=self.project,
            certified_by=self.user,
            export_control_compliant=True,
            not_restricted_entity=True,
            end_use_statement="Existing statement.",
            ip_address="192.168.1.1",
            user_agent="Test Browser",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:compliance_certify",
            kwargs={"pk": self.project.pk},
        )
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "certification" in response.context
        assert response.context["certification"] == existing_cert

    def test_context_certification_is_none_if_not_exists(self):
        """Test that context certification is None if doesn't exist."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:compliance_certify",
            kwargs={"pk": self.project.pk},
        )
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "certification" in response.context
        assert response.context["certification"] is None
