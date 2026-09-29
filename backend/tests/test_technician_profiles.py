from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.authentication.tokens import SessionRefreshToken
from apps.identity.models import User
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import Society, StaffMembership, TechnicianProfile

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


def create_technician(*, society, user, **overrides):
    with transaction.atomic():
        set_local_society_id(society.id)
        return TechnicianProfile.objects.create(
            society=society,
            user=user,
            **overrides,
        )


def test_facility_manager_can_create_and_list_technician_profile(client):
    society = Society.objects.create(registration_code="NIV-TECH-CREATE")
    manager = create_staff_member(
        society=society,
        phone="+919876543330",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )

    create_response = client.post(
        "/api/v1/directory/technicians/",
        {
            "user": str(manager.id),
            "max_active_tickets": 7,
            "current_active_tickets_count": 4,
        },
        content_type="application/json",
        **request_headers(manager, society),
    )
    list_response = client.get(
        "/api/v1/directory/technicians/",
        **request_headers(manager, society),
    )

    assert create_response.status_code == 201
    assert create_response.json()["society_id"] == str(society.id)
    assert create_response.json()["max_active_tickets"] == 7
    assert create_response.json()["current_active_tickets_count"] == 0
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [
        create_response.json()["id"]
    ]


def test_non_manager_cannot_manage_technician_profiles(client):
    society = Society.objects.create(registration_code="NIV-TECH-FORBIDDEN")
    operator = create_staff_member(
        society=society,
        phone="+919876543331",
        role=StaffMembership.Role.HELPDESK_OPERATOR,
    )

    response = client.get(
        "/api/v1/directory/technicians/",
        **request_headers(operator, society),
    )

    assert response.status_code == 403


def test_technician_reads_are_scoped_to_selected_society(client):
    society = Society.objects.create(registration_code="NIV-TECH-SCOPE-A")
    other_society = Society.objects.create(registration_code="NIV-TECH-SCOPE-B")
    manager = create_staff_member(
        society=society,
        phone="+919876543332",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    other_manager = create_staff_member(
        society=other_society,
        phone="+919876543333",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    selected = create_technician(society=society, user=manager)
    create_technician(society=other_society, user=other_manager)

    response = client.get(
        "/api/v1/directory/technicians/",
        **request_headers(manager, society),
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(selected.id)]


def test_current_technician_profile_grants_tenant_entry(client):
    society = Society.objects.create(registration_code="NIV-TECH-CURRENT")
    technician = User.objects.create_user(phone="+919876543334")
    profile = create_technician(society=society, user=technician)

    response = client.get(
        "/api/v1/directory/society/",
        **request_headers(technician, society),
    )

    assert profile.is_current() is True
    assert response.status_code == 200
    assert response.json()["id"] == str(society.id)


def test_expired_technician_profile_denies_tenant_entry(client):
    society = Society.objects.create(registration_code="NIV-TECH-EXPIRED")
    technician = User.objects.create_user(phone="+919876543335")
    create_technician(
        society=society,
        user=technician,
        starts_at=timezone.now() - timedelta(days=2),
        ends_at=timezone.now() - timedelta(days=1),
    )

    response = client.get(
        "/api/v1/directory/society/",
        **request_headers(technician, society),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "No active membership in this society."}


def test_technician_profile_rejects_invalid_period_and_capacity():
    instant = timezone.now()
    profile = TechnicianProfile(
        starts_at=instant,
        ends_at=instant,
        max_active_tickets=0,
        current_active_tickets_count=1,
    )

    with pytest.raises(ValidationError) as exc_info:
        profile.clean()

    assert set(exc_info.value.message_dict) == {
        "ends_at",
        "max_active_tickets",
        "current_active_tickets_count",
    }


def test_database_rejects_technician_workload_above_capacity():
    society = Society.objects.create(registration_code="NIV-TECH-CAPACITY")
    technician = User.objects.create_user(phone="+919876543336")

    with pytest.raises(IntegrityError), transaction.atomic():
        set_local_society_id(society.id)
        TechnicianProfile.objects.create(
            society=society,
            user=technician,
            max_active_tickets=1,
            current_active_tickets_count=2,
        )


def test_technician_rls_is_forced_and_limits_tenant_reads():
    society = Society.objects.create(registration_code="NIV-TECH-RLS-A")
    other_society = Society.objects.create(registration_code="NIV-TECH-RLS-B")
    technician = User.objects.create_user(phone="+919876543337")
    other_technician = User.objects.create_user(phone="+919876543338")
    selected = create_technician(society=society, user=technician)
    create_technician(society=other_society, user=other_technician)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE oid = 'tenancy_technician_profile'::regclass
            """
        )
        assert cursor.fetchone() == (True, True)

    with transaction.atomic():
        set_local_society_id(society.id)
        technician_ids = list(TechnicianProfile.objects.values_list("id", flat=True))

    assert technician_ids == [selected.id]