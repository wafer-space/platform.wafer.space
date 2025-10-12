"""URL configuration for legal app."""

from django.urls import path

from . import views

app_name = "legal"

urlpatterns = [
    path("tos/", views.tos_display, name="tos_display"),
    path("tos/accept/", views.tos_accept, name="tos_accept"),
]
