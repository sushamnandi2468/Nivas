from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import transaction
from django.urls import path
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from apps.authentication.tokens import SessionRefreshToken
from apps.identity.models import User
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import (
    Block,
    CommitteeMembership,
    Society,
    StaffMembership,
    Unit,
    UnitOccupancy,
)

pytestmark = pytest.mark.django_db(transaction=True)


@api_view(["GET"])
def tenant_probe(request):
    return Response(
        {
            "user_id": str(request.user.id),
            "society_id": str(request.society.id),
            "membership_id": str(request.membership.id),
            "persona": request.persona,
        }
    )


urlpatterns = [path("tenant-probe/", tenant_probe)]


@pytest.fixture(autouse=True)
def use_test_urls(settings):
    settings.ROOT_URLCONF = __name__


@pytest.fixture
def tenant_identity():
    society = Society.objects.create(registration_code="NIV-REQUEST-A")
    other_society = Society.objects.create(registration_code="NIV-REQUEST-B")
    user = User.objects.create_user(phone="+919876543211")

    with transaction.atomic():
        set_local_society_id(society.id)
        membership = StaffMembership.objects.create(
            society=society,
            user=user,
            role=StaffMembership.Role.FACILITY_MANAGER,
        )

    return user, society, other_society, membership


def bearer_token(user):
    return str(SessionRefreshToken.for_user(user).access_token)


def test_access_token_contains_required_security_claims(tenant_identity, settings):
    user, _, _, _ = tenant_identity

    token = AccessToken(bearer_token(user))

    assert token["iss"] == settings.SIMPLE_JWT["ISSUER"]
    assert token["aud"] == settings.SIMPLE_JWT["AUDIENCE"]
    assert token["token_type"] == "access"
    assert token["session_version"] == user.session_version
    assert token["exp"] - token["iat"] == 10 * 60


def test_access_token_lifetime_is_stable_across_clock_boundary(tenant_identity):
    user, _, _, _ = tenant_identity
    refresh_created_at = timezone.now().replace(microsecond=900_000)
    access_created_at = refresh_created_at + timedelta(milliseconds=200)

    with patch(
        "rest_framework_simplejwt.tokens.aware_utcnow",
        side_effect=[refresh_created_at, access_created_at],
    ):
        token = SessionRefreshToken.for_user(user).access_token

    assert token["exp"] - token["iat"] == 10 * 60


def test_refresh_token_blacklist_rejects_reuse(tenant_identity):
    user, _, _, _ = tenant_identity
    refresh_token = SessionRefreshToken.for_user(user)
    encoded_token = str(refresh_token)

    refresh_token.blacklist()

    with pytest.raises(TokenError, match="blacklisted"):
        SessionRefreshToken(encoded_token)


def test_authenticated_request_resolves_active_tenant_and_clears_context(
    client, tenant_identity
):
    user, society, _, membership = tenant_identity

    response = client.get(
        "/tenant-probe/",
        HTTP_AUTHORIZATION=f"Bearer {bearer_token(user)}",
        HTTP_X_SOCIETY_ID=str(society.id),
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(user.id),
        "society_id": str(society.id),
        "membership_id": str(membership.id),
        "persona": "staff",
    }
    assert StaffMembership.objects.count() == 0


def test_current_resident_occupancy_grants_tenant_entry(client):
    society = Society.objects.create(registration_code="NIV-RESIDENT-CURRENT")
    user = User.objects.create_user(phone="+919876543212")
    with transaction.atomic():
        set_local_society_id(society.id)
        block = Block.objects.create(society=society, name="Alpha", code="A")
        unit = Unit.objects.create(
            society=society,
            block=block,
            door_number="101",
        )
        occupancy = UnitOccupancy.objects.create(
            society=society,
            unit=unit,
            user=user,
            occupancy_type=UnitOccupancy.OccupancyType.OWNER,
        )

    response = client.get(
        "/tenant-probe/",
        HTTP_AUTHORIZATION=f"Bearer {bearer_token(user)}",
        HTTP_X_SOCIETY_ID=str(society.id),
    )

    assert response.status_code == 200
    assert response.json()["membership_id"] == str(occupancy.id)
    assert response.json()["persona"] == "resident"


def test_expired_resident_occupancy_denies_tenant_entry(client):
    society = Society.objects.create(registration_code="NIV-RESIDENT-EXPIRED")
    user = User.objects.create_user(phone="+919876543213")
    with transaction.atomic():
        set_local_society_id(society.id)
        block = Block.objects.create(society=society, name="Alpha", code="A")
        unit = Unit.objects.create(
            society=society,
            block=block,
            door_number="101",
        )
        UnitOccupancy.objects.create(
            society=society,
            unit=unit,
            user=user,
            occupancy_type=UnitOccupancy.OccupancyType.TENANT,
            starts_at=timezone.now() - timedelta(days=2),
            ends_at=timezone.now() - timedelta(days=1),
        )

    response = client.get(
        "/tenant-probe/",
        HTTP_AUTHORIZATION=f"Bearer {bearer_token(user)}",
        HTTP_X_SOCIETY_ID=str(society.id),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "No active membership in this society."}


def test_current_committee_membership_grants_tenant_entry(client):
    society = Society.objects.create(registration_code="NIV-COMMITTEE-CURRENT")
    user = User.objects.create_user(phone="+919876543214")
    with transaction.atomic():
        set_local_society_id(society.id)
        membership = CommitteeMembership.objects.create(
            society=society,
            user=user,
            role=CommitteeMembership.Role.SECRETARY,
        )

    response = client.get(
        "/tenant-probe/",
        HTTP_AUTHORIZATION=f"Bearer {bearer_token(user)}",
        HTTP_X_SOCIETY_ID=str(society.id),
    )

    assert response.status_code == 200
    assert response.json()["membership_id"] == str(membership.id)
    assert response.json()["persona"] == "committee"


def test_expired_committee_membership_denies_tenant_entry(client):
    society = Society.objects.create(registration_code="NIV-COMMITTEE-EXPIRED")
    user = User.objects.create_user(phone="+919876543215")
    with transaction.atomic():
        set_local_society_id(society.id)
        CommitteeMembership.objects.create(
            society=society,
            user=user,
            role=CommitteeMembership.Role.MEMBER,
            starts_at=timezone.now() - timedelta(days=2),
            ends_at=timezone.now() - timedelta(days=1),
        )

    response = client.get(
        "/tenant-probe/",
        HTTP_AUTHORIZATION=f"Bearer {bearer_token(user)}",
        HTTP_X_SOCIETY_ID=str(society.id),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "No active membership in this society."}


def test_jwt_is_validated_before_society_header(client):
    response = client.get(
        "/tenant-probe/",
        HTTP_AUTHORIZATION="Bearer invalid-token",
        HTTP_X_SOCIETY_ID="not-a-uuid",
    )

    assert response.status_code == 401


def test_authenticated_request_requires_society_header(client, tenant_identity):
    user, _, _, _ = tenant_identity

    response = client.get(
        "/tenant-probe/",
        HTTP_AUTHORIZATION=f"Bearer {bearer_token(user)}",
    )

    assert response.status_code == 400
    assert response.json() == {"X-Society-ID": "This header is required."}


def test_authenticated_request_denies_society_without_membership(client, tenant_identity):
    user, _, other_society, _ = tenant_identity

    response = client.get(
        "/tenant-probe/",
        HTTP_AUTHORIZATION=f"Bearer {bearer_token(user)}",
        HTTP_X_SOCIETY_ID=str(other_society.id),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "No active membership in this society."}
    assert StaffMembership.objects.count() == 0


def test_session_revocation_is_checked_before_tenant_resolution(client, tenant_identity):
    user, society, _, _ = tenant_identity
    token = bearer_token(user)
    user.sessions_revoked_at = timezone.now() + timedelta(seconds=1)
    user.save(update_fields=("sessions_revoked_at",))

    response = client.get(
        "/tenant-probe/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_X_SOCIETY_ID=str(society.id),
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "The session has been revoked."}
    assert StaffMembership.objects.count() == 0


def test_session_version_change_revokes_existing_token(client, tenant_identity):
    user, society, _, _ = tenant_identity
    token = bearer_token(user)
    user.session_version += 1
    user.save(update_fields=("session_version",))

    response = client.get(
        "/tenant-probe/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_X_SOCIETY_ID=str(society.id),
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "The session has been revoked."}
    assert StaffMembership.objects.count() == 0