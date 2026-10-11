"""Tests for project views."""

import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db import connection
from django.template.loader import render_to_string
from django.test import Client
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from wafer_space.core.enums import SlotSize
from wafer_space.projects.list_state import ListStateAnnotations
from wafer_space.projects.list_state import annotate_list_state
from wafer_space.projects.models import DownloadAttempt
from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import PrecheckImageRevision
from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectAccessLog
from wafer_space.projects.models import ProjectFile
from wafer_space.projects.security import SecurityValidationError
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.projects.tests.factories import ProjectFileFactory
from wafer_space.projects.tests.factories import make_downloaded_file
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.shuttles.tests.factories import ShuttleFactory
from wafer_space.users.models import User
from wafer_space.users.tests.factories import UserFactory

from .constants import EXPECTED_CHECKS_AFTER_COB_TOGGLE
from .constants import EXPECTED_USER_PROJECTS
from .constants import FIVE_MB
from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_METHOD_NOT_ALLOWED
from .constants import HTTP_NOT_FOUND
from .constants import HTTP_OK
from .constants import PROGRESS_COMPLETE
from .constants import PROGRESS_HALF
from .constants import TEN_MB
from .constants import TEST_PASSWORD


@pytest.mark.django_db
class TestProjectListView(TestCase):
    """Test ProjectListView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password=TEST_PASSWORD
        )

        # Create projects for both users
        self.project1 = Project.objects.create(
            user=self.user, name="Project 1", description="First project"
        )
        self.project2 = Project.objects.create(
            user=self.user, name="Project 2", description="Second project"
        )
        self.other_project = Project.objects.create(
            user=self.other_user,
            name="Other Project",
            description="Other user's project",
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:list")
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        # Check redirect location (use Location header for type safety)
        assert "/accounts/login/" in response["Location"]

    def test_shows_only_user_projects(self):
        """Test that view shows only current user's projects."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:list")
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "projects" in response.context
        projects = response.context["projects"]

        # Should show user's projects
        assert len(projects) == EXPECTED_USER_PROJECTS
        assert self.project1 in projects
        assert self.project2 in projects
        assert self.other_project not in projects

    def test_shows_cob_badge_for_chip_on_board_project(self):
        """Chip-on-Board projects show a CoB badge in the list."""
        self.project1.chip_on_board = True
        self.project1.save()
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(reverse("projects:list"))

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "bi-cpu" in content
        assert 'title="Chip-on-Board (CoB) packaging"' in content

    def test_shows_bare_badge_for_non_cob_project(self):
        """Non-CoB projects show a Bare badge in the list."""
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(reverse("projects:list"))

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert 'title="Bare die (no packaging)"' in content
        assert "Bare Die" not in content

    def test_packaging_badges_use_consistent_color(self):
        """CoB and Bare packaging badges share the same badge color."""
        self.project1.chip_on_board = True
        self.project1.save()
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(reverse("projects:list"))

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert 'title="Chip-on-Board (CoB) packaging"' in content
        assert 'title="Bare die (no packaging)"' in content
        # Both packaging badges use the same bg-secondary style; no bg-info
        # appears anywhere for a non-staff user viewing their own projects.
        assert "bg-info" not in content
        min_secondary_badges = 2
        assert content.count("badge bg-secondary") >= min_secondary_badges

    def test_shows_submitted_indicator(self):
        """Submitted projects show a submitted-for-manufacturing badge.

        The badge is keyed on submitted_file, the canonical submission
        signal (see docs/manufacturable_vs_submitted.md).
        """
        submitted_file = ProjectFileFactory(project=self.project1)
        self.project1.status = Project.Status.SUBMITTED
        self.project1.submitted_at = timezone.now()
        self.project1.submitted_file = submitted_file
        self.project1.save()
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(reverse("projects:list"))

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert 'title="Submitted for manufacturing"' in content

    def test_shows_not_submitted_indicator(self):
        """Draft projects show a not-submitted indicator."""
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(reverse("projects:list"))

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert 'title="Not submitted for manufacturing"' in content

    def test_shows_crowd_supply_order_link(self):
        """Projects with a CrowdSupply order link to the CS order page."""
        self.project1.crowd_supply_order_id = "327373"
        self.project1.save()
        self.client.login(username="testuser", password=TEST_PASSWORD)

        response = self.client.get(reverse("projects:list"))

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "https://www.crowdsupply.com/account/order/327373" in content
        assert "327373" in content


@pytest.mark.django_db
class TestProjectDetailView(TestCase):
    """Test ProjectDetailView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test project"
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        # Check redirect location (use Location header for type safety)
        assert "/accounts/login/" in response["Location"]

    def test_owner_can_view(self):
        """Test that owner can view project."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["project"] == self.project

    def test_non_owner_cannot_view(self):
        """Test that non-owner cannot view project."""
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == HTTP_FORBIDDEN

    def test_label_links_to_campaign_and_id_links_to_order_page(self):
        """Label links to the shuttle campaign page; ID links to the order page."""
        shuttle = Shuttle.objects.create(
            name="G851",
            description="Linked run",
            crowd_supply_url="https://www.crowdsupply.com/wafer-space/gf180mcu-run-1/",
        )
        project = Project.objects.create(
            user=self.user,
            name="Linked Project",
            shuttle=shuttle,
            crowd_supply_order_id="327373",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "CrowdSupply Order ID:" in content
        assert shuttle.crowd_supply_url in content
        assert "https://www.crowdsupply.com/account/order/327373" in content

    def test_order_id_links_to_order_page_when_shuttle_has_no_url(self):
        """The ID still links to the order page when the shuttle URL is blank."""
        shuttle = Shuttle.objects.create(name="G852", description="Unlinked run")
        project = Project.objects.create(
            user=self.user,
            name="Unlinked Project",
            shuttle=shuttle,
            crowd_supply_order_id="327373",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "CrowdSupply Order ID:" in content
        assert "https://www.crowdsupply.com/account/order/327373" in content
        # No campaign link: the label renders as plain text.
        assert "https://www.crowdsupply.com/wafer-space/" not in content

    def test_order_id_links_to_order_page_when_project_has_no_shuttle(self):
        """The ID still links to the order page when the project has no shuttle."""
        self.project.crowd_supply_order_id = "327373"
        self.project.save()

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "CrowdSupply Order ID:" in content
        assert "https://www.crowdsupply.com/account/order/327373" in content
        assert "https://www.crowdsupply.com/wafer-space/" not in content

    def test_row_always_shown_with_not_set_when_blank(self):
        """The row renders with 'Not set' when the order ID is blank."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "CrowdSupply Order ID:" in content
        assert "Not set" in content
        assert "https://www.crowdsupply.com/account/order/" not in content

    def test_blank_id_shows_not_set_with_campaign_linked_label(self):
        """A blank ID shows 'Not set' while the label still links to the campaign."""
        shuttle = Shuttle.objects.create(
            name="G853",
            description="Linked run without order",
            crowd_supply_url="https://www.crowdsupply.com/wafer-space/gf180mcu-run-1/",
        )
        project = Project.objects.create(
            user=self.user,
            name="No Order Project",
            shuttle=shuttle,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "CrowdSupply Order ID:" in content
        assert shuttle.crowd_supply_url in content
        assert "Not set" in content
        assert "https://www.crowdsupply.com/account/order/" not in content

    def test_includes_active_file_in_context(self):
        """Test that active file is included in context."""
        # Create active file
        active_file = project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        # Active file is provided as in_progress_file in the context
        assert response.context["in_progress_file"] == active_file

    def test_project_detail_staff_access(self):
        """Test that staff user can access any project detail view."""
        staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.get(
            reverse("projects:detail", kwargs={"pk": self.project.pk})
        )
        assert response.status_code == HTTP_OK
        assert response.context["project"] == self.project
        assert response.context["viewing_as_admin"] is True

    def test_detail_shows_cob_badge_when_requested(self):
        """Detail page shows the CoB badge when chip_on_board is set."""
        self.project.chip_on_board = True
        self.project.save()
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})

        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert 'title="Chip-on-Board (CoB) packaging"' in content
        assert "bi-cpu" in content

    def test_detail_shows_bare_packaging_when_not_requested(self):
        """Detail page labels non-CoB packaging as 'Bare'."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})

        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "Chip-on-Board (CoB) packaging" not in content
        assert "Packaging:" in content
        assert 'title="Bare die (no packaging)"' in content
        assert "Bare Die" not in content

    def test_detail_shows_cob_change_badge_in_check_history(self):
        """Detail page shows CoB Change badge for COB_CHANGE trigger in history."""
        project_file = ProjectFileFactory(project=self.project)
        self.project.submitted_file = project_file
        self.project.save()
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            trigger_reason=ManufacturabilityCheck.TriggerReason.COB_CHANGE,
        )
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})

        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "CoB Change" in response.content.decode()


@pytest.mark.django_db
class TestProjectListQueryCount:
    """The project list must not run a query per project."""

    def test_query_count_does_not_grow_with_project_count(self, client):
        """Guard against an N+1 in the list.

        Every row links via get_absolute_url(), which reads full_id and so
        touches the shuttle FK. Without select_related("shuttle") that costs
        one extra query per project. Asserting the count is unchanged by
        adding rows catches that without pinning a brittle absolute number.
        """
        user = UserFactory()
        shuttle = Shuttle.objects.create(name="G881", description="List run")
        ProjectFactory(user=user, shuttle=shuttle)
        client.force_login(user)
        url = reverse("projects:list")

        with CaptureQueriesContext(connection) as one_project:
            client.get(url)

        ProjectFactory.create_batch(5, user=user, shuttle=shuttle)

        with CaptureQueriesContext(connection) as six_projects:
            client.get(url)

        assert len(six_projects.captured_queries) == len(one_project.captured_queries)


@pytest.mark.django_db
class TestProjectDetailPkRedirect:
    """The pk URL redirects to the canonical full_id URL."""

    def test_pk_redirects_to_full_id_for_owner(self, client):
        """Owner hitting the pk URL is sent to the canonical full_id URL."""
        user = UserFactory()
        shuttle = Shuttle.objects.create(name="G871", description="Redirect run")
        project = ProjectFactory(user=user, shuttle=shuttle)
        client.force_login(user)

        response = client.get(reverse("projects:detail", kwargs={"pk": project.pk}))

        assert response.status_code == HTTP_FOUND
        assert response["Location"] == reverse(
            "projects:detail_by_full_id", kwargs={"full_id": project.full_id}
        )

    def test_redirect_preserves_query_string(self, client):
        """The canonical URL answers the request the pk URL was asked.

        Dropping the query string would silently discard the caller's
        parameters on every redirected link.
        """
        user = UserFactory()
        shuttle = Shuttle.objects.create(name="G880", description="Query run")
        project = ProjectFactory(user=user, shuttle=shuttle)
        client.force_login(user)

        response = client.get(
            reverse("projects:detail", kwargs={"pk": project.pk}),
            {"tab": "files", "page": "2"},
        )

        assert response.status_code == HTTP_FOUND
        canonical = reverse(
            "projects:detail_by_full_id", kwargs={"full_id": project.full_id}
        )
        assert response["Location"] == f"{canonical}?tab=files&page=2"

    def test_pk_serves_page_when_project_has_no_shuttle(self, client):
        """Without a shuttle there is no full_id, so the pk URL serves the page."""
        user = UserFactory()
        project = ProjectFactory(user=user, shuttle=None)
        client.force_login(user)

        response = client.get(reverse("projects:detail", kwargs={"pk": project.pk}))

        assert project.full_id == ""
        assert response.status_code == HTTP_OK

    def test_anonymous_is_sent_to_login_and_learns_no_full_id(self, client):
        """Anonymous users must not learn a project's manufacturing ID.

        Regression test: redirecting before the login check ran turned this
        view into an existence oracle that disclosed the full_id to anyone
        holding a pk.
        """
        shuttle = Shuttle.objects.create(name="G872", description="Anon run")
        project = ProjectFactory(shuttle=shuttle)

        response = client.get(reverse("projects:detail", kwargs={"pk": project.pk}))

        assert response.status_code == HTTP_FOUND
        assert "/accounts/login/" in response["Location"]
        assert project.full_id not in response["Location"]

    def test_anonymous_gets_login_redirect_for_unknown_pk(self, client):
        """An unknown pk must not 404 for anonymous users, which leaks existence."""
        known = ProjectFactory(
            shuttle=Shuttle.objects.create(name="G873", description="Oracle run")
        )
        missing_pk = uuid.uuid4()

        known_response = client.get(reverse("projects:detail", kwargs={"pk": known.pk}))
        missing_response = client.get(
            reverse("projects:detail", kwargs={"pk": missing_pk})
        )

        # Both must be indistinguishable to an anonymous caller: same status,
        # and both sent to login rather than one revealing the project.
        assert known_response.status_code == HTTP_FOUND
        assert missing_response.status_code == HTTP_FOUND
        assert "/accounts/login/" in known_response["Location"]
        assert "/accounts/login/" in missing_response["Location"]
        assert known.full_id not in known_response["Location"]

    def test_non_owner_is_forbidden_and_learns_no_full_id(self, client):
        """A non-owner gets 403 rather than a redirect disclosing the full_id."""
        shuttle = Shuttle.objects.create(name="G874", description="Denied run")
        project = ProjectFactory(shuttle=shuttle)
        client.force_login(UserFactory())

        response = client.get(reverse("projects:detail", kwargs={"pk": project.pk}))

        assert response.status_code == HTTP_FORBIDDEN
        assert project.full_id not in response.content.decode()

    def test_staff_pk_access_logs_once_against_canonical_view(self, client):
        """Staff pk access creates exactly one log, named for the canonical view.

        The redirect leg must not log: the canonical request it redirects to
        creates the audit entry, so logging both would record one access twice.
        """
        shuttle = Shuttle.objects.create(name="G875", description="Audit run")
        project = ProjectFactory(shuttle=shuttle)
        client.force_login(UserFactory(is_staff=True))

        response = client.get(
            reverse("projects:detail", kwargs={"pk": project.pk}), follow=True
        )

        assert response.status_code == HTTP_OK
        logs = ProjectAccessLog.objects.filter(project=project)
        assert logs.count() == 1
        assert logs.get().view_name == "ProjectDetailByFullIdView"


@pytest.mark.django_db
class TestProjectDetailByFullIdView:
    """The canonical /projects/<full_id>/ URL."""

    def test_owner_can_view_by_full_id(self, client):
        """Owner can load the project through its manufacturing ID."""
        user = UserFactory()
        shuttle = Shuttle.objects.create(name="G876", description="Canonical run")
        project = ProjectFactory(user=user, shuttle=shuttle)
        client.force_login(user)

        response = client.get(
            reverse("projects:detail_by_full_id", kwargs={"full_id": project.full_id})
        )

        assert response.status_code == HTTP_OK
        assert response.context["project"] == project

    def test_staff_can_view_by_full_id(self, client):
        """Staff can load another user's project through its manufacturing ID."""
        shuttle = Shuttle.objects.create(name="G877", description="Staff run")
        project = ProjectFactory(shuttle=shuttle)
        client.force_login(UserFactory(is_staff=True))

        response = client.get(
            reverse("projects:detail_by_full_id", kwargs={"full_id": project.full_id})
        )

        assert response.status_code == HTTP_OK

    def test_non_owner_cannot_view_by_full_id(self, client):
        """A non-owner is denied on the canonical URL too."""
        shuttle = Shuttle.objects.create(name="G878", description="Denied run")
        project = ProjectFactory(shuttle=shuttle)
        client.force_login(UserFactory())

        response = client.get(
            reverse("projects:detail_by_full_id", kwargs={"full_id": project.full_id})
        )

        assert response.status_code == HTTP_FORBIDDEN

    def test_requires_login(self, client):
        """The canonical URL requires login."""
        shuttle = Shuttle.objects.create(name="G879", description="Anon run")
        project = ProjectFactory(shuttle=shuttle)

        response = client.get(
            reverse("projects:detail_by_full_id", kwargs={"full_id": project.full_id})
        )

        assert response.status_code == HTTP_FOUND
        assert "/accounts/login/" in response["Location"]

    def test_unknown_full_id_returns_404(self, client):
        """A well-formed but unused manufacturing ID is a 404."""
        client.force_login(UserFactory())

        response = client.get("/projects/G999ZZZZ/")

        assert response.status_code == HTTP_NOT_FOUND

    @pytest.mark.parametrize(
        "bad_id",
        [
            "g871abcd",  # lowercase
            "ABCDEFG",  # too short
            "ABCDEFGHI",  # too long
        ],
    )
    def test_malformed_full_id_does_not_resolve(self, client, bad_id):
        """Only 8 upper-case alphanumerics route to the canonical view."""
        client.force_login(UserFactory())

        response = client.get(f"/projects/{bad_id}/")

        assert response.status_code == HTTP_NOT_FOUND


@pytest.mark.django_db
class TestProjectCreateView(TestCase):
    """Test ProjectCreateView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.shuttle = Shuttle.objects.create(
            name="G800", description="Test Shuttle", status=Shuttle.Status.OPEN
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:create")
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        # Check redirect location (use Location header for type safety)
        assert "/accounts/login/" in response["Location"]

    def test_displays_form(self):
        """Test that GET displays the form."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:create")
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "form" in response.context

    def test_create_form_has_campaign_link_anchor_and_url_map(self):
        """The create form renders the label anchor and the pk->URL json map.

        The label href itself is filled client-side from the
        shuttle-campaign-urls json_script, so only the anchor and the map
        entry are asserted here (the default shuttle selection is
        environment-dependent).
        """
        self.shuttle.crowd_supply_url = (
            "https://www.crowdsupply.com/wafer-space/gf180mcu-run-1/"
        )
        self.shuttle.save()

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:create")
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert 'id="crowd-supply-campaign-link"' in content
        assert 'id="shuttle-campaign-urls"' in content
        assert self.shuttle.crowd_supply_url in content

    def test_creates_project(self):
        """Test that POST creates a project."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:create")

        form_data = {
            "name": "New Project",
            "description": "New project description",
            "shuttle": self.shuttle.pk,
            "project_id": "TEST",
            "slot_size": "1x1",
        }
        response = self.client.post(url, form_data)

        # Should redirect to detail page
        assert response.status_code == HTTP_FOUND

        # Verify project was created
        assert Project.objects.count() == 1
        project = Project.objects.first()
        assert project is not None
        assert project.name == "New Project"
        assert project.description == "New project description"
        assert project.user == self.user
        assert project.shuttle == self.shuttle
        assert project.project_id == "TEST"
        assert project.slot_size == "1x1"

        # Verify success message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "created successfully" in str(messages[0])


@pytest.mark.django_db
class TestProjectUpdateView(TestCase):
    """Test ProjectUpdateView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password=TEST_PASSWORD
        )
        self.shuttle = Shuttle.objects.create(
            name="G800", description="Test Shuttle", status=Shuttle.Status.OPEN
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
            shuttle=self.shuttle,
            project_id="ABCD",
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        # Check redirect location (use Location header for type safety)
        assert "/accounts/login/" in response["Location"]

    def test_owner_can_update_project_details(self):
        """Test that owner can update name, description, and visibility.

        Regular users can edit name, description, visibility, repository URL,
        and license settings. Staff-only fields (shuttle, project_id, slot_size)
        are not available to regular users.
        """
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        # Owner submits updated project details
        form_data = {
            "name": "Updated Project Name",
            "description": "Updated project description",
            "is_public": True,
            "repository_url": "",
            "license_type": "proprietary",
            "other_license_spdx_id": "",
            "proprietary_terms_url": "",
        }
        response = self.client.post(url, form_data)

        # Should redirect
        assert response.status_code == HTTP_FOUND

        # Verify all fields were updated
        self.project.refresh_from_db()
        assert self.project.name == "Updated Project Name"
        assert self.project.description == "Updated project description"
        assert self.project.is_public is True

    def test_owner_gets_form_with_disabled_core_fields(self):
        """Test that owner sees form with core fields disabled."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["is_new"] is False
        # The form should have all fields
        form = response.context["form"]
        assert "name" in form.fields
        assert "description" in form.fields
        assert "is_public" in form.fields
        assert "repository_url" in form.fields
        assert "license_type" in form.fields
        # Core fields are present but DISABLED for non-staff
        assert "shuttle" in form.fields
        assert form.fields["shuttle"].disabled is True
        assert "project_id" in form.fields
        assert form.fields["project_id"].disabled is True
        assert "slot_size" in form.fields
        assert form.fields["slot_size"].disabled is True

    def test_owner_sees_locked_static_values_not_dropdowns(self):
        """Non-staff owners see locked core fields as static text, not inputs.

        Regression test for issue #297: locked shuttle/slot-size fields must
        not render as dropdowns, and each locked value carries a lock icon.
        """
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        # No form inputs for locked core fields
        assert 'name="shuttle"' not in content
        assert 'name="project_id"' not in content
        assert 'name="slot_size"' not in content
        # Static values rendered instead
        assert "G800 - Test Shuttle" in content
        assert "ABCD" in content
        assert SlotSize.FULL.full_label in content
        # Lock icon on the banner plus one per locked field value
        min_lock_icons = 4
        assert content.count("bi-lock") >= min_lock_icons

    def test_owner_sees_correct_shuttle_when_project_shuttle_closed(self):
        """The locked display shows the project's own (closed) shuttle.

        Regression test for issue #297: the page displayed the first OPEN
        shuttle instead of the project's actual shuttle once that shuttle
        left OPEN status.
        """
        self.shuttle.status = Shuttle.Status.COMPLETED
        self.shuttle.save()
        Shuttle.objects.create(
            name="G881",
            description="Other Open Shuttle",
            status=Shuttle.Status.OPEN,
        )
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "G800 - Test Shuttle" in content
        assert "G881 - Other Open Shuttle" not in content

    def test_owner_can_update_details_when_shuttle_closed(self):
        """Owner edits still save after the project's shuttle closes."""
        self.shuttle.status = Shuttle.Status.COMPLETED
        self.shuttle.save()
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        form_data = {
            "name": "Renamed After Close",
            "description": "Still editable",
            "repository_url": "",
            "license_type": "proprietary",
            "other_license_spdx_id": "",
            "proprietary_terms_url": "",
        }
        response = self.client.post(url, form_data)

        assert response.status_code == HTTP_FOUND
        self.project.refresh_from_db()
        assert self.project.name == "Renamed After Close"
        assert self.project.shuttle == self.shuttle

    def test_owner_forged_core_field_post_is_ignored(self):
        """A crafted POST cannot change core fields for a non-staff owner."""
        other_shuttle = Shuttle.objects.create(
            name="G882",
            description="Other Open Shuttle",
            status=Shuttle.Status.OPEN,
        )
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        form_data = {
            "name": "Forged Post",
            "description": "",
            "shuttle": other_shuttle.pk,
            "project_id": "EVIL",
            "slot_size": "0p5x0p5",
            "repository_url": "",
            "license_type": "proprietary",
            "other_license_spdx_id": "",
            "proprietary_terms_url": "",
        }
        response = self.client.post(url, form_data)

        assert response.status_code == HTTP_FOUND
        self.project.refresh_from_db()
        assert self.project.name == "Forged Post"
        assert self.project.shuttle == self.shuttle
        assert self.project.project_id == "ABCD"
        assert self.project.slot_size == "1x1"

    def test_staff_sees_editable_core_field_dropdowns(self):
        """Staff still get the editable shuttle/slot-size dropdowns."""
        User.objects.create_user(
            username="staffdrop",
            email="staffdrop@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        self.client.login(username="staffdrop", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert 'name="shuttle"' in content
        assert 'name="slot_size"' in content
        assert 'name="project_id"' in content

    def test_staff_can_update_all_fields(self):
        """Test that staff can update all project fields."""
        User.objects.create_user(
            username="staffuser",
            email="staff@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        self.client.login(username="staffuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        form_data = {
            "name": "Updated Project",
            "description": "Updated description",
            "shuttle": self.shuttle.pk,
            "project_id": "UPDT",  # Different from original to test update
            "slot_size": "0p5x1",
            "is_public": True,
            # License fields
            "license_type": "proprietary",
            "other_license_spdx_id": "",
            "proprietary_terms_url": "",
        }
        response = self.client.post(url, form_data)

        # Should redirect
        assert response.status_code == HTTP_FOUND

        # Verify project was updated
        self.project.refresh_from_db()
        assert self.project.name == "Updated Project"
        assert self.project.description == "Updated description"
        assert self.project.project_id == "UPDT"  # Core field updated by staff
        assert self.project.slot_size == "0p5x1"
        assert self.project.is_public is True

    def test_non_owner_cannot_update(self):
        """Test that non-owner cannot update project."""
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == HTTP_FORBIDDEN

    def _cob_form_data(self, *, chip_on_board: bool) -> dict[str, str]:
        """Valid update-form payload toggling only chip_on_board."""
        data = {
            "name": self.project.name,
            "description": self.project.description,
            "repository_url": "",
            "license_type": "proprietary",
            "other_license_spdx_id": "",
            "proprietary_terms_url": "",
        }
        if chip_on_board:
            data["chip_on_board"] = "on"
        return data

    def _make_submitted_check(
        self, status: ManufacturabilityCheck.Status
    ) -> ManufacturabilityCheck:
        """Attach a submitted file with a check to self.project."""
        project_file = ProjectFileFactory(project=self.project)
        self.project.submitted_file = project_file
        self.project.save()
        return ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=status,
        )

    def test_toggling_cob_creates_cob_change_check(self):
        """Enabling CoB on a project with a check creates one COB_CHANGE check."""
        check = self._make_submitted_check(ManufacturabilityCheck.Status.FINISHED)
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        response = self.client.post(url, self._cob_form_data(chip_on_board=True))

        assert response.status_code == HTTP_FOUND
        self.project.refresh_from_db()
        assert self.project.chip_on_board is True
        checks = ManufacturabilityCheck.objects.filter(
            project_file=check.project_file
        ).order_by("created_at")
        assert checks.count() == EXPECTED_CHECKS_AFTER_COB_TOGGLE
        new_check = checks.last()
        assert new_check is not None
        assert (
            new_check.trigger_reason == ManufacturabilityCheck.TriggerReason.COB_CHANGE
        )
        assert new_check.parent_check == check

    def test_toggling_cob_cancels_in_progress_check(self):
        """Enabling CoB while a check is RUNNING marks it CANCELLING."""
        check = self._make_submitted_check(ManufacturabilityCheck.Status.RUNNING)
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        self.client.post(url, self._cob_form_data(chip_on_board=True))

        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLING

    def test_toggling_cob_on_draft_only_persists(self):
        """No submitted file/check: the flag is saved, no check is created."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        self.client.post(url, self._cob_form_data(chip_on_board=True))

        self.project.refresh_from_db()
        assert self.project.chip_on_board is True
        assert ManufacturabilityCheck.objects.filter(project=self.project).count() == 0

    def test_unchanged_cob_creates_no_check(self):
        """Submitting the form with CoB unchanged creates no new check."""
        check = self._make_submitted_check(ManufacturabilityCheck.Status.FINISHED)
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        self.client.post(url, self._cob_form_data(chip_on_board=False))

        assert (
            ManufacturabilityCheck.objects.filter(
                project_file=check.project_file
            ).count()
            == 1
        )

    def test_cob_recheck_failure_does_not_500_or_lose_edit(self):
        """A ValueError from the re-check must not 500 or revert the saved edit.

        Under ATOMIC_REQUESTS the whole request shares one transaction, so an
        exception raised by create_check_cob_change *after* the project has been
        saved would otherwise roll the request back into a 500 and discard the
        user's valid CoB change. The view must swallow the recoverable error and
        still redirect with the edit persisted.
        """
        self._make_submitted_check(ManufacturabilityCheck.Status.FINISHED)
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})

        self.client.raise_request_exception = False
        with patch.object(
            ManufacturabilityCheck,
            "create_check_cob_change",
            side_effect=ValueError("source check is no longer the latest"),
        ):
            response = self.client.post(url, self._cob_form_data(chip_on_board=True))

        assert response.status_code == HTTP_FOUND
        self.project.refresh_from_db()
        assert self.project.chip_on_board is True

    def test_order_id_field_rendered_on_edit_form(self):
        """The CrowdSupply order field is present and rendered on the form."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "crowd_supply_order_id" in response.context["form"].fields
        # The input must actually appear in the rendered HTML, not just the form.
        assert "id_crowd_supply_order_id" in response.content.decode()
        assert "CrowdSupply Order ID" in response.content.decode()

    def test_order_id_label_links_to_campaign_on_edit_form(self):
        """The CrowdSupply label on the edit form links to the campaign page."""
        self.shuttle.crowd_supply_url = (
            "https://www.crowdsupply.com/wafer-space/gf180mcu-run-1/"
        )
        self.shuttle.save()

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert 'id="crowd-supply-campaign-link"' in content
        assert f'href="{self.shuttle.crowd_supply_url}"' in content
        # The label itself is the anchor text, opening in a new window.
        assert 'class="text-decoration-none">CrowdSupply Order ID</a>' in content

    def test_order_id_label_has_no_href_when_shuttle_has_no_url(self):
        """The label anchor has no href when the shuttle has no campaign URL."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        content = response.content.decode()
        assert "CrowdSupply Order ID" in content
        # The no-href anchor variant renders (its id is directly followed by
        # target=, not href=). Other shuttles' options on the page may carry
        # campaign URLs, so no page-global negative assertion is possible.
        assert '<a id="crowd-supply-campaign-link" target="_blank"' in content

    def test_owner_can_set_order_id_via_update(self):
        """Posting an order id through the update view persists it."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:update", kwargs={"pk": self.project.pk})
        form_data = {
            "name": "Test Project",
            "description": "Test project",
            "is_public": False,
            "repository_url": "",
            "crowd_supply_order_id": "327373",
            "license_type": "proprietary",
            "other_license_spdx_id": "",
            "proprietary_terms_url": "",
        }
        response = self.client.post(url, form_data)

        assert response.status_code == HTTP_FOUND
        self.project.refresh_from_db()
        assert self.project.crowd_supply_order_id == "327373"


@pytest.mark.django_db
class TestProjectFileSubmitURLView(TestCase):
    """Test ProjectFileSubmitURLView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test project"
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        # Check redirect location (use Location header for type safety)
        assert "/accounts/login/" in response["Location"]

    def test_owner_can_view_form(self):
        """Test that owner can view form."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "form" in response.context

    def test_non_owner_cannot_view_form(self):
        """Test that non-owner cannot view form."""
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == HTTP_FORBIDDEN

    @patch("wafer_space.projects.views.ProjectFileService.submit_file_from_url")
    def test_submit_url_success(self, mock_submit):
        """Test successful URL submission."""
        # Mock service layer
        mock_file = Mock(spec=ProjectFile)
        mock_file.original_filename = "test.gds"
        mock_metadata = {
            "url_rewritten": True,
            "rewrite_reason": "Converted GitHub blob URL",
            "file_size": 1048576,
        }
        mock_submit.return_value = (mock_file, mock_metadata)

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})

        form_data = {
            "url": "https://github.com/user/repo/blob/main/file.gds",
            "expected_hash_md5": "abc123def456789012345678901234ab",
            "expected_hash_sha1": "",
        }
        response = self.client.post(url, form_data)

        # Should redirect to detail page
        assert response.status_code == HTTP_FOUND

        # Verify service was called
        mock_submit.assert_called_once()

    @patch("wafer_space.projects.views.ProjectFileService.submit_file_from_url")
    def test_submit_url_security_error(self, mock_submit):
        """Test URL submission with security error."""
        # Mock security validation error
        error_msg = "Cannot download from localhost"
        mock_submit.side_effect = SecurityValidationError(error_msg)

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})

        form_data = {
            "url": "http://localhost/file.gds",
            "expected_hash_md5": "abc123def456789012345678901234ab",
            "expected_hash_sha1": "",
        }
        response = self.client.post(url, form_data)

        # Should re-render form with error
        assert response.status_code == HTTP_OK
        messages = list(get_messages(response.wsgi_request))
        assert any("Security validation failed" in str(m) for m in messages)


@pytest.mark.django_db
class TestProjectFileProgressView(TestCase):
    """Test ProjectFileProgressView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test project"
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        # Check redirect location (use Location header for type safety)
        assert "/accounts/login/" in response["Location"]

    def test_non_owner_cannot_view_progress(self):
        """Test that non-owner cannot view progress."""
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 403 Forbidden
        assert response.status_code == HTTP_FORBIDDEN

    def test_no_active_file_returns_404(self):
        """Test that no active file returns 404."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        # Should return 404
        assert response.status_code == HTTP_NOT_FOUND
        data = response.json()
        assert "error" in data

    @patch("wafer_space.projects.views.ProjectFileService.get_download_progress")
    def test_returns_progress_json(self, mock_progress):
        """Test that view returns progress as JSON."""
        # Create active file
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

        # Create download attempt
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        # Mock progress
        mock_progress.return_value = {
            "status": "downloading",
            "progress": PROGRESS_HALF,
            "current": FIVE_MB,
            "total": TEN_MB,
            "message": "Downloaded 4,718,592 of 10,485,760 bytes",
        }

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        data = response.json()
        assert data["status"] == "downloading"
        assert data["progress"] == PROGRESS_HALF
        assert data["current"] == FIVE_MB
        assert data["total"] == TEN_MB


@pytest.mark.django_db
class TestProjectSubmitView(TestCase):
    """Test ProjectSubmitView."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user,
            name="Test Project",
            description="Test project",
            status=Project.Status.DRAFT,
        )

    def test_requires_login(self):
        """Test that view requires login."""
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should redirect to login
        assert response.status_code == HTTP_FOUND
        # Check redirect location (use Location header for type safety)
        assert "/accounts/login/" in response["Location"]

    def test_requires_ownership(self):
        """Test that only owner can submit project."""
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should return 403 Forbidden
        assert response.status_code == HTTP_FORBIDDEN

    def test_successful_submission(self):
        """Test successful project submission."""

        # Create completed and verified file
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=True,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        # Mark as manufacturable (simulates completed check via mark_finished)
        self.project.submitted_file = project_file
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should redirect to project detail
        assert response.status_code == HTTP_FOUND
        detail_url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        # Check redirect location (use Location header for type safety)
        assert response["Location"] == detail_url

        # Verify project was submitted
        self.project.refresh_from_db()
        assert self.project.status == Project.Status.SUBMITTED
        assert self.project.submitted_at is not None

        # Verify success message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "submitted successfully" in str(messages[0]).lower()

    def test_submission_fails_without_active_file(self):
        """Test that submission fails without active file."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should redirect back to project detail
        assert response.status_code == HTTP_FOUND

        # Verify project was NOT submitted
        self.project.refresh_from_db()
        assert self.project.status == Project.Status.DRAFT
        assert self.project.submitted_at is None

        # Verify error message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "no active file" in str(messages[0]).lower()

    def test_submission_fails_with_pending_download(self):
        """Test that submission fails with pending download."""
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should redirect back to project detail
        assert response.status_code == HTTP_FOUND

        # Verify project was NOT submitted
        self.project.refresh_from_db()
        assert self.project.status == Project.Status.DRAFT

        # Verify error message mentions download not completed
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        message_text = str(messages[0]).lower()
        assert "download" in message_text
        assert "not completed" in message_text or "pending" in message_text

    def test_submission_fails_with_failed_download(self):
        """Test that submission fails with failed download."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_error="Download failed",
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.FAILED,
            download_error="Download failed",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should redirect back to project detail
        assert response.status_code == HTTP_FOUND

        # Verify project was NOT submitted
        self.project.refresh_from_db()
        assert self.project.status == Project.Status.DRAFT

        # Verify error message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "download" in str(messages[0]).lower()

    def test_submission_fails_with_unverified_hash(self):
        """Test that submission fails with unverified hash."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=False,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should redirect back to project detail
        assert response.status_code == HTTP_FOUND

        # Verify project was NOT submitted
        self.project.refresh_from_db()
        assert self.project.status == Project.Status.DRAFT

        # Verify error message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "hash" in str(messages[0]).lower()

    def test_submission_fails_if_already_submitted(self):
        """Test that submission fails if already submitted."""
        # Create completed file
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=True,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        # Mark as manufacturable (simulates completed check via mark_finished)
        self.project.submitted_file = project_file
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

        # Submit once
        self.project.submit()
        first_submitted_at = self.project.submitted_at

        # Try to submit again
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})
        response = self.client.post(url)

        # Should redirect back to project detail
        assert response.status_code == HTTP_FOUND

        # Verify submitted_at didn't change
        self.project.refresh_from_db()
        assert self.project.submitted_at == first_submitted_at

        # Verify error message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "already" in str(messages[0]).lower()

    def test_prevents_double_submission_race_condition(self):
        """Test that double submission is prevented even with race condition."""

        # Create completed file
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            hash_verified=True,
        )
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        # Mark as manufacturable (simulates completed check via mark_finished)
        self.project.submitted_file = project_file
        self.project.status = Project.Status.MANUFACTURABLE
        self.project.save()
        ManufacturabilityCheckFactory(
            project=self.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit", kwargs={"pk": self.project.pk})

        # First submission
        response1 = self.client.post(url)
        assert response1.status_code == HTTP_FOUND

        # Second submission (simulating race condition)
        response2 = self.client.post(url)
        assert response2.status_code == HTTP_FOUND

        # Verify only submitted once
        self.project.refresh_from_db()
        assert self.project.status == Project.Status.SUBMITTED

        # Second request should have error message
        messages = list(get_messages(response2.wsgi_request))
        assert any("already" in str(m).lower() for m in messages)


@pytest.mark.django_db
class TestEnhancedProgressDashboard(TestCase):
    """Test enhanced progress dashboard features."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test project"
        )

    def test_detail_view_shows_progress_flag_when_downloading(self):
        """Test that detail view sets show_progress flag when downloading."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

        # Create download attempt
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.DOWNLOADING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["show_progress"] is True
        assert "progress" in response.context

    def test_detail_view_shows_progress_flag_when_pending(self):
        """Test that detail view sets show_progress flag when pending."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

        # Create download attempt
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.PENDING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["show_progress"] is True
        assert "progress" in response.context

    def test_detail_view_shows_progress_when_task_queued_no_attempt_yet(self):
        """Test show_progress is True when task queued but DownloadAttempt not created.

        This reproduces the bug where polling didn't start after URL submission:
        - User submits URL → ProjectFile created with download_task_id
        - User redirected to detail page
        - DownloadAttempt doesn't exist yet (created inside Celery task)
        - Before fix: show_progress was False → no polling JavaScript
        - After fix: show_progress is True → polling starts immediately

        VERIFIED: This test FAILS without the fix (show_progress is False)
                  and PASSES with the fix (show_progress is True)
        """
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_task_id="celery-task-123",  # Task dispatched
        )
        # Intentionally NOT creating DownloadAttempt to simulate race condition

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        # This assertion would FAIL before the fix
        assert response.context["show_progress"] is True
        assert "progress" in response.context
        # Verify polling JavaScript is included in the response
        assert b"Progress Polling" in response.content

    def test_detail_view_shows_error_flag_when_failed(self):
        """Test that detail view sets show_error flag when download failed."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_error="Connection timeout",
        )

        # Create download attempt
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.FAILED,
            download_error="Connection timeout",
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["show_error"] is True
        assert response.context["error_message"] == "Connection timeout"

    def test_detail_view_no_progress_when_completed(self):
        """Test that detail view doesn't set show_progress when completed."""
        ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        show_progress = response.context.get("show_progress", False)
        assert not show_progress

    @patch("wafer_space.projects.views.ProjectFileService.get_download_progress")
    def test_progress_view_returns_error_field_when_failed(self, mock_progress):
        """Test that progress view includes error field when download failed."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            download_error="Network error occurred",
        )

        # Create download attempt
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.FAILED,
            download_error="Network error occurred",
        )

        mock_progress.return_value = {
            "status": "failed",
            "progress": 0,
            "current": 0,
            "total": TEN_MB,
            "message": "Download failed",
        }

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        data = response.json()
        assert data["status"] == "failed"
        assert "error" in data
        assert data["error"] == "Network error occurred"

    @patch("wafer_space.projects.views.ProjectFileService.get_download_progress")
    def test_progress_view_with_pending_status(self, mock_progress):
        """Test progress view with pending download status."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

        # Create download attempt
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.PENDING,
        )

        mock_progress.return_value = {
            "status": "pending",
            "progress": 0,
            "current": 0,
            "total": TEN_MB,
            "message": "Download pending - waiting to start",
        }

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        data = response.json()
        assert data["status"] == "pending"
        assert data["progress"] == 0
        assert "pending" in data["message"].lower()

    @patch("wafer_space.projects.views.ProjectFileService.get_download_progress")
    def test_progress_view_with_completed_status(self, mock_progress):
        """Test progress view with completed download status."""
        project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
            file_size=TEN_MB,
        )

        # Create download attempt
        DownloadAttempt.objects.create(
            project_file=project_file,
            attempt_number=1,
            status=DownloadAttempt.Status.COMPLETED,
        )

        mock_progress.return_value = {
            "status": "completed",
            "progress": 100,
            "current": TEN_MB,
            "total": TEN_MB,
            "message": "Download completed successfully",
        }

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:progress", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        data = response.json()
        assert data["status"] == "completed"
        assert data["progress"] == PROGRESS_COMPLETE
        assert data["current"] == TEN_MB
        assert data["total"] == TEN_MB


@pytest.mark.django_db
class TestProjectDetailViewManufacturabilityCheck(TestCase):
    """Test ProjectDetailView with manufacturability check integration."""

    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test Description"
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_filename="test.gds",
            source_url="https://example.com/test.gds",
            is_active=True,
        )

    def test_detail_view_includes_check_when_check_exists(self):
        """Test that detail view includes check in context."""
        # Create a manufacturability check
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        # Log in and access detail view
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "check" in response.context
        check = response.context["check"]
        assert check is not None
        assert check.status == ManufacturabilityCheck.Status.PENDING

    def test_detail_view_check_none_when_no_check(self):
        """Test that check is None when no check exists."""
        # Log in and access detail view
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "check" in response.context
        assert response.context["check"] is None

    def test_detail_view_shows_completed_check(self):
        """Test that detail view shows completed check with results."""
        # Create a completed check
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        # New pathway: PENDING -> DISPATCHING -> STARTING -> RUNNING
        check.mark_dispatching(server_id="server-1")
        check.mark_starting(
            docker_image="test-image:latest",
            docker_image_digest="sha256:abc123",
        )
        check.mark_running(
            docker_container_id="test-container-id",
            docker_command="docker run ...",
        )
        check.mark_analyzing(docker_exit_code=1)
        check.mark_finished(
            is_manufacturable=False,
            errors=["Error 1", "Error 2"],
            warnings=["Warning 1"],
            tool_versions={"precheck": "1.0.0"},
        )

        # Log in and access detail view
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        check = response.context["check"]
        assert check is not None
        assert check.status == ManufacturabilityCheck.Status.FINISHED
        assert check.is_manufacturable is False
        expected_errors = ["Error 1", "Error 2"]
        assert check.errors == expected_errors
        assert check.warnings == ["Warning 1"]

    def test_detail_view_shows_error_message_to_staff(self):
        """Test that staff users can see system error messages."""
        # Create a check with error status and error_message
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            error_message="Docker container failed to start: OOM killed",
        )

        # Create staff user and log in
        User.objects.create_user(
            username="staffuser",
            email="staff@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        self.client.login(username="staffuser", password=TEST_PASSWORD)

        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert b"System Error (Staff Only)" in response.content
        assert b"Docker container failed to start: OOM killed" in response.content

    def test_detail_view_hides_error_message_from_non_staff(self):
        """Test that non-staff users cannot see system error messages."""
        # Create a check with error status and error_message
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.ERROR,
            error_message="Docker container failed to start: OOM killed",
        )

        # Log in as the regular project owner (non-staff)
        self.client.login(username="testuser", password=TEST_PASSWORD)

        url = reverse("projects:detail", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        # The error message section should not be visible to non-staff
        assert b"System Error (Staff Only)" not in response.content
        # The actual error message content should not be visible either
        assert b"Docker container failed to start: OOM killed" not in response.content


@pytest.mark.django_db
class TestManufacturabilityCheckCancelView(TestCase):
    """Test ManufacturabilityCheckCancelView."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.other_user = User.objects.create_user(
            username="otheruser", email="other@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test project"
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

    def test_cancel_check_success(self):
        """Test successfully requesting cancellation of a check."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        response = self.client.post(url)

        assert response.status_code == HTTP_FOUND
        check.refresh_from_db()
        # Should be CANCELLING, not CANCELLED (cleanup task will complete it)
        assert check.status == ManufacturabilityCheck.Status.CANCELLING

    def test_cancel_check_processing_success(self):
        """Test successfully requesting cancellation of a processing check."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        response = self.client.post(url)

        assert response.status_code == HTTP_FOUND
        check.refresh_from_db()
        # Should be CANCELLING, not CANCELLED (cleanup task will complete it)
        assert check.status == ManufacturabilityCheck.Status.CANCELLING

    def test_cancel_check_already_completed(self):
        """Test cancelling already completed check shows warning."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        response = self.client.post(url, follow=True)

        assert response.status_code == HTTP_OK
        messages_list = list(response.context["messages"])
        assert len(messages_list) == 1
        assert "could not be cancelled" in str(messages_list[0]).lower()

    def test_cancel_check_nonexistent_returns_404(self):
        """Test cancelling nonexistent check returns 404."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": 99999},
        )
        response = self.client.post(url)

        assert response.status_code == HTTP_NOT_FOUND

    def test_cancel_check_wrong_project_returns_404(self):
        """Test cancelling check with wrong project pk returns 404."""
        # Create another project
        other_project = Project.objects.create(
            user=self.user, name="Other Project", description="Other"
        )
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        # Try to cancel check from self.project using other_project's pk
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": other_project.pk, "check_id": check.pk},
        )
        response = self.client.post(url)

        # Should be 404 because check doesn't belong to other_project
        assert response.status_code == HTTP_NOT_FOUND

    def test_cancel_check_requires_authentication(self):
        """Test that cancel requires authentication."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        response = self.client.post(url)

        assert response.status_code == HTTP_FOUND
        assert "/accounts/login/" in response["Location"]

    def test_cancel_check_requires_ownership(self):
        """Test that non-owner, non-staff users cannot cancel check."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        # Log in as other user
        self.client.login(username="otheruser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        response = self.client.post(url)

        # Should be forbidden (403)
        assert response.status_code == HTTP_FORBIDDEN

    def test_cancel_check_get_not_allowed(self):
        """Test that GET requests are not allowed."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        response = self.client.get(url)

        # GET should return 405 Method Not Allowed
        assert response.status_code == HTTP_METHOD_NOT_ALLOWED

    def test_staff_user_can_cancel_any_check(self):
        """Test that staff users can cancel any project's check."""
        staff_user = User.objects.create_user(
            username="staffuser",
            email="staff@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        self.client.login(username="staffuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        response = self.client.post(url)

        assert response.status_code == HTTP_FOUND
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLING
        # Verify admin cancellation is logged
        assert f"Cancelled by admin ({staff_user.username})" in check.processing_logs

    def test_superuser_can_cancel_any_check(self):
        """Test that superusers can cancel any project's check."""
        superuser = User.objects.create_superuser(
            username="superuser",
            email="super@example.com",
            password=TEST_PASSWORD,
        )
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        self.client.login(username="superuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        response = self.client.post(url)

        assert response.status_code == HTTP_FOUND
        check.refresh_from_db()
        assert check.status == ManufacturabilityCheck.Status.CANCELLING
        # Verify admin cancellation is logged
        assert f"Cancelled by admin ({superuser.username})" in check.processing_logs

    def test_owner_cancel_logs_correct_reason(self):
        """Test that owner cancellation logs 'Cancelled by owner'."""
        check = ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse(
            "projects:cancel_check",
            kwargs={"pk": self.project.pk, "check_id": check.pk},
        )
        self.client.post(url)

        check.refresh_from_db()
        assert "Cancelled by owner" in check.processing_logs


@pytest.mark.django_db
class TestProjectFileSubmitURLViewWarning(TestCase):
    """Test submit-url page shows warning when check is running."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.user, name="Test Project", description="Test project"
        )
        self.project_file = ProjectFile.objects.create(
            project=self.project,
            original_url="https://example.com/file.gds",
            source_url="https://example.com/file.gds",
            original_filename="file.gds",
            is_active=True,
        )

    def test_submit_url_shows_warning_for_queued_check(self):
        """Test submit URL page shows warning when queued check exists."""
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert "running_check" in response.context
        assert response.context["running_check"] is not None
        assert b"will be cancelled" in response.content.lower() or (
            b"Will Be Cancelled" in response.content
        )

    def test_submit_url_shows_warning_for_processing_check(self):
        """Test submit URL page shows warning when processing check exists."""
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["running_check"] is not None

    def test_submit_url_no_warning_for_completed_check(self):
        """Test submit URL page has no warning when check is completed."""
        ManufacturabilityCheck.objects.create(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
        )

        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["running_check"] is None

    def test_submit_url_no_warning_when_no_check(self):
        """Test submit URL page has no warning when no check exists."""
        self.client.login(username="testuser", password=TEST_PASSWORD)
        url = reverse("projects:submit_url", kwargs={"pk": self.project.pk})
        response = self.client.get(url)

        assert response.status_code == HTTP_OK
        assert response.context["running_check"] is None


@pytest.mark.django_db
class TestProjectDetailSlotVisibility:
    """Test slot assignment visibility on project detail page."""

    def test_staff_sees_slot_assignments(self, client):
        """Staff should see slot assignments on project detail."""
        user = UserFactory(is_staff=True)
        client.force_login(user)

        shuttle = Shuttle.objects.create(
            name="G810", description="Test shuttle", status=Shuttle.Status.OPEN
        )
        project = ProjectFactory(shuttle=shuttle)

        # Assign to two slots
        slot1 = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        slot1.project = project
        slot1.reserved_by = user
        slot1.save()

        slot2 = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=1,
            column=2,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        slot2.project = project
        slot2.reserved_by = user
        slot2.save()

        url = reverse("projects:detail", kwargs={"pk": project.pk})
        response = client.get(url, follow=True)  # follow redirect to full_id URL

        assert response.status_code == HTTP_OK
        content = response.content.decode()

        # Should show slot assignments
        assert "Assigned Slots" in content or "Grid Position" in content
        assert "A1" in content  # slot1 position
        assert "C2" in content  # slot2 position

    def test_regular_user_does_not_see_slots(self, client):
        """Regular users should not see slot assignments."""
        user = UserFactory(is_staff=False)
        shuttle = Shuttle.objects.create(
            name="G811", description="Test shuttle", status=Shuttle.Status.OPEN
        )
        # Create project with shuttle already assigned (core fields are immutable)
        project = ProjectFactory(user=user, shuttle=shuttle)
        client.force_login(user)

        slot = ShuttleSlot.objects.create(
            shuttle=shuttle,
            row=0,
            column=0,
            slot_size=SlotSize.FULL,
            status=ShuttleSlot.Status.RESERVED,
        )
        slot.project = project
        slot.save()

        url = reverse("projects:detail", kwargs={"pk": project.pk})
        response = client.get(url, follow=True)  # follow redirect to full_id URL

        assert response.status_code == HTTP_OK
        content = response.content.decode()

        # Should NOT show slot section
        assert "Assigned Slots" not in content
        assert "Grid Position" not in content


@pytest.mark.django_db
class TestProjectListStateColumn:
    """The projects list's shuttle and state columns (PR #321, Tim 11 Oct).

    The state is derived from Project.submitted_file and the file revisions'
    checks (docs/manufacturable_vs_submitted.md), never from Project.status,
    which later check completions overwrite (issue #354).
    """

    @staticmethod
    def _row(client, user, project: Project) -> str:
        """The rendered list row for ``project``."""
        client.force_login(user)
        html = client.get(reverse("projects:list")).content.decode()
        marker = f'data-project-row="{project.pk}"'
        assert marker in html
        return html.split(marker, 1)[1].split("data-project-row=", 1)[0]

    @staticmethod
    def _revision(project: Project, *checks: tuple[str, bool | None]) -> ProjectFile:
        """A downloaded, active revision of ``project`` with checks.

        Any previously active revision is deactivated first (one active file
        per project).
        """
        project.files.update(is_active=False)
        revision = make_downloaded_file(project)
        start = timezone.now()
        for offset, (status, verdict) in enumerate(checks):
            check = ManufacturabilityCheckFactory(
                project=project,
                project_file=revision,
                status=status,
                is_manufacturable=verdict,
            )
            # created_at is auto_now_add: order the checks explicitly.
            ManufacturabilityCheck.objects.filter(pk=check.pk).update(
                created_at=start + timedelta(seconds=offset),
            )
        return revision

    def test_shows_shuttle_name(self, client) -> None:
        """The first column names the project's shuttle."""
        user = UserFactory()
        project = ProjectFactory(user=user, shuttle=ShuttleFactory(name="G850"))

        assert "G850" in self._row(client, user, project)

    def test_submitted_even_when_status_was_overwritten(self, client) -> None:
        """A submitted project reads Submitted, whatever Project.status says.

        mark_finished() overwrites SUBMITTED with MANUFACTURABLE whenever a
        check finishes, so the raw status would say "Manufacturable".
        """
        user = UserFactory()
        project = ProjectFactory(user=user)
        finished = ManufacturabilityCheck.Status.FINISHED
        project.submitted_file = self._revision(project, (finished, True))
        project.status = Project.Status.MANUFACTURABLE
        project.save()

        row = self._row(client, user, project)

        assert 'data-project-state="submitted"' in row

    def test_submitted_revision_now_failing_is_flagged(self, client) -> None:
        """A submitted revision whose latest finished check failed is flagged."""
        user = UserFactory()
        project = ProjectFactory(user=user)
        finished = ManufacturabilityCheck.Status.FINISHED
        project.submitted_file = self._revision(
            project, (finished, True), (finished, False)
        )
        project.save()

        row = self._row(client, user, project)

        assert 'data-project-state="submitted-failing"' in row

    @pytest.mark.parametrize(
        ("checks", "state"),
        [
            ([("finished", True)], "manufacturable"),
            ([("finished", False)], "not-manufacturable"),
            ([("finished", True), ("running", None)], "manufacturable"),
            ([("pending", None)], "checking"),
            ([("error", None)], "check-error"),
            ([], "not-checked"),
        ],
    )
    def test_unsubmitted_state_comes_from_latest_revision(
        self, client, checks: list[tuple[str, bool | None]], state: str
    ) -> None:
        """Verdict of the latest finished check; else the latest check's state.

        An in-flight re-check does not reset an existing verdict.
        """
        user = UserFactory()
        project = ProjectFactory(user=user)
        self._revision(project, *checks)

        row = self._row(client, user, project)

        assert f'data-project-state="{state}"' in row

    def test_state_says_which_revision_it_describes(self, client) -> None:
        """CLAUDE.md: a precheck status must name the revision it belongs to."""
        user = UserFactory()
        project = ProjectFactory(user=user)
        self._revision(project, (ManufacturabilityCheck.Status.FINISHED, True))

        row = self._row(client, user, project)

        assert 'data-state-basis="latest revision"' in row

    def test_project_without_file(self, client) -> None:
        """No revision yet reads No file, even if Project.status says otherwise."""
        user = UserFactory()
        project = ProjectFactory(user=user, status=Project.Status.CHECKING)

        row = self._row(client, user, project)

        assert ('data-project-state="no-file"' in row, "Checking" in row) == (
            True,
            False,
        )

    @pytest.mark.parametrize(
        ("attempt_status", "state"),
        [
            (DownloadAttempt.Status.FAILED, "download-failed"),
            (DownloadAttempt.Status.DOWNLOADING, "downloading"),
            (DownloadAttempt.Status.PENDING, "download-pending"),
            (None, "download-pending"),
        ],
    )
    def test_revision_without_checks_shows_its_download(
        self, client, attempt_status: str | None, state: str
    ) -> None:
        """A file never checked because it is not downloaded says so."""
        user = UserFactory()
        project = ProjectFactory(user=user)
        revision = ProjectFileFactory(project=project, is_active=True)
        if attempt_status is not None:
            DownloadAttempt.objects.create(
                project_file=revision, attempt_number=1, status=attempt_status
            )

        row = self._row(client, user, project)

        assert f'data-project-state="{state}"' in row

    @pytest.mark.parametrize(
        ("checks", "state"),
        [
            ([("finished", True), ("error", None)], "manufacturable"),
            ([("error", None), ("pending", None)], "checking"),
            ([("cancelled", None)], "not-checked"),
        ],
    )
    def test_later_checks_without_a_verdict(
        self, client, checks: list[tuple[str, bool | None]], state: str
    ) -> None:
        """A verdict survives a later error; a retry after an error is Checking."""
        user = UserFactory()
        project = ProjectFactory(user=user)
        self._revision(project, *checks)

        row = self._row(client, user, project)

        assert f'data-project-state="{state}"' in row

    def test_only_an_older_revision_finished(self, client) -> None:
        """The latest revision's state is shown, not an older revision's verdict."""
        user = UserFactory()
        project = ProjectFactory(user=user)
        finished = ManufacturabilityCheck.Status.FINISHED
        self._revision(project, (finished, True))
        self._revision(project, (ManufacturabilityCheck.Status.RUNNING, None))

        row = self._row(client, user, project)

        assert 'data-project-state="checking"' in row

    def test_submitted_with_newer_failing_revision_shows_both(self, client) -> None:
        """Submitted stays; a second line describes the newer latest revision."""
        user = UserFactory()
        project = ProjectFactory(user=user)
        finished = ManufacturabilityCheck.Status.FINISHED
        project.submitted_file = self._revision(project, (finished, True))
        project.save()
        self._revision(project, (finished, False))

        row = self._row(client, user, project)

        shown = (
            'data-project-state="submitted"' in row,
            'data-state-latest="not-manufacturable"' in row,
        )
        assert shown == (True, True)

    def test_submitted_latest_revision_has_no_second_line(self, client) -> None:
        """No "latest revision" line when the submitted revision is the latest."""
        user = UserFactory()
        project = ProjectFactory(user=user)
        finished = ManufacturabilityCheck.Status.FINISHED
        project.submitted_file = self._revision(project, (finished, True))
        project.save()

        row = self._row(client, user, project)

        assert "data-state-latest=" not in row

    def test_archived_project_keeps_its_state(self, client) -> None:
        """An archived row still shows its derived state."""
        user = UserFactory()
        project = ProjectFactory(user=user, archived_at=timezone.now())
        self._revision(project, (ManufacturabilityCheck.Status.FINISHED, True))

        row = self._row(client, user, project)

        assert 'data-project-state="manufacturable"' in row

    def test_annotation_names_match_the_typed_dict(self) -> None:
        """ListStateAnnotations names exactly what annotate_list_state adds.

        mypy checks attribute names against the TypedDict only, so this pins
        the TypedDict to the real queryset annotations.
        """
        annotated = annotate_list_state(Project.objects.all())

        assert set(annotated.query.annotations) == set(
            ListStateAnnotations.__annotations__
        )

    def test_staff_list_query_count_does_not_grow(self, client) -> None:
        """Staff see everyone's projects; still no per-row queries."""
        staff = UserFactory(is_staff=True)
        finished = ManufacturabilityCheck.Status.FINISHED
        self._revision(ProjectFactory(), (finished, True))
        one_project = self._list_query_count(client, staff)
        for _ in range(24):
            self._revision(ProjectFactory(), (finished, True))

        assert self._list_query_count(client, staff) == one_project

    def _list_query_count(self, client, user) -> int:
        """Number of queries one render of the list takes."""
        client.force_login(user)
        with CaptureQueriesContext(connection) as queries:
            client.get(reverse("projects:list"))
        return len(queries)

    def test_query_count_does_not_grow_with_projects(self, client) -> None:
        """The state is annotated, not computed per row (no N+1)."""
        user = UserFactory()
        finished = ManufacturabilityCheck.Status.FINISHED
        self._revision(ProjectFactory(user=user), (finished, True))
        one_project = self._list_query_count(client, user)
        for _ in range(14):
            self._revision(ProjectFactory(user=user), (finished, True))

        assert self._list_query_count(client, user) == one_project


@pytest.mark.django_db
class TestProjectListViewStaff(TestCase):
    """Test ProjectListView with staff user access."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.owner = User.objects.create_user(
            username="owner", email="owner@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.owner, name="Owner Project", description="Owner description"
        )

    def test_project_list_shows_only_own_projects_for_regular_user(self):
        """Test that regular users only see their own projects in list."""
        # Create another user with a project
        other_user = User.objects.create_user(
            username="other", email="other@example.com", password=TEST_PASSWORD
        )
        other_project = Project.objects.create(
            user=other_user, name="Other Project", description="Other description"
        )

        self.client.force_login(self.owner)
        response = self.client.get(reverse("projects:list"))

        assert response.status_code == HTTP_OK
        projects = list(response.context["object_list"])
        assert self.project in projects
        assert other_project not in projects

    def test_project_list_shows_all_projects_for_staff(self):
        """Test that staff users see all users' projects in list."""
        # Create another user with a project
        other_user = User.objects.create_user(
            username="other", email="other@example.com", password=TEST_PASSWORD
        )
        other_project = Project.objects.create(
            user=other_user, name="Other Project", description="Other description"
        )

        staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.get(reverse("projects:list"))
        assert response.status_code == HTTP_OK

        projects = list(response.context["object_list"])
        assert self.project in projects
        assert other_project in projects


@pytest.mark.django_db
class TestProjectUpdateViewStaff(TestCase):
    """Test ProjectUpdateView with staff user access."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        self.owner = User.objects.create_user(
            username="owner", email="owner@example.com", password=TEST_PASSWORD
        )
        self.project = Project.objects.create(
            user=self.owner, name="Test Project", description="Test description"
        )

    def test_project_update_staff_access(self):
        """Test that staff user can access update view for any project."""
        staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password=TEST_PASSWORD,
            is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.get(
            reverse("projects:update", kwargs={"pk": self.project.pk})
        )
        assert response.status_code == HTTP_OK
        assert response.context["viewing_as_admin"] is True


@pytest.mark.django_db
class TestCheckDrcUpdateRequeue:
    """Tests for check_drc_update_requeue view."""

    def setup_method(self):
        """Set up test data."""
        cache.clear()
        self.user = UserFactory()
        self.project = ProjectFactory(user=self.user)
        self.project_file = ProjectFileFactory(project=self.project, is_active=True)

    def test_requeue_success(self, client):
        """Successful requeue redirects with success message."""
        # Create finished check with outdated digest
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest=(
                "sha256:old123456789012345678901234567890123456789012345678901234567"
            ),
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        # Establish latest digest
        ManufacturabilityCheckFactory(
            docker_image_digest=(
                "sha256:new456789012345678901234567890123456789012345678901234567890"
            ),
            container_started_at=timezone.now(),
        )
        cache.clear()

        client.force_login(self.user)
        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == HTTP_FOUND
        assert response.url == reverse("projects:detail", args=[self.project.id])

        # Verify new check was created
        new_check = ManufacturabilityCheck.objects.filter(
            parent_check=check,
            trigger_reason=ManufacturabilityCheck.TriggerReason.DRC_UPDATE,
        ).first()
        assert new_check is not None

    @pytest.mark.parametrize(
        "shuttle_status",
        [
            Shuttle.Status.IN_PRODUCTION,
            Shuttle.Status.COMPLETED,
            Shuttle.Status.CANCELLED,
        ],
    )
    @pytest.mark.parametrize("as_staff", [False, True])
    def test_requeue_allowed_in_terminal_shuttle(
        self, client, shuttle_status, as_staff
    ):
        """The manual button works in any shuttle state (issue #270, Tim)."""
        # Explicit name avoids colliding with the migration-seeded "G801".
        shuttle = ShuttleFactory(status=shuttle_status, name="G870")
        project = ProjectFactory(user=self.user, shuttle=shuttle)
        project_file = ProjectFileFactory(project=project, is_active=True)
        check = ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest=(
                "sha256:old123456789012345678901234567890123456789012345678901234567"
            ),
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        ManufacturabilityCheckFactory(
            docker_image_digest=(
                "sha256:new456789012345678901234567890123456789012345678901234567890"
            ),
            container_started_at=timezone.now(),
        )
        cache.clear()

        client.force_login(UserFactory(is_staff=True) if as_staff else self.user)
        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == HTTP_FOUND
        assert ManufacturabilityCheck.objects.filter(
            parent_check=check,
            trigger_reason=ManufacturabilityCheck.TriggerReason.DRC_UPDATE,
        ).exists()

    def test_requeue_permission_denied_other_user(self, client):
        """Non-owner non-staff cannot requeue."""
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest=(
                "sha256:old123456789012345678901234567890123456789012345678901234567"
            ),
        )
        other_user = UserFactory()

        client.force_login(other_user)
        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == HTTP_FORBIDDEN

    def test_requeue_allowed_for_staff(self, client):
        """Staff can requeue any project's check."""
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest=(
                "sha256:old123456789012345678901234567890123456789012345678901234567"
            ),
            container_started_at=timezone.now() - timedelta(hours=2),
        )
        ManufacturabilityCheckFactory(
            docker_image_digest=(
                "sha256:new456789012345678901234567890123456789012345678901234567890"
            ),
            container_started_at=timezone.now(),
        )
        cache.clear()
        staff_user = UserFactory(is_staff=True)

        client.force_login(staff_user)
        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == HTTP_FOUND

    def test_requeue_invalid_check_shows_error(self, client):
        """Requeue of already-latest check shows error message."""
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            docker_image_digest=(
                "sha256:latest123456789012345678901234567890123456789012345678901234"
            ),
            container_started_at=timezone.now(),
        )
        cache.clear()

        client.force_login(self.user)
        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id]),
            follow=True,
        )

        assert response.status_code == HTTP_OK
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "already using latest" in str(messages[0])

    def test_requeue_requires_login(self, client):
        """Unauthenticated users are redirected to login."""
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
        )

        response = client.post(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == HTTP_FOUND
        assert "/accounts/login/" in response.url

    def test_requeue_requires_post(self, client):
        """GET requests are not allowed."""
        check = ManufacturabilityCheckFactory(
            project=self.project,
            project_file=self.project_file,
        )

        client.force_login(self.user)
        response = client.get(
            reverse("projects:check_drc_update_requeue", args=[check.id])
        )

        assert response.status_code == HTTP_METHOD_NOT_ALLOWED


@pytest.mark.django_db
class TestManufacturabilityCheckPartialVersionInfo:
    """Version Info panel resolves versions via the catalog (#315)."""

    DIGEST = "sha256:315ccc5678901234567890123456789012345678901234567890123456789012"
    TEMPLATE = "projects/_manufacturability_check.html"

    def test_precheck_row_resolves_version_from_catalog(self):
        """An unstamped historical check shows the catalog version, not '-'."""
        PrecheckImageRevision.objects.create(
            digest=self.DIGEST,
            precheck_version="1.7.2",
        )
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
            docker_image_digest=self.DIGEST,
        )

        html = render_to_string(self.TEMPLATE, {"check": check})

        precheck_row = html.split("<strong>Precheck:</strong>")[1].split("</tr>")[0]
        assert "1.7.2" in precheck_row

    def test_tools_row_hides_unknown_placeholder(self):
        """The legacy 'precheck: unknown' placeholder badge is not rendered."""
        PrecheckImageRevision.objects.create(
            digest=self.DIGEST,
            tool_versions={"klayout": "0.29.1"},
        )
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.FINISHED,
            is_manufacturable=True,
            docker_image_digest=self.DIGEST,
            tool_versions={"precheck": "unknown"},
        )

        html = render_to_string(self.TEMPLATE, {"check": check})

        assert "precheck: unknown" not in html
        assert "klayout: 0.29.1" in html


@pytest.mark.django_db
class TestCheckStatusJsonIsBounded:
    """The 5-second polling JSON carries only the log tail (#308)."""

    @staticmethod
    def _poll(client, logs: str) -> dict:
        user = UserFactory()
        project = ProjectFactory(user=user)
        project_file = ProjectFileFactory(project=project, is_active=True)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
            processing_logs=logs,
        )
        client.force_login(user)
        response = client.get(reverse("projects:check_status", args=[project.pk]))
        assert response.status_code == HTTP_OK
        return {"size": len(response.content), "data": response.json()}

    def test_large_log_response_is_bounded(self, client) -> None:
        """A 5 MB log polls as at most about 64 KiB, newest lines included."""
        logs = "".join(f"line {i:07d}\n" for i in range(400_000))

        polled = self._poll(client, logs)

        tail = polled["data"]["processing_logs_tail"]
        assert (
            polled["size"] < 70 * 1024,
            tail.endswith("line 0399999\n"),
            "line 0000000" in tail,
        ) == (True, True, False)

    def test_reports_length_and_truncation(self, client) -> None:
        """The page can say how much of the log it is showing."""
        logs = "x" * (100 * 1024)

        data = self._poll(client, logs)["data"]

        assert (
            data["processing_logs_length"],
            data["processing_logs_truncated"],
            "processing_logs" in data,
        ) == (len(logs), True, False)

    def test_short_log_is_whole(self, client) -> None:
        """A small log comes back entire, not marked truncated."""
        data = self._poll(client, "started\n")["data"]

        assert (data["processing_logs_tail"], data["processing_logs_truncated"]) == (
            "started\n",
            False,
        )


@pytest.mark.django_db
class TestCheckLogView:
    """projects:check_log serves the full log behind the project permission."""

    @staticmethod
    def _url(check: ManufacturabilityCheck) -> str:
        return reverse(
            "projects:check_log",
            kwargs={"pk": check.project_id, "check_id": check.pk},
        )

    @staticmethod
    def _body(response) -> bytes:
        return b"".join(response.streaming_content)

    def test_owner_gets_the_whole_log_streamed_from_the_db(
        self, client, settings
    ) -> None:
        """A running check (no saved file) streams the field in slices."""
        settings.CHECK_LOG_STREAM_CHARS = 1000
        logs = "".join(f"line {i}\n" for i in range(2000))
        check = ManufacturabilityCheckFactory(processing_logs=logs)
        client.force_login(check.project.user)

        response = client.get(self._url(check))

        assert (response.streaming, self._body(response).decode()) == (True, logs)

    def test_saved_log_file_is_streamed_not_redirected(
        self, client, settings, tmp_path
    ) -> None:
        """/media/ has no access control, so the view never redirects there."""
        settings.MEDIA_ROOT = str(tmp_path)
        check = ManufacturabilityCheckFactory(processing_logs="db copy\n")
        check.log_file.save("check.log", ContentFile(b"saved log\n"), save=True)
        client.force_login(check.project.user)

        response = client.get(self._url(check))

        assert (
            response.status_code,
            response.has_header("Location"),
            self._body(response),
        ) == (HTTP_OK, False, b"saved log\n")

    def test_other_users_are_refused(self, client) -> None:
        """Someone who cannot see the project cannot read its logs."""
        check = ManufacturabilityCheckFactory(processing_logs="secret\n")
        client.force_login(UserFactory())

        assert client.get(self._url(check)).status_code == HTTP_FORBIDDEN

    def test_check_of_another_project_is_not_found(self, client) -> None:
        """A check id is only valid under its own project."""
        check = ManufacturabilityCheckFactory(processing_logs="x\n")
        other = ProjectFactory(user=check.project.user)
        client.force_login(check.project.user)
        url = reverse(
            "projects:check_log", kwargs={"pk": other.pk, "check_id": check.pk}
        )

        assert client.get(url).status_code == HTTP_NOT_FOUND

    def test_anonymous_is_sent_to_login(self, client) -> None:
        """No log for visitors who are not logged in."""
        check = ManufacturabilityCheckFactory(processing_logs="x\n")

        response = client.get(self._url(check))

        assert (response.status_code, "login" in response["Location"]) == (
            HTTP_FOUND,
            True,
        )


@pytest.mark.django_db
class TestDetailPageLogsAreBounded:
    """The project page never ships whole logs (#308: a 25 MB page)."""

    MB = 1024 * 1024
    CHECKS = 11  # the latest plus ten previous checks

    def _detail_with_history(self, client) -> tuple[str, ManufacturabilityCheck]:
        user = UserFactory()
        project = ProjectFactory(user=user)
        project_file = ProjectFileFactory(project=project, is_active=True)
        start = timezone.now()
        checks = []
        for offset in range(self.CHECKS):
            check = ManufacturabilityCheckFactory(
                project=project,
                project_file=project_file,
                status=ManufacturabilityCheck.Status.FINISHED,
                is_manufacturable=True,
                processing_logs=f"run {offset} start\n"
                + "y" * (2 * self.MB)
                + f"\nrun {offset} end\n",
            )
            ManufacturabilityCheck.objects.filter(pk=check.pk).update(
                created_at=start + timedelta(seconds=offset)
            )
            checks.append(check)
        client.force_login(user)
        html = client.get(reverse("projects:detail", args=[project.pk])).content
        return html.decode(), checks[-1]

    def test_page_with_ten_large_previous_checks_stays_small(self, client) -> None:
        """Eleven 2 MB logs render well under 200 KiB in total."""
        html, _latest = self._detail_with_history(client)

        assert len(html) < 200 * 1024

    def test_latest_tail_shown_and_no_history_log_body(self, client) -> None:
        """The newest lines of the latest check show; older runs' logs do not."""
        html, _latest = self._detail_with_history(client)

        assert ("run 10 end" in html, "run 3 end" in html) == (True, False)

    def test_every_check_links_its_full_log(self, client) -> None:
        """The latest and every previous check offer the full-log link."""
        html, latest = self._detail_with_history(client)

        assert (
            html.count("data-full-log-link") >= self.CHECKS,
            f"/checks/{latest.pk}/log/" in html,
        ) == (True, True)

    def test_saved_log_file_is_not_linked_on_media(
        self, client, settings, tmp_path
    ) -> None:
        """/media/ has no access control, so the page never links a log there."""
        settings.MEDIA_ROOT = str(tmp_path)
        user = UserFactory()
        project = ProjectFactory(user=user)
        project_file = ProjectFileFactory(project=project, is_active=True)
        check = ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.FINISHED,
            processing_logs="done\n",
        )
        check.log_file.save("check.log", ContentFile(b"done\n"), save=True)
        client.force_login(user)

        html = client.get(reverse("projects:detail", args=[project.pk])).content

        assert check.log_file.url.encode() not in html


@pytest.mark.django_db
class TestOtherWebPathsLoadNoWholeLogs:
    """Review of #308: every web path that touches checks skips the log."""

    BIG_LOG = "first line of a long run\n" + "z" * (2 * 1024 * 1024) + "\nlast\n"

    @staticmethod
    def _selects_logs(queries) -> list[str]:
        return [
            q["sql"]
            for q in queries
            if q["sql"].lstrip().upper().startswith("SELECT")
            and "processing_logs" in q["sql"]
            and "RIGHT(" not in q["sql"].upper()
            and "LENGTH(" not in q["sql"].upper()
        ]

    def test_admin_check_status_page(self, client) -> None:
        """projects:admin_check_status lists checks without their logs."""
        ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING, processing_logs=self.BIG_LOG
        )
        client.force_login(UserFactory(is_staff=True))

        with CaptureQueriesContext(connection) as queries:
            response = client.get(reverse("projects:admin_check_status"))

        assert (response.status_code, self._selects_logs(queries)) == (HTTP_OK, [])

    def test_cancel_reads_and_rewrites_no_log(self, client) -> None:
        """Cancelling appends its note in SQL; the log never enters Python."""
        check = ManufacturabilityCheckFactory(
            status=ManufacturabilityCheck.Status.RUNNING, processing_logs=self.BIG_LOG
        )
        client.force_login(check.project.user)

        with CaptureQueriesContext(connection) as queries:
            client.post(
                reverse(
                    "projects:cancel_check",
                    kwargs={"pk": check.project_id, "check_id": check.pk},
                )
            )

        check.refresh_from_db()
        assert (
            self._selects_logs(queries),
            check.status,
            check.processing_logs.startswith("first line of a long run"),
        ) == ([], ManufacturabilityCheck.Status.CANCELLING, True)

    def test_staff_can_poll_a_project_they_view(self, client) -> None:
        """Staff see the project page, so its polling must not 403 forever."""
        project = ProjectFactory()
        project_file = ProjectFileFactory(project=project, is_active=True)
        ManufacturabilityCheckFactory(
            project=project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.RUNNING,
            processing_logs="x\n",
        )
        client.force_login(UserFactory(is_staff=True))

        response = client.get(reverse("projects:check_status", args=[project.pk]))

        assert response.status_code == HTTP_OK

    def test_missing_saved_log_file_falls_back_to_the_db(
        self, client, settings, tmp_path
    ) -> None:
        """A row naming a deleted file still serves the log, not a 500."""
        settings.MEDIA_ROOT = str(tmp_path)
        check = ManufacturabilityCheckFactory(processing_logs="db copy\n")
        check.log_file.save("check.log", ContentFile(b"saved\n"), save=True)
        Path(check.log_file.path).unlink()
        client.force_login(check.project.user)

        response = client.get(
            reverse(
                "projects:check_log",
                kwargs={"pk": check.project_id, "check_id": check.pk},
            )
        )

        assert b"".join(response.streaming_content) == b"db copy\n"

    def test_django_admin_change_view_shows_only_the_tail(self, client) -> None:
        """The admin's check page links the full log instead of inlining it."""
        check = ManufacturabilityCheckFactory(processing_logs=self.BIG_LOG)
        client.force_login(UserFactory(is_staff=True, is_superuser=True))

        html = client.get(
            reverse("admin:projects_manufacturabilitycheck_change", args=[check.pk])
        ).content

        assert (
            len(html) < 300 * 1024,
            b"first line of a long run" in html,
            f"/checks/{check.pk}/log/".encode() in html,
        ) == (True, False, True)

    def test_django_admin_changelist_loads_no_logs(self, client) -> None:
        """The admin's check list never selects the log column."""
        ManufacturabilityCheckFactory(processing_logs=self.BIG_LOG)
        client.force_login(UserFactory(is_staff=True, is_superuser=True))

        with CaptureQueriesContext(connection) as queries:
            response = client.get(
                reverse("admin:projects_manufacturabilitycheck_changelist")
            )

        assert (response.status_code, self._selects_logs(queries)) == (HTTP_OK, [])
