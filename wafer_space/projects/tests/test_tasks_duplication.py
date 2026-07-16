"""Tests for the project-duplication Celery task."""

from __future__ import annotations

import pytest
from django.contrib.admin.models import ADDITION
from django.contrib.admin.models import CHANGE
from django.contrib.admin.models import LogEntry
from django.test import TestCase

from wafer_space.projects.models import Project
from wafer_space.projects.tasks_duplication import duplicate_project_task
from wafer_space.users.models import User

from .constants import TEST_PASSWORD
from .factories import ProjectFactory
from .test_duplication import make_shuttle
from .test_duplication import make_source_project


def test_task_routed_to_rw_downloads_queue() -> None:
    """The whole async design hangs on running in a worker that may
    write user files; pin the queue so a routing change fails loudly."""
    assert duplicate_project_task.queue == "http:rw:downloads"


@pytest.mark.django_db
class TestDuplicateProjectTask(TestCase):
    """The task performs the copy and records LogEntry outcomes."""

    def setUp(self) -> None:
        self.admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password=TEST_PASSWORD,
        )
        self.source_shuttle = make_shuttle("G890")
        self.target_shuttle = make_shuttle("G891")
        self.source = make_source_project(shuttle=self.source_shuttle)

    def test_success_creates_duplicate_and_log_entries(self) -> None:
        result = duplicate_project_task(
            str(self.source.pk),
            self.target_shuttle.pk,
            self.admin_user.pk,
        )

        assert result["status"] == "ok"
        duplicate = Project.objects.get(pk=result["duplicate_pk"])
        assert duplicate.shuttle == self.target_shuttle
        assert duplicate.status == Project.Status.DRAFT
        assert LogEntry.objects.filter(
            action_flag=ADDITION,
            object_id=str(duplicate.pk),
            user=self.admin_user,
        ).exists()
        assert LogEntry.objects.filter(
            action_flag=CHANGE,
            object_id=str(self.source.pk),
            user=self.admin_user,
        ).exists()

    def test_failure_records_log_entry_and_creates_nothing(self) -> None:
        # Collision appears after the admin's pre-flight validation: the
        # task must catch it, record the failure, and create no project.
        ProjectFactory(
            shuttle=self.target_shuttle,
            project_id=self.source.project_id,
        )
        projects_before = Project.objects.count()

        result = duplicate_project_task(
            str(self.source.pk),
            self.target_shuttle.pk,
            self.admin_user.pk,
        )

        assert result["status"] == "failed"
        assert "already used" in result["error"]
        assert Project.objects.count() == projects_before
        failure_log = LogEntry.objects.get(
            action_flag=CHANGE,
            object_id=str(self.source.pk),
        )
        assert "FAILED" in failure_log.get_change_message()
