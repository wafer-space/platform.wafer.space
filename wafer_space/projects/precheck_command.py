"""Single source of truth for the precheck container command line.

Used by both the Docker task runner (tasks_checks.do_starting) and the
user-facing "reproduce locally" instructions
(ManufacturabilityCheck.get_reproduction_instructions), so the two can
never drift apart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .docker_utils import get_server_config

if TYPE_CHECKING:
    from .models import ManufacturabilityCheck


def build_precheck_command(check: ManufacturabilityCheck) -> list[str]:
    """Build the precheck.py command line for a check's container.

    Args:
        check: ManufacturabilityCheck to build the command for.

    Returns:
        Command as a list of arguments.

    Raises:
        ValueError: If the project has no full_id (not assigned to a shuttle).
    """
    # Get top cell name for precheck command
    top_cell = check.project_file.top_cell or "unknown"

    # Get slot size and full_id from project (required for precheck)
    slot_size = check.project.slot_size
    full_id = check.project.full_id
    if not full_id:
        msg = (
            "Cannot run manufacturability check: "
            "project must be assigned to shuttle with project ID"
        )
        raise ValueError(msg)

    # Build precheck command with slot size and project ID
    # The container has ENTRYPOINT ["dev-shell"] and WORKDIR /workspace
    # precheck.py is at /workspace/precheck.py
    command = [
        "python3",
        "precheck.py",
        "--input",
        "/input/design.gds",
        # Output the processed layout as OASIS (.oas) to save disk space (#272)
        "--output",
        "/output/design.oas",
        "--top",
        top_cell,
        "--slot",
        slot_size,
        "--id",
        full_id,
    ]
    # Parallelism from server config: check_workers/check_threads are tuned
    # per environment (see the DOCKER_SERVERS settings comments).
    # When unset, precheck.py defaults apply (--workers 1, --threads max).
    server_config = (
        get_server_config(check.docker_server_id) if check.docker_server_id else None
    )
    if server_config and "check_workers" in server_config:
        command += ["--workers", str(server_config["check_workers"])]
    if server_config and "check_threads" in server_config:
        command += ["--threads", str(server_config["check_threads"])]
    if check.project.chip_on_board:
        command.append("--cob")
    return command
