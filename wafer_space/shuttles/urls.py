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
]
