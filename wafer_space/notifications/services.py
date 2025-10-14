"""Service layer for creating and managing notifications."""

from django.contrib.contenttypes.models import ContentType

from .models import Notification


class NotificationService:
    """Service for creating notifications."""

    @staticmethod
    def create_download_complete_notification(user, project_file):
        """Create notification when file download completes successfully.

        Args:
            user: User to notify
            project_file: ProjectFile instance that completed download

        Returns:
            Notification instance
        """
        content_type = ContentType.objects.get_for_model(project_file)

        title = f"Download Complete: {project_file.original_filename}"
        message = (
            f"Your file '{project_file.original_filename}' "
            f"has been successfully downloaded and is ready for processing."
        )

        return Notification.objects.create(
            user=user,
            notification_type=Notification.Type.DOWNLOAD_COMPLETE,
            title=title,
            message=message,
            content_type=content_type,
            object_id=project_file.id,
        )

    @staticmethod
    def create_download_failed_notification(user, project_file, error_message):
        """Create notification when file download fails.

        Args:
            user: User to notify
            project_file: ProjectFile instance that failed download
            error_message: Error message describing the failure

        Returns:
            Notification instance
        """
        content_type = ContentType.objects.get_for_model(project_file)

        title = f"Download Failed: {project_file.original_filename}"
        message = (
            f"Failed to download '{project_file.original_filename}'. "
            f"Error: {error_message}"
        )

        return Notification.objects.create(
            user=user,
            notification_type=Notification.Type.DOWNLOAD_FAILED,
            title=title,
            message=message,
            content_type=content_type,
            object_id=project_file.id,
        )

    @staticmethod
    def create_checksum_verified_notification(user, project_file):
        """Create notification when checksum verification succeeds.

        Args:
            user: User to notify
            project_file: ProjectFile instance with verified checksum

        Returns:
            Notification instance
        """
        content_type = ContentType.objects.get_for_model(project_file)

        title = f"Checksum Verified: {project_file.original_filename}"
        message = (
            f"File integrity verified for '{project_file.original_filename}'. "
            f"The downloaded file matches the expected checksums."
        )

        return Notification.objects.create(
            user=user,
            notification_type=Notification.Type.CHECKSUM_VERIFIED,
            title=title,
            message=message,
            content_type=content_type,
            object_id=project_file.id,
        )

    @staticmethod
    def create_checksum_mismatch_notification(user, project_file, errors):
        """Create notification when checksum verification fails.

        Args:
            user: User to notify
            project_file: ProjectFile instance with mismatched checksum
            errors: List of error messages describing mismatches

        Returns:
            Notification instance
        """
        content_type = ContentType.objects.get_for_model(project_file)

        title = f"Checksum Mismatch: {project_file.original_filename}"
        error_details = " ".join(errors) if errors else "Checksum verification failed."
        message = (
            f"File integrity check failed for '{project_file.original_filename}'. "
            f"{error_details}"
        )

        return Notification.objects.create(
            user=user,
            notification_type=Notification.Type.CHECKSUM_MISMATCH,
            title=title,
            message=message,
            content_type=content_type,
            object_id=project_file.id,
        )
