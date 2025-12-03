"""URL configuration for projects app."""

from django.urls import path
from django.urls import re_path

from . import views
from .views import ProjectAdminSummaryView
from .views_compliance import compliance_certification_create

app_name = "projects"

urlpatterns = [
    # Admin status page
    path(
        "admin/check-status/",
        views.ManufacturabilityCheckAdminStatusView.as_view(),
        name="admin_check_status",
    ),
    path("admin/summary/", ProjectAdminSummaryView.as_view(), name="admin_summary"),
    # Project CRUD
    path("", views.ProjectListView.as_view(), name="list"),
    path("<uuid:pk>/", views.ProjectDetailView.as_view(), name="detail"),
    # Alternative URL using 8-character manufacturing ID (e.g., G801ABCD)
    re_path(
        r"^(?P<full_id>[A-Z0-9]{8})/$",
        views.ProjectFullIdRedirectView.as_view(),
        name="detail_by_full_id",
    ),
    path("create/", views.ProjectCreateView.as_view(), name="create"),
    path("<uuid:pk>/update/", views.ProjectUpdateView.as_view(), name="update"),
    path("<uuid:pk>/delete/", views.ProjectDeleteView.as_view(), name="delete"),
    # Project submission
    path("<uuid:pk>/submit/", views.ProjectSubmitView.as_view(), name="submit"),
    # File submission
    path(
        "<uuid:pk>/submit-url/",
        views.ProjectFileSubmitURLView.as_view(),
        name="submit_url",
    ),
    # AJAX endpoints
    path(
        "<uuid:pk>/progress/",
        views.ProjectFileProgressView.as_view(),
        name="progress",
    ),
    path(
        "<uuid:pk>/check-status/",
        views.ManufacturabilityCheckStatusView.as_view(),
        name="check_status",
    ),
    path(
        "<uuid:pk>/cancel-check/<int:check_id>/",
        views.ManufacturabilityCheckCancelView.as_view(),
        name="cancel_check",
    ),
    path(
        "check/<int:check_id>/requeue-drc-update/",
        views.check_drc_update_requeue,
        name="check_drc_update_requeue",
    ),
    # AJAX endpoints for project form validation
    path(
        "check-project-id/",
        views.ProjectIDCheckView.as_view(),
        name="check_project_id",
    ),
    path(
        "shuttle-available-sizes/",
        views.ShuttleAvailableSizesView.as_view(),
        name="shuttle_available_sizes",
    ),
    # Compliance certification
    path(
        "<uuid:pk>/compliance/certify/",
        compliance_certification_create,
        name="compliance_certify",
    ),
]
