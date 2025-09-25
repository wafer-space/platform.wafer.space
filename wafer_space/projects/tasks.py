"""
Background tasks for project processing.
"""
import hashlib
import mimetypes
import os
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen, Request

from celery import shared_task
from django.core.files.base import ContentFile
from django.utils import timezone

from .models import ManufacturabilityCheck, Project, ProjectFile


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


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def download_project_file(self, file_id):
    """
    Background task to download a project file from a URL.

    Args:
        file_id: The ID of the ProjectFile instance

    Returns:
        dict: Result data with status and details
    """
    try:
        # Get the project file instance
        project_file = ProjectFile.objects.get(id=file_id)

        if not project_file.source_url:
            return {
                "status": "error",
                "message": "No source URL provided for file download"
            }

        # Create temp directory if it doesn't exist
        temp_dir = os.path.join(tempfile.gettempdir(), 'wafer_space_downloads')
        os.makedirs(temp_dir, exist_ok=True)

        # Parse URL to get filename
        parsed_url = urlparse(project_file.source_url)
        if not project_file.original_filename:
            # Extract filename from URL if not already set
            filename = os.path.basename(parsed_url.path) or "downloaded_file"
            project_file.original_filename = filename
            project_file.save()

        # Create request with proper headers
        request = Request(project_file.source_url)
        request.add_header('User-Agent', 'wafer.space/1.0')

        # Download the file
        with urlopen(request) as response:
            # Get content type and size if available
            content_type = response.headers.get('Content-Type', '')
            if content_type:
                project_file.content_type = content_type

            # Read file content
            file_content = response.read()
            project_file.file_size = len(file_content)

        # Create temporary file to store content
        temp_filename = f"{project_file.id}_{project_file.original_filename}"
        temp_path = os.path.join(temp_dir, temp_filename)

        with open(temp_path, 'wb') as temp_file:
            temp_file.write(file_content)

        # Create Django file from the downloaded content
        with open(temp_path, 'rb') as temp_file:
            django_file = ContentFile(temp_file.read())
            django_file.name = project_file.original_filename
            project_file.file.save(project_file.original_filename, django_file, save=False)

        # Calculate file hashes
        project_file.hash_md5 = hashlib.md5(file_content).hexdigest()
        project_file.hash_sha1 = hashlib.sha1(file_content).hexdigest()

        # Verify hashes if expected values were provided
        hash_verified = True
        verification_errors = []

        if project_file.expected_hash_md5:
            if project_file.hash_md5.lower() != project_file.expected_hash_md5.lower():
                hash_verified = False
                verification_errors.append(
                    f"MD5 mismatch: expected {project_file.expected_hash_md5}, got {project_file.hash_md5}"
                )

        if project_file.expected_hash_sha1:
            if project_file.hash_sha1.lower() != project_file.expected_hash_sha1.lower():
                hash_verified = False
                verification_errors.append(
                    f"SHA1 mismatch: expected {project_file.expected_hash_sha1}, got {project_file.hash_sha1}"
                )

        project_file.hash_verified = hash_verified
        project_file.mark_download_complete()

        # Clean up temp file
        try:
            os.remove(temp_path)
        except OSError:
            pass

        return {
            "status": "completed",
            "file_id": str(file_id),
            "original_filename": project_file.original_filename,
            "file_size": project_file.file_size,
            "hash_verified": hash_verified,
            "verification_errors": verification_errors,
            "md5": project_file.hash_md5,
            "sha1": project_file.hash_sha1
        }

    except ProjectFile.DoesNotExist:
        return {
            "status": "error",
            "message": f"ProjectFile with id {file_id} not found"
        }

    except Exception as exc:
        # Handle task retry logic
        if self.request.retries < self.max_retries:
            # Update file with retry info
            try:
                project_file = ProjectFile.objects.get(id=file_id)
                project_file.download_error = f"Retry {self.request.retries + 1}: {str(exc)}"
                project_file.save()
            except ProjectFile.DoesNotExist:
                pass

            # Retry the task
            raise self.retry(exc=exc)
        else:
            # Max retries reached, mark as failed
            try:
                project_file = ProjectFile.objects.get(id=file_id)
                project_file.mark_download_failed(f"Max retries reached: {str(exc)}")
            except ProjectFile.DoesNotExist:
                pass

            return {
                "status": "failed",
                "message": str(exc),
                "retries": self.request.retries
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