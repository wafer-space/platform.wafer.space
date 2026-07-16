# Manufacturability Checking

## Overview

The platform automatically checks your design files for manufacturability using the [gf180mcu-precheck](https://github.com/wafer-space/gf180mcu-precheck) tool. This runs 5 checks in a Docker container to verify your design meets manufacturing requirements.

Checks are always attached to a specific **file revision**. Passing a check (being *manufacturable*) is a separate concept from being *submitted to be manufactured* — see [Manufacturable vs Submitted for Manufacturing](manufacturable_vs_submitted.md) for the authoritative definitions.

## The Five Checks

1. **Top Cell Validation** - Ensures only one top-level cell exists with correct name
2. **ID Cell QR Code** - Verifies `gf180mcu_ws_ip__id` cell exists for QR code generation
3. **Density Analysis** - Checks design density meets requirements
4. **Magic DRC** - Runs Design Rule Checking with Magic tool
5. **KLayout DRC** - Runs Design Rule Checking with KLayout tool

## Process Flow

### 1. Upload Your Design

Upload your GDS file via URL with hash verification. The system will:
- Download the file
- Verify the MD5/SHA1 hash
- Automatically queue a manufacturability check

### 2. Manufacturability Check Runs

The check runs in a Docker container and takes up to 3 hours. You can:
- View real-time progress (which check is currently running)
- See full logs as they stream
- Close the page and come back later (check continues)

**Concurrency Limits:**
- You can only have 1 active check at a time
- Multiple checks can be pending
- System-wide limit (default: 4 concurrent checks)

**Check States:**
- **PENDING** - Waiting for capacity to start
- **DISPATCHED** - Sent to worker queue
- **RUNNING** - Docker container executing analysis
- **FINISHED** - Analysis complete (check results available)
- **ERROR** - System failure (auto-retries up to 3 times)
- **CANCELLED** - User cancelled (terminal, cannot be restarted)

### 3. Review Results

**If Passed:**
- Project status becomes "Manufacturable"
- You can proceed to export compliance certification
- Warnings (if any) are shown but don't block progress

**If Failed:**
- Detailed error messages explain what's wrong
- Errors are grouped by category (DRC, density, etc.)
- Full logs available for debugging

### 4. Export Compliance Certification

Before requesting a shuttle slot, you must certify:
- ✓ Design complies with U.S. Export Control Regulations (EAR/ITAR)
- ✓ You are not from a restricted country or sanctioned entity
- ✓ Intended end-use statement (text description)

This certification is legally binding and recorded with your IP address.

### 5. Request Shuttle Slot

After certification, you can request assignment to an active shuttle run.

## Reproducibility

Every check records:
- Exact Docker image used (SHA256 digest)
- Tool versions (Magic, KLayout, PDK version)
- Precheck script version (git commit)

You can reproduce the check locally:
1. View "Reproduction Instructions" on project detail page
2. Copy the exact Docker command
3. Run on your local machine to debug

## Error Types

### Design Errors (No Automatic Retry)

These indicate problems with your GDS file:
- DRC violations (spacing, width, etc.)
- Missing required cells
- Density violations
- Multiple top-level cells

**Fix:** Update your design and upload a new file.

### System Errors (Automatic Retry)

These indicate infrastructure problems:
- Docker container failures
- Out of memory errors
- Timeout (>3 hours)
- Worker crashes

**Fix:** System automatically retries up to 3 times. If still failing, contact support.

## Troubleshooting

### Check is Pending for a Long Time

- Check queue position on project detail page
- System has limited concurrent capacity (default: 4)
- Large designs take longer to process
- Checks progress through states: PENDING → DISPATCHED → RUNNING → FINISHED

### Different Results Locally

1. Verify Docker image digest matches exactly
2. Check file hashes (MD5/SHA1) match
3. Use exact same `--top` cell name
4. Ensure Docker has enough memory (8GB recommended)

### Need Help?

- Click "Report Issue to GitHub" to create pre-filled bug report
- Include full logs and environment information
- Contact support with check ID

## Admin Features

Administrators can:
- Re-run checks when Docker image/rules are updated
- Record reason for re-run (e.g., "Updated DRC deck")
- Review compliance certifications
- Add admin notes to certifications

## API / Programmatic Access

Currently, manufacturability checks are triggered automatically after file hash verification. Manual triggering via API is planned for future release.

## Future Enhancements

Planned improvements:
- Enhanced progress tracking (show specific check step)
- Email notifications when check completes
- Caching for identical files
- Parallel check execution for multi-core systems
- Integration with design verification tools
