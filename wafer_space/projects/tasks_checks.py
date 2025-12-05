"""
Background tasks for manufacturability checks.
"""

import logging
import time
from pathlib import Path
from typing import Any

import docker
import docker.errors
from celery import shared_task
from celery.utils.log import get_task_logger
from django.conf import settings

from .docker_utils import parse_docker_timestamp_float
from .docker_utils import queued_check_task
from .docker_utils import strip_docker_timestamps
from .exceptions import InvalidStateTransitionError
from .models import ManufacturabilityCheck
from .models import ManufacturabilityCheckTask
from .models import ProjectFile
from .precheck_parser import PrecheckLogParser

__all__ = [
    "checks_analyzing",
    "checks_cancelling",
    "checks_cleanup_orphaned_docker",
    "checks_cleanup_stale_files",
    "checks_create",
    "checks_dispatching",
    "checks_pending",
    "checks_retry",
    "checks_running",
    "checks_starting",
    "do_analyzing",
    "do_cancelling",
    "do_dispatching",
    "do_running",
    "do_starting",
]


def _stop_and_remove_container(container, logger) -> None:
    """Stop and remove a Docker container safely."""
    try:
        if container.status == "running":
            container.stop(timeout=10)
        container.remove(force=True)
    except docker.errors.DockerException:
        logger.exception("Failed to remove container %s", container.id)


def _get_server_config(server_id: str) -> dict | None:
    """Get server config by ID from DOCKER_SERVERS settings.

    Args:
        server_id: The server ID to look up.

    Returns:
        Server config dict if found, None otherwise.
    """
    return next(
        (s for s in settings.DOCKER_SERVERS if s["id"] == server_id),
        None,
    )


def _get_docker_client(server: dict) -> docker.DockerClient:
    """Create a Docker client for the given server config.

    Args:
        server: Server config dict with 'url' key.

    Returns:
        Docker client instance.

    Raises:
        docker.errors.DockerException: If connection fails.
    """
    return docker.DockerClient(base_url=str(server["url"]))


@shared_task(queue="docker-ephemeral")
def checks_cleanup_orphaned_docker() -> dict:
    """Remove Docker containers not linked to active checks (fallback cleanup).

    Starts from Docker (source of truth) and validates against database.
    Removes containers where the associated ManufacturabilityCheck is:
    - Missing (deleted)
    - FINISHED
    - ERROR
    - CANCELLED

    CANCELLING containers are handled by checks_cancelling task, not here.

    Returns:
        dict with 'containers_scanned' and 'removed' counts
    """
    logger = get_task_logger(__name__)
    logger.info("=" * 60)
    logger.info("CLEANING UP ORPHANED DOCKER CONTAINERS")
    logger.info("=" * 60)

    try:
        client = docker.from_env()
    except docker.errors.DockerException as exc:
        logger.exception("Failed to connect to Docker")
        return {
            "status": "error",
            "error": str(exc),
        }

    # Get all containers with our label
    containers = client.containers.list(
        all=True,
        filters={"label": "wafer.space.service=manufacturability-check"},
    )

    logger.info("  Found %d containers with service label", len(containers))

    removed = 0
    for container in containers:
        check_id = container.labels.get("wafer.space.check_id")

        # No check_id label = definitely orphaned
        if not check_id:
            logger.info(
                "  Container %s: no check_id label, removing",
                container.short_id,
            )
            _stop_and_remove_container(container, logger)
            removed += 1
            continue

        # Look up the check
        try:
            check = ManufacturabilityCheck.objects.get(id=check_id)
        except ManufacturabilityCheck.DoesNotExist:
            logger.info(
                "  Container %s: check %s not found, removing",
                container.short_id,
                check_id,
            )
            _stop_and_remove_container(container, logger)
            removed += 1
            continue

        # Check exists - is it in an active state?
        # CANCELLING containers are handled by checks_cancelling, not here
        # Use Status.active() + CANCELLING
        active_states = [
            *ManufacturabilityCheck.Status.active(),
            ManufacturabilityCheck.Status.CANCELLING,
        ]
        if check.status not in active_states:
            logger.info(
                "  Container %s: check %s in %s state, removing",
                container.short_id,
                check_id,
                check.status,
            )
            _stop_and_remove_container(container, logger)
            removed += 1
        else:
            logger.debug(
                "  Container %s: check %s in %s state, keeping",
                container.short_id,
                check_id,
                check.status,
            )

    logger.info("=" * 60)
    logger.info("CLEANUP COMPLETE")
    logger.info("  Scanned: %d", len(containers))
    logger.info("  Removed: %d", removed)
    logger.info("=" * 60)

    return {"containers_scanned": len(containers), "removed": removed}


@shared_task(queue="default")
def checks_pending() -> dict[str, int]:
    """Transition PENDING checks to DISPATCHING with server assignment.

    Respects per-server concurrent limits. Assigns to servers in priority order.

    Returns:
        Dict with count of dispatched checks.
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_pending] Starting pending check assignment")

    dispatched = 0

    # Sort servers by priority (lowest first)
    servers = sorted(settings.DOCKER_SERVERS, key=lambda s: s["priority"])

    for server in servers:
        server_id = str(server["id"])
        max_concurrent = int(server["max_concurrent"])

        # Count active checks on this server
        active_count = ManufacturabilityCheck.objects.filter(
            docker_server_id=server_id,
            status__in=ManufacturabilityCheck.Status.active(),
        ).count()

        available_slots = max_concurrent - active_count

        if available_slots > 0:
            logger.info(
                "[checks_pending] Server %s: %d/%d active, %d slots available",
                server_id,
                active_count,
                max_concurrent,
                available_slots,
            )

            pending_checks = ManufacturabilityCheck.objects.filter(
                status=ManufacturabilityCheck.Status.PENDING,
            ).order_by("created_at")[:available_slots]

            for check in pending_checks:
                check.mark_dispatching(server_id=server_id)
                logger.info(
                    "[checks_pending] Assigned check %s to server %s",
                    check.id,
                    server_id,
                )
                dispatched += 1

    logger.info("[checks_pending] Complete: dispatched=%d", dispatched)
    return {"dispatched": dispatched}


@shared_task(queue="default")
def checks_dispatching() -> dict[str, int]:
    """Queue do_dispatching work tasks for DISPATCHING checks.

    Only queues if check doesn't already have a pending task.

    Returns:
        Dict with count of queued tasks.
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_dispatching] Starting dispatching cycle")

    queued = 0

    dispatching_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.DISPATCHING,
    ).exclude(pending_task__isnull=False)

    logger.info(
        "[checks_dispatching] Found %d DISPATCHING checks without pending task",
        dispatching_checks.count(),
    )

    for check in dispatching_checks:
        result = do_dispatching.delay(check.id)
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id=result.id,
            task_name="do_dispatching",
        )
        logger.info(
            "[checks_dispatching] Queued do_dispatching for check %s (task: %s)",
            check.id,
            result.id,
        )
        queued += 1

    logger.info("[checks_dispatching] Complete: queued=%d", queued)
    return {"queued": queued}


@shared_task(queue="default")
def checks_starting() -> dict[str, int]:
    """Queue do_starting work tasks for STARTING checks.

    Only queues if check doesn't already have a pending task.

    Returns:
        Dict with count of queued tasks.
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_starting] Starting starting cycle")

    queued = 0

    starting_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.STARTING,
    ).exclude(pending_task__isnull=False)

    logger.info(
        "[checks_starting] Found %d STARTING checks without pending task",
        starting_checks.count(),
    )

    for check in starting_checks:
        result = do_starting.delay(check.id)
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id=result.id,
            task_name="do_starting",
        )
        logger.info(
            "[checks_starting] Queued do_starting for check %s (task: %s)",
            check.id,
            result.id,
        )
        queued += 1

    logger.info("[checks_starting] Complete: queued=%d", queued)
    return {"queued": queued}


@shared_task(queue="default")
def checks_running() -> dict[str, int]:
    """Queue do_running work tasks for RUNNING checks.

    Only queues if check doesn't already have a pending task.

    Returns:
        Dict with count of queued tasks.
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_running] Starting running cycle")

    queued = 0

    running_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.RUNNING,
    ).exclude(pending_task__isnull=False)

    logger.info(
        "[checks_running] Found %d RUNNING checks without pending task",
        running_checks.count(),
    )

    for check in running_checks:
        result = do_running.delay(check.id)
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id=result.id,
            task_name="do_running",
        )
        logger.info(
            "[checks_running] Queued do_running for check %s (task: %s)",
            check.id,
            result.id,
        )
        queued += 1

    logger.info("[checks_running] Complete: queued=%d", queued)
    return {"queued": queued}


@shared_task(queue="default")
def checks_analyzing() -> dict[str, int]:
    """Queue do_analyzing work tasks for ANALYZING checks.

    Only queues if check doesn't already have a pending task.

    Returns:
        Dict with count of queued tasks.
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_analyzing] Starting analyzing cycle")

    queued = 0

    analyzing_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.ANALYZING,
    ).exclude(pending_task__isnull=False)

    logger.info(
        "[checks_analyzing] Found %d ANALYZING checks without pending task",
        analyzing_checks.count(),
    )

    for check in analyzing_checks:
        result = do_analyzing.delay(check.id)
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id=result.id,
            task_name="do_analyzing",
        )
        logger.info(
            "[checks_analyzing] Queued do_analyzing for check %s (task: %s)",
            check.id,
            result.id,
        )
        queued += 1

    logger.info("[checks_analyzing] Complete: queued=%d", queued)
    return {"queued": queued}


@shared_task(queue="default")
def checks_retry() -> dict:
    """Move retryable ERROR checks back to PENDING state.

    Returns:
        dict with 'retried' and 'exhausted' counts
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_retry] Starting retry cycle")

    retried = 0
    exhausted = 0

    error_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.ERROR,
    )
    error_count = error_checks.count()
    logger.info("[checks_retry] Found %d checks in ERROR state", error_count)

    for check in error_checks:
        if check.can_retry():
            logger.info(
                "[checks_retry] Retrying check %s (project: %s, attempt %d/%d)",
                check.id,
                check.project.name,
                check.retry_count + 1,
                check.max_retries,
            )
            check.reset_for_retry(reason="Automatic retry after error")
            retried += 1
        else:
            logger.info(
                "[checks_retry] Check %s exhausted retries (%d/%d)",
                check.id,
                check.retry_count,
                check.max_retries,
            )
            exhausted += 1

    logger.info(
        "[checks_retry] Complete: retried=%d, exhausted=%d",
        retried,
        exhausted,
    )
    return {"retried": retried, "exhausted": exhausted}


@shared_task(queue="default")
def checks_create() -> dict:
    """Create ManufacturabilityChecks for verified downloads that need them.

    Returns:
        dict with 'created' count
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_create] Starting check creation cycle")

    created = 0

    # Find active, verified files without a check
    files_needing_checks = ProjectFile.objects.filter(
        is_active=True,
        hash_verified=True,
    ).exclude(
        manufacturability_check__isnull=False,
    )

    files_count = files_needing_checks.count()
    logger.info("[checks_create] Found %d verified files needing checks", files_count)

    for project_file in files_needing_checks:
        check = ManufacturabilityCheck.objects.create(
            project=project_file.project,
            project_file=project_file,
            status=ManufacturabilityCheck.Status.PENDING,
        )
        logger.info(
            "[checks_create] Created check %s for project %s, file %s",
            check.id,
            project_file.project.name,
            project_file.original_filename,
        )
        created += 1

    logger.info("[checks_create] Complete: created=%d", created)
    return {"created": created}


@shared_task(queue="default")
def checks_cancelling() -> dict[str, int]:
    """Queue do_cancelling work tasks for CANCELLING checks.

    Only queues if check doesn't already have a pending task.

    Returns:
        Dict with count of queued tasks.
    """
    logger = logging.getLogger(__name__)
    logger.info("[checks_cancelling] Starting cancelling cycle")

    queued = 0

    cancelling_checks = ManufacturabilityCheck.objects.filter(
        status=ManufacturabilityCheck.Status.CANCELLING,
    ).exclude(pending_task__isnull=False)

    logger.info(
        "[checks_cancelling] Found %d CANCELLING checks without pending task",
        cancelling_checks.count(),
    )

    for check in cancelling_checks:
        result = do_cancelling.delay(check.id)
        ManufacturabilityCheckTask.objects.create(
            manufacturability_check=check,
            task_id=result.id,
            task_name="do_cancelling",
        )
        logger.info(
            "[checks_cancelling] Queued do_cancelling for check %s (task: %s)",
            check.id,
            result.id,
        )
        queued += 1

    logger.info("[checks_cancelling] Complete: queued=%d", queued)
    return {"queued": queued}


# Work tasks (do_*) - Placeholder stubs for polling architecture
# These will be implemented in later phases


@queued_check_task()
def do_dispatching(check_id: int) -> dict[str, str]:
    """Pull Docker image for a DISPATCHING check.

    Transitions to STARTING on success.

    Args:
        check_id: ManufacturabilityCheck ID.

    Returns:
        Dict with result status.
    """
    check = ManufacturabilityCheck.objects.get(id=check_id)

    if check.status != ManufacturabilityCheck.Status.DISPATCHING:
        return {"status": "skipped", "reason": "status_changed"}

    server = _get_server_config(check.docker_server_id)
    if not server:
        error_msg = f"Unknown server: {check.docker_server_id}"
        check.mark_error(error_message=error_msg)
        return {"status": "error", "reason": "unknown_server"}

    client = _get_docker_client(server)

    try:
        image_name = settings.PRECHECK_DOCKER_IMAGE
        image = client.images.pull(image_name)

        # Extract digest from pulled image
        digests = image.attrs.get("RepoDigests", [])
        digest = digests[0].split("@")[1] if digests else "unknown"

        check.mark_starting(
            docker_image=image_name,
            docker_image_digest=digest,
        )
    except docker.errors.DockerException as e:
        error_msg = f"Docker pull failed: {e}"
        check.mark_error(error_message=error_msg)
        return {"status": "error", "reason": str(e)}
    else:
        return {"status": "success", "image": image_name, "digest": digest}


@queued_check_task()
def do_starting(check_id: int) -> dict[str, Any]:  # noqa: C901, PLR0911, PLR0915
    """Create and start Docker container for a STARTING check.

    Creates a Docker container with appropriate labels and volume mounts,
    starts it, and waits briefly for it to reach running state.

    Args:
        check_id: ManufacturabilityCheck ID.

    Returns:
        Dict with status and container info.
    """
    logger = logging.getLogger(__name__)
    check = ManufacturabilityCheck.objects.get(id=check_id)

    if check.status != ManufacturabilityCheck.Status.STARTING:
        logger.info(
            "Skipping do_starting for check %s - status changed to %s",
            check_id,
            check.status,
        )
        return {"status": "skipped", "reason": "status_changed"}

    server = _get_server_config(check.docker_server_id)
    if not server:
        error_msg = f"Unknown server: {check.docker_server_id}"
        logger.error(error_msg)
        check.mark_error(error_message=error_msg)
        return {"status": "error", "reason": "unknown_server"}

    try:
        client = _get_docker_client(server)
    except docker.errors.DockerException as e:
        error_msg = f"Failed to connect to Docker server: {e}"
        logger.exception(error_msg)
        check.mark_error(error_message=error_msg)
        return {"status": "error", "reason": str(e)}

    try:
        # Get the project file path
        project_file = check.project_file
        if not project_file.file:
            error_msg = "Project file not downloaded yet"
            logger.error(error_msg)
            check.mark_error(error_message=error_msg)
            return {"status": "error", "reason": "file_not_ready"}

        gds_path = Path(project_file.file.path)
        if not gds_path.exists():
            error_msg = f"File not found at {gds_path}"
            logger.error(error_msg)
            check.mark_error(error_message=error_msg)
            return {"status": "error", "reason": "file_not_found"}

        # Create container with labels and volume mount
        command = "precheck"
        container = client.containers.create(
            check.docker_image,
            command=command,
            labels={
                "wafer.space.service": "manufacturability-check",
                "wafer.space.check_id": str(check.id),
                "wafer.space.project_id": str(check.project.id),
            },
            volumes={
                str(gds_path): {
                    "bind": "/input/design.gds",
                    "mode": "ro",
                },
            },
            # Limit resources to prevent runaway containers
            mem_limit="4g",
            cpu_count=2,
        )

        logger.info(
            "Created container %s for check %s on server %s",
            container.id[:12],
            check_id,
            check.docker_server_id,
        )

        # Start the container
        container.start()
        logger.info("Started container %s", container.id[:12])

        # Wait briefly for container to be running
        # Give it a few seconds to start
        max_wait = 10
        for _ in range(max_wait):
            container.reload()
            if container.status == "running":
                break
            if container.status == "exited":
                # Container exited immediately - this is an error
                error_msg = "Container exited immediately after start"
                logger.error(error_msg)
                check.mark_error(error_message=error_msg)
                return {"status": "error", "reason": "container_exited_immediately"}
            time.sleep(1)

        # Final status check
        container.reload()
        if container.status != "running":
            error_msg = f"Container failed to start: status={container.status}"
            logger.error(error_msg)
            check.mark_error(error_message=error_msg)
            return {"status": "error", "reason": "failed_to_start"}

        # Transition to RUNNING
        check.mark_running(
            docker_container_id=container.id,
            docker_command=command,
        )

        logger.info(
            "Check %s transitioned to RUNNING with container %s",
            check_id,
            container.id[:12],
        )

        return {  # noqa: TRY300
            "status": "success",
            "container_id": container.id,
            "command": command,
        }

    except docker.errors.DockerException as e:
        error_msg = f"Docker container creation failed: {e}"
        logger.exception(error_msg)
        check.mark_error(error_message=error_msg)
        return {"status": "error", "reason": str(e)}


@queued_check_task()
def do_running(check_id: int) -> dict[str, Any]:  # noqa: C901, PLR0911, PLR0912, PLR0915
    """Monitor running container and download logs incrementally.

    Checks container status, downloads new logs since last fetch,
    and transitions to ANALYZING if container has exited.

    Args:
        check_id: ManufacturabilityCheck ID.

    Returns:
        Dict with status and log info.
    """
    logger = logging.getLogger(__name__)
    check = ManufacturabilityCheck.objects.get(id=check_id)

    if check.status != ManufacturabilityCheck.Status.RUNNING:
        logger.info(
            "Skipping do_running for check %s - status changed to %s",
            check_id,
            check.status,
        )
        return {"status": "skipped", "reason": "status_changed"}

    server = _get_server_config(check.docker_server_id)
    if not server:
        error_msg = f"Unknown server: {check.docker_server_id}"
        logger.error(error_msg)
        check.mark_error(error_message=error_msg)
        return {"status": "error", "reason": "unknown_server"}

    try:
        client = _get_docker_client(server)
    except docker.errors.DockerException as e:
        error_msg = f"Failed to connect to Docker server: {e}"
        logger.exception(error_msg)
        check.mark_error(error_message=error_msg)
        return {"status": "error", "reason": str(e)}

    try:
        container = client.containers.get(check.docker_container_id)
    except docker.errors.NotFound:
        error_msg = f"Container {check.docker_container_id} not found"
        logger.exception(error_msg)
        check.mark_error(error_message=error_msg)
        return {"status": "error", "reason": "container_not_found"}
    except docker.errors.DockerException as e:
        error_msg = f"Failed to get container: {e}"
        logger.exception(error_msg)
        check.mark_error(error_message=error_msg)
        return {"status": "error", "reason": str(e)}

    try:
        # Download logs incrementally
        logs_kwargs: dict[str, Any] = {"timestamps": True}
        if check.logs_downloaded_until:
            # Only get logs since last download
            logs_kwargs["since"] = check.logs_downloaded_until

        raw_logs = container.logs(**logs_kwargs).decode("utf-8", errors="replace")

        # Find the latest timestamp in the logs for next incremental fetch
        latest_timestamp = None
        if raw_logs:
            for line in raw_logs.split("\n"):
                timestamp = parse_docker_timestamp_float(line)
                if timestamp:
                    latest_timestamp = timestamp

            # Strip timestamps and append to processing logs
            clean_logs = strip_docker_timestamps(raw_logs)
            if clean_logs.strip():
                check.append_to_processing_logs(clean_logs)
                logger.info(
                    "Downloaded %d bytes of logs for check %s",
                    len(clean_logs),
                    check_id,
                )

        # Check container status
        container.reload()
        container_status = container.status

        if container_status == "exited":
            # Container has finished - get exit code and transition
            exit_code = container.attrs.get("State", {}).get("ExitCode", -1)
            logger.info(
                "Container %s exited with code %d",
                container.id[:12],
                exit_code,
            )

            check.mark_analyzing(docker_exit_code=exit_code)
            return {
                "status": "container_exited",
                "exit_code": exit_code,
            }

        # Container still running - update logs timestamp
        if latest_timestamp:
            check.logs_downloaded_until = latest_timestamp
            check.save(update_fields=["logs_downloaded_until"])

        logger.info(
            "Container %s still running for check %s",
            container.id[:12],
            check_id,
        )

        return {
            "status": "still_running",
            "container_status": container_status,
            "logs_bytes": len(raw_logs) if raw_logs else 0,
        }

    except docker.errors.DockerException as e:
        error_msg = f"Docker error while monitoring container: {e}"
        logger.exception(error_msg)
        check.mark_error(error_message=error_msg)
        return {"status": "error", "reason": str(e)}


@queued_check_task()
def do_analyzing(check_id: int) -> dict[str, Any]:
    """Analyze container logs and extract results.

    Parses the container logs to determine if the design is manufacturable,
    extracts errors and warnings, and transitions to FINISHED.

    Args:
        check_id: ManufacturabilityCheck ID.

    Returns:
        Dict with analysis results.
    """
    logger = logging.getLogger(__name__)
    check = ManufacturabilityCheck.objects.get(id=check_id)

    if check.status != ManufacturabilityCheck.Status.ANALYZING:
        logger.info(
            "Skipping do_analyzing for check %s - status changed to %s",
            check_id,
            check.status,
        )
        return {"status": "skipped", "reason": "status_changed"}

    try:
        # Parse the logs
        logs = check.processing_logs or ""
        exit_code = check.docker_exit_code or 0

        logger.info(
            "Parsing logs for check %s (exit_code=%d, log_length=%d)",
            check_id,
            exit_code,
            len(logs),
        )

        parse_result = PrecheckLogParser.parse_logs(logs, exit_code)

        # Extract errors and warnings
        error_messages = [e["message"] for e in parse_result["errors"]]
        warning_messages = [w.get("message", str(w)) for w in parse_result["warnings"]]

        # Determine manufacturability
        is_manufacturable = parse_result["success"]

        # Extract tool versions from logs if available
        # For now, use a simple approach - look for version strings
        tool_versions: dict[str, str] = {}
        # Placeholder - real version extraction would be more sophisticated
        if "precheck" in logs.lower():
            tool_versions["precheck"] = "unknown"

        logger.info(
            "Analysis complete for check %s: manufacturable=%s, errors=%d, warnings=%d",
            check_id,
            is_manufacturable,
            len(error_messages),
            len(warning_messages),
        )

        # Transition to FINISHED
        check.mark_finished(
            is_manufacturable=is_manufacturable,
            errors=error_messages,
            warnings=warning_messages,
            tool_versions=tool_versions,
        )

        return {
            "status": "success",
            "is_manufacturable": is_manufacturable,
            "error_count": len(error_messages),
            "warning_count": len(warning_messages),
        }

    except Exception as e:
        # Catch any parsing errors and mark as system error
        error_msg = f"Failed to analyze logs: {e}"
        logger.exception(error_msg)
        check.mark_error(error_message=error_msg)
        return {"status": "error", "reason": str(e)}


@queued_check_task()
def do_cancelling(check_id: int) -> dict[str, Any]:
    """Transition a CANCELLING check to CANCELLED.

    Simply marks the check as cancelled. Any Docker container cleanup
    is handled by checks_cleanup_orphaned_docker which will detect the
    container (via its wafer.space.check_id label) and remove it.

    Args:
        check_id: ManufacturabilityCheck ID.

    Returns:
        Dict with cancellation status.
    """
    logger = logging.getLogger(__name__)
    check = ManufacturabilityCheck.objects.get(id=check_id)

    if check.status != ManufacturabilityCheck.Status.CANCELLING:
        logger.info(
            "Skipping do_cancelling for check %s - status changed to %s",
            check_id,
            check.status,
        )
        return {"status": "skipped", "reason": "status_changed"}

    # Transition to CANCELLED - container cleanup handled by orphan task
    check.mark_cancelled()

    logger.info("Check %s marked as cancelled", check_id)

    return {"status": "success"}


@shared_task(queue="default")
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
        status__in=ManufacturabilityCheck.IN_PROGRESS_STATUSES,
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
