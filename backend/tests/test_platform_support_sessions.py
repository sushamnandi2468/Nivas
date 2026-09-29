from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.authentication.tokens import SessionRefreshToken
from apps.identity.models import User
from apps.platform_access.models import (
    PlatformAccessEvent,
    PlatformRoleGrant,
    PlatformSupportSession,
)
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import Block, Society, StaffMembership

pytestmark = pytest.mark.django_db(transaction=True)


def bearer_token(user, *, auth_time=None, amr=None):
    refresh_token = SessionRefreshToken.for_user(user)
    if auth_time is not None:
        refresh_token["auth_time"] = int(auth_time.timestamp())
    if amr is not None:
        refresh_token["amr"] = amr
    return str(refresh_token.access_token)


def platform_headers(user, *, auth_time=None, amr=None):
    return {
        "HTTP_AUTHORIZATION": (
            f"Bearer {bearer_token(user, auth_time=auth_time, amr=amr)}"
        )
    }


def create_approved_grant(*, user, role, requested_by, approved_by):
    return PlatformRoleGrant.objects.create(
        user=user,
        role=role,
        status=PlatformRoleGrant.Status.ACTIVE,
        reason="Approved controlled platform access",
        requested_by=requested_by,
        approved_by=approved_by,
        approved_at=timezone.now(),
    )


@pytest.fixture
def support_identity():
    support_user = User.objects.create_user(phone="+919876543310")
    requester = User.objects.create_user(phone="+919876543311")
    approver = User.objects.create_user(phone="+919876543312")
    society = Society.objects.create(registration_code="NIV-SUPPORT-A")
    grant = create_approved_grant(
        user=support_user,
        role=PlatformRoleGrant.Role.PLATFORM_SUPPORT,
        requested_by=requester,
        approved_by=approver,
    )
    return support_user, society, grant


def session_payload(society, **overrides):
    payload = {
        "society": str(society.id),
        "case_reference": "CASE-2026-1001",
        "reason": "Investigate a reported society directory issue.",
        "duration_minutes": 15,
    }
    payload.update(overrides)
    return payload


def start_support_session(client, user, society, **payload_overrides):
    return client.post(
        "/api/v1/platform/support-sessions/",
        session_payload(society, **payload_overrides),
        content_type="application/json",
        **platform_headers(
            user,
            auth_time=timezone.now() - timedelta(minutes=1),
            amr=["mfa"],
        ),
    )


def support_session_headers(user, society, session_id):
    return {
        **platform_headers(user),
        "HTTP_X_SOCIETY_ID": str(society.id),
        "HTTP_X_SUPPORT_SESSION_ID": str(session_id),
    }


def test_fresh_step_up_creates_bound_session_and_immutable_events(
    client,
    support_identity,
):
    support_user, society, grant = support_identity

    response = client.post(
        "/api/v1/platform/support-sessions/",
        session_payload(society),
        content_type="application/json",
        **platform_headers(
            support_user,
            auth_time=timezone.now() - timedelta(minutes=1),
            amr=["mfa"],
        ),
    )

    assert response.status_code == 201
    assert response.json()["persona"] == "platform_support"
    assert response.json()["read_only"] is True
    session = PlatformSupportSession.objects.get(id=response.json()["id"])
    assert session.user == support_user
    assert session.role_grant == grant
    assert session.platform_role == PlatformRoleGrant.Role.PLATFORM_SUPPORT
    assert session.society == society
    assert session.session_version == support_user.session_version
    assert list(
        PlatformAccessEvent.objects.filter(support_session_id=session.id).values_list(
            "event_type", flat=True
        )
    ) == [
        PlatformAccessEvent.EventType.SESSION_REQUESTED,
        PlatformAccessEvent.EventType.SESSION_STARTED,
    ]


@pytest.mark.parametrize(
    ("auth_time_offset", "amr"),
    [
        (None, ["mfa"]),
        (-timedelta(minutes=6), ["mfa"]),
        (timedelta(minutes=1), ["mfa"]),
        (timedelta(), None),
        (timedelta(), "mfa"),
        (timedelta(), ["pwd"]),
    ],
)
def test_session_creation_rejects_invalid_step_up(
    client,
    support_identity,
    auth_time_offset,
    amr,
):
    support_user, society, _ = support_identity
    auth_time = (
        None if auth_time_offset is None else timezone.now() + auth_time_offset
    )

    response = client.post(
        "/api/v1/platform/support-sessions/",
        session_payload(society),
        content_type="application/json",
        **platform_headers(support_user, auth_time=auth_time, amr=amr),
    )

    assert response.status_code == 403
    assert PlatformSupportSession.objects.count() == 0
    assert PlatformAccessEvent.objects.filter(
        actor=support_user,
        event_type=PlatformAccessEvent.EventType.ACCESS_DENIED,
        metadata={
            "reason_code": "step_up_denied",
            "requested_duration_minutes": 15,
        },
    ).exists()


def test_platform_admin_grant_cannot_start_tenant_session(client):
    administrator = User.objects.create_user(phone="+919876543313")
    requester = User.objects.create_user(phone="+919876543314")
    approver = User.objects.create_user(phone="+919876543315")
    society = Society.objects.create(registration_code="NIV-SUPPORT-ADMIN")
    create_approved_grant(
        user=administrator,
        role=PlatformRoleGrant.Role.PLATFORM_ADMIN,
        requested_by=requester,
        approved_by=approver,
    )

    response = client.post(
        "/api/v1/platform/support-sessions/",
        session_payload(society),
        content_type="application/json",
        **platform_headers(
            administrator,
            auth_time=timezone.now(),
            amr=["hwk"],
        ),
    )

    assert response.status_code == 403
    assert PlatformSupportSession.objects.count() == 0


def test_second_active_session_is_rejected(client, support_identity):
    support_user, society, _ = support_identity
    headers = platform_headers(
        support_user,
        auth_time=timezone.now(),
        amr=["otp"],
    )
    first_response = client.post(
        "/api/v1/platform/support-sessions/",
        session_payload(society),
        content_type="application/json",
        **headers,
    )

    second_response = client.post(
        "/api/v1/platform/support-sessions/",
        session_payload(society, case_reference="CASE-2026-1002"),
        content_type="application/json",
        **headers,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert PlatformSupportSession.objects.filter(ended_at__isnull=True).count() == 1


def test_expired_session_is_closed_before_replacement(client, support_identity):
    support_user, society, grant = support_identity
    instant = timezone.now()
    expired_session = PlatformSupportSession.objects.create(
        user=support_user,
        role_grant=grant,
        platform_role=grant.role,
        society=society,
        session_version=support_user.session_version,
        case_reference="CASE-2026-1000",
        reason="Investigate an earlier society directory issue.",
        requested_duration_minutes=30,
        started_at=instant - timedelta(minutes=40),
        expires_at=instant - timedelta(minutes=10),
    )

    response = client.post(
        "/api/v1/platform/support-sessions/",
        session_payload(society),
        content_type="application/json",
        **platform_headers(
            support_user,
            auth_time=instant,
            amr=["mfa"],
        ),
    )

    assert response.status_code == 201
    expired_session.refresh_from_db()
    assert expired_session.end_reason == PlatformSupportSession.EndReason.EXPIRED
    assert PlatformAccessEvent.objects.filter(
        support_session_id=expired_session.id,
        event_type=PlatformAccessEvent.EventType.SESSION_EXPIRED,
    ).exists()


def test_owner_can_end_session_early(client, support_identity):
    support_user, society, _ = support_identity
    headers = platform_headers(
        support_user,
        auth_time=timezone.now(),
        amr=["mfa"],
    )
    create_response = client.post(
        "/api/v1/platform/support-sessions/",
        session_payload(society),
        content_type="application/json",
        **headers,
    )
    session_id = create_response.json()["id"]

    response = client.delete(
        f"/api/v1/platform/support-sessions/{session_id}/",
        **platform_headers(support_user),
    )

    assert response.status_code == 204
    session = PlatformSupportSession.objects.get(id=session_id)
    assert session.ended_by == support_user
    assert session.end_reason == PlatformSupportSession.EndReason.ENDED_BY_USER
    assert PlatformAccessEvent.objects.filter(
        support_session_id=session.id,
        event_type=PlatformAccessEvent.EventType.SESSION_ENDED,
    ).exists()


def test_current_support_sessions_are_self_scoped_and_not_cacheable(
    client,
    support_identity,
):
    support_user, society, grant = support_identity
    own_session_id = start_support_session(client, support_user, society).json()["id"]
    other_user = User.objects.create_user(phone="+919876543321")
    create_approved_grant(
        user=other_user,
        role=PlatformRoleGrant.Role.PLATFORM_SUPPORT,
        requested_by=grant.requested_by,
        approved_by=grant.approved_by,
    )
    start_support_session(client, other_user, society)

    response = client.get(
        "/api/v1/platform/support-sessions/",
        **platform_headers(support_user),
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [own_session_id]
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-Correlation-ID"]


def test_current_support_sessions_expire_elapsed_session(client, support_identity):
    support_user, society, grant = support_identity
    instant = timezone.now()
    expired_session = PlatformSupportSession.objects.create(
        user=support_user,
        role_grant=grant,
        platform_role=grant.role,
        society=society,
        session_version=support_user.session_version,
        case_reference="CASE-2026-1004",
        reason="Investigate an elapsed support session safely.",
        requested_duration_minutes=15,
        started_at=instant - timedelta(minutes=20),
        expires_at=instant - timedelta(minutes=5),
    )

    response = client.get(
        "/api/v1/platform/support-sessions/",
        **platform_headers(support_user),
    )

    assert response.status_code == 200
    assert response.json() == []
    expired_session.refresh_from_db()
    assert expired_session.end_reason == PlatformSupportSession.EndReason.EXPIRED
    assert PlatformAccessEvent.objects.filter(
        support_session_id=expired_session.id,
        event_type=PlatformAccessEvent.EventType.SESSION_EXPIRED,
    ).exists()


def test_other_user_cannot_end_session(client, support_identity):
    support_user, society, _ = support_identity
    create_response = client.post(
        "/api/v1/platform/support-sessions/",
        session_payload(society),
        content_type="application/json",
        **platform_headers(
            support_user,
            auth_time=timezone.now(),
            amr=["mfa"],
        ),
    )
    other_user = User.objects.create_user(phone="+919876543316")

    response = client.delete(
        f"/api/v1/platform/support-sessions/{create_response.json()['id']}/",
        **platform_headers(other_user),
    )

    assert response.status_code == 403
    assert PlatformSupportSession.objects.filter(ended_at__isnull=True).exists()


def test_database_rejects_session_shorter_than_five_minutes(support_identity):
    support_user, society, grant = support_identity
    instant = timezone.now()

    with pytest.raises(IntegrityError), transaction.atomic():
        PlatformSupportSession.objects.create(
            user=support_user,
            role_grant=grant,
            platform_role=grant.role,
            society=society,
            session_version=support_user.session_version,
            case_reference="CASE-2026-1003",
            reason="Investigate a reported society directory issue.",
            requested_duration_minutes=5,
            started_at=instant,
            expires_at=instant + timedelta(minutes=4),
        )


def test_support_session_reads_only_selected_society_and_emits_event(
    client,
    support_identity,
):
    support_user, society, _ = support_identity
    other_society = Society.objects.create(registration_code="NIV-SUPPORT-B")
    with transaction.atomic():
        set_local_society_id(society.id)
        selected_block = Block.objects.create(
            society=society,
            name="Selected block",
            code="SEL",
        )
    with transaction.atomic():
        set_local_society_id(other_society.id)
        Block.objects.create(
            society=other_society,
            name="Other block",
            code="OTH",
        )
    session_id = start_support_session(client, support_user, society).json()["id"]

    response = client.get(
        "/api/v1/directory/blocks/",
        **support_session_headers(support_user, society, session_id),
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(selected_block.id)]
    assert response["Cache-Control"] == "private, no-store"
    assert response["X-NivasOps-Persona"] == "platform_support"
    assert response["X-NivasOps-Society-ID"] == str(society.id)
    assert response["X-NivasOps-Support-Case"] == "CASE-2026-1001"
    assert response["X-NivasOps-Support-Read-Only"] == "true"
    assert response["X-NivasOps-Support-Expires-At"]
    assert PlatformAccessEvent.objects.filter(
        support_session_id=session_id,
        event_type=PlatformAccessEvent.EventType.TENANT_ROUTE_ACCESSED,
        route_or_action="GET /api/v1/directory/blocks/",
    ).exists()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/directory/society/",
        "/api/v1/directory/blocks/",
        "/api/v1/directory/units/",
        "/api/v1/directory/common-areas/",
    ],
)
def test_initial_directory_allowlist_accepts_support_session(
    client,
    support_identity,
    path,
):
    support_user, society, _ = support_identity
    session_id = start_support_session(client, support_user, society).json()["id"]

    response = client.get(
        path,
        **support_session_headers(support_user, society, session_id),
    )

    assert response.status_code == 200
    assert response["X-NivasOps-Support-Read-Only"] == "true"


def test_support_session_mutation_is_denied_and_audited(client, support_identity):
    support_user, society, _ = support_identity
    session_id = start_support_session(client, support_user, society).json()["id"]

    response = client.post(
        "/api/v1/directory/blocks/",
        {"name": "Denied block", "code": "DEN"},
        content_type="application/json",
        **support_session_headers(support_user, society, session_id),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Platform support sessions are read-only."}
    with transaction.atomic():
        set_local_society_id(society.id)
        assert not Block.objects.filter(code="DEN").exists()
    assert PlatformAccessEvent.objects.filter(
        support_session_id=session_id,
        event_type=PlatformAccessEvent.EventType.ACCESS_DENIED,
        outcome=PlatformAccessEvent.Outcome.DENIED,
        metadata={"reason_code": "read_only_session"},
    ).exists()


def test_support_session_cannot_read_membership_routes(client, support_identity):
    support_user, society, _ = support_identity
    session_id = start_support_session(client, support_user, society).json()["id"]

    response = client.get(
        "/api/v1/directory/occupancies/",
        **support_session_headers(support_user, society, session_id),
    )

    assert response.status_code == 403
    assert PlatformAccessEvent.objects.filter(
        support_session_id=session_id,
        event_type=PlatformAccessEvent.EventType.ACCESS_DENIED,
        metadata={"reason_code": "route_not_allowlisted"},
    ).exists()


def test_dual_role_user_cannot_fall_through_to_tenant_authority(
    client,
    support_identity,
):
    support_user, society, _ = support_identity
    with transaction.atomic():
        set_local_society_id(society.id)
        StaffMembership.objects.create(
            society=society,
            user=support_user,
            role=StaffMembership.Role.FACILITY_MANAGER,
        )
    session_id = start_support_session(client, support_user, society).json()["id"]

    response = client.get(
        "/api/v1/directory/occupancies/",
        **support_session_headers(support_user, society, session_id),
    )

    assert response.status_code == 403
    assert response["X-NivasOps-Support-Read-Only"] == "true"
    assert PlatformAccessEvent.objects.filter(
        support_session_id=session_id,
        event_type=PlatformAccessEvent.EventType.ACCESS_DENIED,
        metadata={"reason_code": "route_not_allowlisted"},
    ).exists()


def test_support_session_rejects_cross_society_header(client, support_identity):
    support_user, society, _ = support_identity
    other_society = Society.objects.create(registration_code="NIV-SUPPORT-MISMATCH")
    session_id = start_support_session(client, support_user, society).json()["id"]

    response = client.get(
        "/api/v1/directory/blocks/",
        **support_session_headers(support_user, other_society, session_id),
    )

    assert response.status_code == 403
    assert PlatformAccessEvent.objects.filter(
        support_session_id=session_id,
        event_type=PlatformAccessEvent.EventType.ACCESS_DENIED,
        metadata={"reason_code": "society_mismatch"},
    ).exists()


def test_role_revocation_invalidates_support_session(client, support_identity):
    support_user, society, grant = support_identity
    session_id = start_support_session(client, support_user, society).json()["id"]
    revoker = User.objects.create_user(phone="+919876543317")
    grant.status = PlatformRoleGrant.Status.REVOKED
    grant.revoked_by = revoker
    grant.revoked_at = timezone.now()
    grant.save(update_fields=("status", "revoked_by", "revoked_at", "updated_at"))

    response = client.get(
        "/api/v1/directory/blocks/",
        **support_session_headers(support_user, society, session_id),
    )

    assert response.status_code == 403
    assert PlatformAccessEvent.objects.filter(
        support_session_id=session_id,
        event_type=PlatformAccessEvent.EventType.ACCESS_DENIED,
        metadata={"reason_code": "inactive_support_session"},
    ).exists()


def test_session_version_change_invalidates_support_session(client, support_identity):
    support_user, society, _ = support_identity
    session_id = start_support_session(client, support_user, society).json()["id"]
    support_user.session_version += 1
    support_user.save(update_fields=("session_version", "updated_at"))

    response = client.get(
        "/api/v1/directory/blocks/",
        **support_session_headers(support_user, society, session_id),
    )

    assert response.status_code == 403


def test_auditor_session_uses_distinct_read_only_persona(client):
    auditor = User.objects.create_user(phone="+919876543318")
    requester = User.objects.create_user(phone="+919876543319")
    approver = User.objects.create_user(phone="+919876543320")
    society = Society.objects.create(registration_code="NIV-SUPPORT-AUDITOR")
    create_approved_grant(
        user=auditor,
        role=PlatformRoleGrant.Role.PLATFORM_AUDITOR,
        requested_by=requester,
        approved_by=approver,
    )

    create_response = start_support_session(client, auditor, society)
    response = client.get(
        "/api/v1/directory/society/",
        **support_session_headers(auditor, society, create_response.json()["id"]),
    )

    assert create_response.status_code == 201
    assert create_response.json()["persona"] == "platform_auditor"
    assert response.status_code == 200
    assert response["X-NivasOps-Persona"] == "platform_auditor"


def test_elapsed_support_session_is_rejected(client, support_identity):
    support_user, society, _ = support_identity
    session_id = start_support_session(client, support_user, society).json()["id"]
    instant = timezone.now()
    PlatformSupportSession.objects.filter(id=session_id).update(
        started_at=instant - timedelta(minutes=20),
        expires_at=instant - timedelta(minutes=5),
    )

    response = client.get(
        "/api/v1/directory/blocks/",
        **support_session_headers(support_user, society, session_id),
    )

    assert response.status_code == 403
    assert PlatformAccessEvent.objects.filter(
        support_session_id=session_id,
        event_type=PlatformAccessEvent.EventType.ACCESS_DENIED,
        metadata={"reason_code": "inactive_support_session"},
    ).exists()


def test_user_deactivation_invalidates_support_session(client, support_identity):
    support_user, society, _ = support_identity
    session_id = start_support_session(client, support_user, society).json()["id"]
    headers = support_session_headers(support_user, society, session_id)
    support_user.is_active = False
    support_user.save(update_fields=("is_active", "updated_at"))

    response = client.get(
        "/api/v1/directory/blocks/",
        **headers,
    )

    assert response.status_code == 401