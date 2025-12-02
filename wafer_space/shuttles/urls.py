from django.urls import path

from . import views

app_name = "shuttles"

urlpatterns = [
    path("<int:pk>/", views.ShuttleDetailView.as_view(), name="detail"),
    path(
        "<int:pk>/assign/",
        views.ShuttleAssignmentView.as_view(),
        name="assignment",
    ),
    path(
        "<int:pk>/grid-preview/",
        views.GridPreviewView.as_view(),
        name="grid_preview",
    ),
    path(
        "<int:pk>/assign-project/",
        views.AssignProjectView.as_view(),
        name="assign_project",
    ),
    path(
        "<int:pk>/remove-assignment/<int:slot_id>/",
        views.RemoveAssignmentView.as_view(),
        name="remove_assignment",
    ),
]
