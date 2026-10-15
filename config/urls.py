from django.conf import settings
from django.contrib import admin
from django.urls import include
from django.urls import path
from django.views import defaults as default_views
from django.views.generic import TemplateView

from wafer_space.core.views import health

urlpatterns = [
    path("", TemplateView.as_view(template_name="pages/home.html"), name="home"),
    # Liveness probe for nginx and deployment tooling (issue #336)
    path("health/", health, name="health"),
    path(
        "about/",
        TemplateView.as_view(template_name="pages/about.html"),
        name="about",
    ),
    # Keep crawlers off login and account URLs (issue #338)
    path(
        "robots.txt",
        TemplateView.as_view(
            template_name="robots.txt",
            content_type="text/plain",
            extra_context={"admin_url": settings.ADMIN_URL},
        ),
        name="robots_txt",
    ),
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    # User management
    path("users/", include("wafer_space.users.urls", namespace="users")),
    path("accounts/", include("allauth.urls")),
    # Legal
    path("legal/", include("wafer_space.legal.urls", namespace="legal")),
    # Your stuff: custom urls includes go here
    path("projects/", include("wafer_space.projects.urls", namespace="projects")),
    path("shuttles/", include("wafer_space.shuttles.urls", namespace="shuttles")),
    path(
        "notifications/",
        include("wafer_space.notifications.urls", namespace="notifications"),
    ),
    # ...
    # User files under MEDIA_ROOT are private: nothing serves MEDIA_URL, not
    # even in development. Views send them after a permission check
    # (wafer_space/projects/file_serving.py).
]


if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [
            path("__debug__/", include(debug_toolbar.urls)),
            *urlpatterns,
        ]
