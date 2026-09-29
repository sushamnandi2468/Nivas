from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.authentication.tokens import SessionRefreshToken
from apps.identity.models import User
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import (
    Society,
    StaffMembership,
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
        StaffMembership.objects.create(society=society, user=user, role=role)
    return user


def create_vendor_contract(*, society, company_name="Apex Services", **overrides):
    contract_values = {
        "starts_on": timezone.localdate() - timedelta(days=1),
        "ends_on": timezone.localdate() + timedelta(days=30),
    }
    contract_values.update(overrides)
    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name=company_name,
            normalized_company_name=company_name.casefold(),
            contact_person="Karan Joshi",
            phone_number="+919876543400",
        )
        contract = VendorContract.objects.create(
            society=society,
            vendor=vendor,
            **contract_values,
        )
    return vendor, contract


def create_vendor_member(*, society, vendor, contract, user, **overrides):
    with transaction.atomic():
        set_local_society_id(society.id)
        return VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=user,
            role=VendorStaffMembership.Role.WORKER,
            **overrides,
        )


def test_facility_manager_can_create_vendor_contract_and_membership(client):
    society = Society.objects.create(registration_code="NIV-VENDOR-CREATE")
    manager = create_staff_member(
        society=society,
        phone="+919876543401",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )

    vendor_response = client.post(
        "/api/v1/directory/vendors/",
        {
            "company_name": "  Apex   Services  ",
            "contact_person": "  Karan   Joshi ",
            "phone_number": "+919876543402",
            "email": " OPERATIONS@APEX.EXAMPLE ",
        },
        content_type="application/json",
        **request_headers(manager, society),
    )
    contract_response = client.post(
        "/api/v1/directory/vendor-contracts/",
        {
            "vendor": vendor_response.json()["id"],
            "starts_on": str(timezone.localdate()),
            "ends_on": str(timezone.localdate() + timedelta(days=30)),
            "max_active_tickets": 10,
            "current_active_tickets_count": 7,
        },
        content_type="application/json",
        **request_headers(manager, society),
    )
    membership_response = client.post(
        "/api/v1/directory/vendor-staff-memberships/",
        {
            "vendor": vendor_response.json()["id"],
            "contract": contract_response.json()["id"],
            "user": str(manager.id),
            "role": VendorStaffMembership.Role.DISPATCHER,
        },
        content_type="application/json",
        **request_headers(manager, society),
    )

    assert vendor_response.status_code == 201
    assert vendor_response.json()["company_name"] == "Apex Services"
    assert vendor_response.json()["email"] == "operations@apex.example"
    assert contract_response.status_code == 201
    assert contract_response.json()["current_active_tickets_count"] == 0
    assert membership_response.status_code == 201
    assert membership_response.json()["society_id"] == str(society.id)


@pytest.mark.parametrize(
    "path",
    (
        "/api/v1/directory/vendors/",
        "/api/v1/directory/vendor-contracts/",
        "/api/v1/directory/vendor-staff-memberships/",
    ),
)
def test_non_manager_cannot_manage_vendor_records(client, path):
    society = Society.objects.create(registration_code=f"NIV-{path.split('/')[-2]}")
    operator = create_staff_member(
        society=society,
        phone="+919876543403",
        role=StaffMembership.Role.HELPDESK_OPERATOR,
    )

    response = client.get(path, **request_headers(operator, society))

    assert response.status_code == 403


def test_vendor_reads_are_scoped_to_selected_society(client):
    society = Society.objects.create(registration_code="NIV-VENDOR-SCOPE-A")
    other_society = Society.objects.create(registration_code="NIV-VENDOR-SCOPE-B")
    manager = create_staff_member(
        society=society,
        phone="+919876543404",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    selected, _ = create_vendor_contract(society=society)
    create_vendor_contract(society=other_society, company_name="Other Services")

    response = client.get(
        "/api/v1/directory/vendors/",
        **request_headers(manager, society),
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(selected.id)]


def test_current_vendor_membership_grants_tenant_entry(client):
    society = Society.objects.create(registration_code="NIV-VENDOR-CURRENT")
    vendor_user = User.objects.create_user(phone="+919876543405")
    vendor, contract = create_vendor_contract(society=society)
    membership = create_vendor_member(
        society=society,
        vendor=vendor,
        contract=contract,
        user=vendor_user,
    )

    response = client.get(
        "/api/v1/directory/society/",
        **request_headers(vendor_user, society),
    )

    assert membership.is_current() is True
    assert response.status_code == 200


def test_expired_vendor_contract_denies_tenant_entry(client):
    society = Society.objects.create(registration_code="NIV-VENDOR-EXPIRED")
    vendor_user = User.objects.create_user(phone="+919876543406")
    vendor, contract = create_vendor_contract(
        society=society,
        starts_on=timezone.localdate() - timedelta(days=30),
        ends_on=timezone.localdate() - timedelta(days=1),
    )
    create_vendor_member(
        society=society,
        vendor=vendor,
        contract=contract,
        user=vendor_user,
    )

    response = client.get(
        "/api/v1/directory/society/",
        **request_headers(vendor_user, society),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "No active membership in this society."}


def test_inactive_vendor_denies_tenant_entry(client):
    society = Society.objects.create(registration_code="NIV-VENDOR-INACTIVE")
    vendor_user = User.objects.create_user(phone="+919876543407")
    vendor, contract = create_vendor_contract(society=society)
    with transaction.atomic():
        set_local_society_id(society.id)
        vendor.is_active = False
        vendor.save(update_fields=("is_active", "updated_at"))
    create_vendor_member(
        society=society,
        vendor=vendor,
        contract=contract,
        user=vendor_user,
    )

    response = client.get(
        "/api/v1/directory/society/",
        **request_headers(vendor_user, society),
    )

    assert response.status_code == 403


def test_database_rejects_cross_society_vendor_contract():
    society = Society.objects.create(registration_code="NIV-VENDOR-FK-A")
    other_society = Society.objects.create(registration_code="NIV-VENDOR-FK-B")
    vendor, _ = create_vendor_contract(society=society)

    with pytest.raises(IntegrityError), transaction.atomic():
        set_local_society_id(other_society.id)
        VendorContract.objects.create(
            society=other_society,
            vendor=vendor,
            starts_on=timezone.localdate(),
            ends_on=timezone.localdate() + timedelta(days=30),
        )


def test_vendor_tables_force_rls_and_limit_tenant_reads():
    society = Society.objects.create(registration_code="NIV-VENDOR-RLS-A")
    other_society = Society.objects.create(registration_code="NIV-VENDOR-RLS-B")
    vendor, contract = create_vendor_contract(society=society)
    other_vendor, other_contract = create_vendor_contract(
        society=other_society,
        company_name="Other Services",
    )
    user = User.objects.create_user(phone="+919876543408")
    other_user = User.objects.create_user(phone="+919876543409")
    membership = create_vendor_member(
        society=society,
        vendor=vendor,
        contract=contract,
        user=user,
    )
    create_vendor_member(
        society=other_society,
        vendor=other_vendor,
        contract=other_contract,
        user=other_user,
    )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE oid IN (
                'tenancy_vendor'::regclass,
                'tenancy_vendor_contract'::regclass,
                'tenancy_vendor_staff_membership'::regclass
            )
            ORDER BY relname
            """
        )
        assert cursor.fetchall() == [
            ("tenancy_vendor", True, True),
            ("tenancy_vendor_contract", True, True),
            ("tenancy_vendor_staff_membership", True, True),
        ]

    with transaction.atomic():
        set_local_society_id(society.id)
        assert list(Vendor.objects.values_list("id", flat=True)) == [vendor.id]
        assert list(VendorContract.objects.values_list("id", flat=True)) == [contract.id]
        assert list(VendorStaffMembership.objects.values_list("id", flat=True)) == [membership.id]
