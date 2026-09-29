from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import IntegrityError, connection, transaction
from django.test import override_settings
from django.utils import timezone

from apps.authentication.tokens import SessionRefreshToken
from apps.identity.models import User
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import (
    Block,
    CommitteeMembership,
    MembershipInvitation,
    Society,
    StaffMembership,
    Unit,
    UnitOccupancy,
)

pytestmark = pytest.mark.django_db(transaction=True)


def bearer_token(user):
    return str(SessionRefreshToken.for_user(user).access_token)


def request_headers(user, society):
    return {
        "HTTP_AUTHORIZATION": f"Bearer {bearer_token(user)}",
        "HTTP_X_SOCIETY_ID": str(society.id),
    }


def create_staff_member(*, society, phone, role):
    user = User.objects.create_user(phone=phone)
    with transaction.atomic():
        set_local_society_id(society.id)
        StaffMembership.objects.create(
            society=society,
            user=user,
            role=role,
        )
    return user


def create_unit(*, society, code="A", door_number="101"):
    with transaction.atomic():
        set_local_society_id(society.id)
        block = Block.objects.create(society=society, name=code, code=code)
        return Unit.objects.create(
            society=society,
            block=block,
            door_number=door_number,
        )


def create_invitation(*, society, manager, phone, expires_at=None):
    with transaction.atomic():
        set_local_society_id(society.id)
        return MembershipInvitation.objects.create(
            society=society,
            invitee_phone=phone,
            persona=MembershipInvitation.Persona.STAFF,
            staff_role=StaffMembership.Role.HELPDESK_OPERATOR,
            token_digest=MembershipInvitation.digest_token(f"token-{phone}"),
            expires_at=expires_at or timezone.now() + timedelta(days=1),
            created_by=manager,
        )


def test_facility_manager_can_issue_invitation_with_one_time_token(client):
    society = Society.objects.create(registration_code="NIV-INVITE-ISSUE")
    manager = create_staff_member(
        society=society,
        phone="+919876543301",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    unit = create_unit(society=society)

    response = client.post(
        "/api/v1/directory/membership-invitations/",
        {
            "invitee_phone": "+919876543302",
            "invitee_email": "resident@example.com",
            "persona": MembershipInvitation.Persona.RESIDENT,
            "unit": str(unit.id),
            "occupancy_type": UnitOccupancy.OccupancyType.OWNER,
        },
        content_type="application/json",
        **request_headers(manager, society),
    )

    assert response.status_code == 201
    payload = response.json()
    raw_token = payload["invitation_token"]
    assert len(raw_token) >= 40
    assert "token_digest" not in payload

    with transaction.atomic():
        set_local_society_id(society.id)
        invitation = MembershipInvitation.objects.get(id=payload["id"])
        assert invitation.matches_token(raw_token)
        assert raw_token != invitation.token_digest

    list_response = client.get(
        "/api/v1/directory/membership-invitations/",
        **request_headers(manager, society),
    )
    assert list_response.status_code == 200
    assert "invitation_token" not in list_response.json()[0]
    assert "token_digest" not in list_response.json()[0]


def test_resident_can_activate_invitation_once(client):
    society = Society.objects.create(registration_code="NIV-INV-ACTIVATE")
    manager = create_staff_member(
        society=society,
        phone="+919876543324",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    unit = create_unit(society=society)
    raw_token = "activate-resident-token"
    with transaction.atomic():
        set_local_society_id(society.id)
        invitation = MembershipInvitation.objects.create(
            society=society,
            invitee_phone="+919876543325",
            invitee_email="activate.resident@example.com",
            persona=MembershipInvitation.Persona.RESIDENT,
            unit=unit,
            occupancy_type=UnitOccupancy.OccupancyType.OWNER,
            token_digest=MembershipInvitation.digest_token(raw_token),
            created_by=manager,
        )

    payload = {
        "society_id": str(society.id),
        "invitation_id": str(invitation.id),
        "token": raw_token,
        "password": "ActivatedPassword123!",
    }
    response = client.post(
        "/api/v1/auth/activate/",
        payload,
        content_type="application/json",
    )
    replay_response = client.post(
        "/api/v1/auth/activate/",
        payload,
        content_type="application/json",
    )
    login_response = client.post(
        "/api/v1/auth/login/",
        {
            "email": "activate.resident@example.com",
            "password": "ActivatedPassword123!",
        },
        content_type="application/json",
    )

    assert response.status_code == 204
    assert replay_response.status_code == 400
    assert login_response.status_code == 200
    user = User.objects.get(phone="+919876543325")
    assert user.email == "activate.resident@example.com"
    assert user.email_verified_at is not None
    assert user.check_password("ActivatedPassword123!")
    with transaction.atomic():
        set_local_society_id(society.id)
        invitation.refresh_from_db()
        occupancy = UnitOccupancy.objects.get(society=society, user=user)
        assert invitation.status == MembershipInvitation.Status.ACCEPTED
        assert invitation.accepted_by_id == user.id
        assert occupancy.unit_id == unit.id
        assert occupancy.occupancy_type == UnitOccupancy.OccupancyType.OWNER


@override_settings(PUBLIC_AUTH_EMAIL_BACKEND="azure_communication_services")
def test_issuing_invitation_queues_configured_email_delivery(client):
    society = Society.objects.create(registration_code="NIV-INV-EMAIL")
    manager = create_staff_member(
        society=society,
        phone="+919876543331",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    with patch("apps.tenancy.views.send_membership_invitation_email") as send_email:
        response = client.post(
            "/api/v1/directory/membership-invitations/",
            {
                "invitee_phone": "+919876543332",
                "invitee_email": "ACTIVATE.EMAIL@example.com",
                "persona": MembershipInvitation.Persona.STAFF,
                "staff_role": StaffMembership.Role.HELPDESK_OPERATOR,
            },
            content_type="application/json",
            **request_headers(manager, society),
        )

    assert response.status_code == 201
    assert send_email.call_count == 1
    invitation = send_email.call_args.kwargs["invitation"]
    assert invitation.invitee_email == "activate.email@example.com"
    assert invitation.matches_token(response.json()["invitation_token"])


@pytest.mark.parametrize(
    ("persona", "role", "phone", "email"),
    [
        (
            MembershipInvitation.Persona.STAFF,
            StaffMembership.Role.HELPDESK_OPERATOR,
            "+919876543326",
            "activate.staff@example.com",
        ),
        (
            MembershipInvitation.Persona.COMMITTEE,
            "MEMBER",
            "+919876543327",
            "activate.committee@example.com",
        ),
    ],
)
def test_activation_provisions_invited_non_resident_persona(
    client,
    persona,
    role,
    phone,
    email,
):
    society = Society.objects.create(registration_code=f"NIV-INV-{persona}")
    manager = create_staff_member(
        society=society,
        phone="+919876543328",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    raw_token = f"activate-{persona.lower()}-token"
    invitation_data = {"staff_role": role}
    if persona == MembershipInvitation.Persona.COMMITTEE:
        invitation_data = {"committee_role": role}
    with transaction.atomic():
        set_local_society_id(society.id)
        invitation = MembershipInvitation.objects.create(
            society=society,
            invitee_phone=phone,
            invitee_email=email,
            persona=persona,
            token_digest=MembershipInvitation.digest_token(raw_token),
            created_by=manager,
            **invitation_data,
        )

    response = client.post(
        "/api/v1/auth/activate/",
        {
            "society_id": str(society.id),
            "invitation_id": str(invitation.id),
            "token": raw_token,
            "password": "ActivatedPassword123!",
        },
        content_type="application/json",
    )

    assert response.status_code == 204
    user = User.objects.get(phone=phone)
    with transaction.atomic():
        set_local_society_id(society.id)
        if persona == MembershipInvitation.Persona.STAFF:
            membership = StaffMembership.objects.get(society=society, user=user)
        else:
            membership = CommitteeMembership.objects.get(society=society, user=user)
    assert membership.role == role


def test_invalid_token_does_not_consume_valid_invitation(client):
    society = Society.objects.create(registration_code="NIV-INV-INVALID-TOKEN")
    manager = create_staff_member(
        society=society,
        phone="+919876543329",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    invitation = create_invitation(
        society=society,
        manager=manager,
        phone="+919876543330",
    )
    with transaction.atomic():
        set_local_society_id(society.id)
        invitation.invitee_email = "pending.staff@example.com"
        invitation.save(update_fields=("invitee_email", "updated_at"))

    response = client.post(
        "/api/v1/auth/activate/",
        {
            "society_id": str(society.id),
            "invitation_id": str(invitation.id),
            "token": "wrong-token",
            "password": "ActivatedPassword123!",
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    with transaction.atomic():
        set_local_society_id(society.id)
        invitation.refresh_from_db()
        assert invitation.status == MembershipInvitation.Status.PENDING


@pytest.mark.parametrize(
    "role",
    [
        StaffMembership.Role.HELPDESK_OPERATOR,
        StaffMembership.Role.ESTATE_SUPERVISOR,
    ],
)
def test_non_manager_staff_cannot_administer_invitations(client, role):
    society = Society.objects.create(registration_code=f"NIV-INV-{role[:8]}")
    phone_suffix = {
        StaffMembership.Role.HELPDESK_OPERATOR: "303",
        StaffMembership.Role.ESTATE_SUPERVISOR: "304",
    }[role]
    user = create_staff_member(
        society=society,
        phone=f"+919876543{phone_suffix}",
        role=role,
    )

    response = client.get(
        "/api/v1/directory/membership-invitations/",
        **request_headers(user, society),
    )

    assert response.status_code == 403


def test_invitation_reads_are_scoped_to_selected_society(client):
    society = Society.objects.create(registration_code="NIV-INV-SCOPE-A")
    other_society = Society.objects.create(registration_code="NIV-INV-SCOPE-B")
    manager = create_staff_member(
        society=society,
        phone="+919876543305",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    other_manager = create_staff_member(
        society=other_society,
        phone="+919876543306",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    selected = create_invitation(
        society=society,
        manager=manager,
        phone="+919876543307",
    )
    create_invitation(
        society=other_society,
        manager=other_manager,
        phone="+919876543308",
    )

    response = client.get(
        "/api/v1/directory/membership-invitations/",
        **request_headers(manager, society),
    )

    assert response.status_code == 200
    assert [record["id"] for record in response.json()] == [str(selected.id)]


def test_invitation_rejects_mismatched_persona_and_cross_society_unit(client):
    society = Society.objects.create(registration_code="NIV-INV-VALID-A")
    other_society = Society.objects.create(registration_code="NIV-INV-VALID-B")
    manager = create_staff_member(
        society=society,
        phone="+919876543309",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    other_unit = create_unit(society=other_society)
    headers = request_headers(manager, society)

    mismatch_response = client.post(
        "/api/v1/directory/membership-invitations/",
        {
            "invitee_phone": "+919876543310",
            "invitee_email": "staff@example.com",
            "persona": MembershipInvitation.Persona.STAFF,
            "committee_role": "MEMBER",
        },
        content_type="application/json",
        **headers,
    )
    cross_society_response = client.post(
        "/api/v1/directory/membership-invitations/",
        {
            "invitee_phone": "+919876543311",
            "invitee_email": "resident@example.com",
            "persona": MembershipInvitation.Persona.RESIDENT,
            "unit": str(other_unit.id),
            "occupancy_type": UnitOccupancy.OccupancyType.TENANT,
        },
        content_type="application/json",
        **headers,
    )

    assert mismatch_response.status_code == 400
    assert "persona" in mismatch_response.json()
    assert cross_society_response.status_code == 400
    assert "unit" in cross_society_response.json()


def test_pending_invitation_can_be_revoked_idempotently(client):
    society = Society.objects.create(registration_code="NIV-INV-REVOKE")
    manager = create_staff_member(
        society=society,
        phone="+919876543312",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    invitation = create_invitation(
        society=society,
        manager=manager,
        phone="+919876543313",
    )
    url = f"/api/v1/directory/membership-invitations/{invitation.id}/revoke/"
    headers = request_headers(manager, society)

    response = client.post(url, content_type="application/json", **headers)
    repeated_response = client.post(url, content_type="application/json", **headers)

    assert response.status_code == 200
    assert response.json()["status"] == MembershipInvitation.Status.REVOKED
    assert response.json()["revoked_by_id"] == str(manager.id)
    assert repeated_response.status_code == 200
    assert repeated_response.json()["status"] == MembershipInvitation.Status.REVOKED


def test_expired_invitation_is_not_actionable(client):
    society = Society.objects.create(registration_code="NIV-INV-EXPIRED")
    manager = create_staff_member(
        society=society,
        phone="+919876543314",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    invitation = create_invitation(
        society=society,
        manager=manager,
        phone="+919876543315",
        expires_at=timezone.now() - timedelta(minutes=1),
    )

    response = client.post(
        f"/api/v1/directory/membership-invitations/{invitation.id}/revoke/",
        content_type="application/json",
        **request_headers(manager, society),
    )

    assert response.status_code == 409
    with transaction.atomic():
        set_local_society_id(society.id)
        invitation.refresh_from_db()
        assert invitation.status == MembershipInvitation.Status.EXPIRED


def test_expired_invitation_does_not_block_reissue(client):
    society = Society.objects.create(registration_code="NIV-INV-REISSUE")
    manager = create_staff_member(
        society=society,
        phone="+919876543318",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    expired = create_invitation(
        society=society,
        manager=manager,
        phone="+919876543319",
        expires_at=timezone.now() - timedelta(minutes=1),
    )

    response = client.post(
        "/api/v1/directory/membership-invitations/",
        {
            "invitee_phone": "+919876543319",
            "invitee_email": "operator@example.com",
            "persona": MembershipInvitation.Persona.STAFF,
            "staff_role": StaffMembership.Role.HELPDESK_OPERATOR,
        },
        content_type="application/json",
        **request_headers(manager, society),
    )

    assert response.status_code == 201
    with transaction.atomic():
        set_local_society_id(society.id)
        expired.refresh_from_db()
        assert expired.status == MembershipInvitation.Status.EXPIRED


def test_database_rejects_invitation_unit_from_another_society():
    society = Society.objects.create(registration_code="NIV-INV-FK-A")
    other_society = Society.objects.create(registration_code="NIV-INV-FK-B")
    manager = create_staff_member(
        society=society,
        phone="+919876543316",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    other_unit = create_unit(society=other_society)

    with pytest.raises(IntegrityError), transaction.atomic():
        set_local_society_id(society.id)
        MembershipInvitation.objects.create(
            society=society,
            invitee_phone="+919876543317",
            persona=MembershipInvitation.Persona.RESIDENT,
            unit=other_unit,
            occupancy_type=UnitOccupancy.OccupancyType.TENANT,
            token_digest=MembershipInvitation.digest_token("cross-society"),
            created_by=manager,
        )


def test_invitation_rls_is_forced_and_limits_tenant_reads():
    society = Society.objects.create(registration_code="NIV-INV-RLS-A")
    other_society = Society.objects.create(registration_code="NIV-INV-RLS-B")
    manager = create_staff_member(
        society=society,
        phone="+919876543320",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    other_manager = create_staff_member(
        society=other_society,
        phone="+919876543321",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    selected = create_invitation(
        society=society,
        manager=manager,
        phone="+919876543322",
    )
    create_invitation(
        society=other_society,
        manager=other_manager,
        phone="+919876543323",
    )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE oid = 'tenancy_membership_invitation'::regclass
            """
        )
        assert cursor.fetchone() == (True, True)

    with transaction.atomic():
        set_local_society_id(society.id)
        invitation_ids = list(
            MembershipInvitation.objects.values_list("id", flat=True)
        )

    assert invitation_ids == [selected.id]