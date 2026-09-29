import pytest
from django.db import IntegrityError, transaction

from apps.authentication.tokens import SessionRefreshToken
from apps.identity.models import User
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import Block, CommonArea, Society, StaffMembership, Unit

pytestmark = pytest.mark.django_db(transaction=True)


def bearer_token(user):
    return str(SessionRefreshToken.for_user(user).access_token)


def create_member(*, society, phone, role):
    user = User.objects.create_user(phone=phone)
    with transaction.atomic():
        set_local_society_id(society.id)
        StaffMembership.objects.create(society=society, user=user, role=role)
    return user


def create_block(*, society, name, code):
    with transaction.atomic():
        set_local_society_id(society.id)
        return Block.objects.create(society=society, name=name, code=code)


def request_headers(user, society):
    return {
        "HTTP_AUTHORIZATION": f"Bearer {bearer_token(user)}",
        "HTTP_X_SOCIETY_ID": str(society.id),
    }


def test_directory_reads_are_scoped_to_selected_society(client):
    society = Society.objects.create(registration_code="NIV-DIR-A")
    other_society = Society.objects.create(registration_code="NIV-DIR-B")
    user = create_member(
        society=society,
        phone="+919876543221",
        role=StaffMembership.Role.HELPDESK_OPERATOR,
    )
    selected_block = create_block(society=society, name="Alpha", code="A")
    create_block(society=other_society, name="Beta", code="B")

    response = client.get(
        "/api/v1/directory/blocks/",
        **request_headers(user, society),
    )

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(selected_block.id),
            "society_id": str(society.id),
            "name": "Alpha",
            "code": "A",
            "is_active": True,
        }
    ]


@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        (StaffMembership.Role.FACILITY_MANAGER, 201),
        (StaffMembership.Role.ESTATE_SUPERVISOR, 201),
        (StaffMembership.Role.HELPDESK_OPERATOR, 403),
    ],
)
def test_directory_write_authorization_contract(client, role, expected_status):
    society = Society.objects.create(registration_code=f"NIV-{role[:8]}")
    phone_suffix = {
        StaffMembership.Role.FACILITY_MANAGER: "222",
        StaffMembership.Role.ESTATE_SUPERVISOR: "223",
        StaffMembership.Role.HELPDESK_OPERATOR: "224",
    }[role]
    user = create_member(
        society=society,
        phone=f"+919876543{phone_suffix}",
        role=role,
    )

    response = client.post(
        "/api/v1/directory/blocks/",
        {"name": "  North   Tower  ", "code": " nt "},
        content_type="application/json",
        **request_headers(user, society),
    )

    assert response.status_code == expected_status
    if expected_status == 201:
        assert response.json()["name"] == "North Tower"
        assert response.json()["code"] == "NT"


def test_unit_creation_rejects_block_from_another_society(client):
    society = Society.objects.create(registration_code="NIV-UNIT-A")
    other_society = Society.objects.create(registration_code="NIV-UNIT-B")
    user = create_member(
        society=society,
        phone="+919876543225",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    other_block = create_block(society=other_society, name="Other", code="O")

    response = client.post(
        "/api/v1/directory/units/",
        {"block": str(other_block.id), "door_number": "101"},
        content_type="application/json",
        **request_headers(user, society),
    )

    assert response.status_code == 400
    assert "block" in response.json()


def test_common_area_name_is_normalized_and_unique(client):
    society = Society.objects.create(registration_code="NIV-COMMON")
    user = create_member(
        society=society,
        phone="+919876543226",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    headers = request_headers(user, society)

    created = client.post(
        "/api/v1/directory/common-areas/",
        {"name": "  Club   House  "},
        content_type="application/json",
        **headers,
    )
    duplicate = client.post(
        "/api/v1/directory/common-areas/",
        {"name": "club house"},
        content_type="application/json",
        **headers,
    )

    assert created.status_code == 201
    assert created.json()["name"] == "Club House"
    assert duplicate.status_code == 400
    assert duplicate.json() == {
        "name": ["A common area with this name already exists in the society."]
    }


def test_database_rejects_unit_block_from_another_society():
    society = Society.objects.create(registration_code="NIV-FK-A")
    other_society = Society.objects.create(registration_code="NIV-FK-B")
    other_block = create_block(society=other_society, name="Other", code="O")

    with pytest.raises(IntegrityError), transaction.atomic():
        set_local_society_id(society.id)
        Unit.objects.create(
            society=society,
            block=other_block,
            door_number="101",
        )


def test_current_society_endpoint_returns_selected_tenant(client):
    society = Society.objects.create(registration_code="NIV-CURRENT")
    user = create_member(
        society=society,
        phone="+919876543227",
        role=StaffMembership.Role.HELPDESK_OPERATOR,
    )

    response = client.get(
        "/api/v1/directory/society/",
        **request_headers(user, society),
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(society.id)
    assert response.json()["registration_code"] == "NIV-CURRENT"


def test_common_area_model_normalizes_name():
    common_area = CommonArea(name="  Club   House  ")

    common_area.full_clean(exclude=("society",), validate_unique=False)

    assert common_area.name == "Club House"
    assert common_area.normalized_name == "club house"