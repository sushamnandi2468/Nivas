from datetime import timedelta

import pytest
from django.db import connection, transaction
from django.test import override_settings
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
from apps.tickets.attachment_storage import (
    EICAR_STANDARD_TEST_SIGNATURE,
    clear_test_attachment_storage,
    generate_attachment_storage_key,
    get_test_attachment_data,
    put_test_attachment_data,
)
from apps.tickets.tasks import (
    process_quarantined_attachments,
    scan_and_promote_attachment,
)
from apps.tickets.models import (
    BusinessCalendar,
    SLAPolicyBinding,
    SLAPolicySnapshot,
    Ticket,
    TicketAttachment,
    TicketCategory,
    TicketEvent,
    TicketSubCategory,
)

pytestmark = pytest.mark.django_db(transaction=True)


def request_headers(user, society, idempotency_key=None):
    access_token = SessionRefreshToken.for_user(user).access_token
    headers = {
        "HTTP_AUTHORIZATION": f"Bearer {access_token}",
        "HTTP_X_SOCIETY_ID": str(society.id),
    }
    if idempotency_key is not None:
        headers["HTTP_IDEMPOTENCY_KEY"] = idempotency_key
    return headers


def create_unit(*, society, code, door_number):
    with transaction.atomic():
        set_local_society_id(society.id)
        block, _ = Block.objects.get_or_create(
            society=society,
            code=code,
            defaults={"name": code},
        )
        return Unit.objects.create(
            society=society,
            block=block,
            door_number=door_number,
        )


def create_resident(*, society, unit, phone):
    user = User.objects.create_user(
        phone=phone,
        email=f"resident{phone.lstrip('+')}@example.test",
        email_verified_at=timezone.now(),
    )
    with transaction.atomic():
        set_local_society_id(society.id)
        UnitOccupancy.objects.create(
            society=society,
            unit=unit,
            user=user,
            occupancy_type=UnitOccupancy.OccupancyType.OWNER,
        )
    return user


def create_staff(*, society, phone, role):
    user = User.objects.create_user(phone=phone)
    with transaction.atomic():
        set_local_society_id(society.id)
        StaffMembership.objects.create(society=society, user=user, role=role)
    return user


def create_committee_member(*, society, phone):
    user = User.objects.create_user(phone=phone)
    with transaction.atomic():
        set_local_society_id(society.id)
        CommitteeMembership.objects.create(
            society=society,
            user=user,
            role=CommitteeMembership.Role.MEMBER,
        )
    return user


def create_in_house_technician(*, society, phone):
    user = User.objects.create_user(phone=phone)
    with transaction.atomic():
        set_local_society_id(society.id)
        tech_profile = TechnicianProfile.objects.create(
            society=society,
            user=user,
            max_active_tickets=5,
        )
    return user, tech_profile


def create_vendor_with_contract_and_staff(*, society, dispatcher_phone, worker_phone):
    dispatcher_user = User.objects.create_user(phone=dispatcher_phone)
    worker_user = User.objects.create_user(phone=worker_phone)
    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name=f"Vendor {dispatcher_phone[-4:]}",
            contact_person="Manager",
            phone_number=dispatcher_phone,
        )
        contract = VendorContract.objects.create(
            society=society,
            vendor=vendor,
            starts_on=timezone.now().date(),
            ends_on=timezone.now().date() + timedelta(days=365),
            max_active_tickets=10,
        )
        dispatcher_membership = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=dispatcher_user,
            role=VendorStaffMembership.Role.DISPATCHER,
        )
        worker_membership = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=worker_user,
            role=VendorStaffMembership.Role.WORKER,
        )
    return vendor, contract, dispatcher_user, dispatcher_membership, worker_user, worker_membership


def create_sla_binding(*, society, category, priority):
    with transaction.atomic():
        set_local_society_id(society.id)
        snapshot = SLAPolicySnapshot.objects.filter(
            society=society,
            policy_key="service-api",
            policy_version=1,
        ).first()
        if snapshot is None:
            snapshot = SLAPolicySnapshot.objects.create(
                society=society,
                policy_key="service-api",
                policy_version=1,
                calendar_version=1,
                society_timezone=society.timezone,
                acceptance_duration=timedelta(hours=2),
                initial_resolution_duration=timedelta(hours=8),
                reopen_resolution_duration=timedelta(hours=4),
                l3_delay=timedelta(hours=2),
                estimate_decision_duration=timedelta(hours=24),
            )
        binding = SLAPolicyBinding.objects.filter(
            society=society,
            category=category,
            priority=priority,
        ).first()
        if binding is None:
            SLAPolicyBinding.objects.create(
                society=society,
                category=category,
                priority=priority,
                snapshot=snapshot,
            )


def create_business_calendar(*, society):
    with transaction.atomic():
        set_local_society_id(society.id)
        calendar = BusinessCalendar.objects.filter(
            society=society,
            version=1,
        ).first()
        if calendar is None:
            calendar = BusinessCalendar.objects.create(
                society=society,
                version=1,
                timezone=society.timezone,
                working_intervals=[
                    {"weekday": weekday, "start": "09:00", "end": "17:00"}
                    for weekday in range(5)
                ],
            )
        return calendar


def create_classification(*, society, workflow_type):
    is_service = workflow_type == Ticket.WorkflowType.SERVICE
    with transaction.atomic():
        set_local_society_id(society.id)
        category = TicketCategory.objects.create(
            society=society,
            name="Plumbing" if is_service else "Governance",
            normalized_name="plumbing" if is_service else "governance",
            workflow_type=workflow_type,
            allows_unit_location=is_service,
            allows_common_area_location=is_service,
            allows_no_location=not is_service,
            cost_responsibility=(
                TicketCategory.CostResponsibility.RESIDENT_UNIT
                if is_service
                else TicketCategory.CostResponsibility.SOCIETY
            ),
            completion_policy=(
                TicketCategory.CompletionPolicy.RESIDENT_CONFIRMATION
                if is_service
                else TicketCategory.CompletionPolicy.GOVERNANCE_RESOLUTION
            ),
        )
        subcategory = TicketSubCategory.objects.create(
            society=society,
            category=category,
            name="Pipe Burst" if is_service else "Policy",
            normalized_name="pipe burst" if is_service else "policy",
            default_priority=TicketSubCategory.Priority.P2,
        )
    return category, subcategory


def create_service_ticket(*, society, creator, unit):
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    with transaction.atomic():
        set_local_society_id(society.id)
        return Ticket.objects.create(
            society=society,
            creator=creator,
            category=category,
            subcategory=subcategory,
            workflow_type=Ticket.WorkflowType.SERVICE,
            unit=unit,
            title="Leaking pipe",
            description="Pipe under sink is leaking.",
            priority=subcategory.default_priority,
            status=Ticket.Status.DRAFT,
            state_version=1,
        )


def create_governance_ticket(*, society, creator):
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.GOVERNANCE,
    )
    with transaction.atomic():
        set_local_society_id(society.id)
        return Ticket.objects.create(
            society=society,
            creator=creator,
            category=category,
            subcategory=subcategory,
            workflow_type=Ticket.WorkflowType.GOVERNANCE,
            title="Noise complaint policy",
            description="Quiet hours review.",
            priority=subcategory.default_priority,
            status=Ticket.Status.DRAFT,
            state_version=1,
        )


def submit_service_ticket(*, client, society, actor, category, subcategory, unit, key):
    create_sla_binding(
        society=society,
        category=category,
        priority=subcategory.default_priority,
    )
    create_business_calendar(society=society)
    draft = client.post(
        "/api/v1/service-tickets/",
        {
            "category": str(category.id),
            "subcategory": str(subcategory.id),
            "title": "Water leak",
            "description": "Pipe leaking under sink.",
            "unit": str(unit.id),
        },
        content_type="application/json",
        **request_headers(actor, society, f"{key}-draft"),
    ).json()
    response = client.post(
        f"/api/v1/service-tickets/{draft['id']}/submit/",
        {"expected_version": 1},
        content_type="application/json",
        **request_headers(actor, society, f"{key}-submit"),
    )
    assert response.status_code == 200, response.json()
    return response.json()


def create_offered_in_house_assignment(*, client, registration_code, phone_offset):
    society = Society.objects.create(registration_code=registration_code)
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(
        society=society,
        unit=unit,
        phone=f"+91987654{phone_offset:04d}",
    )
    facility_manager = create_staff(
        society=society,
        phone=f"+91987655{phone_offset:04d}",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    technician_user, technician = create_in_house_technician(
        society=society,
        phone=f"+91987656{phone_offset:04d}",
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    submitted = submit_service_ticket(
        client=client,
        society=society,
        actor=resident,
        category=category,
        subcategory=subcategory,
        unit=unit,
        key=f"{registration_code}-offer",
    )
    offered = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-in-house/",
        {
            "expected_version": submitted["state_version"],
            "technician_id": str(technician.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, f"{registration_code}-offer"),
    )
    assert offered.status_code == 200, offered.json()
    return society, facility_manager, technician_user, technician, offered.json()


def test_resident_can_create_attachment_upload_slot(client):
    society = Society.objects.create(registration_code="NIV-ATT-01")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(society=society, unit=unit, phone="+919876541001")
    ticket = create_service_ticket(society=society, creator=resident, unit=unit)

    payload = {
        "expected_version": 1,
        "filename": "water_leak.jpg",
        "content_type": "image/jpeg",
        "byte_size": 102400,
    }
    response = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        payload,
        content_type="application/json",
        **request_headers(resident, society, "att-slot-01"),
    )
    assert response.status_code == 201, response.json()
    data = response.json()

    assert "attachment" in data
    attachment_data = data["attachment"]
    assert attachment_data["ticket_id"] == str(ticket.id)
    assert attachment_data["original_filename"] == "water_leak.jpg"
    assert attachment_data["declared_content_type"] == "image/jpeg"
    assert attachment_data["declared_byte_size"] == 102400
    assert attachment_data["status"] == "PENDING_UPLOAD"
    assert "upload_url" in data
    assert "test-quarantine" in data["upload_url"]
    assert data["upload_headers"] == {"x-ms-blob-type": "BlockBlob"}
    assert data["state_version"] == 2

    # Database verification
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket.refresh_from_db()
        assert ticket.state_version == 2

        att = TicketAttachment.objects.get(id=attachment_data["id"])
        assert att.society_id == society.id
        assert att.ticket_id == ticket.id
        assert att.uploaded_by_id == resident.id
        assert att.uploader_persona == "resident"
        assert att.original_filename == "water_leak.jpg"
        assert att.declared_content_type == "image/jpeg"
        assert att.declared_byte_size == 102400
        assert att.status == TicketAttachment.Status.PENDING_UPLOAD
        assert att.storage_key.startswith("quarantine/")

        # TicketEvent audit evidence
        event = TicketEvent.objects.get(ticket=ticket, ticket_version=2)
        assert event.event_type == TicketEvent.EventType.TICKET_ATTACHMENT_UPLOAD_SLOT_ISSUED
        assert event.actor_id == resident.id
        assert event.actor_persona == "resident"
        assert event.metadata == {
            "attachment_id": str(att.id),
            "declared_content_type": "image/jpeg",
            "declared_byte_size": 102400,
        }
        # Safe metadata: verify no sensitive tokens, raw URLs, storage keys in metadata
        assert "upload_url" not in event.metadata
        assert "storage_key" not in event.metadata
        assert "filename" not in event.metadata


def test_facility_manager_can_create_attachment_slot_on_service_and_governance(client):
    society = Society.objects.create(registration_code="NIV-ATT-02")
    unit = create_unit(society=society, code="A", door_number="102")
    resident = create_resident(society=society, unit=unit, phone="+919876541002")
    fm = create_staff(
        society=society,
        phone="+919876541003",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )

    service_ticket = create_service_ticket(society=society, creator=resident, unit=unit)
    gov_ticket = create_governance_ticket(society=society, creator=resident)

    # FM on service ticket
    resp1 = client.post(
        f"/api/v1/tickets/service/{service_ticket.id}/attachments/upload-slot/",
        {
            "expected_version": 1,
            "filename": "inspection.png",
            "content_type": "image/png",
            "byte_size": 204800,
        },
        content_type="application/json",
        **request_headers(fm, society, "att-fm-01"),
    )
    assert resp1.status_code == 201, resp1.json()

    # FM on governance ticket
    resp2 = client.post(
        f"/api/v1/tickets/governance/{gov_ticket.id}/attachments/upload-slot/",
        {
            "expected_version": 1,
            "filename": "policy_doc.pdf",
            "content_type": "application/pdf",
            "byte_size": 512000,
        },
        content_type="application/json",
        **request_headers(fm, society, "att-fm-02"),
    )
    assert resp2.status_code == 201, resp2.json()


def test_committee_member_can_create_attachment_slot_on_governance_ticket(client):
    society = Society.objects.create(registration_code="NIV-ATT-03")
    committee_user = create_committee_member(society=society, phone="+919876541004")
    gov_ticket = create_governance_ticket(society=society, creator=committee_user)

    response = client.post(
        f"/api/v1/tickets/governance/{gov_ticket.id}/attachments/upload-slot/",
        {
            "expected_version": 1,
            "filename": "resolution.pdf",
            "content_type": "application/pdf",
            "byte_size": 300000,
        },
        content_type="application/json",
        **request_headers(committee_user, society, "att-comm-01"),
    )
    assert response.status_code == 201, response.json()


def test_in_house_technician_can_create_attachment_on_assigned_ticket_and_denied_otherwise(
    client,
):
    (
        society,
        facility_manager,
        tech_user,
        tech_profile,
        offered,
    ) = create_offered_in_house_assignment(
        client=client,
        registration_code="NIV-ATT-TECH",
        phone_offset=2000,
    )
    other_tech_user, _ = create_in_house_technician(society=society, phone="+919876542099")

    # Assigned technician can issue upload slot
    response = client.post(
        f"/api/v1/tickets/service/{offered['id']}/attachments/upload-slot/",
        {
            "expected_version": offered["state_version"],
            "filename": "before_work.jpg",
            "content_type": "image/jpeg",
            "byte_size": 102400,
        },
        content_type="application/json",
        **request_headers(tech_user, society, "att-tech-01"),
    )
    assert response.status_code == 201, response.json()
    assert response.json()["attachment"]["original_filename"] == "before_work.jpg"

    # Verify event evidence records technician persona
    with transaction.atomic():
        set_local_society_id(society.id)
        event = TicketEvent.objects.get(
            ticket_id=offered["id"], ticket_version=offered["state_version"] + 1
        )
        assert event.actor_persona == "technician"

    # Other unassigned technician is denied
    resp_unassigned = client.post(
        f"/api/v1/tickets/service/{offered['id']}/attachments/upload-slot/",
        {
            "expected_version": offered["state_version"] + 1,
            "filename": "other.jpg",
            "content_type": "image/jpeg",
            "byte_size": 102400,
        },
        content_type="application/json",
        **request_headers(other_tech_user, society, "att-tech-02"),
    )
    assert resp_unassigned.status_code in {403, 404}

    # If assignment is rejected/ended, original technician is also denied
    client.post(
        f"/api/v1/service-tickets/{offered['id']}/reject/",
        {
            "expected_version": offered["state_version"] + 1,
            "reason": "Cannot take this ticket.",
        },
        content_type="application/json",
        **request_headers(tech_user, society, "att-tech-reject"),
    )

    resp_ended = client.post(
        f"/api/v1/tickets/service/{offered['id']}/attachments/upload-slot/",
        {
            "expected_version": offered["state_version"] + 2,
            "filename": "after_ended.jpg",
            "content_type": "image/jpeg",
            "byte_size": 102400,
        },
        content_type="application/json",
        **request_headers(tech_user, society, "att-tech-03"),
    )
    assert resp_ended.status_code in {403, 404}


def test_vendor_worker_can_create_attachment_on_allocated_ticket_and_denied_otherwise(client):
    society = Society.objects.create(registration_code="NIV-ATT-VEND")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(society=society, unit=unit, phone="+919876543001")
    fm = create_staff(
        society=society,
        phone="+919876543009",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    (
        vendor,
        contract,
        disp_user,
        _,
        worker_user,
        worker_membership,
    ) = create_vendor_with_contract_and_staff(
        society=society,
        dispatcher_phone="+919876543002",
        worker_phone="+919876543003",
    )
    other_worker_user = User.objects.create_user(phone="+919876543004")
    with transaction.atomic():
        set_local_society_id(society.id)
        VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=other_worker_user,
            role=VendorStaffMembership.Role.WORKER,
        )

    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    submitted = submit_service_ticket(
        client=client,
        society=society,
        actor=resident,
        category=category,
        subcategory=subcategory,
        unit=unit,
        key="vend-att-sub",
    )
    assigned = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-vendor/",
        {
            "expected_version": submitted["state_version"],
            "vendor_contract_id": str(contract.id),
        },
        content_type="application/json",
        **request_headers(fm, society, "vend-att-assign"),
    ).json()

    allocated = client.post(
        f"/api/v1/service-tickets/{assigned['id']}/allocate-vendor-worker/",
        {
            "expected_version": assigned["state_version"],
            "staff_membership_id": str(worker_membership.id),
        },
        content_type="application/json",
        **request_headers(disp_user, society, "vend-att-allocate"),
    ).json()

    # Allocated worker can create attachment
    response = client.post(
        f"/api/v1/tickets/service/{allocated['id']}/attachments/upload-slot/",
        {
            "expected_version": allocated["state_version"],
            "filename": "site_photo.png",
            "content_type": "image/png",
            "byte_size": 204800,
        },
        content_type="application/json",
        **request_headers(worker_user, society, "att-vw-01"),
    )
    assert response.status_code == 201, response.json()
    assert response.json()["attachment"]["original_filename"] == "site_photo.png"

    with transaction.atomic():
        set_local_society_id(society.id)
        event = TicketEvent.objects.get(
            ticket_id=allocated["id"], ticket_version=allocated["state_version"] + 1
        )
        assert event.actor_persona == "vendor_worker"

    # Dispatcher cannot create attachment
    resp_disp = client.post(
        f"/api/v1/tickets/service/{allocated['id']}/attachments/upload-slot/",
        {
            "expected_version": allocated["state_version"] + 1,
            "filename": "disp.png",
            "content_type": "image/png",
            "byte_size": 204800,
        },
        content_type="application/json",
        **request_headers(disp_user, society, "att-disp-01"),
    )
    assert resp_disp.status_code in {403, 404}

    # Other unallocated worker is denied
    resp_other = client.post(
        f"/api/v1/tickets/service/{allocated['id']}/attachments/upload-slot/",
        {
            "expected_version": allocated["state_version"] + 1,
            "filename": "other.png",
            "content_type": "image/png",
            "byte_size": 204800,
        },
        content_type="application/json",
        **request_headers(other_worker_user, society, "att-vw-02"),
    )
    assert resp_other.status_code in {403, 404}

    # If assignment is rejected by dispatcher, worker is denied
    client.post(
        f"/api/v1/service-tickets/{allocated['id']}/reject-vendor-assignment/",
        {
            "expected_version": allocated["state_version"] + 1,
            "reason": "Cannot service this request.",
        },
        content_type="application/json",
        **request_headers(disp_user, society, "vend-att-reject"),
    )

    resp_ended = client.post(
        f"/api/v1/tickets/service/{allocated['id']}/attachments/upload-slot/",
        {
            "expected_version": allocated["state_version"] + 2,
            "filename": "ended.png",
            "content_type": "image/png",
            "byte_size": 204800,
        },
        content_type="application/json",
        **request_headers(worker_user, society, "att-vw-03"),
    )
    assert resp_ended.status_code in {403, 404}


def test_cross_society_access_denied_and_rls_enforced(client):
    society_a = Society.objects.create(registration_code="NIV-ATT-04A")
    society_b = Society.objects.create(registration_code="NIV-ATT-04B")

    unit_a = create_unit(society=society_a, code="A", door_number="101")
    resident_a = create_resident(society=society_a, unit=unit_a, phone="+919876541005")
    ticket_a = create_service_ticket(society=society_a, creator=resident_a, unit=unit_a)

    unit_b = create_unit(society=society_b, code="B", door_number="101")
    resident_b = create_resident(society=society_b, unit=unit_b, phone="+919876541006")

    # Resident B attempts to access Ticket A with Society B header -> 404
    response = client.post(
        f"/api/v1/tickets/service/{ticket_a.id}/attachments/upload-slot/",
        {
            "expected_version": 1,
            "filename": "hack.jpg",
            "content_type": "image/jpeg",
            "byte_size": 1024,
        },
        content_type="application/json",
        **request_headers(resident_b, society_b, "att-cross-01"),
    )
    assert response.status_code == 404

    # Resident B attempts with Society A header -> 401/403 because membership not in Society A
    response_spoof = client.post(
        f"/api/v1/tickets/service/{ticket_a.id}/attachments/upload-slot/",
        {
            "expected_version": 1,
            "filename": "hack.jpg",
            "content_type": "image/jpeg",
            "byte_size": 1024,
        },
        content_type="application/json",
        **request_headers(resident_b, society_a, "att-cross-02"),
    )
    assert response_spoof.status_code in {401, 403}

    # Verify RLS table isolation
    with transaction.atomic():
        set_local_society_id(society_a.id)
        att = TicketAttachment.objects.create(
            society=society_a,
            ticket=ticket_a,
            uploaded_by=resident_a,
            uploader_persona="resident",
            original_filename="a.jpg",
            declared_content_type="image/jpeg",
            declared_byte_size=1024,
            storage_key="quarantine/test-a/obj-a",
        )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname = 'tickets_ticket_attachment'
            """
        )
        assert cursor.fetchall() == [(True, True)]
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM pg_policies
            WHERE schemaname = current_schema()
              AND tablename = 'tickets_ticket_attachment'
              AND policyname = 'tickets_attachment_society_isolation'
            """
        )
        assert cursor.fetchone()[0] == 1


def test_unrelated_resident_cannot_add_attachment(client):
    society = Society.objects.create(registration_code="NIV-ATT-05")
    unit_1 = create_unit(society=society, code="A", door_number="101")
    unit_2 = create_unit(society=society, code="A", door_number="102")
    resident_1 = create_resident(society=society, unit=unit_1, phone="+919876541007")
    resident_2 = create_resident(society=society, unit=unit_2, phone="+919876541008")

    ticket = create_service_ticket(society=society, creator=resident_1, unit=unit_1)

    response = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": 1,
            "filename": "unrelated.jpg",
            "content_type": "image/jpeg",
            "byte_size": 1024,
        },
        content_type="application/json",
        **request_headers(resident_2, society, "att-unrelated-01"),
    )
    assert response.status_code == 404


def test_wrong_workflow_endpoint_rejected(client):
    society = Society.objects.create(registration_code="NIV-ATT-06")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(society=society, unit=unit, phone="+919876541009")
    gov_ticket = create_governance_ticket(society=society, creator=resident)

    # Governance ticket called against service endpoint
    response = client.post(
        f"/api/v1/tickets/service/{gov_ticket.id}/attachments/upload-slot/",
        {
            "expected_version": 1,
            "filename": "doc.pdf",
            "content_type": "application/pdf",
            "byte_size": 1024,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-wf-01"),
    )
    assert response.status_code in {404, 409}


def test_stale_expected_version_rejected(client):
    society = Society.objects.create(registration_code="NIV-ATT-07")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(society=society, unit=unit, phone="+919876541010")
    ticket = create_service_ticket(society=society, creator=resident, unit=unit)

    response = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": 99,
            "filename": "stale.jpg",
            "content_type": "image/jpeg",
            "byte_size": 1024,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-stale-01"),
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "TICKET_VERSION_MISMATCH"
    assert body["current_version"] == 1

    with transaction.atomic():
        set_local_society_id(society.id)
        assert TicketAttachment.objects.count() == 0
        ticket.refresh_from_db()
        assert ticket.state_version == 1


def test_terminal_ticket_rejects_attachment_slot(client):
    society = Society.objects.create(registration_code="NIV-ATT-08")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(society=society, unit=unit, phone="+919876541011")
    ticket = create_service_ticket(society=society, creator=resident, unit=unit)

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket.ticket_number = "SR-2026-0001"
        ticket.submitted_at = timezone.now()
        ticket.status = Ticket.Status.CANCELLED
        ticket.state_version = 2
        ticket.save()

    response = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": 2,
            "filename": "after_cancel.jpg",
            "content_type": "image/jpeg",
            "byte_size": 1024,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-term-01"),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "TICKET_STATE_CONFLICT"


def test_invalid_metadata_rejected(client):
    society = Society.objects.create(registration_code="NIV-ATT-09")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(society=society, unit=unit, phone="+919876541012")
    ticket = create_service_ticket(society=society, creator=resident, unit=unit)

    # Oversized (> 20 MB)
    resp_oversized = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": 1,
            "filename": "huge.jpg",
            "content_type": "image/jpeg",
            "byte_size": 25 * 1024 * 1024,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-val-01"),
    )
    assert resp_oversized.status_code == 400

    # Disallowed MIME type
    resp_mime = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": 1,
            "filename": "audio.mp3",
            "content_type": "audio/mpeg",
            "byte_size": 1024,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-val-02"),
    )
    assert resp_mime.status_code == 400

    # Dangerous extension (.sh)
    resp_ext = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": 1,
            "filename": "script.sh",
            "content_type": "image/jpeg",
            "byte_size": 1024,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-val-03"),
    )
    assert resp_ext.status_code == 400

    # Path traversal filename
    resp_path = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": 1,
            "filename": "../../etc/passwd.jpg",
            "content_type": "image/jpeg",
            "byte_size": 1024,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-val-04"),
    )
    assert resp_path.status_code == 400


def test_macro_enabled_office_documents_and_mismatched_mime_types_rejected(client):
    society = Society.objects.create(registration_code="NIV-ATT-MACRO")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(society=society, unit=unit, phone="+919876541019")
    ticket = create_service_ticket(society=society, creator=resident, unit=unit)

    # Macro-enabled Word document
    resp_docm = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": 1,
            "filename": "invoice_macro.docm",
            "content_type": "application/pdf",
            "byte_size": 10240,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-macro-01"),
    )
    assert resp_docm.status_code == 400

    # Macro-enabled Excel workbook
    resp_xlsm = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": 1,
            "filename": "budget.xlsm",
            "content_type": "application/pdf",
            "byte_size": 10240,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-macro-02"),
    )
    assert resp_xlsm.status_code == 400

    # Macro-enabled PowerPoint presentation
    resp_pptm = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": 1,
            "filename": "deck.pptm",
            "content_type": "application/pdf",
            "byte_size": 10240,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-macro-03"),
    )
    assert resp_pptm.status_code == 400

    # Mismatched MIME and extension (pdf file with jpeg mime)
    resp_mismatch = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": 1,
            "filename": "document.pdf",
            "content_type": "image/jpeg",
            "byte_size": 10240,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-macro-04"),
    )
    assert resp_mismatch.status_code == 400


def test_disabled_storage_fails_closed(client):
    society = Society.objects.create(registration_code="NIV-ATT-10")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(society=society, unit=unit, phone="+919876541013")
    ticket = create_service_ticket(society=society, creator=resident, unit=unit)

    with override_settings(TICKET_ATTACHMENT_STORAGE_BACKEND="disabled"):
        response = client.post(
            f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
            {
                "expected_version": 1,
                "filename": "test.jpg",
                "content_type": "image/jpeg",
                "byte_size": 1024,
            },
            content_type="application/json",
            **request_headers(resident, society, "att-disabled-01"),
        )
        assert response.status_code == 503
        assert response.json()["code"] == "ATTACHMENT_STORAGE_UNAVAILABLE"

    # Verify no database mutation
    with transaction.atomic():
        set_local_society_id(society.id)
        assert TicketAttachment.objects.count() == 0
        ticket.refresh_from_db()
        assert ticket.state_version == 1
        assert TicketEvent.objects.count() == 0


def test_idempotent_replay_and_reused_key(client):
    society = Society.objects.create(registration_code="NIV-ATT-11")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(society=society, unit=unit, phone="+919876541014")
    ticket = create_service_ticket(society=society, creator=resident, unit=unit)

    payload = {
        "expected_version": 1,
        "filename": "replay_test.jpg",
        "content_type": "image/jpeg",
        "byte_size": 50000,
    }
    # First request: returns 201 with signed upload URL and headers
    resp1 = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        payload,
        content_type="application/json",
        **request_headers(resident, society, "idemp-key-att-01"),
    )
    assert resp1.status_code == 201
    body1 = resp1.json()
    assert "upload_url" in body1
    assert "upload_headers" in body1
    assert "expires_at" in body1

    # Replay request: same key, same payload -> returns metadata only (plan 14.2)
    resp2 = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        payload,
        content_type="application/json",
        **request_headers(resident, society, "idemp-key-att-01"),
    )
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body1["attachment"]["id"] == body2["attachment"]["id"]
    assert "upload_url" not in body2
    assert "upload_headers" not in body2
    assert "expires_at" not in body2
    assert body2["state_version"] == 2

    # Reused key with different payload -> 409
    different_payload = {
        "expected_version": 1,
        "filename": "different.jpg",
        "content_type": "image/jpeg",
        "byte_size": 50000,
    }
    resp3 = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        different_payload,
        content_type="application/json",
        **request_headers(resident, society, "idemp-key-att-01"),
    )
    assert resp3.status_code == 409
    assert resp3.json()["code"] == "IDEMPOTENCY_KEY_REUSED"

    # Only 1 attachment was created
    with transaction.atomic():
        set_local_society_id(society.id)
        assert TicketAttachment.objects.count() == 1


def test_storage_key_randomness_and_safety():
    key1 = generate_attachment_storage_key()
    key2 = generate_attachment_storage_key()

    assert key1 != key2
    assert key1.startswith("quarantine/")
    assert len(key1.split("/")) == 3
    # Verify hex characters only in tokens
    parts = key1.split("/")
    assert all(c in "0123456789abcdef" for c in parts[1])
    assert all(c in "0123456789abcdef" for c in parts[2])


def test_technician_attachment_slot_allowed_when_historical_ended_assignment_exists(client):
    (
        society,
        facility_manager,
        tech_user_1,
        _,
        offered_1,
    ) = create_offered_in_house_assignment(
        client=client,
        registration_code="NIV-ATT-HIST1",
        phone_offset=4100,
    )
    tech_user_2, tech_profile_2 = create_in_house_technician(
        society=society,
        phone="+919876544199",
    )

    # Technician 1 rejects assignment -> assignment state becomes ENDED, ticket returns to SUBMITTED
    reject_res = client.post(
        f"/api/v1/service-tickets/{offered_1['id']}/reject/",
        {
            "expected_version": offered_1["state_version"],
            "reason": "Not available.",
        },
        content_type="application/json",
        **request_headers(tech_user_1, society, "att-hist-rej-1"),
    )
    assert reject_res.status_code == 200, reject_res.json()
    rejected_data = reject_res.json()

    # FM reassigns to Technician 2
    reassign_res = client.post(
        f"/api/v1/service-tickets/{offered_1['id']}/assign-in-house/",
        {
            "expected_version": rejected_data["state_version"],
            "technician_id": str(tech_profile_2.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "att-hist-reassign"),
    )
    assert reassign_res.status_code == 200, reassign_res.json()
    reassigned_data = reassign_res.json()

    # Technician 2 (current active assignment) can issue upload slot
    # despite historical ended assignment
    response = client.post(
        f"/api/v1/tickets/service/{offered_1['id']}/attachments/upload-slot/",
        {
            "expected_version": reassigned_data["state_version"],
            "filename": "tech2_photo.jpg",
            "content_type": "image/jpeg",
            "byte_size": 102400,
        },
        content_type="application/json",
        **request_headers(tech_user_2, society, "att-hist-tech2"),
    )
    assert response.status_code == 201, response.json()
    assert response.json()["attachment"]["original_filename"] == "tech2_photo.jpg"

    # Technician 1 (historical ended assignment) is denied
    resp_tech1 = client.post(
        f"/api/v1/tickets/service/{offered_1['id']}/attachments/upload-slot/",
        {
            "expected_version": reassigned_data["state_version"] + 1,
            "filename": "tech1_denied.jpg",
            "content_type": "image/jpeg",
            "byte_size": 102400,
        },
        content_type="application/json",
        **request_headers(tech_user_1, society, "att-hist-tech1-denied"),
    )
    assert resp_tech1.status_code in {403, 404}


def test_replacement_vendor_worker_attachment_slot_allowed_when_earlier_allocation_ended(client):
    society = Society.objects.create(registration_code="NIV-ATT-HIST2")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(society=society, unit=unit, phone="+919876544201")
    fm = create_staff(
        society=society,
        phone="+919876544209",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    (
        vendor,
        contract,
        disp_user,
        _,
        worker_user_1,
        worker_membership_1,
    ) = create_vendor_with_contract_and_staff(
        society=society,
        dispatcher_phone="+919876544202",
        worker_phone="+919876544203",
    )
    worker_user_2 = User.objects.create_user(phone="+919876544204")
    with transaction.atomic():
        set_local_society_id(society.id)
        worker_membership_2 = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=worker_user_2,
            role=VendorStaffMembership.Role.WORKER,
        )

    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    submitted = submit_service_ticket(
        client=client,
        society=society,
        actor=resident,
        category=category,
        subcategory=subcategory,
        unit=unit,
        key="vend-hist-sub",
    )
    assigned = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-vendor/",
        {
            "expected_version": submitted["state_version"],
            "vendor_contract_id": str(contract.id),
        },
        content_type="application/json",
        **request_headers(fm, society, "vend-hist-assign"),
    ).json()

    allocated_1 = client.post(
        f"/api/v1/service-tickets/{assigned['id']}/allocate-vendor-worker/",
        {
            "expected_version": assigned["state_version"],
            "staff_membership_id": str(worker_membership_1.id),
        },
        content_type="application/json",
        **request_headers(disp_user, society, "vend-hist-alloc1"),
    ).json()

    # Pre-acceptance worker replacement: replace worker 1 with worker 2
    replaced = client.post(
        f"/api/v1/service-tickets/{allocated_1['id']}/replace-vendor-worker/",
        {
            "expected_version": allocated_1["state_version"],
            "staff_membership_id": str(worker_membership_2.id),
            "reason": "Worker 1 sick, replacing with Worker 2.",
        },
        content_type="application/json",
        **request_headers(disp_user, society, "vend-hist-replace"),
    ).json()

    # Worker 2 (active replacement allocation) can issue upload slot
    # despite historical ended allocation
    response = client.post(
        f"/api/v1/tickets/service/{replaced['id']}/attachments/upload-slot/",
        {
            "expected_version": replaced["state_version"],
            "filename": "worker2_work.png",
            "content_type": "image/png",
            "byte_size": 204800,
        },
        content_type="application/json",
        **request_headers(worker_user_2, society, "att-hist-vw2"),
    )
    assert response.status_code == 201, response.json()
    assert response.json()["attachment"]["original_filename"] == "worker2_work.png"

    # Worker 1 (historical replaced/ended allocation) is denied
    resp_w1 = client.post(
        f"/api/v1/tickets/service/{replaced['id']}/attachments/upload-slot/",
        {
            "expected_version": replaced["state_version"] + 1,
            "filename": "worker1_denied.png",
            "content_type": "image/png",
            "byte_size": 204800,
        },
        content_type="application/json",
        **request_headers(worker_user_1, society, "att-hist-vw1-denied"),
    )
    assert resp_w1.status_code in {403, 404}


def test_list_ticket_attachments_as_resident_and_fm(client):
    society = Society.objects.create(registration_code="NIV-ATT-LIST-01")
    unit = create_unit(society=society, code="A", door_number="201")
    resident = create_resident(society=society, unit=unit, phone="+919876542001")
    fm = create_staff(society=society, phone="+919876542002", role=StaffMembership.Role.FACILITY_MANAGER)
    ticket = create_service_ticket(society=society, creator=resident, unit=unit)

    # Initially empty
    resp = client.get(
        f"/api/v1/tickets/service/{ticket.id}/attachments/",
        **request_headers(resident, society),
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json() == []

    # Upload attachment 1 as resident
    client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": ticket.state_version,
            "filename": "leak_photo.jpg",
            "content_type": "image/jpeg",
            "byte_size": 150000,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-list-res-01"),
    )

    ticket.refresh_from_db()

    # Upload attachment 2 as FM
    client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": ticket.state_version,
            "filename": "inspection_report.pdf",
            "content_type": "application/pdf",
            "byte_size": 350000,
        },
        content_type="application/json",
        **request_headers(fm, society, "att-list-fm-01"),
    )

    # Resident lists attachments
    resp_res = client.get(
        f"/api/v1/tickets/service/{ticket.id}/attachments/",
        **request_headers(resident, society),
    )
    assert resp_res.status_code == 200
    res_data = resp_res.json()
    assert len(res_data) == 2
    assert res_data[0]["original_filename"] == "leak_photo.jpg"
    assert res_data[0]["uploader_persona"] == "resident"
    assert res_data[0]["byte_size_formatted"] == "146.5 KB"
    assert res_data[1]["original_filename"] == "inspection_report.pdf"
    assert res_data[1]["uploader_persona"] == "staff"
    assert res_data[1]["byte_size_formatted"] == "341.8 KB"

    # FM lists attachments
    resp_fm = client.get(
        f"/api/v1/tickets/service/{ticket.id}/attachments/",
        **request_headers(fm, society),
    )
    assert resp_fm.status_code == 200
    assert len(resp_fm.json()) == 2


def test_list_ticket_attachments_tenant_and_role_isolation(client):
    society_a = Society.objects.create(registration_code="NIV-ATT-ISO-A")
    society_b = Society.objects.create(registration_code="NIV-ATT-ISO-B")
    unit_a = create_unit(society=society_a, code="A", door_number="101")
    unit_b = create_unit(society=society_b, code="B", door_number="101")
    res_a = create_resident(society=society_a, unit=unit_a, phone="+919876543001")
    res_b = create_resident(society=society_b, unit=unit_b, phone="+919876543002")
    ticket_a = create_service_ticket(society=society_a, creator=res_a, unit=unit_a)

    # Add attachment to ticket_a
    client.post(
        f"/api/v1/tickets/service/{ticket_a.id}/attachments/upload-slot/",
        {
            "expected_version": ticket_a.state_version,
            "filename": "secret_doc.pdf",
            "content_type": "application/pdf",
            "byte_size": 50000,
        },
        content_type="application/json",
        **request_headers(res_a, society_a, "att-iso-res-a"),
    )

    # Resident B in Society B cannot list ticket A's attachments
    resp_b = client.get(
        f"/api/v1/tickets/service/{ticket_a.id}/attachments/",
        **request_headers(res_b, society_b),
    )
    assert resp_b.status_code == 404

    # Unrelated Resident C in Society A (different unit) cannot list attachments
    unit_a2 = create_unit(society=society_a, code="A", door_number="102")
    res_c = create_resident(society=society_a, unit=unit_a2, phone="+919876543003")
    resp_c = client.get(
        f"/api/v1/tickets/service/{ticket_a.id}/attachments/",
        **request_headers(res_c, society_a),
    )
    assert resp_c.status_code == 404


def test_attachment_upload_complete_and_clean_promotion(client):
    clear_test_attachment_storage()
    society = Society.objects.create(registration_code="NIV-ATT-PRM-01")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(society=society, unit=unit, phone="+919876544001")
    ticket = create_service_ticket(society=society, creator=resident, unit=unit)

    # 1. Issue slot
    res_slot = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": ticket.state_version,
            "filename": "water_report.pdf",
            "content_type": "application/pdf",
            "byte_size": 1024,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-prm-01"),
    )
    assert res_slot.status_code == 201
    slot_data = res_slot.json()
    att_id = slot_data["attachment"]["id"]
    assert slot_data["attachment"]["status"] == "PENDING_UPLOAD"

    with transaction.atomic():
        set_local_society_id(society.id)
        quarantine_key = TicketAttachment.objects.get(id=att_id).storage_key
    assert quarantine_key.startswith("quarantine/")

    # 2. Put clean PDF data into test storage
    clean_pdf_bytes = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\nxref\n0 1\ntrailer<</Size 1>>\nstartxref\n9\n%%EOF"
    put_test_attachment_data(quarantine_key, clean_pdf_bytes)

    # 3. Complete upload
    res_comp = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/{att_id}/complete/",
        {},
        content_type="application/json",
        **request_headers(resident, society, "att-comp-01"),
    )
    assert res_comp.status_code == 200, res_comp.json()
    comp_data = res_comp.json()
    assert comp_data["status"] == "AVAILABLE"
    assert comp_data["checksum_sha256"] is not None
    assert comp_data["actual_content_type"] == "application/pdf"
    assert comp_data["actual_byte_size"] == len(clean_pdf_bytes)

    # 4. DB checks & immutable event
    with transaction.atomic():
        set_local_society_id(society.id)
        att = TicketAttachment.objects.get(id=att_id)
        assert att.status == TicketAttachment.Status.AVAILABLE
        assert att.storage_key.startswith("clean/")
        assert att.checksum_sha256 == comp_data["checksum_sha256"]

        ticket.refresh_from_db()
        assert ticket.state_version == 3

        event = TicketEvent.objects.get(ticket=ticket, ticket_version=3)
        assert event.event_type == TicketEvent.EventType.TICKET_ATTACHMENT_PROMOTED
        assert event.actor_id == resident.id
        assert event.actor_persona == "resident"
        assert event.metadata["attachment_id"] == str(att_id)
        assert event.metadata["checksum_sha256"] == att.checksum_sha256


def test_attachment_upload_complete_eicar_malware_rejected(client):
    clear_test_attachment_storage()
    society = Society.objects.create(registration_code="NIV-ATT-PRM-02")
    unit = create_unit(society=society, code="A", door_number="102")
    resident = create_resident(society=society, unit=unit, phone="+919876544002")
    ticket = create_service_ticket(society=society, creator=resident, unit=unit)

    res_slot = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": ticket.state_version,
            "filename": "suspicious.pdf",
            "content_type": "application/pdf",
            "byte_size": 68,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-mal-01"),
    )
    assert res_slot.status_code == 201
    slot_data = res_slot.json()
    att_id = slot_data["attachment"]["id"]

    with transaction.atomic():
        set_local_society_id(society.id)
        quarantine_key = TicketAttachment.objects.get(id=att_id).storage_key

    # Put EICAR malware test string into test storage
    put_test_attachment_data(quarantine_key, EICAR_STANDARD_TEST_SIGNATURE)

    res_comp = client.post(
        f"/api/v1/attachments/{att_id}/complete/",
        {},
        content_type="application/json",
        **request_headers(resident, society, "att-comp-mal"),
    )
    assert res_comp.status_code == 200
    comp_data = res_comp.json()
    assert comp_data["status"] == "REJECTED"

    with transaction.atomic():
        set_local_society_id(society.id)
        att = TicketAttachment.objects.get(id=att_id)
        assert att.status == TicketAttachment.Status.REJECTED

        # Verify quarantine object was purged from storage
        assert get_test_attachment_data(quarantine_key) is None

        ticket.refresh_from_db()
        event = TicketEvent.objects.get(ticket=ticket, ticket_version=ticket.state_version)
        assert event.event_type == TicketEvent.EventType.TICKET_ATTACHMENT_REJECTED
        assert event.metadata["threat_name"] == "EICAR-Standard-AV-Test-Signature"
        assert event.metadata["error_code"] == "MALWARE_DETECTED"


def test_attachment_upload_complete_mime_mismatch_rejected(client):
    clear_test_attachment_storage()
    society = Society.objects.create(registration_code="NIV-ATT-PRM-03")
    unit = create_unit(society=society, code="A", door_number="103")
    resident = create_resident(society=society, unit=unit, phone="+919876544003")
    ticket = create_service_ticket(society=society, creator=resident, unit=unit)

    res_slot = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": ticket.state_version,
            "filename": "fake_image.jpg",
            "content_type": "image/jpeg",
            "byte_size": 256,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-mime-01"),
    )
    assert res_slot.status_code == 201
    slot_data = res_slot.json()
    att_id = slot_data["attachment"]["id"]

    with transaction.atomic():
        set_local_society_id(society.id)
        quarantine_key = TicketAttachment.objects.get(id=att_id).storage_key

    # Put PNG data instead of declared JPEG
    png_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    put_test_attachment_data(quarantine_key, png_data)

    res_comp = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/{att_id}/complete/",
        {},
        content_type="application/json",
        **request_headers(resident, society, "att-comp-mime"),
    )
    assert res_comp.status_code == 200
    comp_data = res_comp.json()
    assert comp_data["status"] == "REJECTED"

    with transaction.atomic():
        set_local_society_id(society.id)
        att = TicketAttachment.objects.get(id=att_id)
        assert att.status == TicketAttachment.Status.REJECTED

        ticket.refresh_from_db()
        event = TicketEvent.objects.get(ticket=ticket, ticket_version=ticket.state_version)
        assert event.event_type == TicketEvent.EventType.TICKET_ATTACHMENT_REJECTED
        assert event.metadata["error_code"] == "MIME_TYPE_MISMATCH"


def test_celery_task_scan_and_promote_attachment(client):
    clear_test_attachment_storage()
    society = Society.objects.create(registration_code="NIV-ATT-CEL-01")
    unit = create_unit(society=society, code="A", door_number="104")
    resident = create_resident(society=society, unit=unit, phone="+919876544004")
    ticket = create_service_ticket(society=society, creator=resident, unit=unit)

    res_slot = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": ticket.state_version,
            "filename": "task_photo.png",
            "content_type": "image/png",
            "byte_size": 256,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-cel-01"),
    )
    att_id = res_slot.json()["attachment"]["id"]

    with transaction.atomic():
        set_local_society_id(society.id)
        quarantine_key = TicketAttachment.objects.get(id=att_id).storage_key

    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    put_test_attachment_data(quarantine_key, png_bytes)

    # Run Celery task directly
    result = scan_and_promote_attachment(str(society.id), str(att_id))
    assert result["status"] == "AVAILABLE"
    assert result["storage_key"].startswith("clean/")

    with transaction.atomic():
        set_local_society_id(society.id)
        att = TicketAttachment.objects.get(id=att_id)
        assert att.status == TicketAttachment.Status.AVAILABLE
        assert att.actual_content_type == "image/png"


def test_celery_task_process_quarantined_attachments(client):
    clear_test_attachment_storage()
    society = Society.objects.create(registration_code="NIV-ATT-CEL-02")
    unit = create_unit(society=society, code="A", door_number="105")
    resident = create_resident(society=society, unit=unit, phone="+919876544005")
    ticket = create_service_ticket(society=society, creator=resident, unit=unit)

    res_slot = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": ticket.state_version,
            "filename": "batch_photo.png",
            "content_type": "image/png",
            "byte_size": 256,
        },
        content_type="application/json",
        **request_headers(resident, society, "att-cel-02"),
    )
    att_id = res_slot.json()["attachment"]["id"]

    with transaction.atomic():
        set_local_society_id(society.id)
        quarantine_key = TicketAttachment.objects.get(id=att_id).storage_key

    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    put_test_attachment_data(quarantine_key, png_bytes)

    with transaction.atomic():
        set_local_society_id(society.id)
        TicketAttachment.objects.filter(id=att_id).update(status=TicketAttachment.Status.QUARANTINED)

    batch_result = process_quarantined_attachments(str(society.id), batch_size=10)
    assert batch_result["scanned"] == 1
    assert batch_result["available"] == 1
    assert batch_result["rejected"] == 0


def test_attachment_complete_unauthorized_user_denied(client):
    society = Society.objects.create(registration_code="NIV-ATT-DEN-01")
    unit1 = create_unit(society=society, code="A", door_number="101")
    unit2 = create_unit(society=society, code="A", door_number="102")
    resident1 = create_resident(society=society, unit=unit1, phone="+919876545001")
    resident2 = create_resident(society=society, unit=unit2, phone="+919876545002")
    ticket = create_service_ticket(society=society, creator=resident1, unit=unit1)

    res_slot = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/upload-slot/",
        {
            "expected_version": ticket.state_version,
            "filename": "secret.pdf",
            "content_type": "application/pdf",
            "byte_size": 100,
        },
        content_type="application/json",
        **request_headers(resident1, society, "att-den-slot"),
    )
    att_id = res_slot.json()["attachment"]["id"]

    # Resident 2 (different unit) cannot complete upload
    resp_denied = client.post(
        f"/api/v1/tickets/service/{ticket.id}/attachments/{att_id}/complete/",
        {},
        content_type="application/json",
        **request_headers(resident2, society, "att-den-comp"),
    )
    assert resp_denied.status_code == 403



