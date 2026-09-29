from django.urls import path

from apps.authentication.views import (
    EmailPasswordLoginView,
    InvitationActivationView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    SessionLogoutView,
    SessionRefreshView,
)

urlpatterns = [
    path("login/", EmailPasswordLoginView.as_view(), name="email-password-login"),
    path("refresh/", SessionRefreshView.as_view(), name="session-refresh"),
    path("logout/", SessionLogoutView.as_view(), name="session-logout"),
    path("activate/", InvitationActivationView.as_view(), name="invitation-activation"),
    path("password-reset/", PasswordResetRequestView.as_view(), name="password-reset-request"),
    path(
        "password-reset/confirm/",
        PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
]