# Staff Submit Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Staff can submit a project for manufacturing although its latest revision failed the precheck, with a required reason that is recorded, audit-logged and shown on the project page.

**Architecture:** Two Project fields (`submission_override_by`, `submission_override_reason`) and two ProjectAccessLog changes (`SUBMIT_OVERRIDE` action, `details` text) in one migration. `Project.can_override_submit()` / `override_submit()` beside `can_submit()` / `submit()`, sharing the locked write. A staff-only POST view with a reason form. A banner on the project page. Markers in the admin, the admin summary and the reticle README.

**Tech Stack:** Django 5.2, simple_history, pytest-django, factory-boy, Selenium (headless).

**Spec:** `docs/superpowers/specs/2026-10-11-staff-submit-override-design.md`

## Global Constraints

- Only staff (`is_staff`) may override; owners who are not staff get 403.
- Mandatory even with the override: an active file, download completed, hash verified, a finished check with a processed layout (`output_gds`), and the project not archived.
- The reason must be at least 20 characters (`SUBMIT_OVERRIDE_REASON_MIN_LENGTH = 20`).
- Every override writes `ProjectAccessLog(action=SUBMIT_OVERRIDE, details=<reason>)`.
- A normal `submit()` clears both override fields; simple_history keeps the old values.
- No owner email.
- Before every commit: `make lint-fix && make lint && make type-check && make test`; templates through `uv run pre-commit run --files`. No `# noqa` or `# type: ignore`.
- Never use `Project.status` to decide submission; use `submitted_file`.

## Review Focus

1. Override on a project whose latest revision passed: refused ("use Submit"), and no override button is shown (Task 1 and Task 3 tests).
2. The revision is replaced between page load and the override POST: the same "file was replaced" error as `submit()` (Task 1 test).
3. Override, then a new manufacturable revision submitted normally: the override fields are cleared, history has both (Task 1 test).
4. A reason of whitespace or 19 characters: form error, nothing saved (Task 2 test).
5. The banner is visible to the owner, not only staff (Task 3 test).

---

### Task 1: Model fields, rules and the locked write

**Files:**
- Modify: `wafer_space/projects/models.py`: Project fields after `archived_at`; `SYSTEM_FIELDS`; constant `SUBMIT_OVERRIDE_REASON_MIN_LENGTH = 20` beside `ARCHIVED_READ_ONLY_MESSAGE`; `can_override_submit()`, `override_submit()` and `is_submission_override` after `submit()`; `submit()` clears the override fields; `ProjectAccessLog.Action.SUBMIT_OVERRIDE`, `ProjectAccessLog.details`.
- Create: migration `00NN_submission_override` (via `makemigrations projects -n submission_override`).
- Test: `wafer_space/projects/tests/test_models_submit_override.py`

**Interfaces:**
- Produces: `Project.can_override_submit(user) -> tuple[bool, str]`, `Project.override_submit(user, reason: str) -> None` (raises `ValidationError` with the refusal), `Project.is_submission_override -> bool` (`submission_override_by_id is not None`), `SUBMIT_OVERRIDE_REASON_MIN_LENGTH`.

- [ ] **Step 1: Failing tests.** Helper `make_failed_project(*, with_layout=True)`: a project with an active `ProjectFile`; a completed `DownloadAttempt` and a task id; `hash_verified=True`; a FINISHED `ManufacturabilityCheck` on that file with `finished_status` set to a failing value (read the `FinishedStatus` enum and pick its "not manufacturable" member); `output_gds` set via `SimpleUploadedFile("out.oas", b"x")` when `with_layout`. Tests:
  - staff may override (`(True, "")`); a non-staff owner is refused;
  - refused: archived; no active file; download not complete; hash not verified; no finished check; no `output_gds`; and already submittable (passing check);
  - `override_submit(staff, "x" * 20)` sets `submitted_file` to the active revision, `submitted_at`, `status == SUBMITTED`, `submission_override_by == staff`, and the reason;
  - a reason of `"x" * 19` or whitespace raises `ValidationError`;
  - after an override, a passing check on a new active revision plus `submit()` clears both fields, and `project.history` contains a row with the reason;
  - the revision was replaced (set `is_active=False` on the loaded revision before the call) raises "file was replaced".
- [ ] **Step 2:** Run them; expect an ImportError or AttributeError.
- [ ] **Step 3: Implement.**

```python
    submission_override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        help_text="Staff user who submitted despite a failed precheck (#252).",
    )
    submission_override_reason = models.TextField(
        blank=True,
        help_text="Why staff overrode the precheck when submitting (#252).",
    )
```

`can_override_submit(user)` checks, in this order:
1. not staff: "Only staff can override";
2. archived: `ARCHIVED_READ_ONLY_MESSAGE`;
3. `self._latest_file_problem()`, if any;
4. `can_submit()[0]`: "The latest revision passed its precheck; use Submit";
5. `check = self.latest_file.output_check`; `check.pk is None`: "No finished precheck to override yet";
6. `not check.output_gds`: "The precheck produced no processed layout; nothing could be manufactured".

Factor the locked write of `submit()` into `_write_submission(submitted, *, override_by=None, reason="")`, and call it from both `submit()` and `override_submit()`. `override_submit` strips the reason, enforces the length, calls `can_override_submit` (raising `ValidationError(reason)`), then `_write_submission`. Add both new fields to `SYSTEM_FIELDS`.

`ProjectAccessLog`: `SUBMIT_OVERRIDE = "submit_override", "Submitted by override"` and `details = models.TextField(blank=True)`.
- [ ] **Step 4:** Migration; tests pass.
- [ ] **Step 5:** Gate and commit: "feat(projects): staff submit override model and rules (#252)".

### Task 2: Form, view, URL, audit log

**Files:** `wafer_space/projects/forms.py` (`SubmitOverrideForm`), `views.py` (`ProjectOverrideSubmitView`), `urls.py` (`<uuid:pk>/submit-override/`, name `submit_override`), `admin.py` (`ProjectAccessLogAdmin`: `details` in `readonly_fields` and `list_display`), `tests/test_archive_read_only.py` (add `submit_override` to `REFUSED_ON_ARCHIVED`). Test: `wafer_space/projects/tests/test_submit_override_views.py`.

- [ ] **Step 1: Failing tests:**
  - staff POST with a valid reason: 302 to the project page, project submitted with override fields, exactly one `ProjectAccessLog(action=SUBMIT_OVERRIDE, details=reason)`;
  - non-staff owner POST: 403 and nothing changed;
  - stranger: 403;
  - GET: 405;
  - a 19-character reason: redirect with a form error message and nothing saved;
  - refused rule (no layout): error message and nothing saved;
  - archived: the read-only refusal.
- [ ] **Step 2:** Run; expect `NoReverseMatch`.
- [ ] **Step 3: Implement.**
  - `class ProjectOverrideSubmitView(LoginRequiredMixin, ProjectOwnerOrStaffMixin, RefuseArchivedProjectMixin, View)`, with `http_method_names = ["post"]` and `get_object()`.
  - In `post`: if not staff, `raise PermissionDenied`. Validate the form; on error, `messages.error` with the field error. Call `project.override_submit(request.user, reason)`, catching `ValidationError` into `messages.error`. On success, create the log entry: copy the IP and user-agent handling from `ProjectOwnerOrStaffMixin._create_audit_log` by calling a shared helper. Do not duplicate it: refactor `_create_audit_log` to accept `action` and `details` keyword arguments with the current defaults, and call `self._create_audit_log(project, user, request, action=..., details=reason)`.
  - Then `messages.success("Submitted for manufacturing by staff override.")` and redirect to the project page.
  - `SubmitOverrideForm`: `reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), min_length=SUBMIT_OVERRIDE_REASON_MIN_LENGTH, strip=True)`.
- [ ] **Step 4:** Tests pass, including the read-only guard test.
- [ ] **Step 5:** Gate and commit: "feat(projects): staff submit override view and audit log (#252)".

### Task 3: Project page

**Files:** `views.py` (`ProjectDetailView` context: `can_override_submit`, `override_form`), `project_detail.html` (the override form beside the disabled Submit button; the banner in the Submitted File card), test `wafer_space/projects/tests/test_submit_override_detail.py`.

- [ ] **Step 1: Failing tests:**
  - staff on an overridable project sees the form posting to `submit_override` and the text "Submit anyway (staff override)";
  - the owner (non-staff) does not see it;
  - staff on a passing project do not see it;
  - after an override, both the owner and staff see `data-submission-override-banner` with the staff username, the date and the reason.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3: Implement.**
  - Context: `can_override_submit = project.can_override_submit(user)` (it returns early for non-staff), and `override_form = SubmitOverrideForm()`.
  - Template: under the disabled Submit wrapper, `{% if can_override_submit.0 %}` shows a `btn-outline-danger btn-sm` button with `data-bs-toggle="collapse"` targeting `#submit-override-form`, and a collapse `<form method="post" action="{% url 'projects:submit_override' pk=project.pk %}" onsubmit="return confirm('Submit despite the failed precheck? This is recorded with your name and reason.');">` with `{% csrf_token %}`, `{{ override_form.reason }}` and a label.
  - Banner: in the Submitted File card, `{% if project.is_submission_override %}` shows `<div class="alert alert-warning" data-submission-override-banner>`: "Submitted by staff override — {{ project.submission_override_by.username }} on {{ project.submitted_at|date:'Y-m-d H:i' }}: {{ project.submission_override_reason }}".
- [ ] **Step 4:** Pass; djLint.
- [ ] **Step 5:** Gate and commit: "feat(projects): override form and banner on the project page (#252)".

### Task 4: Admin, admin summary, reticle README, docs

**Files:**
- `admin.py`: `ProjectAdmin` read-only fields and an "overridden" list filter (a `SimpleListFilter` on `submission_override_by__isnull`).
- `admin_summary.html`: an "override" badge in the status cell when `project.is_submission_override`.
- `shuttles/services/reticle_package.py` `write_readme`: status gets the suffix ` (staff override)`.
- `docs/manufacturable_vs_submitted.md`: a "Staff override" paragraph under rule 1.
- Tests: append to `test_admin.py`, `test_views_admin_summary.py`, and `shuttles/tests/test_reticle_package_service.py`.

- [ ] **Steps:** failing tests, implement, pass, gate, commit: "feat: mark staff overrides in admin, summary and reticle README (#252)".

### Task 5: Browser test

**File:** `tests/browser/test_projects/test_submit_override.py`.

- [ ] **Steps:**
  - Staff logs in and opens the project from `make_failed_project`.
  - Clicks "Submit anyway (staff override)", types a 30-character reason, and accepts the confirm (`window.confirm = () => true`).
  - Submits; waits for the banner and asserts it shows the reason.
  - The owner logs in and sees the same banner.
  - No `SyntaxError` is logged.
  - Gate and commit: "test(browser): staff submit override round trip (#252)".

## After the tasks

- Playwright walk-through on a local server, with screenshots.
- PR "Fixes #252"; independent review; the gate as in the brief.
- Follow-up when #320/#350 lands: a test that a staff override on a closed shuttle behaves like a staff Submit.
