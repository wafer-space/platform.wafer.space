"""
Background tasks for project processing.
"""
import time
from celery import shared_task
from django.utils import timezone

from .models import ManufacturabilityCheck, Project


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_project_manufacturability(self, check_id):
    """
    Background task to check project manufacturability.

    Args:
        check_id: The ID of the ManufacturabilityCheck instance

    Returns:
        dict: Result data with status and details
    """
    try:
        # Get the manufacturability check instance
        check = ManufacturabilityCheck.objects.get(id=check_id)
        check.task_id = self.request.id
        check.start_processing()

        # Simulate manufacturability checking process
        # In a real implementation, this would:
        # 1. Parse design files
        # 2. Run DRC (Design Rule Check)
        # 3. Validate against manufacturing constraints
        # 4. Generate reports

        project = check.project
        errors = []
        warnings = []
        logs = f"Starting manufacturability check for project: {project.name}\n"

        # Simulate processing time
        time.sleep(2)

        # Basic validation checks (placeholder logic)
        logs += "Checking design files...\n"

        if not project.files.exists():
            errors.append("No design files uploaded")
            logs += "ERROR: No design files found\n"
        else:
            file_count = project.files.count()
            logs += f"Found {file_count} design file(s)\n"

            # Check file verification
            unverified_files = project.files.filter(hash_verified=False)
            if unverified_files.exists():
                warnings.append(f"{unverified_files.count()} files have unverified hashes")
                logs += f"WARNING: {unverified_files.count()} files with unverified hashes\n"

        # Simulate additional checks
        logs += "Running design rule checks...\n"
        time.sleep(1)

        logs += "Validating manufacturing constraints...\n"
        time.sleep(1)

        # Determine if manufacturable (simplified logic)
        is_manufacturable = len(errors) == 0

        if is_manufacturable:
            logs += "SUCCESS: Project passed all manufacturability checks\n"
        else:
            logs += f"FAILED: Project failed with {len(errors)} errors\n"

        # Complete the check
        check.complete(
            is_manufacturable=is_manufacturable,
            errors=errors,
            warnings=warnings,
            logs=logs
        )

        return {
            "status": "completed",
            "is_manufacturable": is_manufacturable,
            "errors": errors,
            "warnings": warnings,
            "project_id": str(project.id)
        }

    except ManufacturabilityCheck.DoesNotExist:
        return {
            "status": "error",
            "message": f"ManufacturabilityCheck with id {check_id} not found"
        }

    except Exception as exc:
        # Handle task retry logic
        if self.request.retries < self.max_retries:
            # Update check with retry info
            try:
                check = ManufacturabilityCheck.objects.get(id=check_id)
                check.retry_count += 1
                check.processing_logs += f"\nRetry {check.retry_count}: {str(exc)}\n"
                check.save()
            except ManufacturabilityCheck.DoesNotExist:
                pass

            # Retry the task
            raise self.retry(exc=exc)
        else:
            # Max retries reached, mark as failed
            try:
                check = ManufacturabilityCheck.objects.get(id=check_id)
                check.fail(f"Max retries reached: {str(exc)}")
            except ManufacturabilityCheck.DoesNotExist:
                pass

            return {
                "status": "failed",
                "message": str(exc),
                "retries": self.request.retries
            }


@shared_task
def cleanup_old_task_results():
    """
    Periodic task to clean up old Celery task results.
    """
    from django_celery_results.models import TaskResult
    from datetime import timedelta

    # Delete task results older than 24 hours
    cutoff_date = timezone.now() - timedelta(hours=24)
    deleted_count = TaskResult.objects.filter(date_created__lt=cutoff_date).delete()[0]

    return {
        "status": "completed",
        "deleted_count": deleted_count,
        "cutoff_date": cutoff_date.isoformat()
    }


@shared_task
def update_project_status(project_id, new_status):
    """
    Update a project's status.

    Args:
        project_id: UUID of the project
        new_status: New status to set

    Returns:
        dict: Result data
    """
    try:
        project = Project.objects.get(id=project_id)
        old_status = project.status
        project.status = new_status
        project.save()

        return {
            "status": "completed",
            "project_id": str(project_id),
            "old_status": old_status,
            "new_status": new_status
        }

    except Project.DoesNotExist:
        return {
            "status": "error",
            "message": f"Project with id {project_id} not found"
        }