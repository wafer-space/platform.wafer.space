from django.urls import path

from . import views

app_name = "shuttles"

urlpatterns = [
    path("", views.ShuttleListView.as_view(), name="list"),
    path("<str:name>/", views.ShuttleDetailView.as_view(), name="detail"),
    path(
        "<str:name>/assign/",
        views.ShuttleAssignmentView.as_view(),
        name="assignment",
    ),
    path(
        "<str:name>/grid-preview/",
        views.GridPreviewView.as_view(),
        name="grid_preview",
    ),
    path(
        "<str:name>/assign-project/",
        views.AssignProjectView.as_view(),
        name="assign_project",
    ),
    path(
        "<str:name>/remove-assignment/<int:slot_id>/",
        views.RemoveAssignmentView.as_view(),
        name="remove_assignment",
    ),
]
