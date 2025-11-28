"""URL configuration for projects app."""

from django.urls import path

from . import views
from .views_compliance import compliance_certification_create

app_name = "projects"

urlpatterns = [
    # Admin status page
    path(
        "admin/check-status/",
        views.ManufacturabilityCheckAdminStatusView.as_view(),
        name="admin_check_status",
    ),
    # Project CRUD
    path("", views.ProjectListView.as_view(), name="list"),
    path("<uuid:pk>/", views.ProjectDetailView.as_view(), name="detail"),
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
        "<uuid:pk>/cancel-check/",
        views.ManufacturabilityCheckCancelView.as_view(),
        name="cancel_check",
    ),
    # Compliance certification
    path(
        "<uuid:pk>/compliance/certify/",
        compliance_certification_create,
        name="compliance_certify",
    ),
]
