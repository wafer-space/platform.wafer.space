# Shuttle closed-to-users rule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One computed open/closed rule on `Shuttle`, enforced for non-staff
users wherever a project's design can change, shown on every page that names
a project's shuttle, with run-page links (#320, #350).

**Architecture:**
- The rule lives on the model: `Shuttle.is_open_to_users`, `is_closed`,
  `closed_reason`, and the QuerySet method `open_to_users`.
- The user/staff decision lives in `projects/mixins.py`, in the shape of
  PR #353's archive rule: a function helper
  `refuse_if_shuttle_closed(request, project)`, a view mixin
  `RefuseClosedShuttleMixin`, and a guard test that classifies every project
  URL.
- Display goes through one include, `shuttles/_shuttle_state.html`.

**Tech Stack:** Django 5.2, pytest-django, factory-boy, Selenium browser tests
(`tests/browser`), uv, ruff, mypy, djlint.

**Spec:** `docs/superpowers/specs/2026-10-11-shuttle-closed-rule-design.md`.
Coordinator amendments of 11 Oct 2026:
- (a) Mirror PR #353's shape: one mixin, one function helper, one URL guard
  test. This replaces the spec's `services/shuttle_gate.py`.
- (b) The projects-list include is a follow-up on top of PR #321, not part
  of this PR.

## Global Constraints

- Open = `status == "open"` and (`submission_deadline` is None or
  `now < submission_deadline`). Closed from the deadline instant
  (`now >= deadline`).
- Staff are never blocked (dates-03 default). Projects without a shuttle are
  never blocked.
- Chip-on-board is locked for non-staff on a closed shuttle (dates-02
  default).
- Owner fields that stay editable when closed: name, description,
  `is_public`, licence fields, `repository_url`, `crowd_supply_order_id`.
- Display words: "Open", "Closed" (with the `bi-lock-fill` icon), "GDS due
  <aoe_deadline>", "Run page", "CrowdSupply". The word "CrowdSupply" is
  always one word.
- `website_url`:
  - G801 `https://wafer.space/ws-run1/`
  - G802 `https://wafer.space/ws-run2/`
  - G803 none
  - set by an update-only migration; creates nothing; reverse `noop`.
- Repo rules:
  - no `# noqa` / `# type: ignore`;
  - in tests, explicit shuttle names (never ShuttleFactory's sequence);
  - never assert that migration-seeded rows exist;
  - before every commit: `make lint-fix && make lint && make type-check &&
    make test`, then `uv run pre-commit run --files <templates>`.

## Review Focus

1. **A project with no shuttle** (`project.shuttle is None`): it must never
   be blocked, and no page may crash. The test goes in Task 4.
2. **An open shuttle with a past deadline that staff never flipped** (the
   G802 situation in #320): it must be refused for owners, and the creation
   form must not offer it. Tests in Tasks 1 and 3.
3. **An owner editing a closed-shuttle project's name** while chip-on-board
   is locked: the save must succeed and must not re-run the CoB check. Test
   in Task 3.
4. **Staff viewing an owner's closed project:** the upload and submit
   controls stay usable for staff. Test in Task 5.
5. **A new view added later without the rule:** the URL guard test fails
   until the view is classified. Test in Task 4.

---

### Task 1: The rule on Shuttle

**Files:**
- Modify: `wafer_space/shuttles/models.py` (Shuttle: add QuerySet, manager,
  three members)
- Test: `wafer_space/shuttles/tests/test_closed_rule.py` (create)

**Interfaces:**
- Produces:
  - `Shuttle.objects.open_to_users(now: datetime | None = None) -> ShuttleQuerySet`
  - `Shuttle.is_open_to_users(now: datetime | None = None) -> bool`
  - `Shuttle.is_closed -> bool` (property)
  - `Shuttle.closed_reason -> str | None` (property): None when open, else
    `"Shuttle G802 is closed: its GDS deadline has passed"` or
    `"Shuttle G802 is closed (In Production)"`.

- [ ] **Step 1: Write the failing tests**

```python
"""The computed open/closed rule on Shuttle (#320; Tim, issues-09)."""

import datetime

import pytest

from wafer_space.shuttles.models import Shuttle

NOW = datetime.datetime(2026, 12, 17, 11, 59, 59, tzinfo=datetime.UTC)
SECOND = datetime.timedelta(seconds=1)
AOE = datetime.timezone(datetime.timedelta(hours=-12), "AoE")

# (status, deadline, open?)
CASES = [
    (Shuttle.Status.OPEN, None, True),
    (Shuttle.Status.OPEN, NOW + SECOND, True),
    (Shuttle.Status.OPEN, NOW, False),
    (Shuttle.Status.OPEN, NOW - SECOND, False),
    (Shuttle.Status.PLANNING, None, False),
    (Shuttle.Status.FULL, NOW + SECOND, False),
    (Shuttle.Status.LOCKED, NOW + SECOND, False),
    (Shuttle.Status.IN_PRODUCTION, None, False),
    (Shuttle.Status.COMPLETED, NOW - SECOND, False),
    (Shuttle.Status.CANCELLED, None, False),
]


@pytest.mark.django_db
@pytest.mark.parametrize(("status", "deadline", "expected"), CASES)
def test_instance_and_queryset_agree(status, deadline, expected):
    shuttle = Shuttle.objects.create(
        name="G880",
        description="Rule",
        status=status,
        submission_deadline=deadline,
    )
    assert shuttle.is_open_to_users(now=NOW) is expected
    assert (
        Shuttle.objects.open_to_users(now=NOW).filter(pk=shuttle.pk).exists()
        is expected
    )


def test_open_until_last_second_of_aoe_day():
    shuttle = Shuttle(
        name="G881",
        status=Shuttle.Status.OPEN,
        submission_deadline=datetime.datetime(2026, 12, 16, 23, 59, 59, tzinfo=AOE),
    )
    assert shuttle.is_open_to_users(
        now=datetime.datetime(2026, 12, 16, 23, 59, 58, tzinfo=AOE)
    )
    assert not shuttle.is_open_to_users(
        now=datetime.datetime(2026, 12, 16, 23, 59, 59, tzinfo=AOE)
    )


def test_closed_reason_for_passed_deadline():
    shuttle = Shuttle(
        name="G882",
        status=Shuttle.Status.OPEN,
        submission_deadline=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
    )
    assert (
        shuttle.closed_reason == "Shuttle G882 is closed: its GDS deadline has passed"
    )


def test_closed_reason_for_status():
    shuttle = Shuttle(name="G883", status=Shuttle.Status.IN_PRODUCTION)
    assert shuttle.closed_reason == "Shuttle G883 is closed (In Production)"


def test_open_shuttle_has_no_reason():
    shuttle = Shuttle(name="G884", status=Shuttle.Status.OPEN)
    assert (shuttle.is_closed, shuttle.closed_reason) == (False, None)
```

- [ ] **Step 2:** Run `uv run pytest wafer_space/shuttles/tests/test_closed_rule.py -q`.
  Expected: FAIL (`AttributeError: ... open_to_users`).

- [ ] **Step 3: Implement** in `wafer_space/shuttles/models.py`. Imports:
  `from django.db.models import Q`; `datetime` under `TYPE_CHECKING`; Django
  `timezone` is already imported. Define the QuerySet before `Shuttle`:

```python
class ShuttleQuerySet(models.QuerySet["Shuttle"]):
    """Shuttle queries."""

    def open_to_users(self, now: datetime.datetime | None = None) -> ShuttleQuerySet:
        """Shuttles users may create projects on and submit to (#320)."""
        moment = now or timezone.now()
        return self.filter(status=Shuttle.Status.OPEN).filter(
            Q(submission_deadline__isnull=True) | Q(submission_deadline__gt=moment)
        )
```

In `Shuttle`, set `objects = ShuttleQuerySet.as_manager()` and add:

```python
def is_open_to_users(self, now: datetime.datetime | None = None) -> bool:
    """Open = status open and the GDS deadline, if set, not yet reached.

    The one definition of a closed shuttle (#320; Tim, issues-09:
    "Computed: closed after deadline or status not open").
    ShuttleQuerySet.open_to_users must agree with it.
    """
    moment = now or timezone.now()
    return self.status == self.Status.OPEN and (
        self.submission_deadline is None or moment < self.submission_deadline
    )


@property
def is_closed(self) -> bool:
    """True when users may no longer create, upload or submit."""
    return not self.is_open_to_users()


@property
def closed_reason(self) -> str | None:
    """Why the shuttle is closed, in plain words; None when open."""
    if self.is_open_to_users():
        return None
    if self.status == self.Status.OPEN:
        return f"Shuttle {self.name} is closed: its GDS deadline has passed"
    return f"Shuttle {self.name} is closed ({self.get_status_display()})"
```

- [ ] **Step 4:** Rerun the tests. Expected: PASS. Run `make type-check`.
- [ ] **Step 5:** Run the gate, then commit: `feat(shuttles): computed open/closed rule (#320)`.

### Task 2: website_url field and data migration

**Files:**
- Modify: `wafer_space/shuttles/models.py` (field after `crowd_supply_url`)
- Modify: `wafer_space/shuttles/admin.py` (first fieldset: add `"website_url"`)
- Create: `wafer_space/shuttles/migrations/0011_shuttle_website_url.py` (by
  `makemigrations`)
- Create: `wafer_space/shuttles/migrations/0012_set_run_page_urls.py`
- Test: `wafer_space/shuttles/tests/test_closed_rule.py` (append)

**Interfaces:** Produces `Shuttle.website_url: str` (blank default `""`).

- [ ] **Step 1: Failing test** (append):

```python
import importlib
from django.apps import apps as django_apps

RUN_PAGES_MODULE = "wafer_space.shuttles.migrations.0012_set_run_page_urls"


@pytest.mark.django_db
def test_run_page_migration_sets_g801_g802_only():
    for name in ("G801", "G802", "G803"):
        Shuttle.objects.update_or_create(
            name=name, defaults={"description": name, "website_url": ""}
        )
    importlib.import_module(RUN_PAGES_MODULE).set_run_page_urls(django_apps, None)
    assert dict(
        Shuttle.objects.filter(name__in=["G801", "G802", "G803"]).values_list(
            "name", "website_url"
        )
    ) == {
        "G801": "https://wafer.space/ws-run1/",
        "G802": "https://wafer.space/ws-run2/",
        "G803": "",
    }


@pytest.mark.django_db
def test_run_page_migration_creates_nothing():
    Shuttle.objects.filter(name__in=["G801", "G802"]).delete()
    importlib.import_module(RUN_PAGES_MODULE).set_run_page_urls(django_apps, None)
    assert not Shuttle.objects.filter(name__in=["G801", "G802"]).exists()
```

- [ ] **Step 2:** Run it. Expected: FAIL (`ModuleNotFoundError`, or no field).
- [ ] **Step 3: Field:**

```python
    website_url = models.URLField(
        blank=True,
        default="",
        verbose_name="wafer.space run page",
        help_text="This run's page on wafer.space, e.g. https://wafer.space/ws-run1/ (optional).",
    )
```

  Then run `UV_ENV_FILE=.env uv run python manage.py makemigrations shuttles
  -n shuttle_website_url`. Write `0012_set_run_page_urls.py` in 0009's style:

```python
# Data migration linking past shuttle runs to their wafer.space run pages
# (issue #350; Tim, 11 Oct 2026: "link to https://wafer.space/ws-run1/ and
# https://wafer.space/ws-run2/"). Run 3 has no page yet (404 on 11 Oct 2026).

import logging
from typing import ClassVar

from django.db import migrations

logger = logging.getLogger(__name__)

RUN_PAGES = {
    "G801": "https://wafer.space/ws-run1/",
    "G802": "https://wafer.space/ws-run2/",
}


def set_run_page_urls(apps, _schema_editor):
    """Update-only: shuttles are never created here (see 0009)."""
    Shuttle = apps.get_model("shuttles", "Shuttle")
    for name, url in RUN_PAGES.items():
        updated = Shuttle.objects.filter(name=name).update(website_url=url)
        logger.info("Set run page URL on %d %s shuttle(s)", updated, name)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("shuttles", "0011_shuttle_website_url"),
    ]

    operations: ClassVar[list[migrations.RunPython]] = [
        migrations.RunPython(set_run_page_urls, migrations.RunPython.noop),
    ]
```

  Admin: the first fieldset becomes
  `("name", "description", "status", "crowd_supply_url", "website_url")`.
- [ ] **Step 4:** Run the tests and `makemigrations --check --dry-run`.
  Expected: PASS, "No changes detected".
- [ ] **Step 5:** Run the gate, then commit: `feat(shuttles): website_url run-page link, set for G801/G802 (#350)`.

### Task 3: Project form uses the rule

**Files:**
- Modify: `wafer_space/projects/forms.py`:
  - `__init__`: the queryset;
  - `_set_defaults`: the default pick;
  - `_configure_fields`: the CoB lock.
- Test: `wafer_space/projects/tests/test_forms_closed_shuttle.py` (create)

**Interfaces:** Consumes `Shuttle.objects.open_to_users()` and `Shuttle.is_closed`.

- [ ] **Step 1: Failing tests**:

```python
"""The project form never offers a closed shuttle (#320, #350)."""

import datetime

import pytest
from django import forms

from wafer_space.projects.forms import ProjectForm
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

PAST = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
FUTURE = datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC)


def _names(field: forms.Field) -> set[str]:
    assert isinstance(field, forms.ModelChoiceField)
    queryset = field.queryset
    assert queryset is not None
    return set(queryset.values_list("name", flat=True))


@pytest.fixture
def shuttles():
    return {
        "open": Shuttle.objects.create(
            name="G885", description="o", status="open", submission_deadline=FUTURE
        ),
        "nodeadline": Shuttle.objects.create(
            name="G886", description="n", status="open"
        ),
        "lapsed": Shuttle.objects.create(
            name="G887", description="l", status="open", submission_deadline=PAST
        ),
        "production": Shuttle.objects.create(
            name="G888", description="p", status="production"
        ),
    }


@pytest.mark.django_db
def test_create_form_offers_only_open_shuttles(shuttles):
    form = ProjectForm(user=UserFactory())
    assert _names(form.fields["shuttle"]) >= {"G885", "G886"}
    assert _names(form.fields["shuttle"]).isdisjoint({"G887", "G888"})


@pytest.mark.django_db
def test_default_skips_lapsed_open_shuttle(shuttles):
    Shuttle.objects.filter(name="G887").update(created_at=PAST)  # oldest
    form = ProjectForm(user=UserFactory())
    assert form.fields["shuttle"].initial.name != "G887"


@pytest.mark.django_db
def test_cob_locked_for_owner_on_closed_shuttle(shuttles):
    project = ProjectFactory(shuttle=shuttles["production"])
    form = ProjectForm(instance=project, user=project.user)
    assert form.fields["chip_on_board"].disabled


@pytest.mark.django_db
def test_cob_editable_for_staff_on_closed_shuttle(shuttles):
    project = ProjectFactory(shuttle=shuttles["production"])
    form = ProjectForm(instance=project, user=UserFactory(is_staff=True))
    assert not form.fields["chip_on_board"].disabled


@pytest.mark.django_db
def test_cob_editable_for_owner_on_open_shuttle(shuttles):
    project = ProjectFactory(shuttle=shuttles["open"])
    form = ProjectForm(instance=project, user=project.user)
    assert not form.fields["chip_on_board"].disabled
```

  Before writing the next test, read how `test_forms.py` builds valid POST
  data for an existing project, and reuse its helper. Add a test that an
  owner POSTing a new name and a flipped `chip_on_board` for a
  closed-shuttle project through `projects:update` saves the name, leaves
  `chip_on_board` unchanged, and creates no new `ManufacturabilityCheck`
  (Review Focus 3).

- [ ] **Step 2:** Run them. Expected: FAIL (the lapsed shuttle is offered;
  CoB is not disabled).
- [ ] **Step 3: Implement.** Changes in `forms.py`:
  - In `__init__`, `Shuttle.objects.filter(status=Shuttle.Status.OPEN)`
    becomes `Shuttle.objects.open_to_users()`. Keep the `| own shuttle`
    union.
  - In `_set_defaults`, use `Shuttle.objects.open_to_users().order_by("created_at").first()`.
  - At the end of `_configure_fields`:

```python
        # A closed shuttle freezes the design: owners may no longer change
        # the packaging, which re-runs the manufacturability check
        # (#320; dates-02 default). Staff can.
        shuttle = self.instance.shuttle if self.instance.shuttle_id else None
        if not is_new and not is_staff and shuttle is not None and shuttle.is_closed:
            self.fields["chip_on_board"].disabled = True
```

- [ ] **Step 4:** Run them plus `uv run pytest wafer_space/projects/tests/test_forms.py -q`. Expected: PASS.
- [ ] **Step 5:** Run the gate, then commit: `feat(projects): form offers only open shuttles; CoB locked when closed (#320)`.

### Task 4: The gate in the views, the URL guard test

**Files:**
- Modify: `wafer_space/projects/mixins.py`: add `refuse_if_shuttle_closed`,
  `shuttle_closed_reason_for`, `RefuseClosedShuttleMixin`.
- Modify: `wafer_space/projects/views.py`: `ProjectSubmitView` and
  `ProjectFileSubmitURLView` gain `RefuseClosedShuttleMixin` after
  `ProjectOwnerOrStaffMixin`.
- Test: `wafer_space/projects/tests/test_closed_shuttle_views.py` (create)

**Interfaces:**
- Produces:
  - `shuttle_closed_reason_for(project: Project, user: User | AnonymousUser) -> str | None`:
    None for staff, for a project without a shuttle, and for an open
    shuttle; otherwise `shuttle.closed_reason`.
  - `refuse_if_shuttle_closed(request: HttpRequest, project: Project) -> HttpResponseRedirect | None`
  - `class RefuseClosedShuttleMixin(View)`

- [ ] **Step 1: Failing tests:**

```python
"""Owners cannot upload or submit on a closed shuttle (#320)."""

import pytest
from django.urls import URLPattern, reverse

from wafer_space.projects import urls as project_urls
from wafer_space.projects.models import Project, ProjectFile
from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

# Every project URL is either allowed on a closed shuttle or refused to
# its owner. A new URL must be added to one set (as PR #353 does for
# archived projects), so a new write view cannot skip the rule.
ALLOWED_ON_CLOSED = {
    "detail",
    "progress",
    "check_status",
    "cancel_check",
    "update",  # other fields stay editable; CoB is locked by the form
    "delete",
    "compliance_certify",
    "check_drc_update_requeue",  # re-checks a revision; submission is frozen
}
REFUSED_ON_CLOSED = {"submit", "submit_url"}
PROJECT_KWARGS = ("<uuid:pk>", "<int:check_id>")
REASON = "Shuttle G889 is closed (In Production)"


def project_url_names():
    return {
        p.name
        for p in project_urls.urlpatterns
        if isinstance(p, URLPattern)
        and p.name
        and any(k in str(p.pattern) for k in PROJECT_KWARGS)
    }


def test_every_project_url_is_classified():
    assert project_url_names() == ALLOWED_ON_CLOSED | REFUSED_ON_CLOSED


@pytest.fixture
def closed_project():
    shuttle = Shuttle.objects.create(name="G889", description="c", status="production")
    return ProjectFactory(shuttle=shuttle)


@pytest.mark.parametrize("name", sorted(REFUSED_ON_CLOSED))
@pytest.mark.parametrize("method", ["get", "post"])
def test_owner_refused(client, closed_project, name, method):
    client.force_login(closed_project.user)
    response = getattr(client, method)(
        reverse(f"projects:{name}", args=[closed_project.pk]),
        {"url": "https://example.com/design.gds"},
        follow=True,
    )
    detail = reverse("projects:detail", args=[closed_project.pk])
    assert response.redirect_chain[-1][0] == detail
    assert REASON in response.content.decode()
    assert not ProjectFile.objects.filter(project=closed_project).exists()
    assert Project.objects.get(pk=closed_project.pk).submitted_file is None


def test_staff_not_refused(client, closed_project):
    client.force_login(UserFactory(is_staff=True))
    response = client.get(reverse("projects:submit_url", args=[closed_project.pk]))
    assert response.status_code == 200


def test_project_without_shuttle_not_refused(client):
    project = ProjectFactory(shuttle=None)
    client.force_login(project.user)
    response = client.get(reverse("projects:submit_url", args=[project.pk]))
    assert response.status_code == 200


def test_stranger_still_gets_403(client, closed_project):
    client.force_login(UserFactory())
    assert (
        client.get(reverse("projects:submit_url", args=[closed_project.pk])).status_code
        == 403
    )
```

  Before running: check that `submit` is POST-only (`ProjectSubmitView` has
  no `get`). If a GET returns 405 before the mixin runs, change the
  parametrisation to POST only for `submit`, with a comment, as PR #353
  does for `archive`.

- [ ] **Step 2:** Run it. Expected: FAIL (an upload page renders for the owner).
- [ ] **Step 3: Implement** in `mixins.py`. Add imports: `messages`,
  `get_object_or_404`, `redirect`, `View`; under `TYPE_CHECKING`,
  `HttpResponseRedirect` and `AnonymousUser`. Then:

```python
def shuttle_closed_reason_for(
    project: Project, user: User | AnonymousUser
) -> str | None:
    """Why `user` may not change this project's design, or None (#320).

    Staff are never blocked (dates-03 default); a project without a shuttle
    is not blocked. The rule itself is Shuttle.is_open_to_users.
    """
    if user.is_authenticated and user.is_staff:
        return None
    shuttle = project.shuttle
    if shuttle is None:
        return None
    return shuttle.closed_reason


def refuse_if_shuttle_closed(
    request: HttpRequest, project: Project
) -> HttpResponseRedirect | None:
    """Refuse an upload or submission on a closed shuttle (#320).

    Returns a redirect to the project page with the reason, or None when
    the caller may proceed. RefuseClosedShuttleMixin calls it.
    """
    reason = shuttle_closed_reason_for(project, request.user)
    if reason is None:
        return None
    messages.error(request, reason)
    return redirect("projects:detail", pk=project.pk)


class RefuseClosedShuttleMixin(View):
    """Refuse every request to a design-changing view on a closed shuttle.

    List it after ProjectOwnerOrStaffMixin, so strangers still get a 403.
    The view's URL must carry the project's ``pk``.
    """

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        """Redirect with the reason if the project's shuttle is closed."""
        project = get_object_or_404(Project, pk=kwargs["pk"])
        refusal = refuse_if_shuttle_closed(request, project)
        if refusal is not None:
            return refusal
        return super().dispatch(request, *args, **kwargs)
```

  `views.py`: the bases become
  `(LoginRequiredMixin, ProjectOwnerOrStaffMixin, RefuseClosedShuttleMixin, View)`
  for `ProjectSubmitView` and `ProjectFileSubmitURLView`. Import the mixin.
  Check the MRO order: `ProjectOwnerOrStaffMixin.dispatch` (through
  `UserPassesTestMixin`) must run first. The stranger test proves it.

- [ ] **Step 4:** Run the tests, plus `uv run pytest wafer_space/projects -q`.
  Expected: PASS.
- [ ] **Step 5:** Run the gate, then commit: `feat(projects): refuse uploads and submission on a closed shuttle (#320)`.

### Task 5: Project detail shows the refusal instead of dead buttons

**Files:**
- Modify: `wafer_space/projects/views.py`: `ProjectDetailView.get_context_data`
  sets `context["shuttle_closed_reason"] = shuttle_closed_reason_for(project, user)`.
- Modify: `wafer_space/templates/projects/project_detail.html`:
  - the "Submit New File URL" card and the "Retry Download" button: when
    `shuttle_closed_reason` is set, show an `alert alert-secondary` with
    `bi-lock-fill` and the reason instead;
  - the submit button: when `shuttle_closed_reason` is set, render the
    disabled button with `title="{{ shuttle_closed_reason }}"`; otherwise
    keep the existing `can_submit` branches.
- Test: append to `test_closed_shuttle_views.py`.

- [ ] **Step 1: Failing tests:**

```python
def test_detail_shows_reason_not_upload_button_to_owner(client, closed_project):
    client.force_login(closed_project.user)
    content = client.get(
        reverse("projects:detail", args=[closed_project.pk])
    ).content.decode()
    assert REASON in content
    assert reverse("projects:submit_url", args=[closed_project.pk]) not in content


def test_detail_keeps_upload_button_for_staff(client, closed_project):
    client.force_login(UserFactory(is_staff=True))
    content = client.get(
        reverse("projects:detail", args=[closed_project.pk])
    ).content.decode()
    assert reverse("projects:submit_url", args=[closed_project.pk]) in content
```

- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement** the context line and the template branches.
- [ ] **Step 4:** Run them plus `uv run pytest wafer_space/projects/tests/test_views.py -q`.
  Then `uv run pre-commit run --files wafer_space/templates/projects/project_detail.html`.
- [ ] **Step 5:** Run the gate, then commit: `feat(projects): project page explains a closed shuttle (#320)`.

### Task 6: Shuttle state everywhere a shuttle is named

**Files:**
- Create: `wafer_space/shuttles/templates/shuttles/_shuttle_state.html`
- Modify:
  - `wafer_space/shuttles/templates/shuttles/list.html`: card header;
  - `wafer_space/shuttles/templates/shuttles/detail.html`: under the `<h1>`;
  - `wafer_space/shuttles/templates/shuttles/assignment_dashboard.html`:
    the heading;
  - `wafer_space/templates/projects/project_detail.html`: the "Shuttle Run" line;
  - `wafer_space/templates/projects/project_form.html`: the locked shuttle
    display.
- Test: `wafer_space/shuttles/tests/test_shuttle_state_display.py` (create)

- [ ] **Step 1: Failing tests:**

```python
"""Every page naming a shuttle says open or closed (#350)."""

import datetime

import pytest
from django.urls import reverse

from wafer_space.projects.tests.factories import ProjectFactory
from wafer_space.shuttles.models import Shuttle
from wafer_space.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db
RUN1 = "https://wafer.space/ws-run1/"
FUTURE = datetime.datetime(2099, 12, 17, 11, 59, 59, tzinfo=datetime.UTC)


@pytest.fixture
def closed():
    return Shuttle.objects.create(
        name="G890", description="Past run", status="completed", website_url=RUN1
    )


@pytest.fixture
def open_shuttle():
    return Shuttle.objects.create(
        name="G891", description="Now", status="open", submission_deadline=FUTURE
    )


@pytest.fixture
def staff(client):
    client.force_login(UserFactory(is_staff=True))
    return client


@pytest.mark.parametrize("url_name", ["shuttles:detail", "shuttles:assignment"])
def test_staff_pages_show_closed_and_run_page(staff, closed, url_name):
    content = staff.get(reverse(url_name, kwargs={"name": "G890"})).content.decode()
    assert "Closed" in content
    assert RUN1 in content


def test_list_shows_closed_and_open(staff, closed, open_shuttle):
    content = staff.get(reverse("shuttles:list")).content.decode()
    assert "Closed" in content
    assert "GDS due 16 December 2099 @ 11:59 PM AoE" in content


def test_project_detail_shows_closed_and_run_page(client, closed):
    project = ProjectFactory(shuttle=closed)
    client.force_login(project.user)
    content = client.get(reverse("projects:detail", args=[project.pk])).content.decode()
    assert "Closed" in content
    assert RUN1 in content


def test_project_form_locked_shuttle_shows_closed(client, closed):
    project = ProjectFactory(shuttle=closed)
    client.force_login(project.user)
    content = client.get(reverse("projects:update", args=[project.pk])).content.decode()
    assert "Closed" in content


def test_project_detail_open_shuttle_says_open(client, open_shuttle):
    project = ProjectFactory(shuttle=open_shuttle)
    client.force_login(project.user)
    content = client.get(reverse("projects:detail", args=[project.pk])).content.decode()
    assert "GDS due 16 December 2099 @ 11:59 PM AoE" in content
```

- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement** the include:

```django
{% load shuttle_dates %}
{# Shuttle name with its open/closed state and links (#350). Pass shuttle. #}
<span class="shuttle-state">
  <span class="fw-semibold">{{ shuttle.name }}</span>
  {% if shuttle.is_closed %}
    <span class="badge bg-secondary"><i class="bi bi-lock-fill" aria-hidden="true"></i> Closed</span>
  {% else %}
    <span class="badge bg-success">Open</span>
    {% if shuttle.submission_deadline %}
      <span class="small">GDS due {{ shuttle.submission_deadline|aoe_deadline }}</span>
    {% endif %}
  {% endif %}
  {% if shuttle.website_url %}
    <a href="{{ shuttle.website_url }}" target="_blank" rel="noopener" class="small ms-1">Run page <i class="bi bi-box-arrow-up-right" aria-hidden="true"></i></a>
  {% endif %}
  {% if shuttle.crowd_supply_url %}
    <a href="{{ shuttle.crowd_supply_url }}" target="_blank" rel="noopener" class="small ms-1">CrowdSupply <i class="bi bi-box-arrow-up-right" aria-hidden="true"></i></a>
  {% endif %}
</span>
```

  Use it as `{% include "shuttles/_shuttle_state.html" with shuttle=... %}`.
  Placement:
  - on the project detail page, replace `{{ project.shuttle.name }}` inside
    the existing `{% if project.shuttle %}`;
  - on the project form, replace `{{ form.instance.shuttle }}` in the locked
    branch;
  - on the shuttle pages, put it beside the name; the existing status badges
    remain, so staff still see the internal status.
- [ ] **Step 4:** Run the tests, then `uv run pytest wafer_space/shuttles wafer_space/projects -q`.
  Then pre-commit on all changed templates.
- [ ] **Step 5:** Run the gate, then commit: `feat(shuttles): show open/closed and run-page link wherever a shuttle is named (#350)`.

### Task 7: Browser test and PR

**Files:**
- Create: `tests/browser/test_projects/test_closed_shuttle.py`. Follow
  `test_crowdsupply_campaign_link.py`'s setup: user, verified email, ToS
  acceptance, explicit shuttle names.

- [ ] **Step 1: Browser test.** Set up an owner with a project on a
  `completed` shuttle G892 (`website_url` set) and an open shuttle G893.
  - Load the project page. Wait (`WebDriverWait`) for the text "Closed".
    Assert there is no link whose href contains `/submit-url/`.
  - Load `/projects/create/`. Assert the shuttle `<select>` options include
    G893 and not G892.
- [ ] **Step 2:** Run `uv run pytest tests/browser/test_projects/test_closed_shuttle.py -q`. Expected: PASS.
- [ ] **Step 3:** Run the gate, then commit.
- [ ] **Step 4:** Walk through it with headless Playwright on a local dev
  database seeded with production's G801–G803 values
  (`scratch/tmp/dates-cs/seed_prod_shuttles.py`) plus a project on G802.
  Screenshot the project page as the owner, the creation form and the
  shuttle list. Push the screenshots to the orphan branch
  `assets/pr-NNN-screenshots`.
- [ ] **Step 5:** Push the branch and open the PR. The body carries:
  - the rule, and the table of user actions;
  - Tim's words (issues-09, #350);
  - the defaults for dates-02 and dates-03;
  - "Fixes #320", "Fixes #350";
  - the follow-up for the projects list on top of PR #321;
  - the screenshots.

  Then the merge gate: an independent Sonnet review hunting for shortcuts,
  CI read to the end, the coordinator's word.
