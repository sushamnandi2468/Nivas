from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.authentication.tokens import SessionRefreshToken
from apps.identity.models import EmailAuthChallenge, User

pytestmark = pytest.mark.django_db(transaction=True)


def create_verified_user(*, email="resident@example.com", password="StrongPassword123!"):
    user = User.objects.create_user(
        phone="+919876543401",
        email=email,
        password=password,
    )
    user.email_verified_at = timezone.now()
    user.save(update_fields=("email_verified_at", "updated_at"))
    return user


def test_verified_user_can_login_with_email_and_password(client):
    user = create_verified_user()

    response = client.post(
        "/api/v1/auth/login/",
        {"email": "RESIDENT@example.com", "password": "StrongPassword123!"},
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert AccessToken(payload["access"])["user_id"] == str(user.id)
    assert RefreshToken(payload["refresh"])["user_id"] == str(user.id)


def test_login_does_not_reveal_unverified_or_unknown_accounts(client):
    user = User.objects.create_user(
        phone="+919876543402",
        email="unverified@example.com",
        password="StrongPassword123!",
    )

    unverified_response = client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "StrongPassword123!"},
        content_type="application/json",
    )
    unknown_response = client.post(
        "/api/v1/auth/login/",
        {"email": "unknown@example.com", "password": "StrongPassword123!"},
        content_type="application/json",
    )

    assert unverified_response.status_code == unknown_response.status_code == 401
    assert unverified_response.json() == unknown_response.json() == {
        "detail": "Invalid email or password."
    }


def test_refresh_rotates_and_blacklists_the_original_token(client):
    user = create_verified_user()
    login_response = client.post(
        "/api/v1/auth/login/",
        {"email": user.email, "password": "StrongPassword123!"},
        content_type="application/json",
    )
    original_refresh = login_response.json()["refresh"]

    refresh_response = client.post(
        "/api/v1/auth/refresh/",
        {"refresh": original_refresh},
        content_type="application/json",
    )
    replay_response = client.post(
        "/api/v1/auth/refresh/",
        {"refresh": original_refresh},
        content_type="application/json",
    )

    assert refresh_response.status_code == 200
    assert replay_response.status_code == 401
    payload = refresh_response.json()
    assert payload["refresh"] != original_refresh
    assert AccessToken(payload["access"])["user_id"] == str(user.id)
    assert RefreshToken(payload["refresh"])["user_id"] == str(user.id)


def test_logout_blacklists_refresh_token(client):
    user = create_verified_user()
    refresh = str(SessionRefreshToken.for_user(user))

    logout_response = client.post(
        "/api/v1/auth/logout/",
        {"refresh": refresh},
        content_type="application/json",
    )
    refresh_response = client.post(
        "/api/v1/auth/refresh/",
        {"refresh": refresh},
        content_type="application/json",
    )

    assert logout_response.status_code == 204
    assert refresh_response.status_code == 401


def test_password_reset_is_generic_rate_limited_and_single_use(client):
    user = create_verified_user()
    refresh = str(SessionRefreshToken.for_user(user))
    with patch("apps.authentication.services._send_password_reset_email") as send_email:
        first_response = client.post(
            "/api/v1/auth/password-reset/",
            {"email": user.email},
            content_type="application/json",
        )
        repeat_response = client.post(
            "/api/v1/auth/password-reset/",
            {"email": user.email},
            content_type="application/json",
        )
        unknown_response = client.post(
            "/api/v1/auth/password-reset/",
            {"email": "unknown@example.com"},
            content_type="application/json",
        )

    assert (
        first_response.status_code
        == repeat_response.status_code
        == unknown_response.status_code
        == 202
    )
    assert first_response.json() == repeat_response.json() == unknown_response.json()
    assert send_email.call_count == 1
    challenge = EmailAuthChallenge.objects.get(user=user)
    assert challenge.purpose == EmailAuthChallenge.Purpose.PASSWORD_RESET
    raw_token = send_email.call_args.kwargs["challenge"].raw_token
    assert raw_token != challenge.token_digest

    response = client.post(
        "/api/v1/auth/password-reset/confirm/",
        {"token": raw_token, "password": "ChangedPassword123!"},
        content_type="application/json",
    )
    replay_response = client.post(
        "/api/v1/auth/password-reset/confirm/",
        {"token": raw_token, "password": "ChangedPassword123!"},
        content_type="application/json",
    )
    refresh_response = client.post(
        "/api/v1/auth/refresh/",
        {"refresh": refresh},
        content_type="application/json",
    )

    user.refresh_from_db()
    challenge.refresh_from_db()
    assert response.status_code == 204
    assert replay_response.status_code == 400
    assert user.check_password("ChangedPassword123!")
    assert user.session_version == 2
    assert challenge.consumed_at is not None
    assert refresh_response.status_code == 401