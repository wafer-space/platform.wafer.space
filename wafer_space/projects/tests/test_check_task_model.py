"""Tests for ManufacturabilityCheckTask model."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from wafer_space.projects.models import ManufacturabilityCheckTask
from wafer_space.projects.tests.factories import ManufacturabilityCheckFactory

pytestmark = pytest.mark.django_db


class TestManufacturabilityCheckTaskModel:
    """Test ManufacturabilityCheckTask model."""

    def test_can_create_task_for_check(self) -> None:
        """Can create a task tracking row for a check."""
        check = ManufacturabilityCheckFactory()
        task = ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id="abc123",
            task_name="do_running",
        )
        assert task.manufacturability_check == check
        assert task.task_id == "abc123"
        assert task.task_name == "do_running"
        assert task.queued_at is not None

    def test_one_to_one_enforces_single_task(self) -> None:
        """Only one pending task allowed per check (OneToOne constraint)."""
        check = ManufacturabilityCheckFactory()
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id="task1",
            task_name="do_running",
        )
        with pytest.raises(IntegrityError):
            ManufacturabilityCheckTask.objects.create(
                manufacturability_check=check,
                task_id="task2",
                task_name="do_running",
            )

    def test_deleting_check_deletes_task(self) -> None:
        """Deleting check cascades to delete task."""
        check = ManufacturabilityCheckFactory()
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id="abc123",
            task_name="do_running",
        )
        check_id = check.id
        check.delete()
        assert not ManufacturabilityCheckTask.objects.filter(
            manufacturability_check_id=check_id
        ).exists()

    def test_pending_task_relation(self) -> None:
        """Check has pending_task reverse relation."""
        check = ManufacturabilityCheckFactory()
        task = ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id="abc123",
            task_name="do_running",
        )
        assert check.pending_task == task
