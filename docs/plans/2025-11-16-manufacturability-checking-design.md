# Manufacturing Checking System Design

**Date:** 2025-11-16
**Status:** Design
**Author:** Claude (with user requirements)

## Overview

This design document describes the implementation of automated manufacturability checking using the gf180mcu-precheck tool, running in Docker containers. The system will replace the current mock implementation with real DRC (Design Rule Checking) validation, add export compliance certification, and provide users with detailed error reporting and reproducibility instructions.

## Background

Currently, the platform has a mock `check_project_manufacturability` task that simulates checking with random success/failure. We need to replace this with real validation using the [gf180mcu-precheck](https://github.com/wafer-space/gf180mcu-precheck) tool, which performs:

1. Top cell validation (single top-level cell matching expected name)
2. ID cell QR code generation (`gf180mcu_ws_ip__id` cell)
3. Design density analysis
4. Magic DRC checks
5. KLayout DRC checks

## Requirements

### Functional Requirements

1. **Real Manufacturability Checking**
   - Run gf180mcu-precheck tool in Docker container
   - Parse and report errors clearly to users
   - Track which of the 5 checks is currently running (real-time progress)
   - Distinguish between system failures (retry) and design errors (no retry)

2. **Export Compliance Certification**
   - Project-level attestation before shuttle assignment
   - Three required confirmations:
     - EAR/ITAR export control compliance
     - End-use statement (text description)
     - Not from restricted country/sanctioned entity
   - Track certification metadata (IP address, timestamp, user agent)

3. **Version Tracking and Reproducibility**
   - Record Docker image digest used for each check
   - Capture tool versions (magic, klayout, PDK version)
   - Provide exact reproduction instructions for local testing
   - Generate pre-filled GitHub issue reports

4. **Admin Controls**
   - Ability to re-run checks when Docker image/rules are updated
   - Track re-run reason and admin who requested it
   - Review compliance certifications

### Non-Functional Requirements

1. **Performance & Scalability**
   - 3-hour timeout per check
   - Configurable concurrent check limit (default: 4)
   - One active check per user (multiple can queue)
   - Display queue position to users

2. **Reliability**
   - Automatic retry for system failures (max 3 retries)
   - No retry for design errors (user must fix and re-submit)
   - Graceful timeout handling
   - Resource limits (8GB RAM, 1 CPU per container)

3. **Observability**
   - Stream logs in real-time during execution
   - Store complete logs for debugging
   - Track last activity timestamp (detect hung tasks)
   - Celery task state updates for progress tracking

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                         User                                │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Django Views/Forms                       │
│  - Project detail page (show check status)                 │
│  - Compliance certification form                           │
│  - Shuttle assignment (validate compliance)                │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                ManufacturabilityService                     │
│  - queue_check() - enforce per-user limits                 │
│  - admin_rerun_check() - admin-triggered re-runs           │
│  - generate_reproduction_instructions()                    │
│  - generate_precheck_issue_url()                           │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│            Celery Task: check_project_manufacturability     │
│  - Pull Docker image (ghcr.io/.../gf180mcu-precheck)       │
│  - Mount GDS file into container                           │
│  - Execute precheck.py with streaming output               │
│  - Parse logs with PrecheckLogParser                       │
│  - Update task state with progress (1-5 checks)            │
│  - Classify errors (system vs design)                      │
│  - Retry on system failures, complete on design failures   │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Docker Container                         │
│  Image: ghcr.io/wafer-space/gf180mcu-precheck:latest       │
│  - Nix environment with LibreLane                          │
│  - gf180mcu PDK                                            │
│  - Magic, KLayout DRC tools                                │
│  - precheck.py script                                      │
│  Mounts: /input/design.gds (read-only)                     │
│  Limits: 8GB RAM, 1 CPU, 3-hour timeout                    │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **User triggers check** (after file hash verified)
   - `ManufacturabilityService.queue_check(project)` called
   - Validates per-user concurrency limit
   - Creates/resets `ManufacturabilityCheck` record
   - Queues Celery task on `manufacturability` queue

2. **Celery worker picks up task**
   - Pulls Docker image from ghcr.io
   - Records image digest and versions
   - Mounts GDS file into container
   - Starts container and streams output

3. **Real-time progress tracking**
   - Parse output lines for check patterns
   - Update Celery task state: `{"current": 3, "total": 5, "progress": 60, "message": "Running Magic DRC..."}`
   - Update `last_activity` timestamp
   - Append logs to `processing_logs` field

4. **Completion handling**
   - Exit code 0: Mark as manufacturable, extract warnings
   - Exit code 1 + system errors: Retry (max 3 attempts)
   - Exit code 1 + design errors: Complete with errors, update project status
   - Store final results in `ManufacturabilityCheck`

5. **Compliance certification** (if check passed)
   - User clicks "Request Shuttle Slot"
   - If no certification exists, redirect to form
   - User confirms three attestations + end-use statement
   - Create `ProjectComplianceCertification` record
   - Allow shuttle assignment

## Database Schema Changes

### ManufacturabilityCheck (Extend Existing Model)

```python
class ManufacturabilityCheck(models.Model):
    # Existing fields:
    # - project (OneToOne)
    # - status (QUEUED, PROCESSING, COMPLETED, FAILED, CANCELLED)
    # - started_at, completed_at, task_id
    # - is_manufacturable, errors, warnings, processing_logs
    # - retry_count, max_retries

    # NEW FIELDS:

    # Version tracking
    docker_image = models.CharField(
        max_length=500,
        blank=True,
        help_text="Docker image used (e.g., ghcr.io/wafer-space/gf180mcu-precheck:latest)"
    )
    docker_image_digest = models.CharField(
        max_length=100,
        blank=True,
        help_text="SHA256 digest of Docker image for reproducibility"
    )
    tool_versions = models.JSONField(
        default=dict,
        blank=True,
        help_text="Tool versions: {magic: '8.3.x', klayout: '0.28.x', pdk: 'gf180mcuD-v1.2.3'}"
    )
    precheck_version = models.CharField(
        max_length=50,
        blank=True,
        help_text="gf180mcu-precheck version/commit hash"
    )

    # Activity tracking (like ProjectFile)
    last_activity = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last activity timestamp for progress tracking"
    )

    # Admin controls
    rerun_requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_precheck_reruns",
        help_text="Admin who requested re-run"
    )
    rerun_reason = models.TextField(
        blank=True,
        help_text="Why this check was re-run (e.g., 'Updated DRC rules')"
    )
```

**Migration:** Add new fields with `blank=True` defaults, no data migration needed.

### ProjectComplianceCertification (New Model)

```python
class ProjectComplianceCertification(models.Model):
    """Export compliance attestation for a specific project."""

    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="compliance_certification",
    )

    # Attestations
    export_control_compliant = models.BooleanField(
        default=False,
        help_text="User confirms compliance with EAR/ITAR export control regulations"
    )
    end_use_statement = models.TextField(
        help_text="Description of intended end-use (commercial, research, educational, etc.)"
    )
    not_restricted_entity = models.BooleanField(
        default=False,
        help_text="User confirms they are not from a restricted country or sanctioned entity"
    )

    # Tracking
    certified_at = models.DateTimeField(auto_now_add=True)
    certified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="compliance_certifications",
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address from which certification was submitted"
    )
    user_agent = models.TextField(
        blank=True,
        help_text="Browser user agent string"
    )

    # Admin review (optional - can be added later)
    admin_reviewed = models.BooleanField(default=False)
    admin_reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_certifications",
    )
    admin_notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Compliance Certification"
        verbose_name_plural = "Compliance Certifications"
        indexes = [
            models.Index(fields=["certified_at"]),
            models.Index(fields=["admin_reviewed"]),
        ]
```

**Migration:** Create new table, no data migration needed (existing projects will not have certification until they request shuttle slots).

## Implementation Details

### Docker Image Creation

**Separate Task:** Create `Dockerfile` and submit to gf180mcu-precheck repository.

```dockerfile
# Dockerfile (to be created and submitted upstream)
FROM nixos/nix:latest

# Install LibreLane and dependencies
RUN nix-channel --add https://github.com/efabless/librelane/archive/main.tar.gz librelane
RUN nix-channel --update

# Clone gf180mcu PDK
WORKDIR /
RUN git clone https://github.com/google/gf180mcu-pdk.git gf180mcu
ENV PDK_ROOT=/gf180mcu
ENV PDK=gf180mcuD

# Copy precheck script
COPY precheck.py /precheck/precheck.py
WORKDIR /precheck

# Default command
ENTRYPOINT ["python3", "/precheck/precheck.py"]
```

**Docker Image Publishing:**
- Build and push to GitHub Container Registry: `ghcr.io/wafer-space/gf180mcu-precheck:latest`
- Tag with version numbers: `ghcr.io/wafer-space/gf180mcu-precheck:v1.0.0`
- Use SHA256 digests for reproducibility

### Log Parsing Strategy

**Phase 1 - Minimal Parser (Initial Release):**

Since gf180mcu-precheck is still WIP and we don't have example outputs, start with minimal parsing:

```python
class PrecheckLogParser:
    """Parse gf180mcu-precheck output - designed to evolve as we learn actual format."""

    @classmethod
    def parse_logs(cls, logs: str, exit_code: int) -> dict:
        """Parse precheck logs - conservative initial implementation."""
        result = {
            "success": exit_code == 0,
            "errors": [],
            "warnings": [],
            "raw_output": logs,
            "detected_checks": [],
        }

        # Simple success detection
        if "Precheck successfully completed." in logs:
            result["success"] = True
            return result

        # Simple error detection - just find "Error:" lines
        for line_num, line in enumerate(logs.split('\n'), 1):
            if line.strip().startswith("Error:"):
                result["errors"].append({
                    "message": line.strip(),
                    "line": line_num,
                    "category": "Unknown",
                })

        # If exit code != 0 but no errors found, treat whole output as error
        if exit_code != 0 and not result["errors"]:
            result["errors"].append({
                "message": "Precheck failed - see full logs for details",
                "line": 0,
                "category": "System",
            })

        return result
```

**Phase 2 - Enhanced Parser (After Testing):**

After running real precheck tests:
1. Capture output from successful runs
2. Capture output from various failure modes (DRC errors, missing cells, etc.)
3. Update parser with real patterns
4. Add unit tests with captured log samples

**TODO markers for enhancement:**
```python
# TODO: Update these patterns after running real precheck tests
#
# Testing checklist:
# [ ] Run precheck with known good design → capture output
# [ ] Run precheck with DRC errors → capture output
# [ ] Run precheck with missing ID cell → capture output
# [ ] Run precheck with multiple top cells → capture output
# [ ] Update patterns based on actual output format
```

### Error Classification

**System Errors (Retry):**
- Container failed to start
- Container exceeded timeout
- Container OOM/crashed (exit codes 137, 139)
- Worker process crashed
- File system errors
- Network issues pulling image

**Design Errors (No Retry):**
- DRC violations
- Missing/invalid top cell
- Missing ID cell
- Density violations
- Multiple top-level cells

**Detection:**
```python
SYSTEM_ERROR_PATTERNS = [
    r"Error: The precheck failed with the following exception:",
    r"Traceback \(most recent call last\):",
    r"MemoryError",
    r"TimeoutError",
    r"Docker.*error",
    r"Container.*failed",
]

def classify_failure(logs: str, exit_code: int) -> str:
    """Classify failure as 'system' or 'design'."""
    if exit_code == 0:
        return "success"

    for pattern in SYSTEM_ERROR_PATTERNS:
        if re.search(pattern, logs, re.IGNORECASE):
            return "system"

    return "design"  # Default to design error
```

### Celery Task Implementation

```python
@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    time_limit=settings.PRECHECK_TIMEOUT_SECONDS,
    soft_time_limit=settings.PRECHECK_TIMEOUT_SECONDS - 300,
)
def check_project_manufacturability(self, check_id):
    """Run manufacturability check in Docker container."""
    logger = logging.getLogger(__name__)

    try:
        # 1. Get check and project
        check = ManufacturabilityCheck.objects.get(id=check_id)
        check.task_id = self.request.id or "test-task"
        check.save(update_fields=["task_id"])
        check.start_processing()

        project = check.project
        project_file = project.submitted_file or project.files.filter(is_active=True).first()

        if not project_file or not project_file.file:
            raise ValueError("No GDS file available for checking")

        # 2. Initialize Docker client
        client = docker.from_env()

        # 3. Pull Docker image and record metadata
        logger.info("Pulling Docker image: %s", settings.PRECHECK_DOCKER_IMAGE)
        image = client.images.pull(settings.PRECHECK_DOCKER_IMAGE)
        check.docker_image = image.tags[0] if image.tags else settings.PRECHECK_DOCKER_IMAGE
        check.docker_image_digest = image.id
        check.save(update_fields=["docker_image", "docker_image_digest"])

        # 4. Prepare GDS file path
        gds_path = project_file.file.path

        # 5. Run container with streaming output
        container = client.containers.run(
            image=settings.PRECHECK_DOCKER_IMAGE,
            command=[
                "python3", "/precheck/precheck.py",
                "--input", "/input/design.gds",
                "--top", project.name,
                "--id", str(project.id),
            ],
            volumes={gds_path: {'bind': '/input/design.gds', 'mode': 'ro'}},
            detach=True,
            mem_limit='8g',
            cpu_quota=100000,  # 1 CPU
        )

        # 6. Stream logs and update progress
        logs = ""
        for line in container.logs(stream=True):
            line_text = line.decode('utf-8')
            logs += line_text

            # Update last activity
            check.last_activity = timezone.now()
            check.processing_logs = logs
            check.save(update_fields=["last_activity", "processing_logs"])

            # Parse for progress (simple initial implementation)
            # TODO: Enhance after seeing real output
            self.update_state(
                state="PROGRESS",
                meta={
                    "message": "Running precheck...",
                    "logs": logs[-1000:],  # Last 1000 chars
                }
            )

        # 7. Wait for completion
        result = container.wait(timeout=settings.PRECHECK_TIMEOUT_SECONDS)
        exit_code = result['StatusCode']

        # 8. Extract version information
        # TODO: Parse tool versions from logs
        check.tool_versions = {
            "pdk": "gf180mcuD",  # Extract from logs
            "magic": "unknown",  # Extract from logs
            "klayout": "unknown",  # Extract from logs
        }
        check.save(update_fields=["tool_versions"])

        # 9. Parse logs
        parsed = PrecheckLogParser.parse_logs(logs, exit_code)

        # 10. Handle results
        if exit_code == 0:
            # Success
            check.complete(
                is_manufacturable=True,
                errors=[],
                warnings=parsed.get("warnings", []),
                logs=logs,
            )
        else:
            # Failure - classify
            failure_type = classify_failure(logs, exit_code)

            if failure_type == "system":
                # System failure - retry
                check.retry_count += 1
                check.processing_logs += f"\nSystem error detected - retry {check.retry_count}/{check.max_retries}\n"
                check.save()

                if check.retry_count < check.max_retries:
                    raise self.retry(exc=Exception(f"System failure: {parsed['errors']}"))
                else:
                    check.fail("Max retries reached - system error")
            else:
                # Design failure - complete with errors
                check.complete(
                    is_manufacturable=False,
                    errors=parsed.get("errors", []),
                    warnings=parsed.get("warnings", []),
                    logs=logs,
                )

        # 11. Cleanup
        container.remove()

        return {
            "status": "completed",
            "is_manufacturable": check.is_manufacturable,
            "errors": check.errors,
            "warnings": check.warnings,
        }

    except ManufacturabilityCheck.DoesNotExist:
        logger.error("ManufacturabilityCheck %s not found", check_id)
        return {"status": "error", "message": "Check not found"}

    except docker.errors.ContainerError as exc:
        logger.exception("Container error")
        # Handle container failures...

    except docker.errors.Timeout:
        logger.error("Container timeout after %s seconds", settings.PRECHECK_TIMEOUT_SECONDS)
        # Handle timeout...
```

### Concurrency Control

**Celery Configuration:**

```python
# In config/settings/base.py
CELERY_TASK_ROUTES = {
    'wafer_space.projects.tasks.check_project_manufacturability': {'queue': 'manufacturability'},
}

PRECHECK_CONCURRENT_LIMIT = env.int('PRECHECK_CONCURRENT_LIMIT', default=4)
PRECHECK_PER_USER_LIMIT = env.int('PRECHECK_PER_USER_LIMIT', default=1)
PRECHECK_TIMEOUT_SECONDS = env.int('PRECHECK_TIMEOUT_SECONDS', default=10800)  # 3 hours
PRECHECK_DOCKER_IMAGE = env('PRECHECK_DOCKER_IMAGE', default='ghcr.io/wafer-space/gf180mcu-precheck:latest')
```

**Worker Configuration:**

```bash
# Start dedicated worker for manufacturability checks
celery -A config worker \
  -Q manufacturability \
  --concurrency=4 \
  --max-tasks-per-child=1 \
  --time-limit=10800 \
  --soft-time-limit=10500 \
  --loglevel=info
```

**Per-User Enforcement:**

Enforced in `ManufacturabilityService.queue_check()` - checks for existing QUEUED or PROCESSING checks for the user before creating new check.

### Compliance Certification Flow

**User Flow:**

1. Project passes manufacturability check → status = MANUFACTURABLE
2. User clicks "Request Shuttle Slot"
3. System checks: `hasattr(project, 'compliance_certification')`
4. If no certification:
   - Redirect to `/projects/{id}/compliance/certify/`
   - Show form with three checkboxes + text area
   - Form includes legal disclaimer text
5. On submit:
   - Capture IP address and user agent
   - Create `ProjectComplianceCertification` record
   - Redirect to shuttle list
6. When reserving shuttle slot:
   - Validate certification exists
   - Validate all required fields are true/filled

**Form Template:**

```html
<form method="post">
  {% csrf_token %}

  <div class="alert alert-warning">
    <h5>Export Compliance Certification</h5>
    <p>Before your project can be assigned to a manufacturing shuttle, you must certify compliance with export control regulations.</p>
  </div>

  <div class="form-check mb-3">
    <input type="checkbox" class="form-check-input" id="export_control" name="export_control_compliant" required>
    <label class="form-check-label" for="export_control">
      I confirm this design complies with U.S. Export Control Regulations (EAR/ITAR)
    </label>
  </div>

  <div class="form-check mb-3">
    <input type="checkbox" class="form-check-input" id="not_restricted" name="not_restricted_entity" required>
    <label class="form-check-label" for="not_restricted">
      I confirm I am not from a restricted country or sanctioned entity
    </label>
  </div>

  <div class="mb-3">
    <label for="end_use" class="form-label">Intended End-Use</label>
    <textarea class="form-control" id="end_use" name="end_use_statement" rows="4" required
              placeholder="Describe the intended use of this chip (e.g., research, commercial product, educational demonstration)"></textarea>
  </div>

  <button type="submit" class="btn btn-primary">Certify and Continue</button>
</form>
```

**Validation in Shuttle Assignment:**

```python
# In ShuttleSlot.reserve()
def reserve(self, project, user):
    # ... existing validations ...

    # NEW: Compliance validation
    if not hasattr(project, 'compliance_certification'):
        raise ValueError("Project must have compliance certification before shuttle assignment")

    cert = project.compliance_certification
    if not (cert.export_control_compliant and cert.not_restricted_entity):
        raise ValueError("Compliance certification is incomplete")

    if not cert.end_use_statement.strip():
        raise ValueError("End-use statement is required")

    # Continue with reservation...
```

### Reproducibility and Issue Reporting

**Reproduction Instructions:**

```python
def get_reproduction_instructions(self) -> str:
    """Generate markdown instructions for reproducing check locally."""
    project_file = self.project.submitted_file or self.project.files.filter(is_active=True).first()

    return f"""
# Reproducing Manufacturability Check Locally

## Prerequisites
- Docker installed and running
- Access to your GDS file

## Steps

### 1. Pull the exact Docker image used
```bash
docker pull {self.docker_image}
# Verify digest matches: {self.docker_image_digest}
docker images --digests | grep gf180mcu-precheck
```

### 2. Run the precheck
```bash
docker run --rm \\
  -v $(pwd)/{project_file.original_filename}:/input/design.gds:ro \\
  {self.docker_image} \\
  python3 /precheck/precheck.py \\
    --input /input/design.gds \\
    --top {self.project.name} \\
    --id {self.project.id}
```

### 3. Verify file hash
Your GDS file should have:
- MD5: {project_file.hash_md5}
- SHA1: {project_file.hash_sha1}

## Environment
- Precheck Version: {self.precheck_version}
- Tool Versions: {json.dumps(self.tool_versions, indent=2)}

## Need Help?
[Report issue on GitHub]({self._generate_issue_url()})
"""
```

**GitHub Issue Generation:**

```python
def _generate_issue_url(self) -> str:
    """Generate pre-filled GitHub issue URL."""
    title = f"Issue with precheck for project {self.project.name}"

    body = f"""
### Environment
- Docker Image: `{self.docker_image}`
- Image Digest: `{self.docker_image_digest}`
- Precheck Version: `{self.precheck_version}`
- Tool Versions: {json.dumps(self.tool_versions, indent=2)}

### Issue Description
<!-- Describe the issue here -->

### Logs
<details>
<summary>Click to expand logs</summary>

```
{self.processing_logs[-5000:]}
```
</details>

### Error Messages
```json
{json.dumps(self.errors, indent=2)}
```
"""

    params = urllib.parse.urlencode({
        "title": title,
        "body": body,
        "labels": "bug,from-platform"
    })

    return f"https://github.com/wafer-space/gf180mcu-precheck/issues/new?{params}"
```

## Testing Strategy

### Unit Tests

```python
# test_manufacturability_parser.py
def test_parse_success():
    logs = "Precheck successfully completed."
    result = PrecheckLogParser.parse_logs(logs, exit_code=0)
    assert result["success"] is True
    assert len(result["errors"]) == 0

def test_parse_error():
    logs = "Error: Multiple top cells found: top1, top2"
    result = PrecheckLogParser.parse_logs(logs, exit_code=1)
    assert result["success"] is False
    assert len(result["errors"]) > 0

def test_classify_system_error():
    logs = "Error: The precheck failed with the following exception:\nTraceback..."
    assert classify_failure(logs, 1) == "system"

def test_classify_design_error():
    logs = "DRC violation at (100, 200)"
    assert classify_failure(logs, 1) == "design"
```

### Integration Tests

```python
# test_manufacturability_integration.py
def test_queue_check_enforces_per_user_limit(user, project):
    # Create first check
    check1 = ManufacturabilityService.queue_check(project)
    assert check1.status == ManufacturabilityCheck.Status.QUEUED

    # Try to create second check - should fail
    project2 = ProjectFactory(user=user)
    with pytest.raises(ValidationError, match="already have.*check.*running"):
        ManufacturabilityService.queue_check(project2)

def test_compliance_certification_required_for_shuttle():
    project = ProjectFactory(status=Project.Status.MANUFACTURABLE)
    shuttle = ShuttleFactory(status=Shuttle.Status.OPEN)
    slot = shuttle.slots.first()

    # Should fail without certification
    with pytest.raises(ValueError, match="compliance certification"):
        slot.reserve(project, project.user)

    # Create certification
    ProjectComplianceCertification.objects.create(
        project=project,
        export_control_compliant=True,
        not_restricted_entity=True,
        end_use_statement="Research project",
        certified_by=project.user,
    )

    # Should succeed
    slot.reserve(project, project.user)
    assert slot.status == ShuttleSlot.Status.RESERVED
```

### Browser Tests

```python
# test_browser_manufacturability.py
@pytest.mark.browser
def test_compliance_certification_flow(driver, live_server, user, project):
    # Login and navigate to project
    login(driver, user)
    driver.get(f"{live_server.url}/projects/{project.id}/")

    # Click "Request Shuttle Slot"
    driver.find_element(By.ID, "request-shuttle-slot").click()

    # Should redirect to compliance form
    assert "/compliance/certify/" in driver.current_url

    # Fill form
    driver.find_element(By.ID, "export_control").click()
    driver.find_element(By.ID, "not_restricted").click()
    driver.find_element(By.ID, "end_use").send_keys("Research project for university")

    # Submit
    driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()

    # Should redirect to shuttle list
    assert "/shuttles/" in driver.current_url
```

### Manual Testing Checklist

Before finalizing implementation:

- [ ] Create Dockerfile and build test image
- [ ] Find/create sample GDS files for testing
- [ ] Run precheck manually with good design → capture output
- [ ] Run precheck manually with DRC errors → capture output
- [ ] Run precheck manually with missing cells → capture output
- [ ] Update `PrecheckLogParser` with real patterns
- [ ] Test timeout behavior (create design that takes >3 hours or mock timeout)
- [ ] Test retry behavior (force system failure)
- [ ] Test concurrency limits (queue multiple checks)
- [ ] Test compliance certification flow end-to-end

## Deployment Considerations

### Configuration

```bash
# .env additions
PRECHECK_DOCKER_IMAGE=ghcr.io/wafer-space/gf180mcu-precheck:latest
PRECHECK_CONCURRENT_LIMIT=4
PRECHECK_PER_USER_LIMIT=1
PRECHECK_TIMEOUT_SECONDS=10800
```

### Worker Deployment

Add new systemd service for manufacturability worker:

```ini
# /etc/systemd/system/django-celery-manufacturability.service
[Unit]
Description=Celery Worker for Manufacturability Checks
After=network.target redis.target postgresql.target

[Service]
Type=notify
User=django
Group=django
WorkingDirectory=/home/django/platform
Environment="DJANGO_SETTINGS_MODULE=config.settings.production"
ExecStart=/home/django/platform/.venv/bin/celery -A config worker \
  -Q manufacturability \
  --concurrency=4 \
  --max-tasks-per-child=1 \
  --time-limit=10800 \
  --soft-time-limit=10500 \
  --loglevel=info \
  --logfile=/var/log/django/celery-manufacturability.log
Restart=always

[Install]
WantedBy=multi-user.target
```

### Docker Access

Ensure Celery worker user has Docker access:

```bash
sudo usermod -aG docker django
```

Or use Docker socket mounting (more secure):

```python
# In task code
client = docker.DockerClient(base_url='unix://var/run/docker.sock')
```

### Resource Monitoring

Monitor Docker container resource usage:

```bash
docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"
```

Set up alerts for:
- High memory usage (>7GB per container)
- Long-running containers (>2.5 hours)
- Failed container starts

## Future Enhancements

### Phase 2 Improvements

1. **Enhanced Log Parsing**
   - Pattern-based progress detection for real-time check status
   - Extract specific DRC coordinates and layer information
   - Categorize errors by severity (error vs warning)

2. **Progress Visualization**
   - Show which of 5 checks is currently running
   - Display estimated time remaining per check
   - Show historical average check times

3. **Admin Dashboard**
   - View all running checks
   - Kill hung containers
   - Batch re-run checks after rule updates
   - Statistics: success rate, average time, failure modes

4. **Notification Integration**
   - Email when check completes (success or failure)
   - Slack/Discord webhooks for admin alerts
   - Push notifications for mobile app

5. **Caching and Optimization**
   - Cache Docker images locally (image pull can be slow)
   - Deduplicate checks for identical GDS files
   - Warm container pool for faster startup

6. **Advanced Compliance**
   - Admin review workflow for high-risk projects
   - Integration with export control databases
   - Periodic re-certification (annual)

## Open Questions / Decisions Needed

1. **Docker Image Hosting**
   - ✅ Use GitHub Container Registry (ghcr.io)
   - Who maintains/updates the image?
   - Versioning strategy (latest + semantic versions)?

2. **Sample GDS Files**
   - Where to get test files for development?
   - Can we include in test suite or need separate repo?

3. **Concurrency Limits**
   - Start with 4 concurrent checks, adjust based on server resources
   - Monitor CPU/memory usage in production

4. **Admin Review of Compliance**
   - Initially: User self-certifies, admin can review later
   - Future: Option to require admin approval before shuttle assignment

5. **Precheck Tool Evolution**
   - Tool is still WIP - expect breaking changes
   - Need process for updating Docker image and re-running checks

## References

- [gf180mcu-precheck repository](https://github.com/wafer-space/gf180mcu-precheck)
- [Existing download progress implementation](wafer_space/projects/tasks.py)
- [ManufacturabilityCheck model](wafer_space/projects/models.py#L620-L700)
- [Export control regulations (EAR)](https://www.bis.doc.gov/index.php/regulations/export-administration-regulations-ear)
