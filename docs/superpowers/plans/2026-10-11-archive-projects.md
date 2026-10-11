# Archive Projects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let owners and staff archive a project: it sorts last on `/projects/`, becomes read-only, disappears from shuttle slot allocation, and nothing is deleted.

**Architecture:** A nullable `Project.archived_at` timestamp with model-level rules (`is_archived`, `can_be_archived_by`, `can_submit`). One read-only gate (`refuse_if_archived` plus `RefuseArchivedProjectMixin`) guards every project write view, and a guard test fails if a new pk-taking view is not classified. `ShuttleSlot.reserve()` and the assignment page exclude archived projects.

**Tech Stack:** Django 5.2, django-simple-history, pytest-django, factory-boy, Selenium (headless) browser tests.

**Spec:** `docs/superpowers/specs/2026-10-11-archive-projects-design.md`

## Global Constraints

- Nothing is ever deleted by archiving; IDs (`project_id`, pk) never change or get reused.
- Owner may archive unless `submitted_file` is set; staff may archive any project; nobody may archive a project that holds a shuttle slot.
- Owner and staff may unarchive.
- Read-only message, verbatim: `This project is archived and cannot be changed. Unarchive it first.`
- Before every commit: `make lint-fix && make lint && make type-check && make test`; templates also `uv run pre-commit run --files <templates>`. No `# noqa`, no `# type: ignore`.
- Layering: models never import views/services/tasks; views import models and mixins.
- Use `Project.submitted_file`, never `Project.status`, to decide submission.
- Tests pass explicit `name=` to shuttles (never rely on auto-named or migration-seeded G801).

## Review Focus

1. Double-submitted Archive (two tabs): the second POST must give an error message and no change. `can_be_archived_by` returns "already archived" (Task 1 test).
2. Staff archives a project with a submitted file that holds no slot: allowed. A project whose slot was released can then be archived (Task 1 tests).
3. A pending background check finishing on an archived project must still be able to save its result. No model `save()` guard (Task 1 test: `status` update on an archived project saves).
4. Pagination with archived projects on `/projects/`: archived rows still come after every active row across pages (Task 5 test with `paginate_by` overflow).
5. Staff opening another user's archived project and pressing Unarchive: allowed and audit-logged (Task 4 test).

---

### Task 1: Model field and archive rules

**Files:**
- Modify: `wafer_space/projects/models.py` (Project: `SYSTEM_FIELDS`, new field after `submitted_file`, `can_submit()`, new methods after `submit()`; module constant near the top-level validators)
- Create: `wafer_space/projects/migrations/00NN_project_archived_at.py` (via `makemigrations`)
- Test: `wafer_space/projects/tests/test_models_archive.py`

**Interfaces:**
- Produces: `ARCHIVED_READ_ONLY_MESSAGE: str` (module constant in `wafer_space.projects.models`), `Project.archived_at: datetime | None`, `Project.is_archived -> bool`, `Project.can_be_archived_by(user: User) -> tuple[bool, str]`, `Project.archive() -> None`, `Project.unarchive() -> None`.

- [ ] **Step 1: Write the failing tests** in `wafer_space/projects/tests/test_models_archive.py`:

```python
"""Archive rules on Project (issue #307)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from wafer_space.projects.models import ARCHIVED_READ_ONLY_MESSAGE
from wafer_space.projects.models import Project
from wafer_space.shuttles.models import Shuttle
from wafer_space.shuttles.models import ShuttleSlot
from wafer_space.users.tests.factories import UserFactory

from .factories import ProjectFactory
from .factories import ProjectFileFactory

pytestmark = pytest.mark.django_db


def make_slot_holding(project: Project) -> ShuttleSlot:
    shuttle = Shuttle.objects.create(name="G880", description="Archive test")
    return ShuttleSlot.objects.create(
        shuttle=shuttle,
        project=project,
        status=ShuttleSlot.Status.RESERVED,
        row=0,
        column=0,
    )


def test_new_project_is_not_archived() -> None:
    assert ProjectFactory().is_archived is False


def test_archive_sets_archived_at() -> None:
    project = ProjectFactory()
    project.archive()
    project.refresh_from_db()
    assert project.archived_at is not None


def test_unarchive_clears_archived_at() -> None:
    project = ProjectFactory(archived_at=timezone.now())
    project.unarchive()
    project.refresh_from_db()
    assert project.archived_at is None


def test_archive_is_recorded_in_history() -> None:
    project = ProjectFactory()
    project.archive()
    assert project.history.first().archived_at is not None


def test_can_submit_refuses_archived_project() -> None:
    project = ProjectFactory(archived_at=timezone.now())
    assert project.can_submit() == (False, ARCHIVED_READ_ONLY_MESSAGE)


def test_owner_can_archive_own_draft() -> None:
    project = ProjectFactory()
    assert project.can_be_archived_by(project.user) == (True, "")


def test_owner_cannot_archive_project_with_submitted_file() -> None:
    project = ProjectFactory()
    project.submitted_file = ProjectFileFactory(project=project)
    project.save()
    allowed, reason = project.can_be_archived_by(project.user)
    assert allowed is False
    assert "submitted for manufacturing" in reason


def test_staff_can_archive_project_with_submitted_file() -> None:
    project = ProjectFactory()
    project.submitted_file = ProjectFileFactory(project=project)
    project.save()
    staff = UserFactory(is_staff=True)
    assert project.can_be_archived_by(staff) == (True, "")


def test_nobody_can_archive_project_holding_a_slot() -> None:
    project = ProjectFactory()
    make_slot_holding(project)
    staff = UserFactory(is_staff=True)
    allowed, reason = project.can_be_archived_by(staff)
    assert allowed is False
    assert "shuttle slot" in reason


def test_project_can_be_archived_after_slot_released() -> None:
    project = ProjectFactory()
    slot = make_slot_holding(project)
    slot.cancel_reservation()
    assert project.can_be_archived_by(project.user) == (True, "")


def test_already_archived_project_cannot_be_archived_again() -> None:
    project = ProjectFactory(archived_at=timezone.now())
    assert project.can_be_archived_by(project.user) == (
        False,
        "Project is already archived",
    )


def test_background_status_update_saves_on_archived_project() -> None:
    project = ProjectFactory(archived_at=timezone.now())
    project.status = Project.Status.MANUFACTURABLE
    project.save(update_fields=["status"])
    project.refresh_from_db()
    assert project.status == Project.Status.MANUFACTURABLE
```

Note: `ProjectFileFactory` may need extra required fields. If creating it fails, read `wafer_space/projects/tests/factories.py` and `ProjectFile` to supply them. Do not change the factory's defaults.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_models_archive.py -q`
Expected: collection ERROR, `ImportError: cannot import name 'ARCHIVED_READ_ONLY_MESSAGE'`.

- [ ] **Step 3: Implement** in `wafer_space/projects/models.py`:

Module constant (beside the other module-level constants/validators):

```python
ARCHIVED_READ_ONLY_MESSAGE = (
    "This project is archived and cannot be changed. Unarchive it first."
)
```

Add `"archived_at"` to `Project.SYSTEM_FIELDS`. Add the field after `submitted_file`:

```python
    # Archiving (Issue #307): hides nothing and deletes nothing; an archived
    # project sorts last, is read-only, and is excluded from slot allocation.
    archived_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When the project was archived; empty while active.",
    )
```

At the top of `can_submit()` (before `active_file = self.latest_file`):

```python
        if self.is_archived:
            return False, ARCHIVED_READ_ONLY_MESSAGE
```

After `submit()`:

```python
    @property
    def is_archived(self) -> bool:
        """Whether the project is archived (see archived_at)."""
        return self.archived_at is not None

    def can_be_archived_by(self, user: Any) -> tuple[bool, str]:
        """Check whether ``user`` may archive this project.

        The caller has already established that ``user`` is the owner or
        staff. Returns (allowed, reason_if_not).
        """
        if self.is_archived:
            return False, "Project is already archived"
        if self.shuttle_slots.exists():
            return False, (
                "This project holds a shuttle slot. Staff must remove the "
                "slot assignment before it can be archived."
            )
        if self.submitted_file_id is not None and not user.is_staff:
            return False, (
                "This project has a file submitted for manufacturing. "
                "Contact staff to archive it."
            )
        return True, ""

    def archive(self) -> None:
        """Mark the project archived now. Permission checks are the caller's."""
        self.archived_at = timezone.now()
        self.save(update_fields=["archived_at", "updated_at"])

    def unarchive(self) -> None:
        """Make the project active again. Permission checks are the caller's."""
        self.archived_at = None
        self.save(update_fields=["archived_at", "updated_at"])
```

(`shuttle_slots` is the reverse name of `ShuttleSlot.project`; `Any` and `timezone` are already imported in models.py. Check with `grep -n "^from\|^import" wafer_space/projects/models.py`.)

Check whether `Project.save()` or `clean()` runs the core-field immutability guard on `update_fields` saves. If `archive()` raises the `_loaded_values` RuntimeError on a factory-made instance, the test exposes it. Fix it by reloading in the test (`Project.objects.get(pk=...)`), not by weakening the guard.

- [ ] **Step 4: Create the migration**

Run: `DJANGO_SETTINGS_MODULE=config.settings.dev uv run python manage.py makemigrations projects -n project_archived_at`
Expected: one migration adding `archived_at` to `project` and `historicalproject`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_models_archive.py -q`
Expected: all pass.

- [ ] **Step 6: Gate and commit**

```bash
make lint-fix && make lint && make type-check && make test
git add wafer_space/projects/models.py wafer_space/projects/migrations/*_project_archived_at.py wafer_space/projects/tests/test_models_archive.py docs/superpowers
git commit -m "feat(projects): add Project.archived_at and archive rules (#307)"
```

---

### Task 2: Shuttle slot allocation excludes archived projects

**Files:**
- Modify: `wafer_space/shuttles/models.py` (`ShuttleSlot.reserve`, top of method)
- Modify: `wafer_space/shuttles/views.py` (`ShuttleAssignmentView.get_context_data`, the `all_projects` query near line 73)
- Test: `wafer_space/shuttles/tests/test_models.py`, `wafer_space/shuttles/tests/test_views.py` (append)

**Interfaces:**
- Consumes: `Project.is_archived`, `Project.archived_at` (Task 1).
- Produces: `ShuttleSlot.reserve()` raises `ValueError("Project is archived and cannot be assigned to a slot")`.

- [ ] **Step 1: Write the failing tests.** Append to `wafer_space/shuttles/tests/test_models.py`, matching its import style:

```python
@pytest.mark.django_db
def test_reserve_refuses_archived_project() -> None:
    shuttle = Shuttle.objects.create(name="G881", description="Archive test")
    slot = ShuttleSlot.objects.create(shuttle=shuttle, row=0, column=0)
    project = ProjectFactory(shuttle=shuttle, archived_at=timezone.now())
    with pytest.raises(ValueError, match="archived"):
        slot.reserve(project, UserFactory(is_staff=True))
    slot.refresh_from_db()
    assert slot.project is None
```

Append to `wafer_space/shuttles/tests/test_views.py`, using that file's existing staff-client setup (read its top first and reuse its fixtures/helpers):

```python
@pytest.mark.django_db
def test_assignment_page_omits_archived_projects(client) -> None:
    staff = UserFactory(is_staff=True)
    client.force_login(staff)
    shuttle = Shuttle.objects.create(name="G882", description="Archive test")
    active = ProjectFactory(shuttle=shuttle, name="Active one")
    archived = ProjectFactory(
        shuttle=shuttle, name="Archived one", archived_at=timezone.now()
    )
    response = client.get(reverse("shuttles:assignment", args=[shuttle.name]))
    pks = {p.pk for p in response.context["projects"]}
    assert active.pk in pks
    assert archived.pk not in pks
    data_pks = {str(d["pk"]) for d in response.context["projects_data"]}
    assert str(archived.pk) not in data_pks
```

Read how `projects_data` entries are keyed in `ShuttleAssignmentView` (around line 147) and use the real key name in the last assertion.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest wafer_space/shuttles/tests/test_models.py wafer_space/shuttles/tests/test_views.py -q -k archived`
Expected: 2 failed. `reserve` does not raise, and the archived project appears in the list.

- [ ] **Step 3: Implement.** In `ShuttleSlot.reserve`, first statement after `warnings = []`:

```python
        if project.is_archived:
            msg = "Project is archived and cannot be assigned to a slot"
            raise ValueError(msg)
```

In `ShuttleAssignmentView`, change the `all_projects` query to exclude archived projects:

```python
        all_projects = list(
            shuttle.projects.filter(archived_at__isnull=True)
            .select_related("user")
            .prefetch_related("shuttle_slots")
            ...  # keep the rest of the existing chain unchanged
        )
```

- [ ] **Step 4: Run to verify they pass** (the same command; expected 2 passed).

- [ ] **Step 5: Gate and commit**

```bash
make lint-fix && make lint && make type-check && make test
git add wafer_space/shuttles/models.py wafer_space/shuttles/views.py wafer_space/shuttles/tests/test_models.py wafer_space/shuttles/tests/test_views.py
git commit -m "feat(shuttles): exclude archived projects from slot allocation (#307)"
```

---

### Task 3: Read-only gate for archived projects

**Files:**
- Modify: `wafer_space/projects/mixins.py` (new function and mixin at the end)
- Modify: `wafer_space/projects/views.py` (`ProjectUpdateView`, `ProjectFileSubmitURLView`, `ProjectSubmitView`, `check_drc_update_requeue`)
- Modify: `wafer_space/projects/views_compliance.py` (`compliance_certification_create`)
- Test: `wafer_space/projects/tests/test_archive_read_only.py`

**Interfaces:**
- Consumes: `ARCHIVED_READ_ONLY_MESSAGE`, `Project.is_archived` (Task 1).
- Produces: `refuse_if_archived(request: HttpRequest, project: Project) -> HttpResponseRedirect | None` and `class RefuseArchivedProjectMixin`, both in `wafer_space.projects.mixins`. The mixin requires the view to have `get_object()` returning the Project, and must come **after** `ProjectOwnerOrStaffMixin` in the bases.

- [ ] **Step 1: Write the failing tests** in `wafer_space/projects/tests/test_archive_read_only.py`:

```python
"""Archived projects are read-only (issue #307)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import URLPattern
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects import urls as project_urls
from wafer_space.projects.models import ARCHIVED_READ_ONLY_MESSAGE
from wafer_space.projects.models import Project

from .constants import HTTP_FOUND
from .factories import ManufacturabilityCheckFactory
from .factories import ProjectFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db

# Every projects URL that takes a project pk is either allowed on an
# archived project or refused. A new pk URL must be added to one of these.
ALLOWED_ON_ARCHIVED = {
    "detail",  # read only
    "progress",  # read only (AJAX)
    "check_status",  # read only (AJAX)
    "cancel_check",  # staff stopping a running check: clean-up
    "unarchive",  # the one write allowed
    "delete",  # decided in #344
}
REFUSED_ON_ARCHIVED = {"update", "submit", "submit_url", "archive", "compliance_certify"}


def pk_url_names() -> set[str]:
    return {
        p.name
        for p in project_urls.urlpatterns
        if isinstance(p, URLPattern) and "<uuid:pk>" in str(p.pattern)
    }


def test_every_project_pk_url_is_classified() -> None:
    assert pk_url_names() == ALLOWED_ON_ARCHIVED | REFUSED_ON_ARCHIVED


@pytest.fixture
def archived_project() -> Project:
    project = ProjectFactory(archived_at=timezone.now())
    return Project.objects.get(pk=project.pk)


@pytest.fixture
def owner_client(client: Client, archived_project: Project) -> Client:
    client.force_login(archived_project.user)
    return client


@pytest.mark.parametrize("name", sorted(REFUSED_ON_ARCHIVED))
@pytest.mark.parametrize("method", ["get", "post"])
def test_write_views_refuse_archived_project(
    owner_client: Client, archived_project: Project, name: str, method: str
) -> None:
    before = archived_project.updated_at
    url = reverse(f"projects:{name}", args=[archived_project.pk])
    response = getattr(owner_client, method)(url, {"name": "Changed"})
    assert response.status_code == HTTP_FOUND
    assert response["Location"] == reverse(
        "projects:detail", args=[archived_project.pk]
    )
    archived_project.refresh_from_db()
    assert archived_project.updated_at == before
    assert archived_project.name != "Changed"


def test_refusal_shows_read_only_message(
    owner_client: Client, archived_project: Project
) -> None:
    url = reverse("projects:update", args=[archived_project.pk])
    response = owner_client.post(url, {"name": "Changed"}, follow=True)
    assert ARCHIVED_READ_ONLY_MESSAGE in response.content.decode()


def test_drc_requeue_refuses_archived_project(
    owner_client: Client, archived_project: Project
) -> None:
    check = ManufacturabilityCheckFactory(project_file__project=archived_project)
    url = reverse("projects:check_drc_update_requeue", args=[check.pk])
    response = owner_client.post(url, follow=True)
    assert ARCHIVED_READ_ONLY_MESSAGE in response.content.decode()
    assert archived_project.files.count() == 1  # no new check revision


def test_active_project_edit_page_still_opens(client: Client) -> None:
    project = ProjectFactory()
    client.force_login(project.user)
    response = client.get(reverse("projects:update", args=[project.pk]))
    assert response.status_code == 200  # noqa-free: plain literal is fine in tests
```

Replace the last line's literal with `HTTP_OK` from `.constants`, and drop the comment. Read `ManufacturabilityCheckFactory` first. If it has no `project_file` SubFactory chain, build the `ProjectFile` with `ProjectFileFactory(project=archived_project)` and pass it. Change the last assertion of the requeue test to check that no new `ManufacturabilityCheck` was created: count before and after.

The `"archive"` URL does not exist until Task 4. Until then, mark `test_every_project_pk_url_is_classified` and the `archive` parametrization with `pytest.mark.xfail(strict=True, reason="archive view added in Task 4")`, and remove the xfail in Task 4. Do the same for `unarchive`: the classification test fails until both exist.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_archive_read_only.py -q`
Expected: the refusal tests FAIL. For example, `update` GET returns 200, and POST saves or re-renders.

- [ ] **Step 3: Implement** at the end of `wafer_space/projects/mixins.py`:

```python
def refuse_if_archived(
    request: HttpRequest, project: Project
) -> HttpResponseRedirect | None:
    """Refuse a write to an archived project (issue #307).

    Returns a redirect to the project page with an error message when the
    project is archived, or None when the caller may proceed. The single
    place the read-only rule lives; RefuseArchivedProjectMixin calls it.
    """
    if not project.is_archived:
        return None
    messages.error(request, ARCHIVED_READ_ONLY_MESSAGE)
    return redirect("projects:detail", pk=project.pk)


class RefuseArchivedProjectMixin:
    """Refuse every method on an archived project's write view.

    Place after ProjectOwnerOrStaffMixin in the bases so the permission
    check runs first. The view must provide get_object() -> Project.
    """

    request: HttpRequest

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        refusal = refuse_if_archived(request, self.get_object())  # type: ignore[attr-defined]
        if refusal is not None:
            return refusal
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]
```

The two `# type: ignore` above are **not allowed** (Global Constraints). Instead, declare the dependency so mypy is satisfied: give the mixin a typed stub `def get_object(self) -> Project: ...` and a `dispatch` that calls `super().dispatch` through a `View` base. That is, make `RefuseArchivedProjectMixin(View)`, because every user is a View subclass. Then confirm the MRO still runs `ProjectOwnerOrStaffMixin`'s test first. Check with a unit test that a stranger gets 403, not the archived redirect, on an archived project's update URL. Add that test:

```python
def test_stranger_gets_403_not_archive_redirect(
    client: Client, archived_project: Project
) -> None:
    client.force_login(UserFactory())
    url = reverse("projects:update", args=[archived_project.pk])
    assert client.get(url).status_code == HTTP_FORBIDDEN
```

Imports needed in mixins.py: `from django.contrib import messages`, `from django.shortcuts import redirect`, `from django.http import HttpResponseRedirect`, and `ARCHIVED_READ_ONLY_MESSAGE` from `.models`. Check what is already imported and keep `TYPE_CHECKING` blocks consistent.

Apply:
- `class ProjectUpdateView(LoginRequiredMixin, ProjectOwnerOrStaffMixin, RefuseArchivedProjectMixin, UpdateView)`
- the same insertion for `ProjectFileSubmitURLView` and `ProjectSubmitView`.
- `check_drc_update_requeue`: after the permission check,
  `refusal = refuse_if_archived(request, check.project)`, then `if refusal is not None: return refusal`.
- `compliance_certification_create`: the same, right after `project = get_object_or_404(...)`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_archive_read_only.py wafer_space/projects/tests/test_views.py wafer_space/projects/tests/test_mixins.py -q`
Expected: all pass except the strict xfails.

- [ ] **Step 5: Gate and commit**

```bash
make lint-fix && make lint && make type-check && make test
git add wafer_space/projects/mixins.py wafer_space/projects/views.py wafer_space/projects/views_compliance.py wafer_space/projects/tests/test_archive_read_only.py
git commit -m "feat(projects): archived projects are read-only (#307)"
```

---

### Task 4: Archive and unarchive views

**Files:**
- Modify: `wafer_space/projects/views.py` (two views after `ProjectSubmitView`)
- Modify: `wafer_space/projects/urls.py` (two paths after `submit`)
- Test: `wafer_space/projects/tests/test_archive_views.py`; remove the Task 3 xfails

**Interfaces:**
- Consumes: `can_be_archived_by`, `archive`, `unarchive` (Task 1); `ProjectOwnerOrStaffMixin`.
- Produces: URL names `projects:archive` and `projects:unarchive` (POST, `<uuid:pk>`).

- [ ] **Step 1: Write the failing tests** in `wafer_space/projects/tests/test_archive_views.py`:

```python
"""Archive and unarchive views (issue #307)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects.models import Project
from wafer_space.projects.models import ProjectAccessLog
from wafer_space.users.tests.factories import UserFactory

from .constants import HTTP_FORBIDDEN
from .constants import HTTP_FOUND
from .constants import HTTP_METHOD_NOT_ALLOWED
from .factories import ProjectFactory
from .factories import ProjectFileFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def archive_url(project: Project) -> str:
    return reverse("projects:archive", args=[project.pk])


def unarchive_url(project: Project) -> str:
    return reverse("projects:unarchive", args=[project.pk])


def test_owner_archives_project(client: Client) -> None:
    project = ProjectFactory()
    client.force_login(project.user)
    response = client.post(archive_url(project))
    assert response.status_code == HTTP_FOUND
    project.refresh_from_db()
    assert project.is_archived


def test_owner_unarchives_project(client: Client) -> None:
    project = ProjectFactory(archived_at=timezone.now())
    client.force_login(project.user)
    client.post(unarchive_url(project))
    project.refresh_from_db()
    assert not project.is_archived


def test_owner_refused_with_submitted_file(client: Client) -> None:
    project = ProjectFactory()
    project.submitted_file = ProjectFileFactory(project=project)
    project.save()
    client.force_login(project.user)
    response = client.post(archive_url(project), follow=True)
    project.refresh_from_db()
    assert not project.is_archived
    assert "Contact staff to archive it" in response.content.decode()


def test_staff_archives_other_users_project_and_is_logged(client: Client) -> None:
    project = ProjectFactory()
    staff = UserFactory(is_staff=True)
    client.force_login(staff)
    client.post(archive_url(project))
    project.refresh_from_db()
    assert project.is_archived
    assert ProjectAccessLog.objects.filter(
        project=project, admin_user=staff, view_name="ProjectArchiveView"
    ).exists()


def test_staff_unarchives_other_users_project_and_is_logged(client: Client) -> None:
    project = ProjectFactory(archived_at=timezone.now())
    staff = UserFactory(is_staff=True)
    client.force_login(staff)
    client.post(unarchive_url(project))
    project.refresh_from_db()
    assert not project.is_archived
    assert ProjectAccessLog.objects.filter(
        project=project, admin_user=staff, view_name="ProjectUnarchiveView"
    ).exists()


def test_stranger_cannot_archive(client: Client) -> None:
    project = ProjectFactory()
    client.force_login(UserFactory())
    assert client.post(archive_url(project)).status_code == HTTP_FORBIDDEN


def test_get_archive_not_allowed(client: Client) -> None:
    project = ProjectFactory()
    client.force_login(project.user)
    assert client.get(archive_url(project)).status_code == HTTP_METHOD_NOT_ALLOWED


def test_second_archive_post_changes_nothing(client: Client) -> None:
    project = ProjectFactory()
    client.force_login(project.user)
    client.post(archive_url(project))
    project.refresh_from_db()
    first = project.archived_at
    response = client.post(archive_url(project), follow=True)
    project.refresh_from_db()
    assert project.archived_at == first
    assert "already archived" in response.content.decode()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_archive_views.py -q`
Expected: `NoReverseMatch` for `projects:archive`.

- [ ] **Step 3: Implement** in `views.py` after `ProjectSubmitView`:

```python
class ProjectArchiveView(LoginRequiredMixin, ProjectOwnerOrStaffMixin, View):
    """Archive a project (POST-only). Nothing is deleted (issue #307)."""

    http_method_names: ClassVar[list[str]] = ["post"]

    def get_object(self) -> Project:
        """Get the project object for permission checking."""
        return get_object_or_404(Project, pk=self.kwargs["pk"])

    def post(self, request: HttpRequest, pk: UUID) -> HttpResponse:
        """Archive the project if the rules allow it."""
        project = self.get_object()
        allowed, reason = project.can_be_archived_by(request.user)
        if not allowed:
            messages.error(request, f"Cannot archive project: {reason}")
        else:
            project.archive()
            messages.success(
                request,
                f"Project '{project.name}' archived. It is read-only and "
                "listed last on your projects page.",
            )
        return redirect("projects:detail", pk=pk)


class ProjectUnarchiveView(LoginRequiredMixin, ProjectOwnerOrStaffMixin, View):
    """Unarchive a project (POST-only)."""

    http_method_names: ClassVar[list[str]] = ["post"]

    def get_object(self) -> Project:
        """Get the project object for permission checking."""
        return get_object_or_404(Project, pk=self.kwargs["pk"])

    def post(self, request: HttpRequest, pk: UUID) -> HttpResponse:
        """Make the project active again."""
        project = self.get_object()
        if not project.is_archived:
            messages.info(request, "Project is not archived.")
        else:
            project.unarchive()
            messages.success(request, f"Project '{project.name}' unarchived.")
        return redirect("projects:detail", pk=pk)
```

Check which of `ClassVar`, `UUID`, `HttpRequest` and `HttpResponse` views.py already imports, and add only the missing ones (`UUID` under `TYPE_CHECKING` if the file does that).

In `urls.py`, after the submit path:

```python
    path("<uuid:pk>/archive/", views.ProjectArchiveView.as_view(), name="archive"),
    path(
        "<uuid:pk>/unarchive/",
        views.ProjectUnarchiveView.as_view(),
        name="unarchive",
    ),
```

Remove the Task 3 `xfail` markers.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest wafer_space/projects/tests/test_archive_views.py wafer_space/projects/tests/test_archive_read_only.py -q`
Expected: all pass.

- [ ] **Step 5: Gate and commit**

```bash
make lint-fix && make lint && make type-check && make test
git add wafer_space/projects/views.py wafer_space/projects/urls.py wafer_space/projects/tests/test_archive_views.py wafer_space/projects/tests/test_archive_read_only.py
git commit -m "feat(projects): archive and unarchive views (#307)"
```

---

### Task 5: Project list sorts archived projects last

**Files:**
- Modify: `wafer_space/projects/views.py` (`ProjectListView.get_queryset`)
- Modify: `wafer_space/templates/projects/project_list.html` (row title line)
- Test: `wafer_space/projects/tests/test_archive_list.py`

**Interfaces:**
- Consumes: `Project.archived_at`, `Project.is_archived`.

- [ ] **Step 1: Write the failing tests** in `wafer_space/projects/tests/test_archive_list.py`:

```python
"""Archived projects sort last on /projects/ (issue #307)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects.models import Project
from wafer_space.users.tests.factories import UserFactory

from .factories import ProjectFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def make_projects(user) -> tuple[Project, Project, Project]:
    now = timezone.now()
    old_active = ProjectFactory(user=user, name="Old active")
    new_archived = ProjectFactory(user=user, name="New archived", archived_at=now)
    new_active = ProjectFactory(user=user, name="New active")
    # created_at is auto_now_add; set explicit order.
    Project.objects.filter(pk=old_active.pk).update(created_at=now - timedelta(days=3))
    Project.objects.filter(pk=new_archived.pk).update(created_at=now - timedelta(days=1))
    Project.objects.filter(pk=new_active.pk).update(created_at=now - timedelta(days=2))
    return old_active, new_archived, new_active


def test_owner_list_has_archived_last(client: Client) -> None:
    user = UserFactory()
    old_active, new_archived, new_active = make_projects(user)
    client.force_login(user)
    response = client.get(reverse("projects:list"))
    names = [p.name for p in response.context["projects"]]
    assert names == ["New active", "Old active", "New archived"]


def test_staff_list_has_archived_last(client: Client) -> None:
    make_projects(UserFactory())
    client.force_login(UserFactory(is_staff=True))
    response = client.get(reverse("projects:list"))
    names = [p.name for p in response.context["projects"]]
    assert names[-1] == "New archived"


def test_archived_row_has_badge(client: Client) -> None:
    user = UserFactory()
    make_projects(user)
    client.force_login(user)
    content = client.get(reverse("projects:list")).content.decode()
    assert content.count('data-archived-badge') == 1


def test_archived_projects_after_all_active_across_pages(client: Client) -> None:
    user = UserFactory()
    archived = ProjectFactory(user=user, name="Archived", archived_at=timezone.now())
    for i in range(20):
        ProjectFactory(user=user, name=f"Active {i}")
    client.force_login(user)
    first = client.get(reverse("projects:list"))
    assert archived.pk not in {p.pk for p in first.context["projects"]}
    second = client.get(reverse("projects:list") + "?page=2")
    assert [p.pk for p in second.context["projects"]] == [archived.pk]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_archive_list.py -q`
Expected: order and badge tests FAIL.

- [ ] **Step 3: Implement.** In `ProjectListView.get_queryset`, define the ordering once:

```python
        # Archived projects come last, each group newest first (issue #307).
        is_archived = ExpressionWrapper(
            Q(archived_at__isnull=False), output_field=BooleanField()
        )
        if user.is_staff:
            queryset = Project.objects.all().select_related("user")
        else:
            queryset = Project.objects.filter(user=user)
        return queryset.annotate(is_archived_sort=is_archived).order_by(
            "is_archived_sort", "-created_at"
        )
```

(Imports: `BooleanField`, `ExpressionWrapper` and `Q` from `django.db.models`; check what is already imported.)

In `project_list.html`, inside the title `<h5>` after the Submitted/Draft badge block:

```django
                    {% if project.is_archived %}
                      <span class="badge bg-secondary" data-archived-badge title="Archived: read-only"><i class="bi bi-archive"></i> Archived</span>
                    {% endif %}
```

and add `{% if project.is_archived %} text-muted{% endif %}` to the row's `list-group-item` class.

- [ ] **Step 4: Run to verify they pass** (the same command).

- [ ] **Step 5: Gate and commit**

```bash
make lint-fix && make lint && make type-check && make test
uv run pre-commit run --files wafer_space/templates/projects/project_list.html
git add wafer_space/projects/views.py wafer_space/templates/projects/project_list.html wafer_space/projects/tests/test_archive_list.py
git commit -m "feat(projects): list archived projects last with a badge (#307)"
```

---

### Task 6: Detail page buttons and read-only state

**Files:**
- Modify: `wafer_space/templates/projects/project_detail.html` (header near line 14, Edit button near line 109, Submit New File URL near lines 227 and 251, Submit form near line 281)
- Modify: `wafer_space/templates/projects/_manufacturability_check.html` (Recheck form near line 26)
- Modify: `wafer_space/projects/views.py` (`ProjectDetailView.get_context_data`: add `can_archive`)
- Test: `wafer_space/projects/tests/test_archive_detail.py`

**Interfaces:**
- Consumes: `can_be_archived_by`, `is_archived`, `ARCHIVED_READ_ONLY_MESSAGE`, URL names `projects:archive` and `projects:unarchive`.
- Produces: context keys `can_archive: tuple[bool, str]` and `archived_read_only_message: str` on the detail view.

- [ ] **Step 1: Write the failing tests** in `wafer_space/projects/tests/test_archive_detail.py`:

```python
"""Project detail page in archived and active states (issue #307)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.urls import reverse
from django.utils import timezone

from wafer_space.projects.models import ARCHIVED_READ_ONLY_MESSAGE

from .factories import ProjectFactory
from .factories import ProjectFileFactory

if TYPE_CHECKING:
    from django.test import Client

pytestmark = pytest.mark.django_db


def detail(client: Client, project) -> str:
    client.force_login(project.user)
    return client.get(reverse("projects:detail", args=[project.pk])).content.decode()


def test_active_project_shows_archive_form(client: Client) -> None:
    project = ProjectFactory()
    assert reverse("projects:archive", args=[project.pk]) in detail(client, project)


def test_archived_project_shows_unarchive_form_and_banner(client: Client) -> None:
    project = ProjectFactory(archived_at=timezone.now())
    content = detail(client, project)
    assert reverse("projects:unarchive", args=[project.pk]) in content
    assert "This project was archived on" in content


def test_archived_project_hides_edit_and_file_links(client: Client) -> None:
    project = ProjectFactory(archived_at=timezone.now())
    content = detail(client, project)
    assert reverse("projects:update", args=[project.pk]) not in content
    assert reverse("projects:submit_url", args=[project.pk]) not in content
    assert ARCHIVED_READ_ONLY_MESSAGE in content


def test_archive_button_disabled_with_reason_for_owner_with_submitted_file(
    client: Client,
) -> None:
    project = ProjectFactory()
    project.submitted_file = ProjectFileFactory(project=project)
    project.save()
    content = detail(client, project)
    assert reverse("projects:archive", args=[project.pk]) not in content
    assert "Contact staff to archive it" in content
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest wafer_space/projects/tests/test_archive_detail.py -q`
Expected: all fail.

- [ ] **Step 3: Implement.**
  - `ProjectDetailView.get_context_data`: `context["can_archive"] = project.can_be_archived_by(user)`, and `context["archived_read_only_message"] = ARCHIVED_READ_ONLY_MESSAGE`. Import the constant from `.models`.
  - `project_detail.html`, right after the admin warning banner include:

```django
        {% if project.is_archived %}
          <div class="alert alert-secondary d-flex justify-content-between align-items-center"
               role="status">
            <div>
              <i class="bi bi-archive me-2" aria-hidden="true"></i>
              This project was archived on {{ project.archived_at|date:"Y-m-d" }}. It is read-only.
            </div>
            <form action="{% url 'projects:unarchive' pk=project.pk %}" method="post">
              {% csrf_token %}
              <button type="submit" class="btn btn-sm btn-outline-secondary">
                <i class="bi bi-box-arrow-up"></i> Unarchive
              </button>
            </form>
          </div>
        {% endif %}
```

  - Header: wrap the existing Admin button and a new Archive control in `<div class="d-flex gap-2">`. The Archive control is shown when the project is not archived:

```django
            {% if not project.is_archived %}
              {% if can_archive.0 %}
                <form action="{% url 'projects:archive' pk=project.pk %}"
                      method="post"
                      onsubmit="return confirm('Archive this project? It will move to the end of your project list and become read-only. Nothing is deleted and you can unarchive it at any time.');">
                  {% csrf_token %}
                  <button type="submit" class="btn btn-outline-secondary">
                    <i class="bi bi-archive"></i> Archive
                  </button>
                </form>
              {% else %}
                <button type="button"
                        class="btn btn-outline-secondary"
                        disabled
                        data-bs-toggle="tooltip"
                        data-bs-placement="top"
                        title="{{ can_archive.1 }}">
                  <i class="bi bi-archive"></i> Archive
                </button>
              {% endif %}
            {% endif %}
```

  - Edit link and both "Submit New File URL"/"Retry Download" links: `{% if project.is_archived %}` render a disabled `<button type="button" class="<same classes>" disabled title="{{ archived_read_only_message }}">` with the same icon and label; `{% else %}` keep the existing `<a>`.
  - The Submit form already disables itself through `can_submit` (Task 1 returns the archived message). No change is needed; confirm it in the browser test.
  - `_manufacturability_check.html` Recheck form: wrap it in `{% if not check.project.is_archived %}`.

- [ ] **Step 4: Run to verify they pass**, then run the whole projects test directory:

Run: `uv run pytest wafer_space/projects/tests -q -x`

- [ ] **Step 5: Gate and commit**

```bash
make lint-fix && make lint && make type-check && make test
uv run pre-commit run --files wafer_space/templates/projects/project_detail.html wafer_space/templates/projects/_manufacturability_check.html
git add wafer_space/projects/views.py wafer_space/templates/projects/project_detail.html wafer_space/templates/projects/_manufacturability_check.html wafer_space/projects/tests/test_archive_detail.py
git commit -m "feat(projects): archive/unarchive controls and read-only detail page (#307)"
```

---

### Task 7: Admin filter and admin summary badge

**Files:**
- Modify: `wafer_space/projects/admin.py` (`ProjectAdmin.list_filter`, `readonly_fields`)
- Modify: `wafer_space/templates/projects/admin_summary.html` (name cell)
- Test: `wafer_space/projects/tests/test_admin.py` and `wafer_space/projects/tests/test_views_admin_summary.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `test_admin.py`:

```python
def test_project_admin_filters_and_shows_archived_at() -> None:
    from django.contrib.admin.sites import site

    project_admin = site._registry[Project]
    assert "archived_at" in project_admin.list_filter
    assert "archived_at" in project_admin.readonly_fields
```

Move the import to the top of the file, and avoid `site._registry`: ruff SLF001 flags it. Instead, instantiate `ProjectAdmin(Project, AdminSite())`, as the file's existing tests do.

Append to `test_views_admin_summary.py`, following its existing staff-client setup:

```python
def test_summary_marks_archived_project(...):
    # archived project's row contains data-archived-badge
```

Write the body using that file's existing fixtures: create one archived project, GET `projects:admin_summary` as staff, and assert that `'data-archived-badge'` appears exactly once.

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement.** Append `"archived_at"` to `ProjectAdmin.list_filter` and to `readonly_fields`. In `admin_summary.html`, after the project name in the name cell, add the same badge markup as Task 5.
- [ ] **Step 4: Run to verify they pass.**
- [ ] **Step 5: Gate and commit**

```bash
make lint-fix && make lint && make type-check && make test
uv run pre-commit run --files wafer_space/templates/projects/admin_summary.html
git add wafer_space/projects/admin.py wafer_space/templates/projects/admin_summary.html wafer_space/projects/tests/test_admin.py wafer_space/projects/tests/test_views_admin_summary.py
git commit -m "feat(projects): archived filter in admin and badge on summary (#307)"
```

---

### Task 8: Browser test of the archive round trip

**Files:**
- Create: `tests/browser/test_projects/test_archive_project.py`

- [ ] **Step 1: Write the test.** Follow `tests/browser/test_projects/test_crowdsupply_campaign_link.py` for setup: user, verified EmailAddress, ToS acceptance, a `login()` helper, `@pytest.mark.browser`, and `@pytest.mark.django_db(transaction=True)`. Then:

```python
    def test_archive_round_trip(self):
        """Archive moves the project last and locks it; unarchive restores it."""
        newer = Project.objects.create(user=self.user, name="Keep me")
        older = Project.objects.create(user=self.user, name="Abandon me")
        Project.objects.filter(pk=older.pk).update(
            created_at=timezone.now() - timedelta(days=1)
        )
        Project.objects.filter(pk=newer.pk).update(created_at=timezone.now())
        self.login()

        # Archive "Keep me" (the newest) so the order change is visible.
        self.navigate_to(self.driver, f"/projects/{newer.pk}/")
        self.wait_for_page_load(self.driver)
        self.driver.execute_script("window.confirm = () => true;")
        self.driver.find_element(
            By.CSS_SELECTOR, f'form[action="/projects/{newer.pk}/archive/"] button'
        ).click()
        self.wait_for_element(self.driver, (By.CSS_SELECTOR, ".alert-secondary"))

        # The Edit control is disabled.
        edit = self.driver.find_element(By.XPATH, "//button[contains(., 'Edit')]")
        assert edit.get_attribute("disabled") is not None

        # On /projects/ it is now last, with the badge.
        self.navigate_to(self.driver, "/projects/")
        self.wait_for_page_load(self.driver)
        titles = [
            e.text for e in self.driver.find_elements(By.CSS_SELECTOR, ".list-group-item h5 a")
        ]
        assert titles == ["Abandon me", "Keep me"]
        assert len(self.driver.find_elements(By.CSS_SELECTOR, "[data-archived-badge]")) == 1

        # Unarchive from its page; it returns to first place.
        self.navigate_to(self.driver, f"/projects/{newer.pk}/")
        self.wait_for_page_load(self.driver)
        self.driver.find_element(
            By.CSS_SELECTOR, f'form[action="/projects/{newer.pk}/unarchive/"] button'
        ).click()
        WebDriverWait(self.driver, 10).until(
            lambda d: not d.find_elements(By.CSS_SELECTOR, ".alert-secondary")
        )
        self.navigate_to(self.driver, "/projects/")
        self.wait_for_page_load(self.driver)
        titles = [
            e.text for e in self.driver.find_elements(By.CSS_SELECTOR, ".list-group-item h5 a")
        ]
        assert titles == ["Keep me", "Abandon me"]
```

Use the real project-name link selector from `project_list.html` (`a.stretched-link`). Make sure the archived banner selector cannot match the success message's alert: give the banner `data-archived-banner` and select on that instead of `.alert-secondary`.

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/browser/test_projects/test_archive_project.py -q`
Expected: PASS (headless).

- [ ] **Step 3: Gate and commit**

```bash
make lint-fix && make lint && make type-check && make test
git add tests/browser/test_projects/test_archive_project.py wafer_space/templates/projects/project_detail.html
git commit -m "test(browser): archive and unarchive round trip (#307)"
```

---

## After the tasks

- Walk through in Playwright against a local server on this branch: owner archives a project, sees it last on `/projects/` and read-only, and unarchives it. Also check the shuttle assignment page as staff. Take screenshots for the PR.
- PR "Fixes #307", referencing #244, #324 and #344. Merge gate as in the brief.
