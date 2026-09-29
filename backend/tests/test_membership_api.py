from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.authentication.tokens import SessionRefreshToken
from apps.identity.models import User
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import (
    Block,
    CommitteeMembership,
    Society,
    StaffMembership,
    TechnicianProfile,
    Unit,
    UnitOccupancy,
    Vendor,
    VendorContract,
    VendorStaffMembership,
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


def test_facility_manager_can_create_occupancy_and_committee_membership(client):
    society = Society.objects.create(registration_code="NIV-MEMBER-CREATE")
    manager = create_staff_member(
        society=society,
        phone="+919876543231",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    unit = create_unit(society=society)
    headers = request_headers(manager, society)

    occupancy_response = client.post(
        "/api/v1/directory/occupancies/",
        {
            "unit": str(unit.id),
            "user": str(manager.id),
            "occupancy_type": UnitOccupancy.OccupancyType.OWNER,
            "is_primary_contact": True,
            "can_approve_costs": True,
        },
        content_type="application/json",
        **headers,
    )
    committee_response = client.post(
        "/api/v1/directory/committee-memberships/",
        {
            "user": str(manager.id),
            "role": CommitteeMembership.Role.PRESIDENT,
        },
        content_type="application/json",
        **headers,
    )

    assert occupancy_response.status_code == 201
    assert occupancy_response.json()["society_id"] == str(society.id)
    assert committee_response.status_code == 201
    assert committee_response.json()["society_id"] == str(society.id)


@pytest.mark.parametrize(
    "role",
    [
        StaffMembership.Role.HELPDESK_OPERATOR,
        StaffMembership.Role.ESTATE_SUPERVISOR,
    ],
)
def test_non_manager_staff_cannot_manage_memberships(client, role):
    society = Society.objects.create(registration_code=f"NIV-MEMBER-{role[:8]}")
    phone_suffix = {
        StaffMembership.Role.HELPDESK_OPERATOR: "232",
        StaffMembership.Role.ESTATE_SUPERVISOR: "233",
    }[role]
    user = create_staff_member(
        society=society,
        phone=f"+919876543{phone_suffix}",
        role=role,
    )

    response = client.get(
        "/api/v1/directory/occupancies/",
        **request_headers(user, society),
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    "persona",
    ("resident", "committee", "technician", "vendor"),
)
def test_non_manager_persona_cannot_access_membership_admin_collections(
    client,
    persona,
):
    society = Society.objects.create(
        registration_code=f"NIV-MATRIX-{persona.upper()}",
    )
    phone_suffix = {
        "resident": "243",
        "committee": "244",
        "technician": "245",
        "vendor": "246",
    }[persona]
    user = User.objects.create_user(phone=f"+919876543{phone_suffix}")

    with transaction.atomic():
        set_local_society_id(society.id)
        if persona == "resident":
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
                occupancy_type=UnitOccupancy.OccupancyType.OWNER,
            )
        elif persona == "committee":
            CommitteeMembership.objects.create(
                society=society,
                user=user,
                role=CommitteeMembership.Role.MEMBER,
            )
        elif persona == "technician":
            TechnicianProfile.objects.create(society=society, user=user)
        else:
            vendor = Vendor.objects.create(
                society=society,
                company_name="Matrix Services",
                normalized_company_name="matrix services",
                contact_person="Test Dispatcher",
                phone_number="+919876543247",
            )
            contract = VendorContract.objects.create(
                society=society,
                vendor=vendor,
                starts_on=timezone.localdate() - timedelta(days=1),
                ends_on=timezone.localdate() + timedelta(days=30),
            )
            VendorStaffMembership.objects.create(
                society=society,
                vendor=vendor,
                contract=contract,
                user=user,
                role=VendorStaffMembership.Role.DISPATCHER,
            )

    headers = request_headers(user, society)
    admin_paths = (
        "/api/v1/directory/occupancies/",
        "/api/v1/directory/committee-memberships/",
        "/api/v1/directory/technicians/",
        "/api/v1/directory/vendors/",
        "/api/v1/directory/vendor-contracts/",
        "/api/v1/directory/vendor-staff-memberships/",
        "/api/v1/directory/membership-invitations/",
    )

    for path in admin_paths:
        assert client.get(path, **headers).status_code == 403
        assert (
            client.post(path, {}, content_type="application/json", **headers).status_code
            == 403
        )


def test_membership_reads_are_scoped_to_selected_society(client):
    society = Society.objects.create(registration_code="NIV-MEMBER-SCOPE-A")
    other_society = Society.objects.create(registration_code="NIV-MEMBER-SCOPE-B")
    manager = create_staff_member(
        society=society,
        phone="+919876543234",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    other_manager = create_staff_member(
        society=other_society,
        phone="+919876543235",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    unit = create_unit(society=society)
    other_unit = create_unit(society=other_society)
    with transaction.atomic():
        set_local_society_id(society.id)
        selected = UnitOccupancy.objects.create(
            society=society,
            unit=unit,
            user=manager,
            occupancy_type=UnitOccupancy.OccupancyType.OWNER,
        )
    with transaction.atomic():
        set_local_society_id(other_society.id)
        UnitOccupancy.objects.create(
            society=other_society,
            unit=other_unit,
            user=other_manager,
            occupancy_type=UnitOccupancy.OccupancyType.OWNER,
        )

    response = client.get(
        "/api/v1/directory/occupancies/",
        **request_headers(manager, society),
    )

    assert response.status_code == 200
    assert [record["id"] for record in response.json()] == [str(selected.id)]


def test_occupancy_creation_rejects_cross_society_unit(client):
    society = Society.objects.create(registration_code="NIV-OCCUPANCY-A")
    other_society = Society.objects.create(registration_code="NIV-OCCUPANCY-B")
    manager = create_staff_member(
        society=society,
        phone="+919876543236",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    other_unit = create_unit(society=other_society)

    response = client.post(
        "/api/v1/directory/occupancies/",
        {
            "unit": str(other_unit.id),
            "user": str(manager.id),
            "occupancy_type": UnitOccupancy.OccupancyType.TENANT,
        },
        content_type="application/json",
        **request_headers(manager, society),
    )

    assert response.status_code == 400
    assert "unit" in response.json()


def test_membership_creation_rejects_user_from_another_society(client):
    society = Society.objects.create(registration_code="NIV-USER-SCOPE-A")
    other_society = Society.objects.create(registration_code="NIV-USER-SCOPE-B")
    manager = create_staff_member(
        society=society,
        phone="+919876543237",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    other_user = create_staff_member(
        society=other_society,
        phone="+919876543238",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )

    response = client.post(
        "/api/v1/directory/committee-memberships/",
        {
            "user": str(other_user.id),
            "role": CommitteeMembership.Role.MEMBER,
        },
        content_type="application/json",
        **request_headers(manager, society),
    )

    assert response.status_code == 400
    assert "user" in response.json()


def test_membership_models_reject_invalid_periods():
    instant = timezone.now()
    occupancy = UnitOccupancy(starts_at=instant, ends_at=instant)
    committee_membership = CommitteeMembership(starts_at=instant, ends_at=instant)

    with pytest.raises(ValidationError, match="End time must be later"):
        occupancy.clean()
    with pytest.raises(ValidationError, match="End time must be later"):
        committee_membership.clean()


def test_membership_is_current_observes_date_bounds():
    society = Society.objects.create(registration_code="NIV-MEMBER-DATES")
    user = User.objects.create_user(phone="+919876543239")
    unit = create_unit(society=society)
    instant = timezone.now()
    occupancy = UnitOccupancy(
        society=society,
        unit=unit,
        user=user,
        occupancy_type=UnitOccupancy.OccupancyType.TENANT,
        starts_at=instant - timedelta(days=2),
        ends_at=instant - timedelta(days=1),
    )
    committee_membership = CommitteeMembership(
        society=society,
        user=user,
        role=CommitteeMembership.Role.MEMBER,
        starts_at=instant - timedelta(days=1),
        ends_at=instant + timedelta(days=1),
    )

    assert occupancy.is_current(at=instant) is False
    assert committee_membership.is_current(at=instant) is True


def test_database_rejects_occupancy_unit_from_another_society():
    society = Society.objects.create(registration_code="NIV-OCCUPANCY-FK-A")
    other_society = Society.objects.create(registration_code="NIV-OCCUPANCY-FK-B")
    user = User.objects.create_user(phone="+919876543240")
    other_unit = create_unit(society=other_society)

    with pytest.raises(IntegrityError), transaction.atomic():
        set_local_society_id(society.id)
        UnitOccupancy.objects.create(
            society=society,
            unit=other_unit,
            user=user,
            occupancy_type=UnitOccupancy.OccupancyType.TENANT,
        )