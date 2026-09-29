from django.urls import path

from apps.platform_access.views import (
    PlatformRoleGrantApproveView,
    PlatformRoleGrantListCreateView,
    PlatformRoleGrantRevokeView,
    PlatformSupportSessionCreateView,
    PlatformSupportSessionEndView,
)

urlpatterns = [
    path(
        "role-grants/",
        PlatformRoleGrantListCreateView.as_view(),
        name="platform-role-grant-list",
    ),
    path(
        "role-grants/<uuid:pk>/approve/",
        PlatformRoleGrantApproveView.as_view(),
        name="platform-role-grant-approve",
    ),
    path(
        "role-grants/<uuid:pk>/revoke/",
        PlatformRoleGrantRevokeView.as_view(),
        name="platform-role-grant-revoke",
    ),
    path(
        "support-sessions/",
        PlatformSupportSessionCreateView.as_view(),
        name="platform-support-session-create",
    ),
    path(
        "support-sessions/<uuid:pk>/",
        PlatformSupportSessionEndView.as_view(),
        name="platform-support-session-end",
    ),
]