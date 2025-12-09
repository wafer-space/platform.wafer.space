"""
Background tasks for manufacturability checks.
"""

import logging
import shutil
import tarfile
import time
from datetime import timedelta
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import TypeVar
from urllib.parse import urlparse

import docker
import docker.errors
from celery import shared_task
from celery.utils.log import get_task_logger
from django.conf import settings
from django.core.files import File
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.db.models import Exists
from django.db.models import OuterRef
from django.utils import timezone

from .check_operations import create_retry_check
from .docker_utils import create_directory_tar
from .docker_utils import create_tar_archive
from .docker_utils import get_docker_client
from .docker_utils import get_server_config
from .docker_utils import parse_docker_timestamp_float
from .docker_utils import stop_and_remove_container
from .docker_utils import stream_archive_to_file
from .docker_utils import stream_container_diff_to_file
from .docker_utils import strip_docker_timestamps
from .exceptions import InvalidStateTransitionError
from .exceptions import MaxRetriesExceededError
from .exceptions import TaskExecutionError
from .hashing import MultiHasher
from .models import ManufacturabilityCheck
from .models import ManufacturabilityCheckpoint
from .models import ManufacturabilityCheckTask
from .models import ProjectFile
from .precheck_parser import PrecheckLogParser
from .precheck_parser import classify_failure
from .verification import is_check_task_actively_running

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T")


# =============================================================================
# Task Decorators
# =============================================================================


def checks_task(**celery_kwargs: Any) -> "Callable[[Callable[..., T]], Any]":
    """Decorator for periodic checks_ tasks with automatic logging.

    Wraps function with @shared_task and adds start/stop logging.
    The function name is used in log messages (e.g., "[checks_pending] Starting...").

    Args:
        **celery_kwargs: Arguments passed to @shared_task (e.g., queue="default")

    Returns:
        Decorator that wraps the function with Celery and logging.

    Example:
        @checks_task(queue="default")
        def checks_pending() -> dict[str, int]:
            # ... do work
            return {"dispatched": 5}
    """
    # Default to default queue if not specified
    if "queue" not in celery_kwargs:
        celery_kwargs["queue"] = "default"

    def decorator(func: "Callable[..., T]") -> Any:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            logger = logging.getLogger(__name__)

            logger.info("[%s] Starting", func.__name__)

            result = func(*args, **kwargs)

            logger.info("[%s] Complete", func.__name__)

            return result

        return shared_task(**celery_kwargs)(wrapper)

    return decorator


def queued_check_task(
    *,
    expected_status: str | None = None,
    **celery_kwargs: Any,
) -> "Callable[[Callable[..., T]], Any]":
    """Decorator for manufacturability check work tasks.

    Combines @shared_task with automatic task tracking cleanup and optional
    status verification. The decorated function receives a ManufacturabilityCheck
    object as its first argument (fetched from the check_id passed by Celery).

    Args:
        expected_status: If provided, verify check.status matches this value
            before calling the wrapped function. Returns skip result if mismatch.
            Use the status name, e.g., "DISPATCHING", "STARTING", "RUNNING".
        **celery_kwargs: Arguments passed to @shared_task
            (e.g., queue="docker-ephemeral")

    Returns:
        Decorator that wraps the function with task tracking and Celery integration.

    Example:
        @queued_check_task(expected_status="RUNNING")
        def do_running(check: ManufacturabilityCheck) -> dict[str, Any]:
            # check is already fetched and status verified
            # ... do work
            return {"status": "completed"}
    """
    # Default to docker-ephemeral queue if not specified
    if "queue" not in celery_kwargs:
        celery_kwargs["queue"] = "docker-ephemeral"

    def decorator(func: "Callable[..., T]") -> Any:
        @wraps(func)
        def wrapper(check_id: int, *args: Any, **kwargs: Any) -> T | dict[str, str]:
            logger = logging.getLogger(__name__)

            logger.info("Starting %s for check %s", func.__name__, check_id)

            try:
                # Fetch the check object
                check = ManufacturabilityCheck.objects.get(id=check_id)

                # Verify expected status if specified (case-insensitive comparison)
                if expected_status and check.status.lower() != expected_status.lower():
                    logger.info(
                        "Skipping %s for check %s - status changed to %s",
                        func.__name__,
                        check_id,
                        check.status,
                    )
                    return {"status": "skipped", "reason": "status_changed"}

                # Call wrapped function with check object
                result = func(check, *args, **kwargs)
            except TaskExecutionError as e:
                # Handle task execution errors - mark check as error
                logger.exception(
                    "%s failed for check %s: %s", func.__name__, check_id, e.message
                )
                check.mark_error(error_message=e.message)
                return {"status": "error", "reason": e.reason}
            except Exception as e:
                # Handle all other errors - mark check as error
                error_msg = f"{func.__name__} failed: {e}"
                logger.exception(error_msg)
                check.mark_error(error_message=error_msg)
                return {"status": "error", "reason": str(e)}
            else:
                logger.info("Completed %s for check %s", func.__name__, check_id)
                return result
            finally:
                ManufacturabilityCheckTask.objects.filter(
                    manufacturability_check_id=check_id
                ).delete()

        # Apply shared_task decorator with provided kwargs
        # Return type is Any because Celery tasks have special methods
        # like .delay() and .apply_async()
        return shared_task(**celery_kwargs)(wrapper)

    return decorator


__all__ = [
    "checks_analyzing",
    "checks_cancelling",
    "checks_cleanup",
    "checks_cleanup_orphaned_docker",
    "checks_cleanup_stale_files",
    "checks_cleanup_stale_pending_tasks",
    "checks_create",
    "checks_dispatching",
    "checks_pending",
    "checks_retry",
    "checks_running",
    "checks_starting",
    "do_analyzing",
    "do_dispatching",
    "do_running",
    "do_starting",
]


def _cleanup_container_if_orphaned(
    container: "docker.models.containers.Container",
    server_id: str,
    our_site: str,
    active_states: list[str],
    logger: logging.Logger,
) -> str:
    """Check if container should be cleaned up and remove if so.

    Returns:
        'skipped' - container from different site
        'removed' - container was orphaned and removed
        'kept' - container is still active
    """
    # Check site label - skip containers from other platform instances
    container_site = container.labels.get("wafer.space.site")
    if container_site and container_site != our_site:
        logger.debug(
            "Server %s, container %s: site=%s (ours=%s), skipping",
            server_id,
            container.short_id,
            container_site,
            our_site,
        )
        return "skipped"

    check_id = container.labels.get("wafer.space.check_id")

    # No check_id label = definitely orphaned (and from our site or no site)
    if not check_id:
        logger.info(
            "Server %s, container %s: no check_id label, removing",
            server_id,
            container.short_id,
        )
        stop_and_remove_container(container, logger)
        return "removed"

    # Look up the check
    try:
        check = ManufacturabilityCheck.objects.get(id=check_id)
    except ManufacturabilityCheck.DoesNotExist:
        logger.info(
            "Server %s, container %s: check %s not found, removing",
            server_id,
            container.short_id,
            check_id,
        )
        stop_and_remove_container(container, logger)
        return "removed"

    # Check exists - is it in an active state?
    if check.status not in active_states:
        logger.info(
            "Server %s, container %s: check %s in %s state, removing",
            server_id,
            container.short_id,
            check_id,
            check.status,
        )
        stop_and_remove_container(container, logger)
        return "removed"

    logger.debug(
        "Server %s, container %s: check %s in %s state, keeping",
        server_id,
        container.short_id,
        check_id,
        check.status,
    )
    return "kept"


@shared_task(queue="docker-ephemeral")
def checks_cleanup_orphaned_docker() -> dict:
    """Remove Docker containers not linked to active checks (fallback cleanup).

    Iterates over all configured Docker servers and removes containers where
    the associated ManufacturabilityCheck is:
    - Missing (deleted)
    - FINISHED
    - ERROR
    - CANCELLED

    CANCELLING containers are handled by checks_cancelling task, not here.

    Only cleans up containers created by this platform instance (matching
    wafer.space.site label). This prevents prod from cleaning up staging
    containers and vice versa when sharing Docker servers.

    Returns:
        dict with per-server results and totals
    """
    logger = get_task_logger(__name__)
    logger.info("[checks_cleanup_orphaned_docker] Starting")

    total_scanned = 0
    total_removed = 0
    total_skipped = 0
    server_results: dict[str, dict] = {}

    active_states = list(ManufacturabilityCheck.Status.active())
    our_site = urlparse(settings.SITE_URL).netloc if settings.SITE_URL else "unknown"
    logger.info("Filtering for containers with wafer.space.site=%s", our_site)

    for server in settings.DOCKER_SERVERS:
        server_id = str(server["id"])
        logger.info("Scanning server %s", server_id)

        try:
            client = get_docker_client(server)
        except docker.errors.DockerException as exc:
            logger.exception("Failed to connect to server %s", server_id)
            server_results[server_id] = {"status": "error", "error": str(exc)}
            continue

        try:
            containers = client.containers.list(
                all=True,
                filters={"label": "wafer.space.service=manufacturability-check"},
            )
        except docker.errors.DockerException as exc:
            logger.exception("Failed to list containers on %s", server_id)
            server_results[server_id] = {"status": "error", "error": str(exc)}
            continue

        logger.info("Server %s: found %d containers", server_id, len(containers))
        removed, skipped = 0, 0

        for container in containers:
            result = _cleanup_container_if_orphaned(
                container, server_id, our_site, active_states, logger
            )
            if result == "removed":
                removed += 1
            elif result == "skipped":
                skipped += 1

        server_results[server_id] = {
            "scanned": len(containers),
            "removed": removed,
            "skipped": skipped,
        }
        total_scanned += len(containers)
        total_removed += removed
        total_skipped += skipped

    logger.info(
        "[checks_cleanup_orphaned_docker] Complete: scanned=%d, removed=%d, skipped=%d",
        total_scanned,
        total_removed,
        total_skipped,
    )

    return {
        "containers_scanned": total_scanned,
        "removed": total_removed,
        "skipped": total_skipped,
        "servers": server_results,
    }


@checks_task(queue="default")
def checks_pending() -> dict[str, int]:
    """Transition PENDING checks to DISPATCHING with server assignment.

    Serializes dispatch to prevent Docker API overload:
    - Only ONE check per server can be in DISPATCHING or STARTING state
    - Must wait for check to reach RUNNING before dispatching the next
    - Still respects per-server max_concurrent for total active checks

    This prevents multiple concurrent Docker operations (image pulls,
    container creation) from overloading the Docker API.

    Returns:
        Dict with count of dispatched checks.
    """
    logger = logging.getLogger(__name__)

    dispatched = 0

    # Sort servers by priority (lowest first)
    servers = sorted(settings.DOCKER_SERVERS, key=lambda s: s["priority"])

    for server in servers:
        server_id = str(server["id"])
        max_concurrent = int(server["max_concurrent"])

        # Serialize dispatch: skip if any check is DISPATCHING or STARTING
        # This prevents concurrent Docker operations (image pull, container create)
        initializing_count = ManufacturabilityCheck.objects.filter(
            docker_server_id=server_id,
            status__in=[
                ManufacturabilityCheck.Status.DISPATCHING,
                ManufacturabilityCheck.Status.STARTING,
            ],
        ).count()

        if initializing_count > 0:
            logger.debug(
                "Server %s: %d check(s) initializing (DISPATCHING/STARTING), "
                "skipping dispatch",
                server_id,
                initializing_count,
            )
            continue

        # Count active checks on this server (DISPATCHING, STARTING, RUNNING, etc.)
        active_count = ManufacturabilityCheck.objects.filter(
            docker_server_id=server_id,
            status__in=ManufacturabilityCheck.Status.active(),
        ).count()

        if active_count >= max_concurrent:
            logger.debug(
                "Server %s: at capacity (%d/%d active)",
                server_id,
                active_count,
                max_concurrent,
            )
            continue

        logger.info(
            "Server %s: %d/%d active, dispatching one check",
            server_id,
            active_count,
            max_concurrent,
        )

        # Dispatch only ONE check per server per cycle (serialized dispatch)
        pending_check = (
            ManufacturabilityCheck.objects.filter(
                status=ManufacturabilityCheck.Status.PENDING,
            )
            .order_by("created_at")
            .first()
        )

        if pending_check:
            pending_check.mark_dispatching(server_id=server_id)
            logger.info("Assigned check %s to server %s", pending_check.id, server_id)
            dispatched += 1

    return {"dispatched": dispatched}


@checks_task(queue="default")
def checks_dispatching() -> dict[str, int]:
    """Queue do_dispatching work tasks for DISPATCHING checks.

    Only queues if check doesn't already have a pending task.

    Returns:
        Dict with count of queued tasks.
    """
    logger = logging.getLogger(__name__)

    queued = 0

    dispatching_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.DISPATCHING,
    ).exclude(pending_task__isnull=False)

    logger.info(
        "Found %d DISPATCHING checks without pending task",
        dispatching_checks.count(),
    )

    for check in dispatching_checks:
        result = do_dispatching.delay(check.id)
        try:
            ManufacturabilityCheckTask.objects.create(
                manufacturability_check=check,
                task_id=result.id,
                task_name="do_dispatching",
            )
        except IntegrityError:
            # Task already created by concurrent beat cycle - skip
            logger.debug("Task already exists for check %s, skipping", check.id)
            continue
        logger.info(
            "Queued do_dispatching for check %s (task: %s)", check.id, result.id
        )
        queued += 1

    return {"queued": queued}


@checks_task(queue="default")
def checks_starting() -> dict[str, int]:
    """Queue do_starting work tasks for STARTING checks.

    Only queues if check doesn't already have a pending task.

    Returns:
        Dict with count of queued tasks.
    """
    logger = logging.getLogger(__name__)

    queued = 0

    starting_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.STARTING,
    ).exclude(pending_task__isnull=False)

    logger.info(
        "Found %d STARTING checks without pending task",
        starting_checks.count(),
    )

    for check in starting_checks:
        result = do_starting.delay(check.id)
        try:
            ManufacturabilityCheckTask.objects.create(
                manufacturability_check=check,
                task_id=result.id,
                task_name="do_starting",
            )
        except IntegrityError:
            # Task already created by concurrent beat cycle - skip
            logger.debug("Task already exists for check %s, skipping", check.id)
            continue
        logger.info("Queued do_starting for check %s (task: %s)", check.id, result.id)
        queued += 1

    return {"queued": queued}


@checks_task(queue="default")
def checks_running() -> dict[str, int]:
    """Queue do_running work tasks for RUNNING checks.

    Only queues if check doesn't already have a pending task.

    Returns:
        Dict with count of queued tasks.
    """
    logger = logging.getLogger(__name__)

    queued = 0

    running_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.RUNNING,
    ).exclude(pending_task__isnull=False)

    logger.info(
        "Found %d RUNNING checks without pending task",
        running_checks.count(),
    )

    for check in running_checks:
        result = do_running.delay(check.id)
        try:
            ManufacturabilityCheckTask.objects.create(
                manufacturability_check=check,
                task_id=result.id,
                task_name="do_running",
            )
        except IntegrityError:
            # Task already created by concurrent beat cycle - skip
            logger.debug("Task already exists for check %s, skipping", check.id)
            continue
        logger.info("Queued do_running for check %s (task: %s)", check.id, result.id)
        queued += 1

    return {"queued": queued}


@checks_task(queue="default")
def checks_analyzing() -> dict[str, int]:
    """Queue do_analyzing work tasks for ANALYZING checks.

    Only queues if check doesn't already have a pending task.

    Returns:
        Dict with count of queued tasks.
    """
    logger = logging.getLogger(__name__)

    queued = 0

    analyzing_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.ANALYZING,
    ).exclude(pending_task__isnull=False)

    logger.info(
        "Found %d ANALYZING checks without pending task",
        analyzing_checks.count(),
    )

    for check in analyzing_checks:
        result = do_analyzing.delay(check.id)
        try:
            ManufacturabilityCheckTask.objects.create(
                manufacturability_check=check,
                task_id=result.id,
                task_name="do_analyzing",
            )
        except IntegrityError:
            # Task already created by concurrent beat cycle - skip
            logger.debug("Task already exists for check %s, skipping", check.id)
            continue
        logger.info("Queued do_analyzing for check %s (task: %s)", check.id, result.id)
        queued += 1

    return {"queued": queued}


@checks_task(queue="default")
def checks_retry() -> dict:
    """Create retry checks for ERROR checks that haven't been retried yet.

    Only processes ERROR checks that don't have any retry children (leaf nodes).
    This prevents double-processing when multiple checks in a retry chain fail.

    Returns:
        dict with 'retried' and 'exhausted' counts
    """
    logger = logging.getLogger(__name__)

    retried = 0
    exhausted = 0

    # Only process ERROR checks that haven't been retried yet
    # (leaf nodes in the retry tree)
    error_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.ERROR,
    ).exclude(
        # Exclude checks that already have retries
        id__in=ManufacturabilityCheck.objects.filter(
            parent_check__isnull=False
        ).values_list("parent_check_id", flat=True),
    )
    error_count = error_checks.count()
    logger.info("Found %d checks in ERROR state (without retries)", error_count)

    for check in error_checks:
        try:
            original = check.parent_check or check
            retry_count = original.retry_checks.count()
            new_check = create_retry_check(check)
            logger.info(
                "Created retry check %s for %s (project: %s, attempt %d)",
                new_check.id,
                check.id,
                check.project.name,
                retry_count + 1,
            )
            retried += 1
        except MaxRetriesExceededError:
            original = check.parent_check or check
            retry_count = original.retry_checks.count()
            logger.info(
                "Check %s exhausted retries (%d)",
                check.id,
                retry_count,
            )
            exhausted += 1

    return {"retried": retried, "exhausted": exhausted}


@checks_task(queue="default")
def checks_create() -> dict:
    """Create ManufacturabilityChecks for verified downloads that need them.

    Returns:
        dict with 'created' count
    """
    logger = logging.getLogger(__name__)

    created = 0

    # Find active, verified files without a check
    files_needing_checks = ProjectFile.objects.filter(
        is_active=True,
        hash_verified=True,
    ).exclude(
        manufacturability_checks__isnull=False,
    )

    files_count = files_needing_checks.count()
    logger.info("Found %d verified files needing checks", files_count)

    for project_file in files_needing_checks:
        check = ManufacturabilityCheck.objects.create(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        logger.info(
            "Created check %s for project %s, file %s",
            check.id,
            project_file.project.name,
            project_file.original_filename,
        )
        created += 1

    return {"created": created}


@checks_task(queue="default")
def checks_cancelling() -> dict[str, int]:
    """Transition CANCELLING checks to CANCELLED.

    Unlike other status handlers, this doesn't queue work tasks - it directly
    marks checks as cancelled since there's no async work to do. Container
    cleanup is handled separately by checks_cleanup_orphaned_docker.

    Returns:
        Dict with count of cancelled checks.
    """
    logger = logging.getLogger(__name__)

    cancelled = 0

    cancelling_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.CANCELLING,
    )

    for check in cancelling_checks:
        logger.info("[checks_cancelling] Marking check %s as cancelled", check.id)
        check.mark_cancelled()
        cancelled += 1

    return {"cancelled": cancelled}


# Work tasks (do_*) - Placeholder stubs for polling architecture
# These will be implemented in later phases


@queued_check_task(expected_status="DISPATCHING")
def do_dispatching(check: ManufacturabilityCheck) -> dict[str, str]:
    """Pull Docker image for a DISPATCHING check.

    Transitions to STARTING on success.

    Args:
        check: ManufacturabilityCheck in DISPATCHING status (validated by decorator).

    Returns:
        Dict with result status.

    Raises:
        TaskExecutionError: If server lookup fails (handled by decorator).
        docker.errors.DockerException: If Docker operations fail (handled by decorator).
    """
    logger = logging.getLogger(__name__)

    logger.info(
        "[do_dispatching] Starting for check %s (server=%s, project=%s, file=%s)",
        check.id,
        check.docker_server_id,
        check.project.name,
        check.project_file.original_filename,
    )

    logger.info(
        "[do_dispatching] Connecting to Docker server %s...",
        check.docker_server_id,
    )
    client = _get_docker_client_for_server(check.docker_server_id, logger)
    logger.info("[do_dispatching] Connected to Docker server")

    image_name = settings.PRECHECK_DOCKER_IMAGE
    logger.info(
        "[do_dispatching] Pulling Docker image %s (this may take a while)...",
        image_name,
    )
    image = client.images.pull(image_name)
    logger.info(
        "[do_dispatching] Successfully pulled image %s (id=%s)",
        image_name,
        image.id[:19] if image.id else "unknown",
    )

    # Extract digest from pulled image
    digests = image.attrs.get("RepoDigests", [])
    digest = digests[0].split("@")[1] if digests else "unknown"
    # Truncate digest for logging (SHA256 digests are 64 chars)
    preview_len = 32
    if len(digest) > preview_len:
        digest_preview = digest[:preview_len] + "..."
    else:
        digest_preview = digest
    logger.info("[do_dispatching] Image digest: %s", digest_preview)

    logger.info("[do_dispatching] Transitioning check %s to STARTING", check.id)
    check.mark_starting(
        docker_image=image_name,
        docker_image_digest=digest,
    )
    logger.info(
        "[do_dispatching] Check %s successfully transitioned to STARTING", check.id
    )

    return {"status": "success", "image": image_name, "digest": digest}


# =============================================================================
# Helper Functions for do_starting
# =============================================================================


def _get_docker_client_for_server(
    server_id: str | None, logger: logging.Logger
) -> docker.DockerClient:
    """Get Docker client for a server, raising TaskExecutionError on failure."""
    if not server_id:
        msg = "No server ID configured"
        logger.error(msg)
        raise TaskExecutionError(reason="no_server_id", message=msg)

    server = get_server_config(server_id)
    if not server:
        msg = f"Unknown server: {server_id}"
        logger.error(msg)
        raise TaskExecutionError(reason="unknown_server", message=msg)

    try:
        return get_docker_client(server)
    except docker.errors.DockerException as e:
        msg = f"Failed to connect to Docker server: {e}"
        logger.exception(msg)
        raise TaskExecutionError(reason=str(e), message=msg) from e


def _get_project_file_path(
    check: ManufacturabilityCheck, logger: logging.Logger
) -> Path:
    """Get validated project file path, raising TaskExecutionError on failure."""
    project_file = check.project_file
    if not project_file.file:
        msg = "Project file not downloaded yet"
        logger.error(msg)
        raise TaskExecutionError(reason="file_not_ready", message=msg)

    gds_path = Path(project_file.file.path)
    if not gds_path.exists():
        msg = f"File not found at {gds_path}"
        logger.error(msg)
        raise TaskExecutionError(reason="file_not_found", message=msg)

    return gds_path


def _wait_for_container_running(
    container: "docker.models.containers.Container",
    logger: logging.Logger,
    *,
    max_wait: int = 10,
) -> None:
    """Wait for container to reach running state.

    Raises TaskExecutionError on failure.
    """
    for _ in range(max_wait):
        container.reload()
        if container.status == "running":
            return
        if container.status == "exited":
            msg = "Container exited immediately after start"
            logger.error(msg)
            raise TaskExecutionError(reason="container_exited_immediately", message=msg)
        time.sleep(1)

    # Final status check
    container.reload()
    if container.status != "running":
        msg = f"Container failed to start: status={container.status}"
        logger.error(msg)
        raise TaskExecutionError(reason="failed_to_start", message=msg)


@queued_check_task(expected_status="STARTING")
def do_starting(check: ManufacturabilityCheck) -> dict[str, Any]:
    """Create and start Docker container for a STARTING check.

    Creates a Docker container with appropriate labels, uploads the GDS file
    via put_archive (for remote Docker support), starts the container, and
    waits briefly for it to reach running state.

    Args:
        check: ManufacturabilityCheck in STARTING status (validated by decorator).

    Returns:
        Dict with status and container info.

    Raises:
        TaskExecutionError: If server/file validation fails (handled by decorator).
        docker.errors.DockerException: If Docker operations fail (handled by decorator).
    """
    logger = logging.getLogger(__name__)

    logger.info(
        "[do_starting] Starting for check %s (server=%s, image=%s)",
        check.id,
        check.docker_server_id,
        check.docker_image,
    )

    logger.info(
        "[do_starting] Connecting to Docker server %s...", check.docker_server_id
    )
    client = _get_docker_client_for_server(check.docker_server_id, logger)
    logger.info("[do_starting] Connected to Docker server")

    logger.info("[do_starting] Validating project file path...")
    gds_path = _get_project_file_path(check, logger)
    file_size = gds_path.stat().st_size
    logger.info(
        "[do_starting] Project file validated: %s (%d bytes)",
        gds_path.name,
        file_size,
    )

    # Get top cell name for precheck command
    top_cell = check.project_file.top_cell or "unknown"
    logger.info("[do_starting] Top cell: %s", top_cell)

    # Get slot size and full_id from project (required for precheck)
    slot_size = check.project.slot_size
    full_id = check.project.full_id
    if not full_id:
        msg = (
            "Cannot run manufacturability check: "
            "project must be assigned to shuttle with project ID"
        )
        raise ValueError(msg)
    logger.info("[do_starting] Slot size: %s, Full ID: %s", slot_size, full_id)

    # Build precheck command with slot size and project ID
    # The container has ENTRYPOINT ["dev-shell"] and WORKDIR /workspace
    # precheck.py is at /workspace/precheck.py
    command = [
        "python3",
        "precheck.py",
        "--input",
        "/input/design.gds",
        "--output",
        "/output/design.gds",
        "--top",
        top_cell,
        "--slot",
        slot_size,
        "--id",
        full_id,
    ]
    command_str = " ".join(command)
    logger.info("[do_starting] Container command: %s", command_str)

    # Create container WITHOUT volumes (for remote Docker support)
    logger.info(
        "[do_starting] Creating container from image %s (mem_limit=24g)...",
        check.docker_image,
    )
    # Extract site hostname for container labeling (prevents cross-environment cleanup)
    site_host = urlparse(settings.SITE_URL).netloc if settings.SITE_URL else "unknown"
    container = client.containers.create(
        check.docker_image,
        command=command,
        working_dir="/workspace",
        labels={
            "wafer.space.service": "manufacturability-check",
            "wafer.space.check_id": str(check.id),
            "wafer.space.project_id": str(check.project.id),
            "wafer.space.site": site_host,
        },
        mem_limit="24g",
        network_disabled=True,
        environment={
            "COLUMNS": "200",  # Wide terminal for better log output
            "TERM": "xterm-256color",
        },
    )
    logger.info(
        "[do_starting] Container created: id=%s (check=%s, server=%s)",
        container.id[:12],
        check.id,
        check.docker_server_id,
    )

    # Upload GDS file to container via put_archive
    # Note: put_archive requires the target directory to exist, so we upload to /
    # with the path structure in the arcname to create /input/design.gds
    logger.info(
        "[do_starting] Creating tar archive of GDS file (%d bytes)...",
        file_size,
    )
    tar_stream = create_tar_archive(gds_path, arcname="input/design.gds")
    tar_size = tar_stream.seek(0, 2)  # Get size by seeking to end
    tar_stream.seek(0)  # Reset to beginning
    logger.info(
        "[do_starting] Uploading tar archive to container %s (%d bytes)...",
        container.id[:12],
        tar_size,
    )
    container.put_archive("/", tar_stream)
    logger.info(
        "[do_starting] Successfully uploaded GDS to /input/design.gds in container %s",
        container.id[:12],
    )

    # Create /output directory for precheck to write output GDS
    logger.info(
        "[do_starting] Creating /output directory in container %s...",
        container.id[:12],
    )
    output_dir_tar = create_directory_tar("output")
    container.put_archive("/", output_dir_tar)
    logger.info(
        "[do_starting] Created /output directory in container %s",
        container.id[:12],
    )

    # Start the container and wait for it to be running
    logger.info("[do_starting] Starting container %s...", container.id[:12])
    container.start()
    logger.info(
        "[do_starting] Container %s start command issued, waiting for running state...",
        container.id[:12],
    )
    _wait_for_container_running(container, logger)
    logger.info("[do_starting] Container %s is now running", container.id[:12])

    # Transition to RUNNING
    logger.info("[do_starting] Transitioning check %s to RUNNING...", check.id)
    check.mark_running(
        docker_container_id=container.id,
        docker_command=command_str,
    )
    logger.info(
        "[do_starting] Check %s successfully transitioned to RUNNING (container=%s)",
        check.id,
        container.id[:12],
    )

    return {
        "status": "success",
        "container_id": container.id,
        "command": command_str,
    }


# =============================================================================
# Helper Functions for do_running
# =============================================================================


def _get_container(
    client: docker.DockerClient,
    container_id: str,
    logger: logging.Logger,
) -> "docker.models.containers.Container":
    """Get container by ID, raising TaskExecutionError on failure."""
    try:
        return client.containers.get(container_id)
    except docker.errors.NotFound as e:
        msg = f"Container {container_id} not found"
        logger.exception(msg)
        raise TaskExecutionError(reason="container_not_found", message=msg) from e
    except docker.errors.DockerException as e:
        msg = f"Failed to get container: {e}"
        logger.exception(msg)
        raise TaskExecutionError(reason=str(e), message=msg) from e


def _fetch_and_process_logs(
    container: "docker.models.containers.Container",
    check: ManufacturabilityCheck,
    logger: logging.Logger,
) -> tuple[float | None, str]:
    """Fetch logs incrementally and append to check.

    Returns:
        Tuple of (latest_timestamp, raw_logs).
    """
    logs_kwargs: dict[str, Any] = {"timestamps": True}
    if check.logs_downloaded_until:
        logs_kwargs["since"] = check.logs_downloaded_until

    raw_logs = container.logs(**logs_kwargs).decode("utf-8", errors="replace")

    latest_timestamp = None
    if raw_logs:
        for line in raw_logs.split("\n"):
            timestamp = parse_docker_timestamp_float(line)
            if timestamp:
                latest_timestamp = timestamp

        clean_logs = strip_docker_timestamps(raw_logs)
        if clean_logs.strip():
            check.append_to_processing_logs(clean_logs)
            logger.info(
                "Downloaded %d bytes of logs for check %s",
                len(clean_logs),
                check.id,
            )

    return latest_timestamp, raw_logs


def _handle_container_exited(
    container: "docker.models.containers.Container",
    check: ManufacturabilityCheck,
    logger: logging.Logger,
) -> dict[str, Any]:
    """Handle exited container: transition to ANALYZING and return result."""
    exit_code = container.attrs.get("State", {}).get("ExitCode", -1)
    logger.info(
        "Container %s exited with code %d",
        container.id[:12],
        exit_code,
    )
    check.mark_analyzing(docker_exit_code=exit_code)
    return {"status": "container_exited", "exit_code": exit_code}


def _handle_container_still_running(
    container: "docker.models.containers.Container",
    check: ManufacturabilityCheck,
    latest_timestamp: float | None,
    raw_logs: str,
    logger: logging.Logger,
) -> dict[str, Any]:
    """Handle still-running container: update timestamp and return result."""
    if latest_timestamp:
        check.logs_downloaded_until = latest_timestamp
        check.save(update_fields=["logs_downloaded_until"])

    logger.info(
        "Container %s still running for check %s",
        container.id[:12],
        check.id,
    )

    return {
        "status": "still_running",
        "container_status": container.status,
        "logs_bytes": len(raw_logs) if raw_logs else 0,
    }


def _record_checkpoint(
    check: ManufacturabilityCheck,
    container: "docker.models.containers.Container",
    logger: logging.Logger,
) -> ManufacturabilityCheckpoint | None:
    """Record a checkpoint with container stats.

    Fetches Docker container stats and creates a ManufacturabilityCheckpoint
    record with CPU, memory, I/O, and network usage data.

    Args:
        check: The manufacturability check to record checkpoint for.
        container: Docker container to get stats from.
        logger: Logger instance for messages.

    Returns:
        The created checkpoint, or None if stats unavailable.
    """
    try:
        stats = container.stats(stream=False)
    except docker.errors.DockerException as e:
        logger.warning("Failed to get container stats: %s", e)
        return None

    # Get checkpoint number
    checkpoint_count = check.checkpoints.count()

    # Calculate elapsed time from container start
    if check.container_started_at:
        elapsed = (timezone.now() - check.container_started_at).total_seconds()
    else:
        elapsed = 0.0

    # Extract stats from Docker response
    cpu_stats = stats.get("cpu_stats", {})
    precpu_stats = stats.get("precpu_stats", {})
    memory_stats = stats.get("memory_stats", {})
    blkio_stats = stats.get("blkio_stats", {})
    networks = stats.get("networks", {})

    # Calculate CPU percent (requires comparing current to previous)
    cpu_delta = cpu_stats.get("cpu_usage", {}).get("total_usage", 0) - precpu_stats.get(
        "cpu_usage", {}
    ).get("total_usage", 0)
    system_delta = cpu_stats.get("system_cpu_usage", 0) - precpu_stats.get(
        "system_cpu_usage", 0
    )
    online_cpus = cpu_stats.get("online_cpus", 1)
    cpu_percent = None
    if system_delta > 0 and cpu_delta > 0:
        cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0

    # Calculate memory percent
    memory_usage = memory_stats.get("usage")
    memory_limit = memory_stats.get("limit")
    memory_percent = None
    if memory_limit and memory_limit > 0 and memory_usage is not None:
        memory_percent = (memory_usage / memory_limit) * 100.0

    # Sum network stats across all interfaces
    network_rx = sum(n.get("rx_bytes", 0) for n in networks.values())
    network_tx = sum(n.get("tx_bytes", 0) for n in networks.values())

    # Sum block I/O
    io_stats = blkio_stats.get("io_service_bytes_recursive", []) or []
    block_read = sum(s.get("value", 0) for s in io_stats if s.get("op") == "read")
    block_write = sum(s.get("value", 0) for s in io_stats if s.get("op") == "write")

    checkpoint = ManufacturabilityCheckpoint.objects.create(
        manufacturability_check=check,
        checkpoint_number=checkpoint_count,
        elapsed_seconds=elapsed,
        cpu_percent=cpu_percent,
        cpu_total_usage=cpu_stats.get("cpu_usage", {}).get("total_usage"),
        cpu_system_usage=cpu_stats.get("system_cpu_usage"),
        cpu_online_cpus=online_cpus,
        memory_usage_bytes=memory_usage,
        memory_limit_bytes=memory_limit,
        memory_percent=memory_percent,
        memory_cache_bytes=memory_stats.get("stats", {}).get("cache"),
        block_read_bytes=block_read,
        block_write_bytes=block_write,
        network_rx_bytes=network_rx,
        network_tx_bytes=network_tx,
        container_state=container.status,
        raw_stats_json=stats,
    )

    logger.debug(
        "Recorded checkpoint %d for check %s (CPU: %.1f%%, Memory: %.1f%%)",
        checkpoint_count,
        check.id,
        cpu_percent or 0,
        memory_percent or 0,
    )

    return checkpoint


@queued_check_task(expected_status="RUNNING")
def do_running(check: ManufacturabilityCheck) -> dict[str, Any]:
    """Monitor running container and download logs incrementally.

    Checks container status, downloads new logs since last fetch,
    records a checkpoint with container stats, and transitions to
    ANALYZING if container has exited.

    Args:
        check: ManufacturabilityCheck in RUNNING status (validated by decorator).

    Returns:
        Dict with status and log info.

    Raises:
        TaskExecutionError: If server/container lookup fails (handled by decorator).
        docker.errors.DockerException: If Docker operations fail (handled by decorator).
    """
    logger = logging.getLogger(__name__)

    logger.info(
        "[do_running] Polling check %s (container=%s, checkpoint_count=%d)",
        check.id,
        check.docker_container_id[:12] if check.docker_container_id else "none",
        check.checkpoints.count(),
    )

    client = _get_docker_client_for_server(check.docker_server_id, logger)
    container = _get_container(client, check.docker_container_id, logger)

    # Record checkpoint with container stats
    logger.debug("[do_running] Recording checkpoint...")
    checkpoint = _record_checkpoint(check, container, logger)
    if checkpoint:
        logger.info(
            "[do_running] Checkpoint %d recorded (CPU: %.1f%%, Memory: %.1f%%)",
            checkpoint.checkpoint_number,
            checkpoint.cpu_percent or 0,
            checkpoint.memory_percent or 0,
        )

    # Fetch and process logs
    logger.debug("[do_running] Fetching logs...")
    latest_timestamp, raw_logs = _fetch_and_process_logs(container, check, logger)

    # Check container status
    container.reload()

    if container.status == "exited":
        logger.info(
            "[do_running] Container %s has exited, transitioning to ANALYZING",
            container.id[:12],
        )
        return _handle_container_exited(container, check, logger)

    result = _handle_container_still_running(
        container, check, latest_timestamp, raw_logs, logger
    )

    # Include checkpoint info in result if recorded
    if checkpoint:
        result["checkpoint_number"] = checkpoint.checkpoint_number

    logger.debug(
        "[do_running] Check %s still running (logs_bytes=%d)",
        check.id,
        result.get("logs_bytes", 0),
    )

    return result


# =============================================================================
# Helper Functions for do_analyzing
# =============================================================================


def _get_temp_dir(check: ManufacturabilityCheck) -> Path:
    """Get temporary directory for check outputs (in project dir, not /tmp).

    Creates a temp directory next to the project file to avoid permission
    issues with /tmp and to keep related files together.

    Args:
        check: The manufacturability check.

    Returns:
        Path to temp directory (created if needed).
    """
    project_dir = Path(check.project_file.file.path).parent
    temp_dir = project_dir / ".tmp" / f"check_{check.id}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def _cleanup_temp_dir(check: ManufacturabilityCheck) -> None:
    """Remove temporary directory for check.

    Silently ignores if directory doesn't exist.

    Args:
        check: The manufacturability check.
    """
    project_dir = Path(check.project_file.file.path).parent
    temp_dir = project_dir / ".tmp" / f"check_{check.id}"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)


def _save_log_file(check: ManufacturabilityCheck, logger: logging.Logger) -> None:
    """Save processing logs to log_file field with checksum.

    Creates a log file from check.processing_logs and saves it to the
    log_file FileField with SHA256 checksum.

    Args:
        check: The manufacturability check with logs to save.
        logger: Logger for messages.
    """
    if not check.processing_logs:
        logger.info("No processing logs to save for check %s", check.id)
        return

    content = check.processing_logs.encode("utf-8")

    # Calculate checksum
    hasher = MultiHasher(algorithms=["sha256"])
    hasher.update(content)

    # Save to Django FileField
    filename = f"check_{check.id}.log"
    check.log_file.save(filename, ContentFile(content), save=False)
    check.log_file_sha256 = hasher.hexdigest("sha256")
    check.save(update_fields=["log_file", "log_file_sha256"])

    logger.info(
        "Saved log file for check %s (%d bytes, sha256=%s...)",
        check.id,
        len(content),
        check.log_file_sha256[:16],
    )


def _save_runs_archive(
    check: ManufacturabilityCheck,
    container: "docker.models.containers.Container",
    logger: logging.Logger,
) -> None:
    """Extract and save /workspace/runs/ directory as compressed tarball.

    The runs directory contains precheck tool output files and artifacts.
    Extracts it from the container, compresses with gzip, and saves to
    the runs_archive FileField.

    Args:
        check: The manufacturability check.
        container: Docker container to extract from.
        logger: Logger for messages.
    """
    temp_dir = _get_temp_dir(check)
    temp_path = temp_dir / "runs.tar.gz"

    result = stream_archive_to_file(
        container, "/workspace/runs", temp_path, logger, compress=True
    )
    if not result:
        logger.info("No runs directory found in container for check %s", check.id)
        return

    bytes_written, checksums = result

    # Save to Django FileField
    with temp_path.open("rb") as f:
        filename = f"check_{check.id}_runs.tar.gz"
        check.runs_archive.save(filename, File(f), save=False)
    check.runs_archive_sha256 = checksums["sha256"]
    check.save(update_fields=["runs_archive", "runs_archive_sha256"])

    # Clean up temp file
    temp_path.unlink()

    logger.info(
        "Saved runs archive for check %s (%d bytes, sha256=%s...)",
        check.id,
        bytes_written,
        check.runs_archive_sha256[:16],
    )


def _save_output_gds(
    check: ManufacturabilityCheck,
    container: "docker.models.containers.Container",
    logger: logging.Logger,
) -> None:
    """Extract and save output GDS from /output/design.gds.

    The output GDS is the modified design file produced by precheck,
    which may include added QR codes or other modifications.

    Args:
        check: The manufacturability check.
        container: Docker container to extract from.
        logger: Logger for messages.
    """
    temp_dir = _get_temp_dir(check)
    tar_path = temp_dir / "output_gds.tar"

    # Extract the tar archive containing the GDS file
    result = stream_archive_to_file(
        container, "/output/design.gds", tar_path, logger, compress=False
    )
    if not result:
        logger.info("No output GDS found in container for check %s", check.id)
        return

    # The archive contains the file - need to extract it
    gds_path = temp_dir / "design.gds"

    try:
        with tarfile.open(tar_path, "r") as tar:
            for member in tar.getmembers():
                if member.name.endswith(".gds"):
                    # Extract the GDS file
                    extracted_file = tar.extractfile(member)
                    if extracted_file:
                        gds_path.write_bytes(extracted_file.read())
                    break
    except tarfile.TarError as e:
        logger.warning("Failed to extract GDS from tar for check %s: %s", check.id, e)
        tar_path.unlink(missing_ok=True)
        return

    if not gds_path.exists():
        logger.warning(
            "No GDS file found in /output/design.gds archive for check %s",
            check.id,
        )
        tar_path.unlink(missing_ok=True)
        return

    # Calculate checksum of actual GDS file
    hasher = MultiHasher.from_file(gds_path, algorithms=["sha256"])

    # Save to Django FileField
    with gds_path.open("rb") as f:
        filename = f"check_{check.id}_output.gds"
        check.output_gds.save(filename, File(f), save=False)
    check.output_gds_sha256 = hasher.hexdigest("sha256")
    check.save(update_fields=["output_gds", "output_gds_sha256"])

    # Clean up temp files
    tar_path.unlink(missing_ok=True)
    gds_path.unlink(missing_ok=True)

    logger.info(
        "Saved output GDS for check %s (%d bytes, sha256=%s...)",
        check.id,
        hasher.bytes_processed,
        check.output_gds_sha256[:16],
    )


def _save_docker_layer_export(
    check: ManufacturabilityCheck,
    container: "docker.models.containers.Container",
    logger: logging.Logger,
) -> None:
    """Export container filesystem as compressed tarball for debugging.

    Uses container.export() to get the full filesystem, then compresses it.
    This is useful for debugging container issues.

    Args:
        check: The manufacturability check.
        container: Docker container to export.
        logger: Logger for messages.
    """
    temp_dir = _get_temp_dir(check)
    temp_path = temp_dir / "layer.tar.gz"

    result = stream_container_diff_to_file(container, temp_path, logger)
    if not result:
        logger.info("No container export for check %s", check.id)
        return

    bytes_written, checksums = result

    # Save to Django FileField
    with temp_path.open("rb") as f:
        filename = f"check_{check.id}_layer.tar.gz"
        check.docker_layer_export.save(filename, File(f), save=False)
    check.docker_layer_sha256 = checksums["sha256"]
    check.save(update_fields=["docker_layer_export", "docker_layer_sha256"])

    # Clean up temp file
    temp_path.unlink()

    logger.info(
        "Saved docker layer export for check %s (%d bytes, sha256=%s...)",
        check.id,
        bytes_written,
        check.docker_layer_sha256[:16],
    )


def _finalize_analyzing(
    check: ManufacturabilityCheck,
    failure_type: str,
    error_messages: list[str],
    warning_messages: list[str],
    tool_versions: dict[str, str],
) -> dict[str, Any]:
    """Finalize analysis by transitioning check to appropriate state.

    Args:
        check: The manufacturability check.
        failure_type: 'success', 'design', or 'system'.
        error_messages: List of error messages from parsing.
        warning_messages: List of warning messages from parsing.
        tool_versions: Dict of tool versions detected.

    Returns:
        Result dict with status and details.
    """
    logger = logging.getLogger(__name__)
    outputs_saved = {
        "log_file": bool(check.log_file),
        "runs_archive": bool(check.runs_archive),
        "output_gds": bool(check.output_gds),
        "docker_layer_export": bool(check.docker_layer_export),
    }

    if failure_type == "system":
        # System error - precheck didn't complete properly, can be retried
        if error_messages:
            error_msg = "; ".join(error_messages)
        else:
            error_msg = "Precheck incomplete"
        logger.info(
            "[do_analyzing] System error detected, transitioning check %s to ERROR...",
            check.id,
        )
        check.mark_error(error_message=error_msg)
        logger.info(
            "[do_analyzing] Check %s transitioned to ERROR (outputs=%s)",
            check.id,
            outputs_saved,
        )
        return {
            "status": "error",
            "failure_type": "system",
            "error_count": len(error_messages),
            "outputs_saved": outputs_saved,
        }

    # Success or design error - transition to FINISHED
    is_manufacturable = failure_type == "success"
    logger.info(
        "[do_analyzing] Transitioning check %s to FINISHED (manufacturable=%s)...",
        check.id,
        is_manufacturable,
    )
    check.mark_finished(
        is_manufacturable=is_manufacturable,
        errors=error_messages,
        warnings=warning_messages,
        tool_versions=tool_versions,
    )
    logger.info(
        "[do_analyzing] Check %s transitioned to FINISHED "
        "(manufacturable=%s, outputs=%s)",
        check.id,
        is_manufacturable,
        outputs_saved,
    )
    return {
        "status": "success",
        "is_manufacturable": is_manufacturable,
        "error_count": len(error_messages),
        "warning_count": len(warning_messages),
        "outputs_saved": outputs_saved,
    }


@queued_check_task(expected_status="ANALYZING")
def do_analyzing(check: ManufacturabilityCheck) -> dict[str, Any]:
    """Analyze container logs, extract outputs, and determine results.

    This function:
    1. Saves processing logs to log_file field
    2. Extracts /workspace/runs/ directory as compressed tarball
    3. Extracts output GDS from /output/design.gds if it exists
    4. Exports container filesystem changes for debugging
    5. Parses logs to determine manufacturability
    6. Transitions to FINISHED

    NOTE: Container cleanup is handled by checks_cleanup_orphaned_docker task,
    NOT here. The container remains after this function completes.

    Args:
        check: ManufacturabilityCheck in ANALYZING status (validated by decorator).

    Returns:
        Dict with analysis results and outputs saved.
    """
    logger = logging.getLogger(__name__)

    logger.info(
        "[do_analyzing] Starting for check %s (server=%s, container=%s, exit_code=%s)",
        check.id,
        check.docker_server_id,
        check.docker_container_id[:12] if check.docker_container_id else "none",
        check.docker_exit_code,
    )

    # Get container for output extraction
    container = None
    if check.docker_container_id and check.docker_server_id:
        logger.info(
            "[do_analyzing] Connecting to Docker server %s to retrieve container...",
            check.docker_server_id,
        )
        try:
            client = _get_docker_client_for_server(check.docker_server_id, logger)
            container = _get_container(client, check.docker_container_id, logger)
            logger.info(
                "[do_analyzing] Successfully retrieved container %s (status=%s)",
                check.docker_container_id[:12],
                container.status,
            )
        except docker.errors.DockerException as e:
            logger.warning(
                "[do_analyzing] Could not get container for output extraction: %s",
                e,
            )
    else:
        logger.info(
            "[do_analyzing] No container info available "
            "(container_id=%s, server_id=%s)",
            check.docker_container_id,
            check.docker_server_id,
        )

    try:
        # 1. Save processing logs to log_file
        log_size = len(check.processing_logs) if check.processing_logs else 0
        logger.info("[do_analyzing] Step 1/5: Saving logs (%d bytes)...", log_size)
        _save_log_file(check, logger)

        # 2-4. Extract outputs from container if available
        if container is not None:
            logger.info("[do_analyzing] Steps 2-4: Extracting container outputs...")
            _save_runs_archive(check, container, logger)
            _save_output_gds(check, container, logger)
            logger.info("[do_analyzing] Skipping layer export (disabled)")
        else:
            logger.info("[do_analyzing] Steps 2-4: No container, skipping extraction")

    finally:
        _cleanup_temp_dir(check)

    # 5. Parse the logs (docker_exit_code set by mark_analyzing, can't be None)
    logs = check.processing_logs or ""
    assert check.docker_exit_code is not None, "mark_analyzing requires exit code"
    exit_code = check.docker_exit_code

    logger.info(
        "[do_analyzing] Step 5/5: Parsing logs (exit_code=%d, log_length=%d bytes)...",
        exit_code,
        len(logs),
    )

    parse_result = PrecheckLogParser.parse_logs(logs, exit_code)

    # Extract errors and warnings
    error_messages = [e["message"] for e in parse_result["errors"]]
    warning_messages = [w.get("message", str(w)) for w in parse_result["warnings"]]

    # Classify the failure type: 'success', 'design', or 'system'
    failure_type = classify_failure(logs, exit_code)

    # Extract tool versions from logs if available
    tool_versions: dict[str, str] = {}
    if "precheck" in logs.lower():
        tool_versions["precheck"] = "unknown"

    logger.info(
        "[do_analyzing] Log parsing complete: failure_type=%s, errors=%d, warnings=%d",
        failure_type,
        len(error_messages),
        len(warning_messages),
    )

    # Log first few errors for debugging (limit to avoid log spam)
    max_errors_to_log = 5
    if error_messages:
        for i, err in enumerate(error_messages[:max_errors_to_log], 1):
            logger.info("[do_analyzing] Error %d: %s", i, err[:200])
        if len(error_messages) > max_errors_to_log:
            remaining = len(error_messages) - max_errors_to_log
            logger.info("[do_analyzing] ... and %d more errors", remaining)

    # 6. Transition to appropriate state based on failure type
    return _finalize_analyzing(
        check=check,
        failure_type=failure_type,
        error_messages=error_messages,
        warning_messages=warning_messages,
        tool_versions=tool_versions,
    )


@checks_task(queue="default")
def checks_cleanup_stale_files() -> dict:
    """Cancel checks on project files that are no longer active.

    When a user uploads a new file to a project, the old file's is_active
    flag is set to False. Any in-progress checks on inactive files should
    be cancelled since they're no longer relevant.

    This task finds such checks and marks them as CANCELLING, which will
    then be processed by the checks_cancelling task.

    Returns:
        dict with 'cancelled' count of checks marked for cancellation
    """
    logger = logging.getLogger(__name__)
    cancelled = 0

    # Find checks in progress on inactive project files
    stale_checks = ManufacturabilityCheck.objects.filter(
        status__in=ManufacturabilityCheck.Status.in_progress(),
        project_file__is_active=False,
    )

    for check in stale_checks:
        try:
            logger.info(
                "Cancelling stale check %s on inactive file %s (project %s)",
                check.id,
                check.project_file.original_filename,
                check.project.name,
            )
            check.mark_cancelling(reason="Project file replaced with newer version")
            cancelled += 1
        except InvalidStateTransitionError:
            logger.exception(
                "Failed to mark check %s as cancelling",
                check.id,
            )

    return {"cancelled": cancelled}


def _cancel_superseded_checks() -> int:
    """Cancel in-progress checks that have been superseded by newer checks.

    Returns:
        Number of checks marked for cancellation.
    """
    logger = logging.getLogger(__name__)

    # Subquery: does a newer check exist for the same file?
    newer_exists = ManufacturabilityCheck.objects.filter(
        project_file=OuterRef("project_file"),
        created_at__gt=OuterRef("created_at"),
    )

    # Find all superseded in-progress checks
    superseded = ManufacturabilityCheck.objects.filter(
        status__in=ManufacturabilityCheck.Status.in_progress(),
    ).filter(Exists(newer_exists))

    cancelled = 0
    for check in superseded:
        try:
            check.mark_cancelling(reason="Superseded by newer check")
            logger.info(
                "Marked check %s as cancelling (superseded)",
                check.id,
            )
            cancelled += 1
        except Exception:
            logger.exception("Failed to cancel superseded check %s", check.id)

    return cancelled


@checks_task(queue="default")
def checks_cleanup() -> dict:
    """Cleanup task that performs all periodic cleanup operations.

    This task combines multiple cleanup operations:
    - Cancel checks superseded by newer checks
    - Cancel checks on inactive project files
    - Remove orphaned pending task records

    Returns:
        Dict with counts of cleanup operations performed.
    """
    # Cancel superseded checks
    superseded_cancelled = _cancel_superseded_checks()

    # Cancel checks on stale files
    stale_files_result = checks_cleanup_stale_files()
    stale_files_cancelled = stale_files_result.get("cancelled", 0)

    # Clean up orphaned pending tasks
    pending_tasks_result = checks_cleanup_stale_pending_tasks()
    pending_tasks_deleted = pending_tasks_result.get("deleted", 0)

    return {
        "superseded_cancelled": superseded_cancelled,
        "stale_files_cancelled": stale_files_cancelled,
        "pending_tasks_deleted": pending_tasks_deleted,
    }


@checks_task(queue="default")
def checks_cleanup_stale_pending_tasks() -> dict:
    """Remove orphaned ManufacturabilityCheckTask records that block check re-queuing.

    When a Celery task fails catastrophically (e.g., worker crash, OOM kill)
    before the finally block can delete the ManufacturabilityCheckTask record,
    the record remains and prevents the beat task from re-queuing the check.

    This task finds ManufacturabilityCheckTask records where the associated
    Celery task is no longer active (not in broker queue and not running),
    and deletes them, allowing the check to be re-queued.

    A task is considered orphaned if:
    - It's NOT in the broker queue (kombu_message), AND
    - It's either NOT in TaskResult, OR in TaskResult with a finished status
      (SUCCESS, FAILURE, REVOKED)

    Returns:
        dict with 'deleted' count of orphaned records removed
    """
    logger = logging.getLogger(__name__)
    deleted = 0
    still_active = 0

    # Check all pending tasks - use time filter to avoid checking very recent tasks
    # that might still be in transit between queue and worker
    min_age_threshold = timezone.now() - timedelta(seconds=30)

    pending_tasks = list(
        ManufacturabilityCheckTask.objects.filter(
            queued_at__lt=min_age_threshold,
        )
    )
    logger.info(
        "Pending tasks: %i",
        len(pending_tasks),
    )

    for task in pending_tasks:
        if is_check_task_actively_running(task.task_id):
            # Task is still active - leave it alone
            still_active += 1
            continue

        # Task is orphaned - remove the lock
        logger.info(
            "Removing orphaned pending task %s for check %s "
            "(queued at %s, task_name=%s, not in queue or results)",
            task.task_id,
            task.manufacturability_check_id,
            task.queued_at,
            task.task_name,
        )
        task.delete()
        deleted += 1

    return {"deleted": deleted, "still_active": still_active}
