import uuid
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.authentication.tokens import SessionRefreshToken
from apps.identity.models import User
from apps.platform_access.models import PlatformAccessEvent, PlatformRoleGrant
from apps.tenancy.models import Society

pytestmark = pytest.mark.django_db(transaction=True)


def bearer_token(user):
    return str(SessionRefreshToken.for_user(user).access_token)


def platform_headers(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {bearer_token(user)}"}


def create_approved_grant(*, user, role, requested_by, approved_by, **overrides):
    return PlatformRoleGrant.objects.create(
        user=user,
        role=role,
        status=PlatformRoleGrant.Status.ACTIVE,
        reason="Approved platform access",
        requested_by=requested_by,
        approved_by=approved_by,
        approved_at=timezone.now(),
        **overrides,
    )


def create_platform_access_event(*, actor, role_grant, society):
    return PlatformAccessEvent.objects.create(
        actor=actor,
        role_grant=role_grant,
        platform_role=role_grant.role,
        society=society,
        support_session_id=uuid.uuid4(),
        case_reference="CASE-2026-0001",
        reason="Investigate a reported society directory issue.",
        correlation_id=uuid.uuid4(),
        event_type=PlatformAccessEvent.EventType.SESSION_REQUESTED,
        route_or_action="POST /api/v1/platform/support-sessions",
        outcome=PlatformAccessEvent.Outcome.SUCCEEDED,
        metadata={"requested_duration_minutes": 15},
    )


def test_platform_role_grant_observes_status_and_date_bounds():
    requester = User.objects.create_user(phone="+919876543271")
    approver = User.objects.create_user(phone="+919876543272")
    grantee = User.objects.create_user(phone="+919876543273")
    instant = timezone.now()
    current = create_approved_grant(
        user=grantee,
        role=PlatformRoleGrant.Role.PLATFORM_SUPPORT,
        requested_by=requester,
        approved_by=approver,
        starts_at=instant - timedelta(minutes=1),
        ends_at=instant + timedelta(hours=1),
    )
    expired = PlatformRoleGrant(
        user=grantee,
        role=PlatformRoleGrant.Role.PLATFORM_AUDITOR,
        status=PlatformRoleGrant.Status.ACTIVE,
        reason="Expired audit access",
        requested_by=requester,
        approved_by=approver,
        approved_at=instant - timedelta(days=2),
        starts_at=instant - timedelta(days=2),
        ends_at=instant - timedelta(days=1),
    )

    assert current.is_current(at=instant) is True
    assert expired.is_current(at=instant) is False


def test_platform_role_grant_rejects_invalid_period():
    instant = timezone.now()
    grant = PlatformRoleGrant(starts_at=instant, ends_at=instant)

    with pytest.raises(ValidationError, match="End time must be later"):
        grant.clean()


def test_database_rejects_self_approved_active_grant():
    administrator = User.objects.create_user(phone="+919876543274")

    with pytest.raises(IntegrityError), transaction.atomic():
        create_approved_grant(
            user=administrator,
            role=PlatformRoleGrant.Role.PLATFORM_ADMIN,
            requested_by=administrator,
            approved_by=administrator,
        )


def test_platform_admin_can_request_and_independent_admin_can_approve(client):
    first_admin = User.objects.create_user(phone="+919876543275")
    second_admin = User.objects.create_user(phone="+919876543276")
    bootstrap_requester = User.objects.create_user(phone="+919876543277")
    bootstrap_approver = User.objects.create_user(phone="+919876543278")
    grantee = User.objects.create_user(phone="+919876543279")
    create_approved_grant(
        user=first_admin,
        role=PlatformRoleGrant.Role.PLATFORM_ADMIN,
        requested_by=bootstrap_requester,
        approved_by=bootstrap_approver,
    )
    create_approved_grant(
        user=second_admin,
        role=PlatformRoleGrant.Role.PLATFORM_ADMIN,
        requested_by=bootstrap_requester,
        approved_by=bootstrap_approver,
    )

    create_response = client.post(
        "/api/v1/platform/role-grants/",
        {
            "user": str(grantee.id),
            "role": PlatformRoleGrant.Role.PLATFORM_SUPPORT,
            "reason": "Case management coverage",
            "ends_at": (timezone.now() + timedelta(days=30)).isoformat(),
        },
        content_type="application/json",
        **platform_headers(first_admin),
    )

    assert create_response.status_code == 201
    assert create_response.json()["status"] == PlatformRoleGrant.Status.PENDING
    grant_id = create_response.json()["id"]

    approve_response = client.post(
        f"/api/v1/platform/role-grants/{grant_id}/approve/",
        {},
        content_type="application/json",
        **platform_headers(second_admin),
    )

    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == PlatformRoleGrant.Status.ACTIVE
    assert approve_response.json()["approved_by"] == str(second_admin.id)


def test_platform_admin_cannot_approve_own_request(client):
    administrator = User.objects.create_user(phone="+919876543280")
    bootstrap_requester = User.objects.create_user(phone="+919876543281")
    bootstrap_approver = User.objects.create_user(phone="+919876543282")
    grantee = User.objects.create_user(phone="+919876543283")
    create_approved_grant(
        user=administrator,
        role=PlatformRoleGrant.Role.PLATFORM_ADMIN,
        requested_by=bootstrap_requester,
        approved_by=bootstrap_approver,
    )
    grant = PlatformRoleGrant.objects.create(
        user=grantee,
        role=PlatformRoleGrant.Role.PLATFORM_AUDITOR,
        reason="Compliance review",
        requested_by=administrator,
    )

    response = client.post(
        f"/api/v1/platform/role-grants/{grant.id}/approve/",
        {},
        content_type="application/json",
        **platform_headers(administrator),
    )

    assert response.status_code == 403
    grant.refresh_from_db()
    assert grant.status == PlatformRoleGrant.Status.PENDING


def test_non_admin_platform_role_cannot_manage_grants(client):
    support_user = User.objects.create_user(phone="+919876543284")
    requester = User.objects.create_user(phone="+919876543285")
    approver = User.objects.create_user(phone="+919876543286")
    create_approved_grant(
        user=support_user,
        role=PlatformRoleGrant.Role.PLATFORM_SUPPORT,
        requested_by=requester,
        approved_by=approver,
    )

    response = client.get(
        "/api/v1/platform/role-grants/",
        **platform_headers(support_user),
    )

    assert response.status_code == 403


def test_expired_platform_admin_cannot_manage_grants(client):
    administrator = User.objects.create_user(phone="+919876543290")
    requester = User.objects.create_user(phone="+919876543291")
    approver = User.objects.create_user(phone="+919876543292")
    create_approved_grant(
        user=administrator,
        role=PlatformRoleGrant.Role.PLATFORM_ADMIN,
        requested_by=requester,
        approved_by=approver,
        starts_at=timezone.now() - timedelta(days=2),
        ends_at=timezone.now() - timedelta(days=1),
    )

    response = client.get(
        "/api/v1/platform/role-grants/",
        **platform_headers(administrator),
    )

    assert response.status_code == 403


def test_platform_admin_can_revoke_grant(client):
    administrator = User.objects.create_user(phone="+919876543293")
    requester = User.objects.create_user(phone="+919876543294")
    approver = User.objects.create_user(phone="+919876543295")
    support_user = User.objects.create_user(phone="+919876543296")
    create_approved_grant(
        user=administrator,
        role=PlatformRoleGrant.Role.PLATFORM_ADMIN,
        requested_by=requester,
        approved_by=approver,
    )
    support_grant = create_approved_grant(
        user=support_user,
        role=PlatformRoleGrant.Role.PLATFORM_SUPPORT,
        requested_by=requester,
        approved_by=approver,
    )

    response = client.post(
        f"/api/v1/platform/role-grants/{support_grant.id}/revoke/",
        {},
        content_type="application/json",
        **platform_headers(administrator),
    )

    assert response.status_code == 200
    assert response.json()["status"] == PlatformRoleGrant.Status.REVOKED
    support_grant.refresh_from_db()
    assert support_grant.is_current() is False
    assert support_grant.revoked_by == administrator


def test_platform_role_does_not_grant_implicit_tenant_access(client):
    society = Society.objects.create(registration_code="NIV-PLATFORM-NO-IMPLICIT")
    support_user = User.objects.create_user(phone="+919876543287")
    requester = User.objects.create_user(phone="+919876543288")
    approver = User.objects.create_user(phone="+919876543289")
    create_approved_grant(
        user=support_user,
        role=PlatformRoleGrant.Role.PLATFORM_SUPPORT,
        requested_by=requester,
        approved_by=approver,
    )

    response = client.get(
        "/api/v1/directory/society/",
        HTTP_AUTHORIZATION=f"Bearer {bearer_token(support_user)}",
        HTTP_X_SOCIETY_ID=str(society.id),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "No active membership in this society."}


def test_platform_access_event_records_required_context():
    actor = User.objects.create_user(phone="+919876543297")
    requester = User.objects.create_user(phone="+919876543298")
    approver = User.objects.create_user(phone="+919876543299")
    society = Society.objects.create(registration_code="NIV-PLATFORM-EVENT")
    grant = create_approved_grant(
        user=actor,
        role=PlatformRoleGrant.Role.PLATFORM_SUPPORT,
        requested_by=requester,
        approved_by=approver,
    )

    event = create_platform_access_event(
        actor=actor,
        role_grant=grant,
        society=society,
    )

    assert event.occurred_at is not None
    assert event.platform_role == PlatformRoleGrant.Role.PLATFORM_SUPPORT
    assert event.society == society
    assert event.case_reference == "CASE-2026-0001"
    assert event.metadata == {"requested_duration_minutes": 15}


def test_database_rejects_platform_access_event_update():
    actor = User.objects.create_user(phone="+919876543300")
    requester = User.objects.create_user(phone="+919876543301")
    approver = User.objects.create_user(phone="+919876543302")
    society = Society.objects.create(registration_code="NIV-PLATFORM-EVENT-UPDATE")
    grant = create_approved_grant(
        user=actor,
        role=PlatformRoleGrant.Role.PLATFORM_SUPPORT,
        requested_by=requester,
        approved_by=approver,
    )
    event = create_platform_access_event(
        actor=actor,
        role_grant=grant,
        society=society,
    )

    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
        PlatformAccessEvent.objects.filter(pk=event.pk).update(
            outcome=PlatformAccessEvent.Outcome.FAILED,
        )

    event.refresh_from_db()
    assert event.outcome == PlatformAccessEvent.Outcome.SUCCEEDED


def test_database_rejects_platform_access_event_delete():
    actor = User.objects.create_user(phone="+919876543303")
    requester = User.objects.create_user(phone="+919876543304")
    approver = User.objects.create_user(phone="+919876543305")
    society = Society.objects.create(registration_code="NIV-PLATFORM-EVENT-DELETE")
    grant = create_approved_grant(
        user=actor,
        role=PlatformRoleGrant.Role.PLATFORM_AUDITOR,
        requested_by=requester,
        approved_by=approver,
    )
    event = create_platform_access_event(
        actor=actor,
        role_grant=grant,
        society=society,
    )

    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
        PlatformAccessEvent.objects.filter(pk=event.pk).delete()

    assert PlatformAccessEvent.objects.filter(pk=event.pk).exists()