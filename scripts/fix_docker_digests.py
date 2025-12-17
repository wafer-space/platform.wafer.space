# ruff: noqa: INP001
"""
Fix incorrect docker_image_digest values in ManufacturabilityCheck records.

Background:
Before 2025-12-11, the code incorrectly stored Docker config digests (image.id)
instead of OCI manifest digests (RepoDigests). This script corrects those values.

Additionally, some PrecheckImageRevision records have non-semver precheck_version
values like "main" due to upstream labeling issues. This script resets those
records so they get re-fetched with the improved version resolution logic.

Usage:
    # Dry run (default) - shows what would be changed
    uv run python manage.py runscript fix_docker_digests

    # Actually apply the fixes
    uv run python manage.py runscript fix_docker_digests --script-args apply

See: https://github.com/wafer-space/platform.wafer.space/issues/233
See: https://github.com/wafer-space/platform.wafer.space/issues/236
"""

from __future__ import annotations

import logging
import re

from django.db import transaction

from wafer_space.projects.models import ManufacturabilityCheck
from wafer_space.projects.models import PrecheckImageRevision

logger = logging.getLogger(__name__)

# Mapping of wrong (config) digests to correct (OCI index) digests
# Built by querying GHCR API for all tags, extracting config blob digests,
# and mapping them to their parent OCI index digests.
# Each mapping verified to return HTTP 200 from GHCR before inclusion.
# fmt: off
DIGEST_CORRECTIONS: dict[str, str] = {
    "sha256:30359c4ecdedaf234abafd50aaa0094cc224caa3b0bb80d3b5b60bb59188b732":  # v1.5.2
        "sha256:344919c644f3031315b338b83ecf841434e704e20da3959800b0438b379c0c79",
    "sha256:66b0b53eebd56bebbfa6bfbb6c64174d8d64ce8c9f9a1c7ce0e5687686f8fd38":  # v1.5.1
        "sha256:f611e7b6341716e31f60f155d0ea5585350d3a3505a15f04735e3fbb500ae708",
    "sha256:50d9ae1416f8aa71f2ede44b2d46b60baa73ba9f9da91e62915d8f701ca99f33":  # v1.5.0
        "sha256:e7360b0584acaa86a8e3d046ceca2813ba2287b9c2ec3e4f48f2a8d831b59093",
    "sha256:16424a5b153bae821e17a7e914cdff69988c965655fdd5d6b7f80298065763db":  # v1.4
        "sha256:9b3a593a5c358031be20ac36cf473b682454b6aa5143a06a3b3515e058a6285e",
    "sha256:0f9e51ed2023ebd2b56add2e4ea88843d937df1367d3621ef97b7c05d4ba22ef":  # v1.4.3
        "sha256:63ce02bc4965fbc65048aef19f6ae0187928306fbba6539fdd53377cc2fce11c",
    "sha256:64e7fa03e5d63a93d667b887027727c342e0858b3e204c3497d3c9a52ba069b8":  # v1.4.1
        "sha256:726fb50830a85706517498d5a3f743f61e9a69d8e99457105ba7d417952effac",
    "sha256:ea798a5489c1c61fd52a142bc86170b42f891e37fba6ded3d9de3c16d78fea43":  # v1.4.2
        "sha256:31071e72ea6e9acc782767b1096818e24fda1943e0dadf6a505aa2a0398b1724",
    "sha256:739cb037666aaa6eb1ba43b78c68087e9ecd77fbf2bfbaeaab40138d10537a2f":  # v1.3.1
        "sha256:80a3e206fca8f048933acf317f983527af6111e2f38f2680e532ab95db3bec4e",
}
# fmt: on

# Regex pattern for semver-style versions (must match tasks_revisions._is_semver_tag)
SEMVER_PATTERN = re.compile(r"^v?\d+\.\d+")


def _is_semver_tag(tag: str) -> bool:
    """Check if tag matches semver pattern like 1.5.2 or v1.0.0."""
    return bool(SEMVER_PATTERN.match(tag))


def _fix_digest_corrections(*, dry_run: bool) -> int:
    """Fix ManufacturabilityCheck records with wrong digests.

    Also deletes any PrecheckImageRevision objects for the wrong digests.

    Returns:
        Number of records updated (or would be updated in dry run).
    """
    total_updated = 0

    for wrong_digest, correct_digest in DIGEST_CORRECTIONS.items():
        logger.info("Processing: %s...", wrong_digest[:40])
        logger.info("  Correct:  %s...", correct_digest[:40])

        # Fix ManufacturabilityCheck records
        affected_checks = ManufacturabilityCheck.objects.filter(
            docker_image_digest=wrong_digest
        )
        check_count = affected_checks.count()

        if check_count > 0:
            logger.info("  Found %d ManufacturabilityCheck record(s)", check_count)
            if not dry_run:
                affected_checks.update(docker_image_digest=correct_digest)
                logger.info("  Updated %d record(s)", check_count)
            total_updated += check_count
        else:
            logger.info("  No ManufacturabilityCheck records found")

        # Delete any PrecheckImageRevision for the wrong digest
        wrong_revisions = PrecheckImageRevision.objects.filter(digest=wrong_digest)
        rev_count = wrong_revisions.count()
        if rev_count > 0:
            logger.info("  Found %d PrecheckImageRevision for wrong digest", rev_count)
            if not dry_run:
                wrong_revisions.delete()
                logger.info("  Deleted %d PrecheckImageRevision(s)", rev_count)

    return total_updated


def _reset_nonsemver_revisions(*, dry_run: bool) -> int:
    """Reset PrecheckImageRevision records with non-semver precheck_version.

    Returns:
        Number of records reset (or would be reset in dry run).
    """
    logger.info("")
    logger.info("=" * 60)
    logger.info("PART 2: Resetting non-semver precheck_version records")
    logger.info("=" * 60)

    # Find revisions with non-semver precheck_version that have been fetched
    revisions_to_reset = []
    fetched_revisions = PrecheckImageRevision.objects.filter(
        metadata_fetched_at__isnull=False
    )
    for revision in fetched_revisions:
        version = revision.precheck_version
        if version and not _is_semver_tag(version):
            revisions_to_reset.append(revision)
            logger.info(
                "  Found: %s... precheck_version='%s'",
                revision.digest[:40],
                version,
            )

    if revisions_to_reset:
        count = len(revisions_to_reset)
        logger.info("Found %d revision(s) with non-semver precheck_version", count)
        if not dry_run:
            reset_count = PrecheckImageRevision.objects.filter(
                pk__in=[r.pk for r in revisions_to_reset]
            ).update(metadata_fetched_at=None)
            logger.info("Reset %d revision(s) for re-fetching", reset_count)
    else:
        logger.info("No revisions with non-semver precheck_version found")

    return len(revisions_to_reset)


def run(*args: str) -> None:
    """Run the digest fix script."""
    dry_run = "apply" not in args

    if dry_run:
        logger.info("=" * 60)
        logger.info("DRY RUN MODE - No changes will be made")
        logger.info("Run with --script-args apply to actually apply fixes")
        logger.info("=" * 60)
    else:
        logger.info("=" * 60)
        logger.info("APPLY MODE - Changes will be committed to database")
        logger.info("=" * 60)

    with transaction.atomic():
        digests_fixed = _fix_digest_corrections(dry_run=dry_run)
        revisions_reset = _reset_nonsemver_revisions(dry_run=dry_run)

        logger.info("")
        logger.info("=" * 60)
        logger.info("SUMMARY:")
        logger.info("  ManufacturabilityCheck digests to fix: %d", digests_fixed)
        logger.info("  PrecheckImageRevision to reset: %d", revisions_reset)
        logger.info("=" * 60)

        if dry_run:
            logger.info("DRY RUN - No changes were made")
            transaction.set_rollback(True)
        else:
            logger.info("Changes committed.")
            logger.info("Run 'revisions_needs_fetching' to re-fetch reset revisions.")
