"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny

from config.health import liveness, readiness

urlpatterns = [
    path("api/v1/health/live/", liveness, name="health-live"),
    path("api/v1/health/ready/", readiness, name="health-ready"),
    path("api/v1/auth/", include("apps.authentication.urls")),
    path("api/v1/directory/", include("apps.tenancy.urls")),
    path("api/v1/platform/", include("apps.platform_access.urls")),
    path("api/v1/", include("apps.tickets.urls")),
    path(
        "api/v1/schema/",
        SpectacularAPIView.as_view(
            authentication_classes=[],
            permission_classes=[AllowAny],
        ),
        name="api-schema",
    ),
    path(
        "api/v1/docs/",
        SpectacularSwaggerView.as_view(
            url_name="api-schema",
            authentication_classes=[],
            permission_classes=[AllowAny],
        ),
        name="api-docs",
    ),
]
