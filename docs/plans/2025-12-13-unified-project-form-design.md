# Unified Project Form Design

## Problem

The project edit form has two issues:
1. Users cannot edit their project name/description (fixed in earlier commits)
2. The form system uses two separate form classes with duplicated code
3. No clear separation between "immutable after creation" fields and "always editable" fields

## Solution

Create a unified form system with:
- Clear field groupings (System, Core, User)
- Model-level enforcement of field immutability
- Single adaptive form that changes behavior based on context

## Field Groups

| Group | Fields | Behavior |
|-------|--------|----------|
| **System** | `id`, `user`, `status`, `created_at`, `updated_at`, `submitted_at`, `submitted_file`, `proprietary_terms_cached`, `proprietary_terms_cached_at` | Not shown in forms, system-managed |
| **Core** | `shuttle`, `project_id`, `slot_size` | Editable at creation, immutable after (except by staff) |
| **User** | `name`, `description`, `is_public`, `repository_url`, `license_type`, `other_license_spdx_id`, `proprietary_terms_url` | Always editable by owner |

## Implementation

### 1. Model Changes (`wafer_space/projects/models.py`)

Add field group constants and immutability enforcement following
[Django's recommended pattern](https://docs.djangoproject.com/en/5.2/ref/models/instances/)
using `from_db()` to track original values:

```python
class Project(models.Model):
    """User-submitted design projects for manufacturing.

    Field Immutability
    ------------------
    Core fields (shuttle, project_id, slot_size) are immutable after creation
    except by staff users. This is enforced in clean() following Django's
    recommended pattern of using from_db() to track original values.
    See: https://docs.djangoproject.com/en/5.2/ref/models/instances/
    """

    # Field groups for form handling and validation
    SYSTEM_FIELDS = frozenset({
        "id", "user", "status", "created_at", "updated_at",
        "submitted_at", "submitted_file",
        "proprietary_terms_cached", "proprietary_terms_cached_at",
    })
    CORE_FIELDS = frozenset({"shuttle", "project_id", "slot_size"})
    USER_FIELDS = frozenset({
        "name", "description", "is_public", "repository_url",
        "license_type", "other_license_spdx_id", "proprietary_terms_url",
    })

    @classmethod
    def from_db(cls, db, field_names, values):
        """Capture original field values when loading from database.

        This follows Django's recommended pattern for tracking field changes.
        See: https://docs.djangoproject.com/en/5.2/ref/models/instances/
        """
        instance = super().from_db(db, field_names, values)
        instance._loaded_values = dict(zip(field_names, values))
        return instance

    def clean(self):
        """Validate model, including core field immutability."""
        super().clean()
        if not self._state.adding:
            self._validate_core_fields_immutable()

    def _validate_core_fields_immutable(self):
        """Raise ValidationError if non-staff user modifies core fields.

        Core fields (shuttle, project_id, slot_size) cannot be modified
        after project creation except by staff users.
        """
        # Staff can modify anything
        if getattr(self, '_current_user', None) and self._current_user.is_staff:
            return

        loaded = getattr(self, '_loaded_values', {})
        changed = [
            field for field in self.CORE_FIELDS
            if field in loaded and getattr(self, field) != loaded[field]
        ]

        if changed:
            msg = f"Cannot modify {', '.join(changed)} after project creation. Contact staff."
            raise ValidationError(msg)

    def save(self, **kwargs):
        """Save model, ensuring validation runs first."""
        self.full_clean()
        super().save(**kwargs)
```

### 2. Form Changes (`wafer_space/projects/forms.py`)

Replace `ProjectUserEditForm` and `ProjectStaffEditForm` with single `ProjectForm`:

```python
class ProjectForm(LicenseValidationMixin, forms.ModelForm):
    """Unified form for creating and editing projects.

    Adapts field availability based on:
    - Whether this is a new project (creation) or existing (edit)
    - Whether the user is staff

    Core fields (shuttle, project_id, slot_size):
    - Editable during creation (with warning about immutability)
    - Editable by staff on existing projects (with warning about side effects)
    - Disabled for non-staff on existing projects

    User fields (name, description, etc.):
    - Always editable by project owner
    """

    # ... field definitions ...

    class Meta:
        model = Project
        fields = [
            # Core fields
            "shuttle",
            "project_id",
            "slot_size",
            # User fields
            "name",
            "description",
            "is_public",
            "repository_url",
            "license_type",
            "other_license_spdx_id",
            "proprietary_terms_url",
        ]
        # ... widgets and help_texts ...

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self._configure_fields()

    def _configure_fields(self):
        """Configure field editability based on user and instance state."""
        is_new = self.instance._state.adding
        is_staff = self.user and self.user.is_staff

        for field_name in Project.CORE_FIELDS:
            if field_name not in self.fields:
                continue

            if is_new or is_staff:
                # Editable - keep field as-is
                pass
            else:
                # Disable for non-staff editing existing project
                self.fields[field_name].disabled = True

    def save(self, commit=True):
        """Save form, passing user to model for validation."""
        self.instance._current_user = self.user
        return super().save(commit=commit)
```

### 3. Template Changes (`wafer_space/templates/projects/project_form.html`)

Update to show two sections with contextual warnings:

```html
<form method="post">
  {% csrf_token %}

  {# Section 1: Core Fields (Manufacturing Configuration) #}
  <div class="card mb-3 {% if not is_new and not request.user.is_staff %}border-secondary{% elif request.user.is_staff and not is_new %}border-warning{% endif %}">
    <div class="card-header">
      <h6 class="mb-0">Manufacturing Configuration</h6>
    </div>
    <div class="card-body">
      {% if is_new %}
        <div class="alert alert-info">
          <i class="bi bi-info-circle"></i>
          These settings <strong>cannot be changed</strong> after project creation.
        </div>
      {% elif request.user.is_staff %}
        <div class="alert alert-warning">
          <i class="bi bi-exclamation-triangle"></i>
          <strong>Staff only:</strong> Changing these fields may affect manufacturing.
        </div>
      {% else %}
        <div class="alert alert-secondary">
          <i class="bi bi-lock"></i>
          These settings are locked. Contact staff to modify.
        </div>
      {% endif %}

      {{ form.shuttle|as_crispy_field }}
      {{ form.project_id|as_crispy_field }}
      {{ form.slot_size|as_crispy_field }}
    </div>
  </div>

  {# Section 2: User Fields (Project Details) #}
  <div class="card mb-3">
    <div class="card-header">
      <h6 class="mb-0">Project Details</h6>
    </div>
    <div class="card-body">
      {{ form.name|as_crispy_field }}
      {{ form.description|as_crispy_field }}
      {{ form.is_public|as_crispy_field }}
      {{ form.repository_url|as_crispy_field }}
      {{ form.license_type|as_crispy_field }}
      {{ form.other_license_spdx_id|as_crispy_field }}
      {{ form.proprietary_terms_url|as_crispy_field }}
    </div>
  </div>

  <button type="submit" class="btn btn-primary">
    {% if is_new %}Create Project{% else %}Save Changes{% endif %}
  </button>
</form>
```

### 4. View Changes (`wafer_space/projects/views.py`)

Simplify views to use single form:

```python
class ProjectCreateView(LoginRequiredMixin, CreateView):
    model = Project
    form_class = ProjectForm
    template_name = "projects/project_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_new'] = True
        return context

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, f"Project '{form.instance.name}' created!")
        return super().form_valid(form)


class ProjectUpdateView(LoginRequiredMixin, ProjectOwnerOrStaffMixin, UpdateView):
    model = Project
    form_class = ProjectForm
    template_name = "projects/project_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_new'] = False
        return context
```

### 5. Test Changes

**New model tests:**
- `test_non_staff_cannot_modify_core_fields_after_creation`
- `test_staff_can_modify_core_fields_after_creation`
- `test_new_project_allows_core_field_changes`
- `test_from_db_captures_loaded_values`

**Updated form tests:**
- Rename test classes for unified form
- Add tests for `disabled` field state
- Test that disabled fields ignore POST data

**Updated view tests:**
- Remove `is_limited_form` assertions
- Update to check `is_new` context variable

## Files to Modify

1. `wafer_space/projects/models.py` - Add field groups, `from_db()`, `clean()`, `save()`
2. `wafer_space/projects/forms.py` - Replace two forms with unified `ProjectForm`
3. `wafer_space/templates/projects/project_form.html` - Two-section layout with warnings
4. `wafer_space/projects/views.py` - Simplify to use single form
5. `wafer_space/projects/tests/test_models.py` - Add immutability tests
6. `wafer_space/projects/tests/test_forms.py` - Update for unified form
7. `wafer_space/projects/tests/test_views.py` - Update context assertions

## References

- [Django Model Instance Reference - from_db()](https://docs.djangoproject.com/en/5.2/ref/models/instances/)
- [Django Model Instance Reference - Validating objects](https://docs.djangoproject.com/en/5.2/ref/models/instances/#validating-objects)
- [Django Overriding Model Methods](https://docs.djangoproject.com/en/5.2/topics/db/models/#overriding-model-methods)
