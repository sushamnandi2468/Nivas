from datetime import timedelta
from decimal import Decimal
import uuid
from unittest.mock import patch

import pytest
from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.utils import timezone

from apps.authentication.tokens import SessionRefreshToken
from apps.identity.models import User
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import (
    Block,
    CommitteeMembership,
    CommonArea,
    Society,
    StaffMembership,
    TechnicianProfile,
    Unit,
    UnitOccupancy,
    Vendor,
    VendorContract,
    VendorStaffMembership,
)
from apps.tickets.models import (
    BusinessCalendar,
    GovernanceActionRecord,
    GovernanceDiscussion,
    GovernanceDiscussionParticipant,
    GovernanceReviewAssignment,
    IdempotencyRecord,
    SLACycle,
    SLAPolicyBinding,
    SLAPolicySnapshot,
    Ticket,
    TicketAssignment,
    TicketCategory,
    TicketComment,
    TicketCompletionChallenge,
    TicketEstimate,
    TicketEstimateLineItem,
    TicketEvent,
    TicketFeedback,
    TicketMergeRecord,
    TicketOutboxEvent,
    TicketSubCategory,
    VendorStaffAllocation,
)
from apps.tickets.completion_delivery import retrieve_completion_otp_capsule
from apps.tickets.completion_email import CompletionEmailSubmissionUnknown
from apps.tickets.services import (
    claim_ticket_outbox_events,
    confirm_ticket_outbox_event_delivery,
    mark_ticket_outbox_event_delivered,
    mark_ticket_outbox_event_submitted,
    release_ticket_outbox_event_for_retry,
    TicketOutboxClaimLost,
    TicketOutboxDeliveryConfirmationRejected,
)
from apps.tickets.tasks import publish_ticket_completion_notifications

pytestmark = pytest.mark.django_db(transaction=True)


def stub_completion_otp(monkeypatch, otp_code="123456"):
    monkeypatch.setattr(
        "apps.tickets.services.secrets.randbelow",
        lambda maximum: int(otp_code),
    )
    return otp_code


def request_headers(
    user,
    society,
    idempotency_key=None,
    *,
    step_up=False,
    step_up_at=None,
):
    access_token = SessionRefreshToken.for_user(user).access_token
    if step_up:
        authenticated_at = step_up_at or timezone.now()
        access_token["auth_time"] = int(authenticated_at.timestamp())
        access_token["amr"] = ["mfa"]
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
        block = Block.objects.create(society=society, name=code, code=code)
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


def create_classification(*, society, workflow_type, cost_responsibility=None):
    is_service = workflow_type == Ticket.WorkflowType.SERVICE
    with transaction.atomic():
        set_local_society_id(society.id)
        if cost_responsibility is None:
            cost_responsibility = (
                TicketCategory.CostResponsibility.RESIDENT_UNIT
                if is_service
                else TicketCategory.CostResponsibility.SOCIETY
            )
        category = TicketCategory.objects.create(
            society=society,
            name="Plumbing" if is_service else "Governance",
            normalized_name="plumbing" if is_service else "governance",
            workflow_type=workflow_type,
            allows_unit_location=is_service,
            allows_common_area_location=is_service,
            allows_no_location=not is_service,
            cost_responsibility=cost_responsibility,
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


def get_service_classification(*, society):
    with transaction.atomic():
        set_local_society_id(society.id)
        category = TicketCategory.objects.get(
            society=society,
            workflow_type=Ticket.WorkflowType.SERVICE,
        )
        subcategory = TicketSubCategory.objects.get(
            society=society,
            category=category,
        )
    return category, subcategory


def get_society_unit(*, society):
    with transaction.atomic():
        set_local_society_id(society.id)
        return Unit.objects.filter(society=society).first()


def ticket_payload(*, category, subcategory, unit=None, title="Water leak"):
    payload = {
        "category": str(category.id),
        "subcategory": str(subcategory.id),
        "title": title,
        "description": "Water is leaking below the kitchen sink.",
    }
    if unit is not None:
        payload["unit"] = str(unit.id)
    return payload


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


def submit_service_ticket(*, client, society, actor, category, subcategory, unit, key):
    create_sla_binding(
        society=society,
        category=category,
        priority=subcategory.default_priority,
    )
    create_business_calendar(society=society)
    draft = client.post(
        "/api/v1/service-tickets/",
        ticket_payload(category=category, subcategory=subcategory, unit=unit),
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
    technician_user = User.objects.create_user(phone=f"+91987656{phone_offset:04d}")
    with transaction.atomic():
        set_local_society_id(society.id)
        technician = TechnicianProfile.objects.create(
            society=society,
            user=technician_user,
            max_active_tickets=1,
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


def test_resident_create_is_idempotent_defaults_priority_and_ignores_status(client):
    society = Society.objects.create(registration_code="NIV-API-CREATE")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543530",
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    payload = ticket_payload(category=category, subcategory=subcategory, unit=unit)
    payload["status"] = Ticket.Status.SUBMITTED
    headers = request_headers(resident, society, "create-service-1")

    first = client.post(
        "/api/v1/service-tickets/",
        payload,
        content_type="application/json",
        **headers,
    )
    replay = client.post(
        "/api/v1/service-tickets/",
        payload,
        content_type="application/json",
        **headers,
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.DRAFT
    assert first.json()["state_version"] == 1
    assert first.json()["priority"] == TicketSubCategory.Priority.P2
    with transaction.atomic():
        set_local_society_id(society.id)
        assert Ticket.objects.count() == 1


def test_ticket_options_scope_resident_units_and_return_active_classification(client):
    society = Society.objects.create(registration_code="NIV-API-OPTIONS")
    own_unit = create_unit(society=society, code="A", door_number="110")
    other_unit = create_unit(society=society, code="B", door_number="210")
    resident = create_resident(
        society=society,
        unit=own_unit,
        phone="+919876543541",
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )

    response = client.get(
        "/api/v1/ticket-options/",
        **request_headers(resident, society),
    )

    assert response.status_code == 200
    assert response.json()["units"] == [
        {"id": str(own_unit.id), "door_number": "110", "block": "A"}
    ]
    assert str(other_unit.id) not in response.content.decode()
    assert response.json()["categories"] == [
        {
            "id": str(category.id),
            "name": "Plumbing",
            "workflow_type": Ticket.WorkflowType.SERVICE,
            "allows_unit_location": True,
            "allows_common_area_location": True,
            "allows_no_location": False,
            "subcategories": [
                {
                    "id": str(subcategory.id),
                    "name": "Pipe Burst",
                    "default_priority": TicketSubCategory.Priority.P2,
                }
            ],
        }
    ]


def test_facility_manager_begins_governance_review_idempotently(client):
    society = Society.objects.create(registration_code="NIV-API-REVIEW")
    reporter = create_committee_member(
        society=society,
        phone="+919876543552",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876543553",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.GOVERNANCE,
    )
    create_sla_binding(
        society=society,
        category=category,
        priority=subcategory.default_priority,
    )
    create_business_calendar(society=society)
    draft = client.post(
        "/api/v1/governance-tickets/",
        ticket_payload(category=category, subcategory=subcategory),
        content_type="application/json",
        **request_headers(reporter, society, "governance-review-draft"),
    ).json()
    submitted = client.post(
        f"/api/v1/governance-tickets/{draft['id']}/submit/",
        {"expected_version": 1},
        content_type="application/json",
        **request_headers(reporter, society, "governance-review-submit"),
    )
    assert submitted.status_code == 200, submitted.json()

    endpoint = f"/api/v1/governance-tickets/{draft['id']}/begin-review/"
    denied = client.post(
        endpoint,
        {"expected_version": 2},
        content_type="application/json",
        **request_headers(reporter, society, "committee-begin-review"),
    )
    headers = request_headers(facility_manager, society, "begin-governance-review")
    first = client.post(
        endpoint,
        {"expected_version": 2},
        content_type="application/json",
        **headers,
    )
    replay = client.post(
        endpoint,
        {"expected_version": 2},
        content_type="application/json",
        **headers,
    )

    assert denied.status_code == 403
    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.UNDER_REVIEW
    assert first.json()["state_version"] == 3
    assert first.json()["review_assignment"]["reviewer_id"] == str(facility_manager.id)
    with transaction.atomic():
        set_local_society_id(society.id)
        reviewed_ticket = Ticket.objects.get(id=draft["id"])
        assignment = GovernanceReviewAssignment.objects.get(ticket=reviewed_ticket)
        event = TicketEvent.objects.get(
            ticket=reviewed_ticket,
            event_type=TicketEvent.EventType.GOVERNANCE_REVIEW_BEGUN,
        )
        assert reviewed_ticket.status == Ticket.Status.UNDER_REVIEW
        assert assignment.reviewer_id == facility_manager.id
        assert assignment.assigned_by_id == facility_manager.id
        assert assignment.accepted_at is not None
        assert event.ticket_version == reviewed_ticket.state_version


def test_facility_manager_assigns_available_in_house_technician_idempotently(client):
    society = Society.objects.create(registration_code="NIV-API-IHA")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543557",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876543558",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    technician_user = User.objects.create_user(phone="+919876543559")
    with transaction.atomic():
        set_local_society_id(society.id)
        technician = TechnicianProfile.objects.create(
            society=society,
            user=technician_user,
            max_active_tickets=1,
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
        key="in-house-assign",
    )

    endpoint = f"/api/v1/service-tickets/{submitted['id']}/assign-in-house/"
    payload = {
        "expected_version": submitted["state_version"],
        "technician_id": str(technician.id),
    }
    denied = client.post(
        endpoint,
        payload,
        content_type="application/json",
        **request_headers(resident, society, "resident-in-house-assign"),
    )
    headers = request_headers(facility_manager, society, "in-house-assign")
    first = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert denied.status_code == 403
    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.ASSIGNED
    assert first.json()["state_version"] == submitted["state_version"] + 1
    assert first.json()["assignment"]["technician_id"] == str(technician.id)
    with transaction.atomic():
        set_local_society_id(society.id)
        assigned_ticket = Ticket.objects.get(id=submitted["id"])
        assignment = TicketAssignment.objects.get(ticket=assigned_ticket)
        technician.refresh_from_db()
        event = TicketEvent.objects.get(
            ticket=assigned_ticket,
            event_type=TicketEvent.EventType.TICKET_ASSIGNED,
        )
        assert assigned_ticket.status == Ticket.Status.ASSIGNED
        assert assignment.assigned_by_id == facility_manager.id
        assert assignment.state == TicketAssignment.State.OFFERED
        assert technician.current_active_tickets_count == 1
        assert event.ticket_version == assigned_ticket.state_version


def test_facility_manager_can_assign_current_vendor_contract(client):
    society = Society.objects.create(registration_code="NIV-VENDOR-ASG")
    unit = create_unit(society=society, code="A", door_number="301")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543570",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876543571",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name="Apex Plumbing",
            normalized_company_name="apex plumbing",
            contact_person="Karan Joshi",
            phone_number="+919876543572",
        )
        contract = VendorContract.objects.create(
            society=society,
            vendor=vendor,
            starts_on=timezone.localdate() - timedelta(days=1),
            ends_on=timezone.localdate() + timedelta(days=30),
            max_active_tickets=1,
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
        key="vendor-assign",
    )

    endpoint = f"/api/v1/service-tickets/{submitted['id']}/assign-vendor/"
    payload = {
        "expected_version": submitted["state_version"],
        "vendor_contract_id": str(contract.id),
    }
    denied = client.post(
        endpoint,
        payload,
        content_type="application/json",
        **request_headers(resident, society, "resident-vendor-assign"),
    )
    headers = request_headers(facility_manager, society, "vendor-assign")
    response = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert denied.status_code == 403
    assert response.status_code == 200, response.json()
    assert replay.status_code == 200
    assert replay.json() == response.json()
    assert response.json()["status"] == Ticket.Status.ASSIGNED
    assert response.json()["assignment"]["vendor_contract_id"] == str(contract.id)
    with transaction.atomic():
        set_local_society_id(society.id)
        assigned_ticket = Ticket.objects.get(id=submitted["id"])
        assignment = TicketAssignment.objects.get(ticket=assigned_ticket)
        contract.refresh_from_db()
        event = TicketEvent.objects.get(
            ticket=assigned_ticket,
            event_type=TicketEvent.EventType.TICKET_ASSIGNED,
        )
        assert assignment.target_type == TicketAssignment.TargetType.VENDOR
        assert assignment.vendor_contract_id == contract.id
        assert assignment.state == TicketAssignment.State.OFFERED
        assert contract.current_active_tickets_count == 1
        assert TicketAssignment.objects.filter(ticket=assigned_ticket).count() == 1
        assert event.ticket_version == assigned_ticket.state_version


def test_vendor_dispatcher_can_allocate_current_contract_worker(client):
    society = Society.objects.create(registration_code="NIV-VENDOR-ALLOC-API")
    unit = create_unit(society=society, code="A", door_number="302")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543573",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876543574",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    dispatcher = User.objects.create_user(phone="+919876543575")
    worker = User.objects.create_user(phone="+919876543576")
    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name="Apex Electrical",
            normalized_company_name="apex electrical",
            contact_person="Karan Joshi",
            phone_number="+919876543577",
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
            user=dispatcher,
            role=VendorStaffMembership.Role.DISPATCHER,
        )
        worker_membership = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=worker,
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
        key="vendor-worker-submit",
    )
    assigned = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-vendor/",
        {
            "expected_version": submitted["state_version"],
            "vendor_contract_id": str(contract.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "vendor-worker-assign"),
    )
    assert assigned.status_code == 200, assigned.json()

    response = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/allocate-vendor-worker/",
        {
            "expected_version": assigned.json()["state_version"],
            "staff_membership_id": str(worker_membership.id),
        },
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-worker-allocate"),
    )

    assert response.status_code == 200, response.json()
    assert response.json()["status"] == Ticket.Status.ASSIGNED
    assert response.json()["state_version"] == assigned.json()["state_version"] + 1
    replay = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/allocate-vendor-worker/",
        {
            "expected_version": assigned.json()["state_version"],
            "staff_membership_id": str(worker_membership.id),
        },
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-worker-allocate"),
    )
    assert replay.status_code == 200, replay.json()
    assert replay.json() == response.json()
    assert (
        client.post(
            f"/api/v1/service-tickets/{submitted['id']}/allocate-vendor-worker/",
            {
                "expected_version": response.json()["state_version"],
                "staff_membership_id": str(worker_membership.id),
            },
            content_type="application/json",
            **request_headers(worker, society, "vendor-worker-forbidden"),
        ).status_code
        == 403
    )
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=submitted["id"])
        allocation = VendorStaffAllocation.objects.get(assignment__ticket=ticket)
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.VENDOR_WORKER_ALLOCATED,
        )
        assert allocation.staff_membership_id == worker_membership.id
        assert allocation.allocated_by_id == dispatcher.id
        assert allocation.state == VendorStaffAllocation.State.ALLOCATED
        assert event.ticket_version == ticket.state_version
        assert VendorStaffAllocation.objects.filter(assignment__ticket=ticket).count() == 1


def test_vendor_dispatcher_replaces_allocated_worker_with_history(client):
    society = Society.objects.create(registration_code="NIV-VEND-REPLACE")
    unit = create_unit(society=society, code="A", door_number="305")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543588",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876543589",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    dispatcher = User.objects.create_user(phone="+919876543590")
    original_worker = User.objects.create_user(phone="+919876543591")
    replacement_worker = User.objects.create_user(phone="+919876543592")
    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name="Apex Plumbing",
            normalized_company_name="apex plumbing",
            contact_person="Karan Joshi",
            phone_number="+919876543593",
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
            user=dispatcher,
            role=VendorStaffMembership.Role.DISPATCHER,
        )
        original_membership = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=original_worker,
            role=VendorStaffMembership.Role.WORKER,
        )
        replacement_membership = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=replacement_worker,
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
        key="vendor-worker-replace-submit",
    )
    assigned = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-vendor/",
        {
            "expected_version": submitted["state_version"],
            "vendor_contract_id": str(contract.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "vendor-worker-replace-assign"),
    )
    assert assigned.status_code == 200, assigned.json()
    allocated = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/allocate-vendor-worker/",
        {
            "expected_version": assigned.json()["state_version"],
            "staff_membership_id": str(original_membership.id),
        },
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-worker-replace-allocate"),
    )
    assert allocated.status_code == 200, allocated.json()

    endpoint = f"/api/v1/service-tickets/{submitted['id']}/replace-vendor-worker/"
    expected_version = allocated.json()["state_version"]
    invalid = client.post(
        endpoint,
        {
            "expected_version": expected_version,
            "staff_membership_id": str(replacement_membership.id),
            "reason": "   ",
        },
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-worker-replace-invalid"),
    )
    assert invalid.status_code == 400, invalid.content
    payload = {
        "expected_version": expected_version,
        "staff_membership_id": str(replacement_membership.id),
        "reason": "Original worker is unavailable for this visit.",
    }
    response = client.post(
        endpoint,
        payload,
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-worker-replace"),
    )
    replay = client.post(
        endpoint,
        payload,
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-worker-replace"),
    )

    assert response.status_code == 200, response.content
    assert replay.status_code == 200, replay.content
    assert replay.json() == response.json()
    assert response.json()["status"] == Ticket.Status.ASSIGNED
    assert response.json()["state_version"] == expected_version + 1
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=submitted["id"])
        allocations = list(
            VendorStaffAllocation.objects.filter(assignment__ticket=ticket).order_by(
                "allocated_at"
            )
        )
        event = TicketEvent.objects.get(
            ticket=ticket,
            ticket_version=ticket.state_version,
            event_type=TicketEvent.EventType.VENDOR_WORKER_REPLACED,
        )
        assert len(allocations) == 2
        assert allocations[0].staff_membership_id == original_membership.id
        assert allocations[0].state == VendorStaffAllocation.State.ENDED
        assert allocations[0].ended_at is not None
        assert allocations[0].ended_reason == payload["reason"]
        assert allocations[1].staff_membership_id == replacement_membership.id
        assert allocations[1].state == VendorStaffAllocation.State.ALLOCATED
        assert event.metadata["replaced_vendor_staff_allocation_id"] == str(
            allocations[0].id
        )
        assert event.metadata["staff_membership_id"] == str(replacement_membership.id)
        assert event.reason == payload["reason"]


def test_vendor_worker_accepts_active_allocation_idempotently(client):
    society = Society.objects.create(registration_code="NIV-VENDOR-ACCEPT")
    unit = create_unit(society=society, code="A", door_number="303")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543578",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876543579",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    dispatcher = User.objects.create_user(phone="+919876543580")
    worker = User.objects.create_user(phone="+919876543581")
    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name="Apex HVAC",
            normalized_company_name="apex hvac",
            contact_person="Karan Joshi",
            phone_number="+919876543582",
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
            user=dispatcher,
            role=VendorStaffMembership.Role.DISPATCHER,
        )
        worker_membership = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=worker,
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
        key="vendor-worker-accept-submit",
    )
    assigned = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-vendor/",
        {
            "expected_version": submitted["state_version"],
            "vendor_contract_id": str(contract.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "vendor-worker-accept-assign"),
    )
    assert assigned.status_code == 200, assigned.json()
    allocated = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/allocate-vendor-worker/",
        {
            "expected_version": assigned.json()["state_version"],
            "staff_membership_id": str(worker_membership.id),
        },
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-worker-accept-allocate"),
    )
    assert allocated.status_code == 200, allocated.json()

    endpoint = f"/api/v1/service-tickets/{submitted['id']}/accept-vendor-worker/"
    payload = {"expected_version": allocated.json()["state_version"]}
    assert (
        client.post(
            endpoint,
            payload,
            content_type="application/json",
            **request_headers(dispatcher, society, "vendor-dispatcher-accept-forbidden"),
        ).status_code
        == 403
    )
    response = client.post(
        endpoint,
        payload,
        content_type="application/json",
        **request_headers(worker, society, "vendor-worker-accept"),
    )
    replay = client.post(
        endpoint,
        payload,
        content_type="application/json",
        **request_headers(worker, society, "vendor-worker-accept"),
    )

    assert response.status_code == 200, response.content
    assert replay.status_code == 200, replay.content
    assert replay.json() == response.json()
    assert response.json()["status"] == Ticket.Status.ACCEPTED
    assert response.json()["state_version"] == allocated.json()["state_version"] + 1
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=submitted["id"])
        assignment = TicketAssignment.objects.get(ticket=ticket)
        allocation = VendorStaffAllocation.objects.get(assignment=assignment)
        sla_cycle = SLACycle.objects.get(ticket=ticket, ended_at__isnull=True)
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_ASSIGNMENT_ACCEPTED,
        )
        assert assignment.state == TicketAssignment.State.ACCEPTED
        assert assignment.accepted_by_id == worker.id
        assert assignment.accepted_at is not None
        assert allocation.state == VendorStaffAllocation.State.ACCEPTED
        assert allocation.accepted_by_id == worker.id
        assert allocation.accepted_at is not None
        assert sla_cycle.acceptance_deadline is None
        assert event.ticket_version == ticket.state_version


def test_vendor_dispatcher_accepts_allocated_worker_with_audit_reason(client):
    society = Society.objects.create(registration_code="NIV-VEND-DACCEPT")
    unit = create_unit(society=society, code="A", door_number="304")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543583",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876543584",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    dispatcher = User.objects.create_user(phone="+919876543585")
    worker = User.objects.create_user(phone="+919876543586")
    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name="Apex Elevators",
            normalized_company_name="apex elevators",
            contact_person="Karan Joshi",
            phone_number="+919876543587",
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
            user=dispatcher,
            role=VendorStaffMembership.Role.DISPATCHER,
        )
        worker_membership = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=worker,
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
        key="vendor-dispatcher-accept-submit",
    )
    assigned = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-vendor/",
        {
            "expected_version": submitted["state_version"],
            "vendor_contract_id": str(contract.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "vendor-dispatcher-accept-assign"),
    )
    assert assigned.status_code == 200, assigned.json()
    allocated = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/allocate-vendor-worker/",
        {
            "expected_version": assigned.json()["state_version"],
            "staff_membership_id": str(worker_membership.id),
        },
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-dispatcher-accept-allocate"),
    )
    assert allocated.status_code == 200, allocated.json()

    endpoint = (
        f"/api/v1/service-tickets/{submitted['id']}/accept-vendor-worker-on-behalf/"
    )
    expected_version = allocated.json()["state_version"]
    invalid = client.post(
        endpoint,
        {"expected_version": expected_version, "reason": "   "},
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-dispatcher-accept-invalid"),
    )
    assert invalid.status_code == 400, invalid.content
    assert (
        client.post(
            endpoint,
            {
                "expected_version": expected_version,
                "reason": "Worker confirmed availability by phone.",
            },
            content_type="application/json",
            **request_headers(worker, society, "vendor-worker-on-behalf-forbidden"),
        ).status_code
        == 403
    )
    payload = {
        "expected_version": expected_version,
        "reason": "Worker confirmed availability by phone.",
    }
    response = client.post(
        endpoint,
        payload,
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-dispatcher-accept"),
    )
    replay = client.post(
        endpoint,
        payload,
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-dispatcher-accept"),
    )

    assert response.status_code == 200, response.content
    assert replay.status_code == 200, replay.content
    assert replay.json() == response.json()
    assert response.json()["status"] == Ticket.Status.ACCEPTED
    assert response.json()["state_version"] == expected_version + 1
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=submitted["id"])
        assignment = TicketAssignment.objects.get(ticket=ticket)
        allocation = VendorStaffAllocation.objects.get(assignment=assignment)
        sla_cycle = SLACycle.objects.get(ticket=ticket, ended_at__isnull=True)
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_ASSIGNMENT_ACCEPTED,
        )
        assert assignment.state == TicketAssignment.State.ACCEPTED
        assert assignment.accepted_by_id == dispatcher.id
        assert allocation.state == VendorStaffAllocation.State.ACCEPTED
        assert allocation.accepted_by_id == dispatcher.id
        assert sla_cycle.acceptance_deadline is None
        assert event.actor_id == dispatcher.id
        assert event.reason == payload["reason"]
        assert event.metadata["staff_membership_id"] == str(worker_membership.id)
        assert event.metadata["accepted_on_behalf"] is True


def test_in_house_assignment_rejects_full_technician_without_mutation(client):
    society = Society.objects.create(registration_code="NIV-API-IHC")
    unit = create_unit(society=society, code="A", door_number="102")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543560",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876543561",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    technician_user = User.objects.create_user(phone="+919876543562")
    with transaction.atomic():
        set_local_society_id(society.id)
        technician = TechnicianProfile.objects.create(
            society=society,
            user=technician_user,
            max_active_tickets=1,
            current_active_tickets_count=1,
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
        key="in-house-capacity",
    )

    response = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-in-house/",
        {
            "expected_version": submitted["state_version"],
            "technician_id": str(technician.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "in-house-capacity"),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "TECHNICIAN_CAPACITY_UNAVAILABLE"
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=submitted["id"])
        technician.refresh_from_db()
        assert ticket.status == Ticket.Status.SUBMITTED
        assert ticket.state_version == submitted["state_version"]
        assert TicketAssignment.objects.filter(ticket=ticket).count() == 0
        assert technician.current_active_tickets_count == 1


def test_in_house_assignment_rejects_stale_version_without_mutation(client):
    society = Society.objects.create(registration_code="NIV-API-IHV")
    unit = create_unit(society=society, code="A", door_number="103")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543563",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876543564",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    technician_user = User.objects.create_user(phone="+919876543565")
    with transaction.atomic():
        set_local_society_id(society.id)
        technician = TechnicianProfile.objects.create(
            society=society,
            user=technician_user,
            max_active_tickets=1,
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
        key="in-house-version",
    )

    response = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-in-house/",
        {
            "expected_version": submitted["state_version"] - 1,
            "technician_id": str(technician.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "in-house-version"),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "TICKET_VERSION_CONFLICT"
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=submitted["id"])
        technician.refresh_from_db()
        assert ticket.status == Ticket.Status.SUBMITTED
        assert ticket.state_version == submitted["state_version"]
        assert TicketAssignment.objects.filter(ticket=ticket).count() == 0
        assert technician.current_active_tickets_count == 0


def test_technician_accepts_offered_in_house_assignment_idempotently(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-API-ACCEPT",
            phone_offset=3570,
        )
    )
    endpoint = f"/api/v1/service-tickets/{offered['id']}/accept/"
    payload = {"expected_version": offered["state_version"]}
    denied = client.post(
        endpoint,
        payload,
        content_type="application/json",
        **request_headers(facility_manager, society, "manager-accept"),
    )
    headers = request_headers(technician_user, society, "technician-accept")
    first = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert denied.status_code == 404
    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.ACCEPTED
    assert first.json()["assignment"]["state"] == TicketAssignment.State.ACCEPTED
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        assignment = TicketAssignment.objects.get(ticket=ticket)
        sla_cycle = SLACycle.objects.get(ticket=ticket, ended_at__isnull=True)
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_ASSIGNMENT_ACCEPTED,
        )
        technician.refresh_from_db()
        assert ticket.state_version == offered["state_version"] + 1
        assert assignment.accepted_by_id == technician_user.id
        assert assignment.accepted_at is not None
        assert technician.current_active_tickets_count == 1
        assert sla_cycle.acceptance_deadline is None
        assert event.ticket_version == ticket.state_version


def test_technician_rejection_releases_capacity_and_counts_failure(client):
    society, _, technician_user, technician, offered = create_offered_in_house_assignment(
        client=client,
        registration_code="NIV-API-REJECT",
        phone_offset=3580,
    )
    endpoint = f"/api/v1/service-tickets/{offered['id']}/reject/"
    payload = {
        "expected_version": offered["state_version"],
        "reason": "I am unavailable for this repair window.",
    }
    headers = request_headers(technician_user, society, "technician-reject")
    first = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.SUBMITTED
    assert first.json()["assignment_failure_count"] == 1
    assert first.json()["assignee_rejection_count"] == 1
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        assignment = TicketAssignment.objects.get(ticket=ticket)
        sla_cycle = SLACycle.objects.get(ticket=ticket, ended_at__isnull=True)
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_ASSIGNMENT_REJECTED,
        )
        technician.refresh_from_db()
        assert assignment.state == TicketAssignment.State.ENDED
        assert assignment.ended_reason == payload["reason"]
        assert technician.current_active_tickets_count == 0
        assert sla_cycle.acceptance_deadline is None
        assert sla_cycle.assignment_failure_count == 1
        assert sla_cycle.assignee_rejection_count == 1
        assert event.reason == payload["reason"]


def test_technician_rejection_reaches_supervisor_triage_at_failure_threshold(client):
    society, _, technician_user, technician, offered = create_offered_in_house_assignment(
        client=client,
        registration_code="NIV-API-TRIAGE",
        phone_offset=3590,
    )
    with transaction.atomic():
        set_local_society_id(society.id)
        sla_cycle = SLACycle.objects.get(ticket_id=offered["id"], ended_at__isnull=True)
        sla_cycle.assignment_failure_count = 2
        sla_cycle.assignee_rejection_count = 2
        sla_cycle.save(
            update_fields=("assignment_failure_count", "assignee_rejection_count")
        )

    response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/reject/",
        {
            "expected_version": offered["state_version"],
            "reason": "This requires a supervisor reassignment.",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "technician-triage"),
    )

    assert response.status_code == 200, response.json()
    assert response.json()["status"] == Ticket.Status.SUPERVISOR_TRIAGE
    assert response.json()["assignment_failure_count"] == 3
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        technician.refresh_from_db()
        assert ticket.status == Ticket.Status.SUPERVISOR_TRIAGE
        assert technician.current_active_tickets_count == 0


def test_stale_technician_rejection_does_not_mutate_assignment(client):
    society, _, technician_user, technician, offered = create_offered_in_house_assignment(
        client=client,
        registration_code="NIV-API-STALE",
        phone_offset=3600,
    )
    response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/reject/",
        {
            "expected_version": offered["state_version"] - 1,
            "reason": "The stale command must not change capacity.",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "technician-stale"),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "TICKET_VERSION_CONFLICT"
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        assignment = TicketAssignment.objects.get(ticket=ticket)
        sla_cycle = SLACycle.objects.get(ticket=ticket, ended_at__isnull=True)
        technician.refresh_from_db()
        assert ticket.status == Ticket.Status.ASSIGNED
        assert ticket.state_version == offered["state_version"]
        assert assignment.state == TicketAssignment.State.OFFERED
        assert technician.current_active_tickets_count == 1
        assert sla_cycle.assignment_failure_count == 0
        assert sla_cycle.assignee_rejection_count == 0


def test_expired_technician_acceptance_does_not_mutate_assignment(client):
    society, _, technician_user, technician, offered = create_offered_in_house_assignment(
        client=client,
        registration_code="NIV-API-EXPIRED",
        phone_offset=3610,
    )
    with transaction.atomic():
        set_local_society_id(society.id)
        assignment = TicketAssignment.objects.get(ticket_id=offered["id"])
        assignment.acceptance_deadline = timezone.now() - timedelta(seconds=1)
        assignment.save(update_fields=("acceptance_deadline",))

    response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "technician-expired"),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "ASSIGNMENT_ACCEPTANCE_EXPIRED"
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        assignment = TicketAssignment.objects.get(ticket=ticket)
        sla_cycle = SLACycle.objects.get(ticket=ticket, ended_at__isnull=True)
        technician.refresh_from_db()
        assert ticket.status == Ticket.Status.ASSIGNED
        assert ticket.state_version == offered["state_version"]
        assert assignment.state == TicketAssignment.State.OFFERED
        assert technician.current_active_tickets_count == 1
        assert sla_cycle.acceptance_deadline is not None


def test_assigned_reviewer_opens_governance_discussion_idempotently(client):
    society = Society.objects.create(registration_code="NIV-API-DISCUSSION")
    reporter = create_committee_member(
        society=society,
        phone="+919876543554",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876543555",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    other_facility_manager = create_staff(
        society=society,
        phone="+919876543556",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.GOVERNANCE,
    )
    create_sla_binding(
        society=society,
        category=category,
        priority=subcategory.default_priority,
    )
    create_business_calendar(society=society)
    draft = client.post(
        "/api/v1/governance-tickets/",
        ticket_payload(category=category, subcategory=subcategory),
        content_type="application/json",
        **request_headers(reporter, society, "governance-discussion-draft"),
    ).json()
    submitted = client.post(
        f"/api/v1/governance-tickets/{draft['id']}/submit/",
        {"expected_version": 1},
        content_type="application/json",
        **request_headers(reporter, society, "governance-discussion-submit"),
    )
    assert submitted.status_code == 200, submitted.json()
    review = client.post(
        f"/api/v1/governance-tickets/{draft['id']}/begin-review/",
        {"expected_version": 2},
        content_type="application/json",
        **request_headers(facility_manager, society, "governance-discussion-review"),
    )
    assert review.status_code == 200, review.json()

    endpoint = f"/api/v1/governance-tickets/{draft['id']}/open-discussion/"
    denied = client.post(
        endpoint,
        {"expected_version": 3, "purpose": "Review impact and next steps."},
        content_type="application/json",
        **request_headers(other_facility_manager, society, "other-discussion"),
    )
    reporter_denied = client.post(
        endpoint,
        {"expected_version": 3, "purpose": "Review impact and next steps."},
        content_type="application/json",
        **request_headers(reporter, society, "reporter-discussion"),
    )
    invalid_purpose = client.post(
        endpoint,
        {"expected_version": 3, "purpose": "   "},
        content_type="application/json",
        **request_headers(facility_manager, society, "invalid-discussion-purpose"),
    )
    headers = request_headers(facility_manager, society, "open-governance-discussion")
    first = client.post(
        endpoint,
        {"expected_version": 3, "purpose": "Review impact and next steps."},
        content_type="application/json",
        **headers,
    )
    replay = client.post(
        endpoint,
        {"expected_version": 3, "purpose": "Review impact and next steps."},
        content_type="application/json",
        **headers,
    )

    assert denied.status_code == 403
    assert reporter_denied.status_code == 403
    assert invalid_purpose.status_code == 400
    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.IN_DISCUSSION
    assert first.json()["state_version"] == 4
    assert first.json()["discussion"]["purpose"] == "Review impact and next steps."
    assert set(first.json()["discussion"]["participant_ids"]) == {
        str(reporter.id),
        str(facility_manager.id),
    }
    with transaction.atomic():
        set_local_society_id(society.id)
        discussed_ticket = Ticket.objects.get(id=draft["id"])
        discussion = GovernanceDiscussion.objects.get(ticket=discussed_ticket)
        event = TicketEvent.objects.get(
            ticket=discussed_ticket,
            event_type=TicketEvent.EventType.GOVERNANCE_DISCUSSION_OPENED,
        )
        assert discussion.opened_by_id == facility_manager.id
        assert set(
            GovernanceDiscussionParticipant.objects.filter(discussion=discussion).values_list(
                "user_id", flat=True
            )
        ) == {reporter.id, facility_manager.id}
        assert event.ticket_version == discussed_ticket.state_version


def test_governance_action_records_allow_reviewer_or_facility_manager(client):
    society = Society.objects.create(registration_code="NIV-API-ACTION")
    reporter = create_committee_member(
        society=society,
        phone="+919876543557",
    )
    assigned_facility_manager = create_staff(
        society=society,
        phone="+919876543558",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    other_facility_manager = create_staff(
        society=society,
        phone="+919876543559",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    helpdesk = create_staff(
        society=society,
        phone="+919876543560",
        role=StaffMembership.Role.HELPDESK_OPERATOR,
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.GOVERNANCE,
    )
    create_sla_binding(
        society=society,
        category=category,
        priority=subcategory.default_priority,
    )
    create_business_calendar(society=society)

    direct_draft = client.post(
        "/api/v1/governance-tickets/",
        ticket_payload(category=category, subcategory=subcategory),
        content_type="application/json",
        **request_headers(reporter, society, "governance-action-direct-draft"),
    ).json()
    direct_submitted = client.post(
        f"/api/v1/governance-tickets/{direct_draft['id']}/submit/",
        {"expected_version": 1},
        content_type="application/json",
        **request_headers(reporter, society, "governance-action-direct-submit"),
    )
    assert direct_submitted.status_code == 200, direct_submitted.json()
    direct_review = client.post(
        f"/api/v1/governance-tickets/{direct_draft['id']}/begin-review/",
        {"expected_version": 2},
        content_type="application/json",
        **request_headers(
            assigned_facility_manager,
            society,
            "governance-action-direct-review",
        ),
    )
    assert direct_review.status_code == 200, direct_review.json()

    direct_endpoint = f"/api/v1/governance-tickets/{direct_draft['id']}/record-action/"
    reporter_denied = client.post(
        direct_endpoint,
        {"expected_version": 3, "summary": "Committee should not record this."},
        content_type="application/json",
        **request_headers(reporter, society, "governance-action-reporter-denied"),
    )
    helpdesk_denied = client.post(
        direct_endpoint,
        {"expected_version": 3, "summary": "Helpdesk should not record this."},
        content_type="application/json",
        **request_headers(helpdesk, society, "governance-action-helpdesk-denied"),
    )
    invalid_summary = client.post(
        direct_endpoint,
        {"expected_version": 3, "summary": "   "},
        content_type="application/json",
        **request_headers(
            assigned_facility_manager,
            society,
            "governance-action-invalid-summary",
        ),
    )
    stale = client.post(
        direct_endpoint,
        {"expected_version": 2, "summary": "This is stale."},
        content_type="application/json",
        **request_headers(
            assigned_facility_manager,
            society,
            "governance-action-stale",
        ),
    )
    direct_payload = {
        "expected_version": 3,
        "summary": "Approved repairs and instructed the facilities team to proceed.",
    }
    direct_headers = request_headers(
        assigned_facility_manager,
        society,
        "governance-action-direct",
    )
    direct_action = client.post(
        direct_endpoint,
        direct_payload,
        content_type="application/json",
        **direct_headers,
    )
    direct_replay = client.post(
        direct_endpoint,
        direct_payload,
        content_type="application/json",
        **direct_headers,
    )
    action_cancelled = client.post(
        f"/api/v1/governance-tickets/{direct_draft['id']}/cancel/",
        {"expected_version": 4, "reason": "This action is already irreversible."},
        content_type="application/json",
        **request_headers(
            other_facility_manager,
            society,
            "governance-action-cancel-denied",
        ),
    )

    assert reporter_denied.status_code == 403
    assert helpdesk_denied.status_code == 403
    assert invalid_summary.status_code == 400
    assert stale.status_code == 409
    assert stale.json()["code"] == "TICKET_VERSION_CONFLICT"
    assert direct_action.status_code == 200, direct_action.json()
    assert direct_replay.status_code == 200
    assert direct_replay.json() == direct_action.json()
    assert action_cancelled.status_code == 409
    assert action_cancelled.json()["code"] == "TICKET_STATE_CONFLICT"
    assert direct_action.json()["status"] == Ticket.Status.ACTION_TAKEN
    assert direct_action.json()["state_version"] == 4
    assert direct_action.json()["action_record"]["summary"] == direct_payload["summary"]
    assert direct_action.json()["action_record"]["evidence_policy"] == (
        GovernanceActionRecord.EvidencePolicy.NO_EXTERNAL_EVIDENCE
    )

    discussion_draft = client.post(
        "/api/v1/governance-tickets/",
        ticket_payload(category=category, subcategory=subcategory),
        content_type="application/json",
        **request_headers(reporter, society, "governance-action-discussion-draft"),
    ).json()
    discussion_submitted = client.post(
        f"/api/v1/governance-tickets/{discussion_draft['id']}/submit/",
        {"expected_version": 1},
        content_type="application/json",
        **request_headers(reporter, society, "governance-action-discussion-submit"),
    )
    assert discussion_submitted.status_code == 200, discussion_submitted.json()
    discussion_review = client.post(
        f"/api/v1/governance-tickets/{discussion_draft['id']}/begin-review/",
        {"expected_version": 2},
        content_type="application/json",
        **request_headers(
            assigned_facility_manager,
            society,
            "governance-action-discussion-review",
        ),
    )
    assert discussion_review.status_code == 200, discussion_review.json()
    discussion_opened = client.post(
        f"/api/v1/governance-tickets/{discussion_draft['id']}/open-discussion/",
        {"expected_version": 3, "purpose": "Confirm scope and execution plan."},
        content_type="application/json",
        **request_headers(
            assigned_facility_manager,
            society,
            "governance-action-open-discussion",
        ),
    )
    assert discussion_opened.status_code == 200, discussion_opened.json()

    discussion_action = client.post(
        f"/api/v1/governance-tickets/{discussion_draft['id']}/record-action/",
        {
            "expected_version": 4,
            "summary": "A second facility manager recorded the approved action.",
        },
        content_type="application/json",
        **request_headers(
            other_facility_manager,
            society,
            "governance-action-from-discussion",
        ),
    )

    assert discussion_action.status_code == 200, discussion_action.json()
    assert discussion_action.json()["status"] == Ticket.Status.ACTION_TAKEN
    assert discussion_action.json()["state_version"] == 5
    assert discussion_action.json()["action_record"]["recorded_by_id"] == str(
        other_facility_manager.id
    )
    with transaction.atomic():
        set_local_society_id(society.id)
        direct_ticket = Ticket.objects.get(id=direct_draft["id"])
        discussion_ticket = Ticket.objects.get(id=discussion_draft["id"])
        direct_record = GovernanceActionRecord.objects.get(ticket=direct_ticket)
        discussion_record = GovernanceActionRecord.objects.get(ticket=discussion_ticket)
        direct_event = TicketEvent.objects.get(
            ticket=direct_ticket,
            event_type=TicketEvent.EventType.GOVERNANCE_ACTION_RECORDED,
        )
        discussion_event = TicketEvent.objects.get(
            ticket=discussion_ticket,
            event_type=TicketEvent.EventType.GOVERNANCE_ACTION_RECORDED,
        )
        assert direct_ticket.status == Ticket.Status.ACTION_TAKEN
        assert discussion_ticket.status == Ticket.Status.ACTION_TAKEN
        assert direct_record.recorded_by_id == assigned_facility_manager.id
        assert direct_record.summary == direct_payload["summary"]
        assert discussion_record.recorded_by_id == other_facility_manager.id
        assert direct_event.ticket_version == direct_ticket.state_version
        assert direct_event.reason == direct_record.summary
        assert direct_event.metadata["action_record_id"] == str(direct_record.id)
        assert discussion_event.ticket_version == discussion_ticket.state_version
        assert discussion_event.reason == discussion_record.summary


def test_facility_manager_cancels_governance_review_or_discussion(client):
    society = Society.objects.create(registration_code="NIV-GOV-CAN")
    reporter = create_committee_member(
        society=society,
        phone="+919876543571",
    )
    assigned_facility_manager = create_staff(
        society=society,
        phone="+919876543572",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    other_facility_manager = create_staff(
        society=society,
        phone="+919876543573",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    helpdesk = create_staff(
        society=society,
        phone="+919876543574",
        role=StaffMembership.Role.HELPDESK_OPERATOR,
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.GOVERNANCE,
    )
    create_sla_binding(
        society=society,
        category=category,
        priority=subcategory.default_priority,
    )
    create_business_calendar(society=society)

    def create_reviewed_ticket(*, key):
        draft = client.post(
            "/api/v1/governance-tickets/",
            ticket_payload(category=category, subcategory=subcategory),
            content_type="application/json",
            **request_headers(reporter, society, f"{key}-draft"),
        ).json()
        submitted = client.post(
            f"/api/v1/governance-tickets/{draft['id']}/submit/",
            {"expected_version": 1},
            content_type="application/json",
            **request_headers(reporter, society, f"{key}-submit"),
        )
        assert submitted.status_code == 200, submitted.json()
        reviewed = client.post(
            f"/api/v1/governance-tickets/{draft['id']}/begin-review/",
            {"expected_version": 2},
            content_type="application/json",
            **request_headers(assigned_facility_manager, society, f"{key}-review"),
        )
        assert reviewed.status_code == 200, reviewed.json()
        return draft

    reviewed_draft = create_reviewed_ticket(key="governance-cancel-review")
    reviewed_endpoint = f"/api/v1/governance-tickets/{reviewed_draft['id']}/cancel/"
    reporter_denied = client.post(
        reviewed_endpoint,
        {"expected_version": 3, "reason": "Reporter cannot cancel active review."},
        content_type="application/json",
        **request_headers(reporter, society, "governance-cancel-reporter-denied"),
    )
    helpdesk_denied = client.post(
        reviewed_endpoint,
        {"expected_version": 3, "reason": "Helpdesk cannot cancel active review."},
        content_type="application/json",
        **request_headers(helpdesk, society, "governance-cancel-helpdesk-denied"),
    )
    stale = client.post(
        reviewed_endpoint,
        {"expected_version": 2, "reason": "This version is stale."},
        content_type="application/json",
        **request_headers(other_facility_manager, society, "governance-cancel-stale"),
    )
    reviewed_payload = {
        "expected_version": 3,
        "reason": "The matter was withdrawn before an irreversible action.",
    }
    reviewed_headers = request_headers(
        other_facility_manager,
        society,
        "governance-cancel-review",
    )
    reviewed_cancelled = client.post(
        reviewed_endpoint,
        reviewed_payload,
        content_type="application/json",
        **reviewed_headers,
    )
    reviewed_replay = client.post(
        reviewed_endpoint,
        reviewed_payload,
        content_type="application/json",
        **reviewed_headers,
    )

    assert reporter_denied.status_code == 403
    assert helpdesk_denied.status_code == 403
    assert stale.status_code == 409
    assert stale.json()["code"] == "TICKET_VERSION_CONFLICT"
    assert reviewed_cancelled.status_code == 200, reviewed_cancelled.json()
    assert reviewed_replay.status_code == 200
    assert reviewed_replay.json() == reviewed_cancelled.json()
    assert reviewed_cancelled.json()["status"] == Ticket.Status.CANCELLED
    assert reviewed_cancelled.json()["state_version"] == 4

    discussed_draft = create_reviewed_ticket(key="governance-cancel-discussion")
    discussion = client.post(
        f"/api/v1/governance-tickets/{discussed_draft['id']}/open-discussion/",
        {"expected_version": 3, "purpose": "Discuss the proposed resolution."},
        content_type="application/json",
        **request_headers(
            assigned_facility_manager,
            society,
            "governance-cancel-open-discussion",
        ),
    )
    assert discussion.status_code == 200, discussion.json()
    discussion_cancelled = client.post(
        f"/api/v1/governance-tickets/{discussed_draft['id']}/cancel/",
        {"expected_version": 4, "reason": "The discussion no longer requires action."},
        content_type="application/json",
        **request_headers(
            assigned_facility_manager,
            society,
            "governance-cancel-discussion",
        ),
    )

    assert discussion_cancelled.status_code == 200, discussion_cancelled.json()
    assert discussion_cancelled.json()["status"] == Ticket.Status.CANCELLED
    assert discussion_cancelled.json()["state_version"] == 5
    with transaction.atomic():
        set_local_society_id(society.id)
        reviewed_ticket = Ticket.objects.get(id=reviewed_draft["id"])
        discussed_ticket = Ticket.objects.get(id=discussed_draft["id"])
        for ticket in (reviewed_ticket, discussed_ticket):
            event = TicketEvent.objects.get(
                ticket=ticket,
                event_type=TicketEvent.EventType.TICKET_CANCELLED,
            )
            cycle = SLACycle.objects.get(ticket=ticket)
            assert ticket.status == Ticket.Status.CANCELLED
            assert event.ticket_version == ticket.state_version
            assert cycle.ended_at is not None
            assert cycle.outcome == SLACycle.Outcome.CANCELLED


def test_create_requires_idempotency_key_and_rejects_reuse_for_new_payload(client):
    society = Society.objects.create(registration_code="NIV-API-IDEMP")
    unit = create_unit(society=society, code="A", door_number="102")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543531",
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    payload = ticket_payload(category=category, subcategory=subcategory, unit=unit)

    missing = client.post(
        "/api/v1/service-tickets/",
        payload,
        content_type="application/json",
        **request_headers(resident, society),
    )
    created = client.post(
        "/api/v1/service-tickets/",
        payload,
        content_type="application/json",
        **request_headers(resident, society, "reused-create-key"),
    )
    payload["title"] = "Different request"
    reused = client.post(
        "/api/v1/service-tickets/",
        payload,
        content_type="application/json",
        **request_headers(resident, society, "reused-create-key"),
    )

    assert missing.status_code == 400
    assert "Idempotency-Key" in missing.json()
    assert created.status_code == 201
    assert reused.status_code == 409
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_resident_cannot_create_service_ticket_for_another_unit(client):
    society = Society.objects.create(registration_code="NIV-API-UNIT")
    own_unit = create_unit(society=society, code="A", door_number="103")
    other_unit = create_unit(society=society, code="B", door_number="201")
    resident = create_resident(
        society=society,
        unit=own_unit,
        phone="+919876543532",
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )

    response = client.post(
        "/api/v1/service-tickets/",
        ticket_payload(category=category, subcategory=subcategory, unit=other_unit),
        content_type="application/json",
        **request_headers(resident, society, "other-unit"),
    )

    assert response.status_code == 400
    assert "unit" in response.json()


def test_resident_reads_own_unit_only_and_cross_workflow_detail_is_hidden(client):
    society = Society.objects.create(registration_code="NIV-API-SCOPE")
    own_unit = create_unit(society=society, code="A", door_number="104")
    other_unit = create_unit(society=society, code="B", door_number="202")
    resident = create_resident(
        society=society,
        unit=own_unit,
        phone="+919876543533",
    )
    staff = create_staff(
        society=society,
        phone="+919876543534",
        role=StaffMembership.Role.HELPDESK_OPERATOR,
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    own = client.post(
        "/api/v1/service-tickets/",
        ticket_payload(category=category, subcategory=subcategory, unit=own_unit),
        content_type="application/json",
        **request_headers(staff, society, "own-unit-ticket"),
    ).json()
    client.post(
        "/api/v1/service-tickets/",
        ticket_payload(category=category, subcategory=subcategory, unit=other_unit),
        content_type="application/json",
        **request_headers(staff, society, "other-unit-ticket"),
    )

    listed = client.get(
        "/api/v1/service-tickets/",
        **request_headers(resident, society),
    )
    detail = client.get(
        f"/api/v1/service-tickets/{own['id']}/",
        **request_headers(resident, society),
    )
    wrong_workflow = client.get(
        f"/api/v1/governance-tickets/{own['id']}/",
        **request_headers(resident, society),
    )

    assert listed.status_code == 200
    assert [ticket["id"] for ticket in listed.json()] == [own["id"]]
    assert detail.status_code == 200
    assert wrong_workflow.status_code == 404


def test_staff_reads_society_wide_but_estate_supervisor_cannot_create(client):
    society = Society.objects.create(registration_code="NIV-API-STAFF")
    unit = create_unit(society=society, code="A", door_number="105")
    helpdesk = create_staff(
        society=society,
        phone="+919876543535",
        role=StaffMembership.Role.HELPDESK_OPERATOR,
    )
    supervisor = create_staff(
        society=society,
        phone="+919876543536",
        role=StaffMembership.Role.ESTATE_SUPERVISOR,
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    payload = ticket_payload(category=category, subcategory=subcategory, unit=unit)
    client.post(
        "/api/v1/service-tickets/",
        payload,
        content_type="application/json",
        **request_headers(helpdesk, society, "staff-create"),
    )

    listed = client.get(
        "/api/v1/service-tickets/",
        **request_headers(supervisor, society),
    )
    denied = client.post(
        "/api/v1/service-tickets/",
        payload,
        content_type="application/json",
        **request_headers(supervisor, society, "supervisor-create"),
    )

    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert denied.status_code == 403


def test_committee_member_can_create_governance_but_not_service(client):
    society = Society.objects.create(registration_code="NIV-API-COMMITTEE")
    unit = create_unit(society=society, code="A", door_number="106")
    committee = create_committee_member(
        society=society,
        phone="+919876543537",
    )
    service_category, service_subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    governance_category, governance_subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.GOVERNANCE,
    )

    governance = client.post(
        "/api/v1/governance-tickets/",
        ticket_payload(
            category=governance_category,
            subcategory=governance_subcategory,
        ),
        content_type="application/json",
        **request_headers(committee, society, "committee-governance"),
    )
    service = client.post(
        "/api/v1/service-tickets/",
        ticket_payload(
            category=service_category,
            subcategory=service_subcategory,
            unit=unit,
        ),
        content_type="application/json",
        **request_headers(committee, society, "committee-service"),
    )

    assert governance.status_code == 201
    assert governance.json()["workflow_type"] == Ticket.WorkflowType.GOVERNANCE
    assert service.status_code == 403


def test_submit_requires_expected_version_and_idempotency_key(client):
    society = Society.objects.create(registration_code="NIV-API-SUBMIT-REQ")
    unit = create_unit(society=society, code="A", door_number="107")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543538",
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    draft = client.post(
        "/api/v1/service-tickets/",
        ticket_payload(category=category, subcategory=subcategory, unit=unit),
        content_type="application/json",
        **request_headers(resident, society, "submit-requirements-draft"),
    ).json()

    missing_version = client.post(
        f"/api/v1/service-tickets/{draft['id']}/submit/",
        {},
        content_type="application/json",
        **request_headers(resident, society, "submit-missing-version"),
    )
    missing_key = client.post(
        f"/api/v1/service-tickets/{draft['id']}/submit/",
        {"expected_version": 1},
        content_type="application/json",
        **request_headers(resident, society),
    )

    assert missing_version.status_code == 400
    assert "expected_version" in missing_version.json()
    assert missing_key.status_code == 400
    assert "Idempotency-Key" in missing_key.json()


def test_submit_fails_closed_without_business_calendar_calculator(client):
    society = Society.objects.create(registration_code="NIV-API-CALENDAR")
    unit = create_unit(society=society, code="A", door_number="108")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543539",
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    create_sla_binding(
        society=society,
        category=category,
        priority=subcategory.default_priority,
    )
    draft = client.post(
        "/api/v1/service-tickets/",
        ticket_payload(category=category, subcategory=subcategory, unit=unit),
        content_type="application/json",
        **request_headers(resident, society, "calendar-draft"),
    ).json()

    response = client.post(
        f"/api/v1/service-tickets/{draft['id']}/submit/",
        {"expected_version": 1},
        content_type="application/json",
        **request_headers(resident, society, "calendar-submit"),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "SLA_CALENDAR_UNAVAILABLE"
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=draft["id"])
        assert ticket.status == Ticket.Status.DRAFT
        assert SLACycle.objects.count() == 0


def test_submit_endpoint_persists_cycle_and_replays(client):
    society = Society.objects.create(registration_code="NIV-API-SUBMIT")
    unit = create_unit(society=society, code="A", door_number="109")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543540",
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    create_sla_binding(
        society=society,
        category=category,
        priority=subcategory.default_priority,
    )
    create_business_calendar(society=society)
    draft = client.post(
        "/api/v1/service-tickets/",
        ticket_payload(category=category, subcategory=subcategory, unit=unit),
        content_type="application/json",
        **request_headers(resident, society, "successful-draft"),
    ).json()
    headers = request_headers(resident, society, "successful-submit")

    first = client.post(
        f"/api/v1/service-tickets/{draft['id']}/submit/",
        {"expected_version": 1},
        content_type="application/json",
        **headers,
    )
    replay = client.post(
        f"/api/v1/service-tickets/{draft['id']}/submit/",
        {"expected_version": 1},
        content_type="application/json",
        **headers,
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.SUBMITTED
    assert first.json()["state_version"] == 2
    with transaction.atomic():
        set_local_society_id(society.id)
        assert SLACycle.objects.filter(ticket_id=draft["id"]).count() == 1


def test_resident_comment_create_replays_and_lists_public_thread(client):
    society = Society.objects.create(registration_code="NIV-API-COMMENT")
    unit = create_unit(society=society, code="A", door_number="111")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543542",
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    ticket = submit_service_ticket(
        client=client,
        society=society,
        actor=resident,
        category=category,
        subcategory=subcategory,
        unit=unit,
        key="resident-comment-ticket",
    )
    payload = {
        "body": "The leak is getting worse near the cabinet.",
        "expected_version": ticket["state_version"],
    }
    headers = request_headers(resident, society, "resident-comment-1")

    first = client.post(
        f"/api/v1/tickets/service/{ticket['id']}/comments/",
        payload,
        content_type="application/json",
        **headers,
    )
    replay = client.post(
        f"/api/v1/tickets/service/{ticket['id']}/comments/",
        payload,
        content_type="application/json",
        **headers,
    )
    listed = client.get(
        f"/api/v1/tickets/service/{ticket['id']}/comments/",
        **request_headers(resident, society),
    )

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert listed.status_code == 200
    assert listed.json() == [first.json()]
    assert first.json()["body"] == payload["body"]
    assert first.json()["author_persona"] == "resident"
    assert first.json()["is_authored_by_requester"] is True
    with transaction.atomic():
        set_local_society_id(society.id)
        assert TicketComment.objects.filter(ticket_id=ticket["id"]).count() == 1


def test_staff_internal_comment_is_idempotent_and_hidden_from_residents(client):
    society = Society.objects.create(registration_code="NIV-API-INT-COMMENT")
    unit = create_unit(society=society, code="A", door_number="117")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543550",
    )
    helpdesk = create_staff(
        society=society,
        phone="+919876543551",
        role=StaffMembership.Role.HELPDESK_OPERATOR,
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    ticket = submit_service_ticket(
        client=client,
        society=society,
        actor=helpdesk,
        category=category,
        subcategory=subcategory,
        unit=unit,
        key="internal-comment-ticket",
    )
    payload = {
        "body": "Check the maintenance history before dispatching.",
        "expected_version": ticket["state_version"],
    }
    endpoint = f"/api/v1/tickets/service/{ticket['id']}/internal-comments/"
    headers = request_headers(helpdesk, society, "internal-comment-1")

    first = client.post(
        endpoint,
        payload,
        content_type="application/json",
        **headers,
    )
    replay = client.post(
        endpoint,
        payload,
        content_type="application/json",
        **headers,
    )
    staff_listed = client.get(endpoint, **request_headers(helpdesk, society))
    public_thread = client.get(
        f"/api/v1/tickets/service/{ticket['id']}/comments/",
        **request_headers(resident, society),
    )
    resident_internal = client.get(endpoint, **request_headers(resident, society))

    assert first.status_code == 201, first.json()
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert first.json()["visibility"] == TicketComment.Visibility.INTERNAL
    assert first.json()["author_persona"] == "staff"
    assert staff_listed.status_code == 200
    assert staff_listed.json() == [first.json()]
    assert public_thread.status_code == 200
    assert public_thread.json() == []
    assert resident_internal.status_code == 403
    with transaction.atomic():
        set_local_society_id(society.id)
        assert TicketComment.objects.filter(
            ticket_id=ticket["id"],
            visibility=TicketComment.Visibility.INTERNAL,
        ).count() == 1


def test_governance_discussion_accepts_public_and_internal_comments(client):
    society = Society.objects.create(registration_code="NIV-API-GOV-COMMENT")
    reporter = create_committee_member(
        society=society,
        phone="+919876543581",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876543582",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.GOVERNANCE,
    )
    create_sla_binding(
        society=society,
        category=category,
        priority=subcategory.default_priority,
    )
    create_business_calendar(society=society)
    draft = client.post(
        "/api/v1/governance-tickets/",
        ticket_payload(category=category, subcategory=subcategory),
        content_type="application/json",
        **request_headers(reporter, society, "gov-comment-draft"),
    ).json()
    submitted = client.post(
        f"/api/v1/governance-tickets/{draft['id']}/submit/",
        {"expected_version": 1},
        content_type="application/json",
        **request_headers(reporter, society, "gov-comment-submit"),
    )
    reviewed = client.post(
        f"/api/v1/governance-tickets/{draft['id']}/begin-review/",
        {"expected_version": 2},
        content_type="application/json",
        **request_headers(facility_manager, society, "gov-comment-review"),
    )
    discussion = client.post(
        f"/api/v1/governance-tickets/{draft['id']}/open-discussion/",
        {"expected_version": 3, "purpose": "Review impact and next steps."},
        content_type="application/json",
        **request_headers(facility_manager, society, "gov-comment-discussion"),
    )
    public_endpoint = f"/api/v1/tickets/governance/{draft['id']}/comments/"
    internal_endpoint = f"/api/v1/tickets/governance/{draft['id']}/internal-comments/"
    public_comment = client.post(
        public_endpoint,
        {"body": "Please include the latest resident feedback.", "expected_version": 4},
        content_type="application/json",
        **request_headers(reporter, society, "gov-comment-public"),
    )
    internal_comment = client.post(
        internal_endpoint,
        {"body": "Committee context has been recorded.", "expected_version": 4},
        content_type="application/json",
        **request_headers(facility_manager, society, "gov-comment-internal"),
    )
    public_thread = client.get(
        public_endpoint,
        **request_headers(reporter, society),
    )
    internal_thread = client.get(
        internal_endpoint,
        **request_headers(facility_manager, society),
    )

    assert submitted.status_code == 200, submitted.json()
    assert reviewed.status_code == 200, reviewed.json()
    assert discussion.status_code == 200, discussion.json()
    assert discussion.json()["status"] == Ticket.Status.IN_DISCUSSION
    assert discussion.json()["state_version"] == 4
    assert public_comment.status_code == 201, public_comment.json()
    assert internal_comment.status_code == 201, internal_comment.json()
    assert public_comment.json()["visibility"] == TicketComment.Visibility.PUBLIC
    assert internal_comment.json()["visibility"] == TicketComment.Visibility.INTERNAL
    assert public_thread.status_code == 200
    assert internal_thread.status_code == 200
    assert public_thread.json() == [public_comment.json()]
    assert internal_thread.json() == [internal_comment.json()]


def test_resident_cancels_submitted_ticket_idempotently(client):
    society = Society.objects.create(registration_code="NIV-CANCEL")
    unit = create_unit(society=society, code="A", door_number="114")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543546",
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    ticket = submit_service_ticket(
        client=client,
        society=society,
        actor=resident,
        category=category,
        subcategory=subcategory,
        unit=unit,
        key="resident-cancel-ticket",
    )
    payload = {
        "expected_version": ticket["state_version"],
        "reason": "The leak stopped before a technician was assigned.",
    }
    headers = request_headers(resident, society, "resident-cancel-1")

    first = client.post(
        f"/api/v1/service-tickets/{ticket['id']}/cancel/",
        payload,
        content_type="application/json",
        **headers,
    )
    replay = client.post(
        f"/api/v1/service-tickets/{ticket['id']}/cancel/",
        payload,
        content_type="application/json",
        **headers,
    )

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.CANCELLED
    assert first.json()["state_version"] == ticket["state_version"] + 1
    with transaction.atomic():
        set_local_society_id(society.id)
        cancelled = Ticket.objects.get(id=ticket["id"])
        event = TicketEvent.objects.get(
            ticket=cancelled,
            event_type=TicketEvent.EventType.TICKET_CANCELLED,
        )
        cycle = SLACycle.objects.get(ticket=cancelled)
        assert cancelled.status == Ticket.Status.CANCELLED
        assert event.ticket_version == cancelled.state_version
        assert event.reason == payload["reason"]
        assert cycle.ended_at is not None
        assert cycle.outcome == SLACycle.Outcome.CANCELLED


def test_same_unit_reader_cannot_cancel_ticket(client):
    society = Society.objects.create(registration_code="NIV-CAN-ACC")
    unit = create_unit(society=society, code="A", door_number="115")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543547",
    )
    helpdesk = create_staff(
        society=society,
        phone="+919876543548",
        role=StaffMembership.Role.HELPDESK_OPERATOR,
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    ticket = submit_service_ticket(
        client=client,
        society=society,
        actor=helpdesk,
        category=category,
        subcategory=subcategory,
        unit=unit,
        key="staff-cancel-ticket",
    )

    denied = client.post(
        f"/api/v1/service-tickets/{ticket['id']}/cancel/",
        {"expected_version": 2, "reason": "Not my request."},
        content_type="application/json",
        **request_headers(resident, society, "same-unit-cancel"),
    )

    assert denied.status_code == 403
    with transaction.atomic():
        set_local_society_id(society.id)
        unchanged = Ticket.objects.get(id=ticket["id"])
        assert unchanged.status == Ticket.Status.SUBMITTED
        assert unchanged.state_version == 2


def test_cancel_rejects_stale_version_and_non_submitted_state(client):
    society = Society.objects.create(registration_code="NIV-CAN-STATE")
    unit = create_unit(society=society, code="A", door_number="116")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543549",
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    ticket = submit_service_ticket(
        client=client,
        society=society,
        actor=resident,
        category=category,
        subcategory=subcategory,
        unit=unit,
        key="resident-cancel-state-ticket",
    )
    endpoint = f"/api/v1/service-tickets/{ticket['id']}/cancel/"

    stale = client.post(
        endpoint,
        {"expected_version": 1, "reason": "Stale request."},
        content_type="application/json",
        **request_headers(resident, society, "stale-cancel"),
    )
    cancelled = client.post(
        endpoint,
        {"expected_version": 2, "reason": "Issue resolved itself."},
        content_type="application/json",
        **request_headers(resident, society, "valid-cancel"),
    )
    repeated = client.post(
        endpoint,
        {"expected_version": 3, "reason": "Cancel again."},
        content_type="application/json",
        **request_headers(resident, society, "repeated-cancel"),
    )

    assert stale.status_code == 409
    assert stale.json()["code"] == "TICKET_VERSION_CONFLICT"
    assert cancelled.status_code == 200
    assert repeated.status_code == 409
    assert repeated.json()["code"] == "TICKET_STATE_CONFLICT"
    with transaction.atomic():
        set_local_society_id(society.id)
        assert TicketEvent.objects.filter(
            ticket_id=ticket["id"],
            event_type=TicketEvent.EventType.TICKET_CANCELLED,
        ).count() == 1


def test_same_unit_reader_can_list_but_cannot_create_comment(client):
    society = Society.objects.create(registration_code="NIV-CMT-ACC")
    unit = create_unit(society=society, code="A", door_number="112")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543543",
    )
    helpdesk = create_staff(
        society=society,
        phone="+919876543544",
        role=StaffMembership.Role.HELPDESK_OPERATOR,
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    ticket = submit_service_ticket(
        client=client,
        society=society,
        actor=helpdesk,
        category=category,
        subcategory=subcategory,
        unit=unit,
        key="staff-comment-ticket",
    )
    created = client.post(
        f"/api/v1/tickets/service/{ticket['id']}/comments/",
        {"body": "A technician will inspect this shortly.", "expected_version": 2},
        content_type="application/json",
        **request_headers(helpdesk, society, "staff-comment-1"),
    )

    listed = client.get(
        f"/api/v1/tickets/service/{ticket['id']}/comments/",
        **request_headers(resident, society),
    )
    denied = client.post(
        f"/api/v1/tickets/service/{ticket['id']}/comments/",
        {"body": "I should not be able to write here.", "expected_version": 2},
        content_type="application/json",
        **request_headers(resident, society, "same-unit-comment"),
    )

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json()[0]["body"] == "A technician will inspect this shortly."
    assert listed.json()[0]["is_authored_by_requester"] is False
    assert denied.status_code == 403


def test_comment_create_rejects_draft_and_stale_ticket_version(client):
    society = Society.objects.create(registration_code="NIV-CMT-STATE")
    unit = create_unit(society=society, code="A", door_number="113")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876543545",
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
    )
    draft = client.post(
        "/api/v1/service-tickets/",
        ticket_payload(category=category, subcategory=subcategory, unit=unit),
        content_type="application/json",
        **request_headers(resident, society, "comment-state-draft"),
    ).json()

    draft_comment = client.post(
        f"/api/v1/tickets/service/{draft['id']}/comments/",
        {"body": "Draft comments are not shared.", "expected_version": 1},
        content_type="application/json",
        **request_headers(resident, society, "draft-comment"),
    )
    create_sla_binding(
        society=society,
        category=category,
        priority=subcategory.default_priority,
    )
    create_business_calendar(society=society)
    submitted = client.post(
        f"/api/v1/service-tickets/{draft['id']}/submit/",
        {"expected_version": 1},
        content_type="application/json",
        **request_headers(resident, society, "comment-state-submit"),
    )
    stale_comment = client.post(
        f"/api/v1/tickets/service/{draft['id']}/comments/",
        {"body": "This request uses a stale version.", "expected_version": 1},
        content_type="application/json",
        **request_headers(resident, society, "stale-comment"),
    )

    assert draft_comment.status_code == 409
    assert draft_comment.json()["code"] == "TICKET_STATE_CONFLICT"
    assert submitted.status_code == 200
    assert stale_comment.status_code == 409
    assert stale_comment.json()["code"] == "TICKET_VERSION_CONFLICT"


def test_start_work_in_house_technician(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-START-TECH",
            phone_offset=4100,
        )
    )
    accept_response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "start-tech-accept"),
    )
    assert accept_response.status_code == 200, accept_response.json()
    accepted_version = accept_response.json()["state_version"]

    start_endpoint = f"/api/v1/service-tickets/{offered['id']}/start/"
    payload = {"expected_version": accepted_version}
    headers = request_headers(technician_user, society, "technician-start-work")

    first = client.post(start_endpoint, payload, content_type="application/json", **headers)
    replay = client.post(start_endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.IN_PROGRESS
    assert first.json()["state_version"] == accepted_version + 1
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_WORK_STARTED,
        )
        assert ticket.status == Ticket.Status.IN_PROGRESS
        assert event.ticket_version == ticket.state_version
        assert event.actor_id == technician_user.id
        assert event.actor_persona == "technician"
        assert event.metadata["technician_id"] == str(technician.id)


def test_start_work_vendor_worker(client):
    society = Society.objects.create(registration_code="NIV-START-VEND")
    unit = create_unit(society=society, code="A", door_number="401")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876610001",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876610002",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    dispatcher = User.objects.create_user(phone="+919876610003")
    worker = User.objects.create_user(phone="+919876610004")
    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name="Delta Elevators",
            normalized_company_name="delta elevators",
            contact_person="Ravi Verma",
            phone_number="+919876610005",
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
            user=dispatcher,
            role=VendorStaffMembership.Role.DISPATCHER,
        )
        worker_membership = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=worker,
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
        key="vendor-start-submit",
    )
    assigned = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-vendor/",
        {
            "expected_version": submitted["state_version"],
            "vendor_contract_id": str(contract.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "vendor-start-assign"),
    )
    assert assigned.status_code == 200, assigned.json()
    allocated = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/allocate-vendor-worker/",
        {
            "expected_version": assigned.json()["state_version"],
            "staff_membership_id": str(worker_membership.id),
        },
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-start-allocate"),
    )
    assert allocated.status_code == 200, allocated.json()
    accepted = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/accept-vendor-worker/",
        {"expected_version": allocated.json()["state_version"]},
        content_type="application/json",
        **request_headers(worker, society, "vendor-start-accept"),
    )
    assert accepted.status_code == 200, accepted.json()
    accepted_version = accepted.json()["state_version"]

    start_endpoint = f"/api/v1/service-tickets/{submitted['id']}/start/"
    payload = {"expected_version": accepted_version}
    headers = request_headers(worker, society, "vendor-worker-start-work")

    first = client.post(start_endpoint, payload, content_type="application/json", **headers)
    replay = client.post(start_endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.IN_PROGRESS
    assert first.json()["state_version"] == accepted_version + 1
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=submitted["id"])
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_WORK_STARTED,
        )
        assert ticket.status == Ticket.Status.IN_PROGRESS
        assert event.ticket_version == ticket.state_version
        assert event.actor_id == worker.id
        assert event.actor_persona == "vendor"
        assert event.metadata["staff_membership_id"] == str(worker_membership.id)


def test_start_work_resident_denied(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-START-DENIED",
            phone_offset=4200,
        )
    )
    accept_response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "start-denied-accept"),
    )
    accepted_version = accept_response.json()["state_version"]

    resident = User.objects.get(phone="+919876544200")
    start_endpoint = f"/api/v1/service-tickets/{offered['id']}/start/"
    payload = {"expected_version": accepted_version}
    denied = client.post(
        start_endpoint,
        payload,
        content_type="application/json",
        **request_headers(resident, society, "resident-start-denied"),
    )
    assert denied.status_code in {403, 404}


def test_reject_vendor_assignment_dispatcher(client):
    society = Society.objects.create(registration_code="NIV-REJ-VEND")
    unit = create_unit(society=society, code="A", door_number="501")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876620001",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876620002",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    dispatcher = User.objects.create_user(phone="+919876620003")
    worker = User.objects.create_user(phone="+919876620004")
    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name="Echo Security Systems",
            normalized_company_name="echo security systems",
            contact_person="Suresh Nair",
            phone_number="+919876620005",
        )
        contract = VendorContract.objects.create(
            society=society,
            vendor=vendor,
            starts_on=timezone.localdate() - timedelta(days=1),
            ends_on=timezone.localdate() + timedelta(days=30),
            max_active_tickets=5,
        )
        VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=dispatcher,
            role=VendorStaffMembership.Role.DISPATCHER,
        )
        worker_membership = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=worker,
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
        key="vendor-reject-submit",
    )
    assigned = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-vendor/",
        {
            "expected_version": submitted["state_version"],
            "vendor_contract_id": str(contract.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "vendor-reject-assign"),
    )
    assert assigned.status_code == 200, assigned.json()
    allocated = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/allocate-vendor-worker/",
        {
            "expected_version": assigned.json()["state_version"],
            "staff_membership_id": str(worker_membership.id),
        },
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-reject-allocate"),
    )
    assert allocated.status_code == 200, allocated.json()

    reject_endpoint = f"/api/v1/service-tickets/{submitted['id']}/reject-vendor-assignment/"
    payload = {
        "expected_version": allocated.json()["state_version"],
        "reason": "All vendor technicians are currently on emergency duty.",
    }
    headers = request_headers(dispatcher, society, "dispatcher-reject-assignment")

    first = client.post(reject_endpoint, payload, content_type="application/json", **headers)
    replay = client.post(reject_endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.SUBMITTED
    assert first.json()["assignment_failure_count"] == 1
    assert first.json()["assignee_rejection_count"] == 1
    assert first.json()["assignment"]["state"] == TicketAssignment.State.ENDED
    assert first.json()["assignment"]["ended_reason"] == payload["reason"]

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=submitted["id"])
        assignment = TicketAssignment.objects.get(ticket=ticket)
        allocation = VendorStaffAllocation.objects.get(assignment=assignment)
        sla_cycle = SLACycle.objects.get(ticket=ticket, ended_at__isnull=True)
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_ASSIGNMENT_REJECTED,
        )
        contract.refresh_from_db()
        assert assignment.state == TicketAssignment.State.ENDED
        assert assignment.ended_reason == payload["reason"]
        assert allocation.state == VendorStaffAllocation.State.ENDED
        assert allocation.ended_reason == payload["reason"]
        assert contract.current_active_tickets_count == 0
        assert sla_cycle.acceptance_deadline is None
        assert sla_cycle.assignment_failure_count == 1
        assert sla_cycle.assignee_rejection_count == 1
        assert event.reason == payload["reason"]
        assert event.actor_id == dispatcher.id
        assert event.actor_persona == "vendor"


def test_reject_vendor_assignment_at_threshold(client):
    society = Society.objects.create(registration_code="NIV-REJ-TRIAGE")
    unit = create_unit(society=society, code="A", door_number="502")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876630001",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876630002",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    dispatcher = User.objects.create_user(phone="+919876630003")
    worker = User.objects.create_user(phone="+919876630004")
    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name="Foxtrot Facilities",
            normalized_company_name="foxtrot facilities",
            contact_person="Meera Das",
            phone_number="+919876630005",
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
            user=dispatcher,
            role=VendorStaffMembership.Role.DISPATCHER,
        )
        worker_membership = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=worker,
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
        key="vendor-triage-submit",
    )
    assigned = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-vendor/",
        {
            "expected_version": submitted["state_version"],
            "vendor_contract_id": str(contract.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "vendor-triage-assign"),
    )
    allocated = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/allocate-vendor-worker/",
        {
            "expected_version": assigned.json()["state_version"],
            "staff_membership_id": str(worker_membership.id),
        },
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-triage-allocate"),
    )

    with transaction.atomic():
        set_local_society_id(society.id)
        sla_cycle = SLACycle.objects.get(ticket_id=submitted["id"], ended_at__isnull=True)
        sla_cycle.assignment_failure_count = 2
        sla_cycle.assignee_rejection_count = 2
        sla_cycle.save(
            update_fields=("assignment_failure_count", "assignee_rejection_count")
        )

    response = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/reject-vendor-assignment/",
        {
            "expected_version": allocated.json()["state_version"],
            "reason": "Escalating: no capacity available across contracts.",
        },
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-triage-reject"),
    )

    assert response.status_code == 200, response.json()
    assert response.json()["status"] == Ticket.Status.SUPERVISOR_TRIAGE
    assert response.json()["assignment_failure_count"] == 3
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=submitted["id"])
        contract.refresh_from_db()
        assert ticket.status == Ticket.Status.SUPERVISOR_TRIAGE
        assert contract.current_active_tickets_count == 0


def test_reject_vendor_assignment_worker_denied(client):
    society = Society.objects.create(registration_code="NIV-REJ-DENIED")
    unit = create_unit(society=society, code="A", door_number="503")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876640001",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876640002",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    dispatcher = User.objects.create_user(phone="+919876640003")
    worker = User.objects.create_user(phone="+919876640004")
    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name="Golf Gardening",
            normalized_company_name="golf gardening",
            contact_person="Anita Sen",
            phone_number="+919876640005",
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
            user=dispatcher,
            role=VendorStaffMembership.Role.DISPATCHER,
        )
        worker_membership = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=worker,
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
        key="vendor-rej-denied-submit",
    )
    assigned = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-vendor/",
        {
            "expected_version": submitted["state_version"],
            "vendor_contract_id": str(contract.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "vendor-rej-denied-assign"),
    )
    allocated = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/allocate-vendor-worker/",
        {
            "expected_version": assigned.json()["state_version"],
            "staff_membership_id": str(worker_membership.id),
        },
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-rej-denied-allocate"),
    )

    denied = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/reject-vendor-assignment/",
        {
            "expected_version": allocated.json()["state_version"],
            "reason": "Worker attempting to reject vendor assignment.",
        },
        content_type="application/json",
        **request_headers(worker, society, "worker-reject-denied"),
    )
    assert denied.status_code == 403


def test_resident_cancels_assigned_service_ticket_releases_technician_capacity(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-CAN-ASGN",
            phone_offset=4300,
        )
    )
    resident = User.objects.get(phone="+919876544300")
    endpoint = f"/api/v1/service-tickets/{offered['id']}/cancel/"
    payload = {
        "expected_version": offered["state_version"],
        "reason": "Resident no longer requires plumbing assistance.",
    }
    headers = request_headers(resident, society, "resident-cancel-assigned")

    first = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.CANCELLED
    assert first.json()["state_version"] == offered["state_version"] + 1
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        assignment = TicketAssignment.objects.get(ticket=ticket)
        cycle = SLACycle.objects.get(ticket=ticket)
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_CANCELLED,
        )
        technician.refresh_from_db()
        assert ticket.status == Ticket.Status.CANCELLED
        assert assignment.state == TicketAssignment.State.ENDED
        assert assignment.ended_reason == payload["reason"]
        assert technician.current_active_tickets_count == 0
        assert cycle.outcome == SLACycle.Outcome.CANCELLED
        assert event.actor_id == resident.id
        assert event.actor_persona == "resident"
        assert event.metadata["technician_id"] == str(technician.id)


def test_resident_cancels_accepted_vendor_ticket_releases_contract_capacity(client):
    society = Society.objects.create(registration_code="NIV-CAN-VEND")
    unit = create_unit(society=society, code="A", door_number="601")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876650001",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876650002",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    dispatcher = User.objects.create_user(phone="+919876650003")
    worker = User.objects.create_user(phone="+919876650004")
    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name="Hotel Housekeeping",
            normalized_company_name="hotel housekeeping",
            contact_person="Manoj Kumar",
            phone_number="+919876650005",
        )
        contract = VendorContract.objects.create(
            society=society,
            vendor=vendor,
            starts_on=timezone.localdate() - timedelta(days=1),
            ends_on=timezone.localdate() + timedelta(days=30),
            max_active_tickets=5,
        )
        VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=dispatcher,
            role=VendorStaffMembership.Role.DISPATCHER,
        )
        worker_membership = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=worker,
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
        key="vendor-can-submit",
    )
    assigned = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-vendor/",
        {
            "expected_version": submitted["state_version"],
            "vendor_contract_id": str(contract.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "vendor-can-assign"),
    )
    allocated = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/allocate-vendor-worker/",
        {
            "expected_version": assigned.json()["state_version"],
            "staff_membership_id": str(worker_membership.id),
        },
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-can-allocate"),
    )
    accepted = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/accept-vendor-worker/",
        {"expected_version": allocated.json()["state_version"]},
        content_type="application/json",
        **request_headers(worker, society, "vendor-can-accept"),
    )
    assert accepted.status_code == 200, accepted.json()

    cancel_endpoint = f"/api/v1/service-tickets/{submitted['id']}/cancel/"
    payload = {
        "expected_version": accepted.json()["state_version"],
        "reason": "Resident fixed the issue personally before worker arrival.",
    }
    cancel_res = client.post(
        cancel_endpoint,
        payload,
        content_type="application/json",
        **request_headers(resident, society, "resident-cancel-accepted-vendor"),
    )
    assert cancel_res.status_code == 200, cancel_res.json()
    assert cancel_res.json()["status"] == Ticket.Status.CANCELLED
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=submitted["id"])
        assignment = TicketAssignment.objects.get(ticket=ticket)
        allocation = VendorStaffAllocation.objects.get(assignment=assignment)
        cycle = SLACycle.objects.get(ticket=ticket)
        contract.refresh_from_db()
        assert ticket.status == Ticket.Status.CANCELLED
        assert assignment.state == TicketAssignment.State.ENDED
        assert allocation.state == VendorStaffAllocation.State.ENDED
        assert contract.current_active_tickets_count == 0
        assert cycle.outcome == SLACycle.Outcome.CANCELLED


def test_resident_cannot_cancel_in_progress_service_ticket(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-CAN-INPROG",
            phone_offset=4400,
        )
    )
    accept_response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "can-inprog-accept"),
    )
    start_response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_response.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "can-inprog-start"),
    )
    assert start_response.status_code == 200, start_response.json()

    resident = User.objects.get(phone="+919876544400")
    denied = client.post(
        f"/api/v1/service-tickets/{offered['id']}/cancel/",
        {
            "expected_version": start_response.json()["state_version"],
            "reason": "Trying to cancel after work started.",
        },
        content_type="application/json",
        **request_headers(resident, society, "resident-cancel-inprog"),
    )
    assert denied.status_code == 403
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        technician.refresh_from_db()
        assert ticket.status == Ticket.Status.IN_PROGRESS
        assert technician.current_active_tickets_count == 1


def test_facility_manager_cancels_in_progress_service_ticket(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-FM-CAN-INP",
            phone_offset=4500,
        )
    )
    accept_response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "fm-inp-accept"),
    )
    start_response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_response.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "fm-inp-start"),
    )
    assert start_response.status_code == 200, start_response.json()

    cancel_response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/cancel/",
        {
            "expected_version": start_response.json()["state_version"],
            "reason": "Building management cancelled work order due to structural inspection.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "fm-cancel-inprog"),
    )
    assert cancel_response.status_code == 200, cancel_response.json()
    assert cancel_response.json()["status"] == Ticket.Status.CANCELLED
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        assignment = TicketAssignment.objects.get(ticket=ticket)
        cycle = SLACycle.objects.get(ticket=ticket)
        technician.refresh_from_db()
        assert ticket.status == Ticket.Status.CANCELLED
        assert assignment.state == TicketAssignment.State.ENDED
        assert technician.current_active_tickets_count == 0
        assert cycle.outcome == SLACycle.Outcome.CANCELLED


def test_facility_manager_cancels_supervisor_triage_ticket(client):
    society, _, technician_user, technician, offered = create_offered_in_house_assignment(
        client=client,
        registration_code="NIV-FM-CAN-TRG",
        phone_offset=4600,
    )
    facility_manager = User.objects.get(phone="+919876554600")
    with transaction.atomic():
        set_local_society_id(society.id)
        sla_cycle = SLACycle.objects.get(ticket_id=offered["id"], ended_at__isnull=True)
        sla_cycle.assignment_failure_count = 2
        sla_cycle.assignee_rejection_count = 2
        sla_cycle.save(
            update_fields=("assignment_failure_count", "assignee_rejection_count")
        )

    reject_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/reject/",
        {
            "expected_version": offered["state_version"],
            "reason": "Threshold reached for rejection.",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "tech-triage-reject"),
    )
    assert reject_res.status_code == 200
    assert reject_res.json()["status"] == Ticket.Status.SUPERVISOR_TRIAGE

    cancel_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/cancel/",
        {
            "expected_version": reject_res.json()["state_version"],
            "reason": "Facility manager cancelled triage ticket after resident consultation.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "fm-cancel-triage"),
    )
    assert cancel_res.status_code == 200, cancel_res.json()
    assert cancel_res.json()["status"] == Ticket.Status.CANCELLED
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        assert ticket.status == Ticket.Status.CANCELLED


def test_stale_version_cancellation_with_assignment_does_not_mutate(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-STALE-CAN",
            phone_offset=4700,
        )
    )
    resident = User.objects.get(phone="+919876544700")
    stale_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/cancel/",
        {
            "expected_version": offered["state_version"] - 1,
            "reason": "Stale version cancellation.",
        },
        content_type="application/json",
        **request_headers(resident, society, "stale-version-cancel"),
    )
    assert stale_res.status_code == 409
    assert stale_res.json()["code"] == "TICKET_VERSION_CONFLICT"
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        assignment = TicketAssignment.objects.get(ticket=ticket)
        technician.refresh_from_db()
        assert ticket.status == Ticket.Status.ASSIGNED
        assert assignment.state == TicketAssignment.State.OFFERED
        assert technician.current_active_tickets_count == 1


def test_in_house_technician_requests_completion(client, monkeypatch):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-REQ-COMP",
            phone_offset=4800,
        )
    )
    otp_code = "123456"
    stub_completion_otp(monkeypatch, otp_code)
    accept_response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "req-comp-accept"),
    )
    start_response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_response.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "req-comp-start"),
    )
    assert start_response.status_code == 200, start_response.json()
    started_version = start_response.json()["state_version"]

    endpoint = f"/api/v1/service-tickets/{offered['id']}/request-completion/"
    payload = {
        "expected_version": started_version,
        "work_notes": "Replaced the damaged faucet washer and tested for leaks.",
    }
    headers = request_headers(technician_user, society, "tech-request-completion")

    first = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.PENDING_RESIDENT_CONFIRMATION
    assert first.json()["state_version"] == started_version + 1

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        challenge = TicketCompletionChallenge.objects.get(ticket=ticket)
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_COMPLETION_REQUESTED,
        )
        outbox_event = TicketOutboxEvent.objects.get(ticket_event=event)
        assert ticket.status == Ticket.Status.PENDING_RESIDENT_CONFIRMATION
        assert challenge.worker_notes == payload["work_notes"]
        assert challenge.otp_hash != otp_code
        assert check_password(otp_code, challenge.otp_hash)
        assert challenge.delivery_capsule_name
        assert (
            retrieve_completion_otp_capsule(
                capsule_name=challenge.delivery_capsule_name
            )
            == otp_code
        )
        assert timedelta(minutes=9) <= challenge.expires_at - timezone.now() <= timedelta(minutes=10)
        assert challenge.is_consumed is False
        assert event.ticket_version == ticket.state_version
        assert event.actor_id == technician_user.id
        assert event.actor_persona == "technician"
        assert event.metadata["challenge_id"] == str(challenge.id)
        assert outbox_event.society_id == society.id
        assert outbox_event.ticket_id == ticket.id
        assert outbox_event.completion_challenge_id == challenge.id
        assert (
            outbox_event.event_type
            == TicketOutboxEvent.EventType.SERVICE_COMPLETION_NOTIFICATION_REQUESTED
        )
        assert outbox_event.payload == {
            "challenge_id": str(challenge.id),
            "correlation_id": str(event.correlation_id),
        }
        assert outbox_event.status == TicketOutboxEvent.Status.PENDING
        assert outbox_event.state_version == 1
        assert outbox_event.attempts_count == 0

    outcome = publish_ticket_completion_notifications.run(society.id)
    assert outcome == {
        "submitted": 1,
        "retried": 0,
        "dead_lettered": 0,
        "claim_lost": 0,
    }
    with transaction.atomic():
        set_local_society_id(society.id)
        submitted_event = TicketOutboxEvent.objects.get(id=outbox_event.id)
    assert submitted_event.status == TicketOutboxEvent.Status.SUBMITTED
    assert submitted_event.provider_message_id == f"test-email-{outbox_event.id}"
    assert submitted_event.delivered_at is None
    assert retrieve_completion_otp_capsule(capsule_name=challenge.delivery_capsule_name) is None
    with pytest.raises(TicketOutboxDeliveryConfirmationRejected):
        confirm_ticket_outbox_event_delivery(
            society_id=society.id,
            outbox_event_id=outbox_event.id,
            provider_message_id="unexpected-provider-message",
        )
    delivered_event = confirm_ticket_outbox_event_delivery(
        society_id=society.id,
        outbox_event_id=outbox_event.id,
        provider_message_id=f"test-email-{outbox_event.id}",
    )
    assert delivered_event.status == TicketOutboxEvent.Status.DELIVERED
    assert delivered_event.attempts_count == 1
    assert delivered_event.state_version == 4
    assert (
        confirm_ticket_outbox_event_delivery(
            society_id=society.id,
            outbox_event_id=outbox_event.id,
            provider_message_id=f"test-email-{outbox_event.id}",
        ).state_version
        == 4
    )
    assert claim_ticket_outbox_events(
        society_id=society.id,
        claim_token=uuid.uuid4(),
    ) == []


def test_completion_publisher_dead_letters_ambiguous_provider_outcome(client, monkeypatch):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-COMP-UNKNOWN",
            phone_offset=4810,
        )
    )
    stub_completion_otp(monkeypatch, "123456")
    accepted = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "comp-unknown-accept"),
    )
    started = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accepted.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "comp-unknown-start"),
    )
    completion = client.post(
        f"/api/v1/service-tickets/{offered['id']}/request-completion/",
        {
            "expected_version": started.json()["state_version"],
            "work_notes": "Completed the repair; delivery provider outcome is unknown.",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "comp-unknown-request"),
    )
    assert completion.status_code == 200, completion.json()
    monkeypatch.setattr(
        "apps.tickets.tasks.submit_completion_otp_email",
        lambda **kwargs: (_ for _ in ()).throw(
            CompletionEmailSubmissionUnknown("provider outcome is unknown")
        ),
    )

    outcome = publish_ticket_completion_notifications.run(society.id)

    assert outcome == {
        "submitted": 0,
        "retried": 0,
        "dead_lettered": 1,
        "claim_lost": 0,
    }
    with transaction.atomic():
        set_local_society_id(society.id)
        outbox_event = TicketOutboxEvent.objects.get(ticket_id=offered["id"])
    assert outbox_event.status == TicketOutboxEvent.Status.DEAD_LETTER
    assert outbox_event.last_error_code == "EMAIL_PROVIDER_OUTCOME_UNKNOWN"
    assert outbox_event.attempts_count == 1


def test_completion_publisher_dead_letters_expired_otp_without_sending(client, monkeypatch):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-COMP-EXPIRED",
            phone_offset=4820,
        )
    )
    stub_completion_otp(monkeypatch, "123456")
    accepted = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "comp-expired-accept"),
    )
    started = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accepted.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "comp-expired-start"),
    )
    completion = client.post(
        f"/api/v1/service-tickets/{offered['id']}/request-completion/",
        {
            "expected_version": started.json()["state_version"],
            "work_notes": "Completed the repair; the confirmation code has expired.",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "comp-expired-request"),
    )
    assert completion.status_code == 200, completion.json()
    with transaction.atomic():
        set_local_society_id(society.id)
        challenge = TicketCompletionChallenge.objects.get(ticket_id=offered["id"])
        challenge.expires_at = timezone.now() - timedelta(seconds=1)
        challenge.save(update_fields=("expires_at",))
    monkeypatch.setattr(
        "apps.tickets.tasks.submit_completion_otp_email",
        lambda **kwargs: pytest.fail("The publisher must not send an expired OTP."),
    )

    outcome = publish_ticket_completion_notifications.run(society.id)

    assert outcome == {
        "submitted": 0,
        "retried": 0,
        "dead_lettered": 1,
        "claim_lost": 0,
    }
    with transaction.atomic():
        set_local_society_id(society.id)
        outbox_event = TicketOutboxEvent.objects.get(ticket_id=offered["id"])
    assert outbox_event.status == TicketOutboxEvent.Status.DEAD_LETTER
    assert outbox_event.last_error_code == "OTP_EXPIRED_BEFORE_SUBMISSION"
    assert outbox_event.attempts_count == 1


def test_completion_outbox_dead_letters_after_max_attempts(client, monkeypatch):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-OUTBOX-DEAD",
            phone_offset=4825,
        )
    )
    stub_completion_otp(monkeypatch, "123456")
    accept_response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "outbox-dead-accept"),
    )
    start_response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_response.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "outbox-dead-start"),
    )
    completion_response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/request-completion/",
        {
            "expected_version": start_response.json()["state_version"],
            "work_notes": "Completed the repair but the notification provider is unavailable.",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "outbox-dead-completion"),
    )
    assert completion_response.status_code == 200, completion_response.json()

    with transaction.atomic():
        set_local_society_id(society.id)
        outbox_event = TicketOutboxEvent.objects.get(ticket_id=offered["id"])
        outbox_event.max_attempts = 1
        outbox_event.save(update_fields=("max_attempts",))

    claim_token = uuid.uuid4()
    claimed_events = claim_ticket_outbox_events(
        society_id=society.id,
        claim_token=claim_token,
    )
    assert [event.id for event in claimed_events] == [outbox_event.id]
    with transaction.atomic():
        set_local_society_id(society.id)
        TicketOutboxEvent.objects.filter(id=outbox_event.id).update(
            claim_expires_at=timezone.now() - timedelta(seconds=1)
        )
    with pytest.raises(TicketOutboxClaimLost):
        release_ticket_outbox_event_for_retry(
            society_id=society.id,
            outbox_event_id=outbox_event.id,
            claim_token=claim_token,
            error_code="PROVIDER_UNAVAILABLE",
            retry_delay=timedelta(),
        )

    assert claim_ticket_outbox_events(
        society_id=society.id,
        claim_token=uuid.uuid4(),
    ) == []
    with transaction.atomic():
        set_local_society_id(society.id)
        dead_letter_event = TicketOutboxEvent.objects.get(id=outbox_event.id)
    assert dead_letter_event.status == TicketOutboxEvent.Status.DEAD_LETTER
    assert dead_letter_event.attempts_count == 1
    assert dead_letter_event.dead_lettered_at is not None
    assert dead_letter_event.claim_token is None
    assert claim_ticket_outbox_events(
        society_id=society.id,
        claim_token=uuid.uuid4(),
    ) == []


def test_offered_technician_cannot_request_completion_or_claim_idempotency(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-OFFERED-NO-COMP",
            phone_offset=4850,
        )
    )

    response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/request-completion/",
        {
            "expected_version": offered["state_version"],
            "work_notes": "Attempted completion before accepting the assignment.",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "offered-request-completion"),
    )

    assert response.status_code == 403
    with transaction.atomic():
        set_local_society_id(society.id)
        assert (
            IdempotencyRecord.objects.filter(
                society=society,
                principal=technician_user,
                idempotency_key="offered-request-completion",
            ).exists()
            is False
        )


def test_vendor_worker_requests_completion(client):
    society = Society.objects.create(registration_code="NIV-VEND-COMP")
    unit = create_unit(society=society, code="A", door_number="701")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876660001",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876660002",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    dispatcher = User.objects.create_user(phone="+919876660003")
    worker = User.objects.create_user(phone="+919876660004")
    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name="India Power Works",
            normalized_company_name="india power works",
            contact_person="Kiran Rao",
            phone_number="+919876660005",
        )
        contract = VendorContract.objects.create(
            society=society,
            vendor=vendor,
            starts_on=timezone.localdate() - timedelta(days=1),
            ends_on=timezone.localdate() + timedelta(days=30),
            max_active_tickets=5,
        )
        VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=dispatcher,
            role=VendorStaffMembership.Role.DISPATCHER,
        )
        worker_membership = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=worker,
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
        key="vendor-comp-submit",
    )
    assigned = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-vendor/",
        {
            "expected_version": submitted["state_version"],
            "vendor_contract_id": str(contract.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "vendor-comp-assign"),
    )
    allocated = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/allocate-vendor-worker/",
        {
            "expected_version": assigned.json()["state_version"],
            "staff_membership_id": str(worker_membership.id),
        },
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-comp-allocate"),
    )
    accepted = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/accept-vendor-worker/",
        {"expected_version": allocated.json()["state_version"]},
        content_type="application/json",
        **request_headers(worker, society, "vendor-comp-accept"),
    )
    started = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/start/",
        {"expected_version": accepted.json()["state_version"]},
        content_type="application/json",
        **request_headers(worker, society, "vendor-comp-start"),
    )
    assert started.status_code == 200, started.json()

    endpoint = f"/api/v1/service-tickets/{submitted['id']}/request-completion/"
    payload = {
        "expected_version": started.json()["state_version"],
        "work_notes": "Repaired the electrical circuit breaker.",
    }
    headers = request_headers(worker, society, "vendor-worker-request-completion")

    res = client.post(endpoint, payload, content_type="application/json", **headers)
    assert res.status_code == 200, res.json()
    assert res.json()["status"] == Ticket.Status.PENDING_RESIDENT_CONFIRMATION
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=submitted["id"])
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_COMPLETION_REQUESTED,
        )
        assert event.actor_id == worker.id
        assert event.actor_persona == "vendor"
        assert event.metadata["staff_membership_id"] == str(worker_membership.id)


def test_resident_verifies_completion_and_resolves_ticket(client, monkeypatch):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-VER-COMP",
            phone_offset=4900,
        )
    )
    resident = User.objects.get(phone="+919876544900")
    accept_response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "ver-comp-accept"),
    )
    start_response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_response.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "ver-comp-start"),
    )
    otp_code = stub_completion_otp(monkeypatch)
    req_response = client.post(
        f"/api/v1/service-tickets/{offered['id']}/request-completion/",
        {
            "expected_version": start_response.json()["state_version"],
            "work_notes": "Plumbing repair completed and verified dry.",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "ver-comp-req"),
    )
    assert req_response.status_code == 200, req_response.json()
    pending_version = req_response.json()["state_version"]

    endpoint = f"/api/v1/service-tickets/{offered['id']}/verify-completion/"
    payload = {
        "expected_version": pending_version,
        "otp": otp_code,
    }
    headers = request_headers(resident, society, "resident-verify-completion")

    first = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.RESOLVED
    assert first.json()["state_version"] == pending_version + 1

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        assignment = TicketAssignment.objects.get(ticket=ticket)
        cycle = SLACycle.objects.get(ticket=ticket)
        challenge = TicketCompletionChallenge.objects.get(ticket=ticket)
        technician.refresh_from_db()
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_RESOLVED,
        )
        assert ticket.status == Ticket.Status.RESOLVED
        assert challenge.is_consumed is True
        assert challenge.consumed_by_id == resident.id
        assert assignment.state == TicketAssignment.State.ENDED
        assert technician.current_active_tickets_count == 0
        assert cycle.outcome == SLACycle.Outcome.RESOLVED
        assert event.actor_id == resident.id
        assert event.actor_persona == "resident"


def test_resident_wrong_otp_increments_attempts_and_conflicts(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-WRG-OTP",
            phone_offset=5000,
        )
    )
    resident = User.objects.get(phone="+919876545000")
    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "wrg-otp-accept"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "wrg-otp-start"),
    )
    req_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/request-completion/",
        {
            "expected_version": start_res.json()["state_version"],
            "work_notes": "Plumbing repair finished.",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "wrg-otp-req"),
    )
    pending_version = req_res.json()["state_version"]

    wrong_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/verify-completion/",
        {
            "expected_version": pending_version,
            "otp": "000000",
        },
        content_type="application/json",
        **request_headers(resident, society, "wrong-otp-attempt"),
    )
    assert wrong_res.status_code == 409
    assert wrong_res.json()["code"] == "INVALID_COMPLETION_OTP"

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        challenge = TicketCompletionChallenge.objects.get(ticket=ticket)
        assert ticket.status == Ticket.Status.PENDING_RESIDENT_CONFIRMATION
        assert challenge.attempts_count == 1
        assert challenge.is_consumed is False


def test_otp_lockout_after_max_attempts(client, monkeypatch):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-LCK-OTP",
            phone_offset=5100,
        )
    )
    resident = User.objects.get(phone="+919876545100")
    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "lck-otp-accept"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "lck-otp-start"),
    )
    correct_otp = stub_completion_otp(monkeypatch)
    req_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/request-completion/",
        {
            "expected_version": start_res.json()["state_version"],
            "work_notes": "Plumbing repair complete.",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "lck-otp-req"),
    )
    pending_version = req_res.json()["state_version"]

    with transaction.atomic():
        set_local_society_id(society.id)
        challenge = TicketCompletionChallenge.objects.get(ticket_id=offered["id"])
        challenge.attempts_count = 4
        challenge.save(update_fields=("attempts_count",))

    # 5th wrong attempt triggers lockout
    lockout_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/verify-completion/",
        {
            "expected_version": pending_version,
            "otp": "999999",
        },
        content_type="application/json",
        **request_headers(resident, society, "lockout-attempt-5"),
    )
    assert lockout_res.status_code == 409
    assert lockout_res.json()["code"] == "OTP_MAX_ATTEMPTS_EXCEEDED"

    # Even with correct OTP, subsequent attempt fails with lockout
    locked_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/verify-completion/",
        {
            "expected_version": pending_version,
            "otp": correct_otp,
        },
        content_type="application/json",
        **request_headers(resident, society, "locked-correct-otp"),
    )
    assert locked_res.status_code == 409
    assert locked_res.json()["code"] == "OTP_MAX_ATTEMPTS_EXCEEDED"


def test_resident_cannot_request_completion(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-RES-NO-REQ",
            phone_offset=5200,
        )
    )
    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "res-noreq-accept"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "res-noreq-start"),
    )
    resident = User.objects.get(phone="+919876545200")

    denied = client.post(
        f"/api/v1/service-tickets/{offered['id']}/request-completion/",
        {
            "expected_version": start_res.json()["state_version"],
            "work_notes": "Resident attempting to mark completed.",
        },
        content_type="application/json",
        **request_headers(resident, society, "resident-req-denied"),
    )
    assert denied.status_code in {403, 404}


def test_worker_cannot_verify_completion(client, monkeypatch):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-WRK-NO-VER",
            phone_offset=5300,
        )
    )
    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "wrk-nover-accept"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "wrk-nover-start"),
    )
    otp_code = stub_completion_otp(monkeypatch)
    req_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/request-completion/",
        {
            "expected_version": start_res.json()["state_version"],
            "work_notes": "Plumbing repair completed.",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "wrk-nover-req"),
    )
    pending_version = req_res.json()["state_version"]

    denied = client.post(
        f"/api/v1/service-tickets/{offered['id']}/verify-completion/",
        {
            "expected_version": pending_version,
            "otp": otp_code,
        },
        content_type="application/json",
        **request_headers(technician_user, society, "technician-verify-denied"),
    )
    assert denied.status_code in {403, 404}


def test_stale_version_completion_request_and_verification_rejected(client, monkeypatch):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-STL-COMP",
            phone_offset=5400,
        )
    )
    resident = User.objects.get(phone="+919876545400")
    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "stl-comp-accept"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "stl-comp-start"),
    )

    # Stale completion request
    stale_req = client.post(
        f"/api/v1/service-tickets/{offered['id']}/request-completion/",
        {
            "expected_version": start_res.json()["state_version"] - 1,
            "work_notes": "Stale version request.",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "stale-req-comp"),
    )
    assert stale_req.status_code == 409
    assert stale_req.json()["code"] == "TICKET_VERSION_CONFLICT"

    # Valid completion request
    otp_code = stub_completion_otp(monkeypatch)
    valid_req = client.post(
        f"/api/v1/service-tickets/{offered['id']}/request-completion/",
        {
            "expected_version": start_res.json()["state_version"],
            "work_notes": "Valid version request.",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "valid-req-comp"),
    )
    assert valid_req.status_code == 200, valid_req.json()
    pending_version = valid_req.json()["state_version"]

    # Stale verification request
    stale_ver = client.post(
        f"/api/v1/service-tickets/{offered['id']}/verify-completion/",
        {
            "expected_version": pending_version - 1,
            "otp": otp_code,
        },
        content_type="application/json",
        **request_headers(resident, society, "stale-ver-comp"),
    )
    assert stale_ver.status_code == 409
    assert stale_ver.json()["code"] == "TICKET_VERSION_CONFLICT"


def test_in_house_technician_submits_estimate(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-SUB-EST",
            phone_offset=5500,
        )
    )
    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "sub-est-accept"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "sub-est-start"),
    )
    started_version = start_res.json()["state_version"]

    endpoint = f"/api/v1/service-tickets/{offered['id']}/submit-estimate/"
    payload = {
        "expected_version": started_version,
        "items": [
            {"description": "Brass Ball Valve 1 inch", "quantity": 2, "unit_cost": 250},
            {"description": "Teflon Tape Roll", "quantity": 1, "unit_cost": 50},
        ],
        "tax_amount": 90,
        "notes": "Materials needed for bathroom pipe replacement.",
    }
    headers = request_headers(technician_user, society, "tech-submit-estimate")

    first = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.PENDING_ESTIMATE_APPROVAL
    assert first.json()["state_version"] == started_version + 1
    assert first.json()["total_amount"] == "640.00"

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        estimate = TicketEstimate.objects.get(ticket=ticket)
        items = list(estimate.items.all())
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_ESTIMATE_SUBMITTED,
        )
        assert ticket.status == Ticket.Status.PENDING_ESTIMATE_APPROVAL
        assert estimate.subtotal_amount == 550
        assert estimate.tax_amount == 90
        assert estimate.total_amount == 640
        assert estimate.status == TicketEstimate.Status.SUBMITTED
        assert len(items) == 2
        assert event.ticket_version == ticket.state_version
        assert event.actor_id == technician_user.id
        assert event.actor_persona == "technician"


def test_vendor_worker_submits_estimate(client):
    society = Society.objects.create(registration_code="NIV-VEND-EST")
    unit = create_unit(society=society, code="A", door_number="801")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876670001",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876670002",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    dispatcher = User.objects.create_user(phone="+919876670003")
    worker = User.objects.create_user(phone="+919876670004")
    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name="Apex Electricals",
            normalized_company_name="apex electricals",
            contact_person="Manoj Kumar",
            phone_number="+919876670005",
        )
        contract = VendorContract.objects.create(
            society=society,
            vendor=vendor,
            starts_on=timezone.localdate() - timedelta(days=1),
            ends_on=timezone.localdate() + timedelta(days=30),
            max_active_tickets=5,
        )
        VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=dispatcher,
            role=VendorStaffMembership.Role.DISPATCHER,
        )
        worker_membership = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=worker,
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
        key="vendor-est-submit",
    )
    assigned = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-vendor/",
        {
            "expected_version": submitted["state_version"],
            "vendor_contract_id": str(contract.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "vendor-est-assign"),
    )
    allocated = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/allocate-vendor-worker/",
        {
            "expected_version": assigned.json()["state_version"],
            "staff_membership_id": str(worker_membership.id),
        },
        content_type="application/json",
        **request_headers(dispatcher, society, "vendor-est-allocate"),
    )
    accepted = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/accept-vendor-worker/",
        {"expected_version": allocated.json()["state_version"]},
        content_type="application/json",
        **request_headers(worker, society, "vendor-est-accept"),
    )
    started = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/start/",
        {"expected_version": accepted.json()["state_version"]},
        content_type="application/json",
        **request_headers(worker, society, "vendor-est-start"),
    )

    endpoint = f"/api/v1/service-tickets/{submitted['id']}/submit-estimate/"
    payload = {
        "expected_version": started.json()["state_version"],
        "items": [
            {"description": "Copper wire spool 50m", "quantity": 1, "unit_cost": 1200},
        ],
        "notes": "Electrical rewiring required.",
    }
    headers = request_headers(worker, society, "vendor-worker-submit-estimate")

    res = client.post(endpoint, payload, content_type="application/json", **headers)
    assert res.status_code == 200, res.json()
    assert res.json()["status"] == Ticket.Status.PENDING_ESTIMATE_APPROVAL
    assert res.json()["total_amount"] == "1200.00"


def test_resident_approves_resident_unit_estimate(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-APP-EST",
            phone_offset=5600,
        )
    )
    resident = User.objects.get(phone="+919876545600")
    with transaction.atomic():
        set_local_society_id(society.id)
        occupancy = UnitOccupancy.objects.get(society=society, user=resident)
        occupancy.can_approve_costs = True
        occupancy.save(update_fields=["can_approve_costs"])
    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "app-est-accept"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "app-est-start"),
    )
    est_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/submit-estimate/",
        {
            "expected_version": start_res.json()["state_version"],
            "items": [{"description": "Mixer tap cartridge", "quantity": 1, "unit_cost": 450}],
            "notes": "Cartridge replacement",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "app-est-sub"),
    )
    pending_version = est_res.json()["state_version"]

    endpoint = f"/api/v1/service-tickets/{offered['id']}/approve-estimate/"
    payload = {
        "expected_version": pending_version,
        "notes": "Approved for replacement.",
    }
    headers = request_headers(resident, society, "resident-approve-estimate")

    first = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.IN_PROGRESS
    assert first.json()["state_version"] == pending_version + 1

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        estimate = TicketEstimate.objects.get(ticket=ticket)
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_ESTIMATE_APPROVED,
        )
        assert ticket.status == Ticket.Status.IN_PROGRESS
        assert estimate.status == TicketEstimate.Status.APPROVED
        assert estimate.decided_by_id == resident.id
        assert event.actor_id == resident.id
        assert event.actor_persona == "resident"


def test_facility_manager_approves_society_estimate(client):
    society = Society.objects.create(registration_code="NIV-SOC-EST")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876680001",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876680002",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    technician_user = User.objects.create_user(phone="+919876680003")
    with transaction.atomic():
        set_local_society_id(society.id)
        technician = TechnicianProfile.objects.create(
            society=society,
            user=technician_user,
            max_active_tickets=5,
        )
        common_area = CommonArea.objects.create(
            society=society,
            name="Clubhouse Pool",
        )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
        cost_responsibility=TicketCategory.CostResponsibility.SOCIETY,
    )
    submitted = submit_service_ticket(
        client=client,
        society=society,
        actor=facility_manager,
        category=category,
        subcategory=subcategory,
        unit=unit,
        key="soc-est-submit",
    )
    assigned = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-in-house/",
        {
            "expected_version": submitted["state_version"],
            "technician_id": str(technician.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "soc-est-assign"),
    )
    accepted = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/accept/",
        {"expected_version": assigned.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "soc-est-accept"),
    )
    started = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/start/",
        {"expected_version": accepted.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "soc-est-start"),
    )
    est = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/submit-estimate/",
        {
            "expected_version": started.json()["state_version"],
            "items": [{"description": "Pool filter cartridge", "quantity": 1, "unit_cost": 3500}],
            "notes": "Pool pump maintenance",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "soc-est-submit-est"),
    )

    # FM approves society-responsibility estimate
    approve_res = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/approve-estimate/",
        {
            "expected_version": est.json()["state_version"],
            "notes": "FM approved society cost.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "fm-approve-society-estimate"),
    )
    assert approve_res.status_code == 200, approve_res.json()
    assert approve_res.json()["status"] == Ticket.Status.IN_PROGRESS


def test_service_ticket_estimates_read_endpoint(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-READ-EST",
            phone_offset=5650,
        )
    )
    resident = User.objects.get(phone="+919876545650")
    with transaction.atomic():
        set_local_society_id(society.id)
        occupancy = UnitOccupancy.objects.get(society=society, user=resident)
        occupancy.can_approve_costs = True
        occupancy.save(update_fields=["can_approve_costs"])

    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "read-est-accept"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "read-est-start"),
    )
    est_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/submit-estimate/",
        {
            "expected_version": start_res.json()["state_version"],
            "items": [
                {"description": "Copper Pipe 15mm", "quantity": 3, "unit_cost": 200},
                {"description": "Sealant Ring", "quantity": 2, "unit_cost": 75},
            ],
            "tax_amount": 135,
            "notes": "Materials needed for pipe repair.",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "read-est-sub"),
    )
    assert est_res.status_code == 200, est_res.json()

    read_url = f"/api/v1/service-tickets/{offered['id']}/estimates/"

    # 1. Resident reads estimates
    res_headers = request_headers(resident, society, "res-read-est")
    res_get = client.get(read_url, **res_headers)
    assert res_get.status_code == 200, res_get.json()
    data = res_get.json()
    assert len(data) == 1
    estimate = data[0]
    assert estimate["status"] == "SUBMITTED"
    assert estimate["cost_responsibility"] == "RESIDENT_UNIT"
    assert estimate["currency"] == "INR"
    assert Decimal(str(estimate["subtotal_amount"])) == Decimal("750.00")
    assert Decimal(str(estimate["tax_amount"])) == Decimal("135.00")
    assert Decimal(str(estimate["total_amount"])) == Decimal("885.00")
    assert estimate["notes"] == "Materials needed for pipe repair."
    assert len(estimate["items"]) == 2
    assert estimate["items"][0]["description"] == "Copper Pipe 15mm"
    assert Decimal(str(estimate["items"][0]["quantity"])) == Decimal("3.00")
    assert Decimal(str(estimate["items"][0]["unit_cost"])) == Decimal("200.00")
    assert Decimal(str(estimate["items"][0]["total_cost"])) == Decimal("600.00")
    assert estimate["items"][1]["description"] == "Sealant Ring"
    assert estimate["can_decide"] is True

    # 2. Facility Manager reads estimates (for RESIDENT_UNIT, FM can view but cannot decide)
    fm_headers = request_headers(facility_manager, society, "fm-read-est")
    fm_get = client.get(read_url, **fm_headers)
    assert fm_get.status_code == 200, fm_get.json()
    assert fm_get.json()[0]["can_decide"] is False

    # 3. Technician reads estimates
    tech_headers = request_headers(technician_user, society, "tech-read-est")
    tech_get = client.get(read_url, **tech_headers)
    assert tech_get.status_code == 200, tech_get.json()
    assert tech_get.json()[0]["can_decide"] is False

    # 4. Another resident from a different unit cannot access
    other_unit = create_unit(society=society, code="B", door_number="999")
    other_resident = create_resident(society=society, unit=other_unit, phone="+919876549999")
    other_headers = request_headers(other_resident, society, "other-read-est")
    other_get = client.get(read_url, **other_headers)
    assert other_get.status_code == 403, other_get.json()


def test_resident_rejects_estimate_escalates_to_supervisor_triage(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-REJ-EST",
            phone_offset=5700,
        )
    )
    resident = User.objects.get(phone="+919876545700")
    with transaction.atomic():
        set_local_society_id(society.id)
        occupancy = UnitOccupancy.objects.get(society=society, user=resident)
        occupancy.can_approve_costs = True
        occupancy.save(update_fields=["can_approve_costs"])
    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "rej-est-accept"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "rej-est-start"),
    )
    est_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/submit-estimate/",
        {
            "expected_version": start_res.json()["state_version"],
            "items": [{"description": "High-end water heater", "quantity": 1, "unit_cost": 15000}],
            "notes": "Replacement heater",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "rej-est-sub"),
    )
    pending_version = est_res.json()["state_version"]

    endpoint = f"/api/v1/service-tickets/{offered['id']}/reject-estimate/"
    payload = {
        "expected_version": pending_version,
        "reason": "Cost is above my budget, please provide a cheaper alternative.",
    }
    headers = request_headers(resident, society, "resident-reject-estimate")

    first = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.SUPERVISOR_TRIAGE
    assert first.json()["state_version"] == pending_version + 1

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        estimate = TicketEstimate.objects.get(ticket=ticket)
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_ESTIMATE_REJECTED,
        )
        assert ticket.status == Ticket.Status.SUPERVISOR_TRIAGE
        assert estimate.status == TicketEstimate.Status.REJECTED
        assert estimate.decision_reason == payload["reason"]
        assert event.actor_id == resident.id
        assert event.actor_persona == "resident"
        assignment = TicketAssignment.objects.get(ticket=ticket)
        technician.refresh_from_db()
        assert assignment.state == TicketAssignment.State.ENDED
        assert technician.current_active_tickets_count == 0

    reassignment = client.post(
        f"/api/v1/service-tickets/{offered['id']}/reassign-triage/",
        {
            "expected_version": first.json()["state_version"],
            "target_type": TicketAssignment.TargetType.IN_HOUSE,
            "technician_id": str(technician.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "reject-estimate-reassign"),
    )
    assert reassignment.status_code == 200, reassignment.json()

    with transaction.atomic():
        set_local_society_id(society.id)
        reassigned = TicketAssignment.objects.get(id=reassignment.json()["assignment_id"])
        technician.refresh_from_db()
        assert reassigned.state == TicketAssignment.State.OFFERED
        assert reassigned.id != assignment.id
        assert technician.current_active_tickets_count == 1


def test_worker_withdraws_estimate_returns_to_in_progress(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-WDR-EST",
            phone_offset=5800,
        )
    )
    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "wdr-est-accept"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "wdr-est-start"),
    )
    est_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/submit-estimate/",
        {
            "expected_version": start_res.json()["state_version"],
            "items": [{"description": "Spare washer set", "quantity": 1, "unit_cost": 200}],
            "notes": "Washer replacement",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "wdr-est-sub"),
    )
    pending_version = est_res.json()["state_version"]

    endpoint = f"/api/v1/service-tickets/{offered['id']}/withdraw-estimate/"
    payload = {
        "expected_version": pending_version,
        "reason": "Found spare parts in inventory, no purchase required.",
    }
    headers = request_headers(technician_user, society, "tech-withdraw-estimate")

    first = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.IN_PROGRESS
    assert first.json()["state_version"] == pending_version + 1

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        estimate = TicketEstimate.objects.get(ticket=ticket)
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_ESTIMATE_WITHDRAWN,
        )
        assert ticket.status == Ticket.Status.IN_PROGRESS
        assert estimate.status == TicketEstimate.Status.WITHDRAWN
        assert event.actor_id == technician_user.id
        assert event.actor_persona == "technician"


def test_unauthorized_resident_cannot_approve_other_unit_estimate(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-UNAUTH-EST",
            phone_offset=5900,
        )
    )
    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "unauth-est-accept"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "unauth-est-start"),
    )
    est_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/submit-estimate/",
        {
            "expected_version": start_res.json()["state_version"],
            "items": [{"description": "Part", "quantity": 1, "unit_cost": 100}],
            "notes": "Cost estimate",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "unauth-est-sub"),
    )
    pending_version = est_res.json()["state_version"]

    # Another resident from another unit
    unit_b = create_unit(society=society, code="B", door_number="902")
    other_resident = create_resident(society=society, unit=unit_b, phone="+919876690099")

    denied = client.post(
        f"/api/v1/service-tickets/{offered['id']}/approve-estimate/",
        {
            "expected_version": pending_version,
            "notes": "Unauthorized approval attempt.",
        },
        content_type="application/json",
        **request_headers(other_resident, society, "other-resident-approve-attempt"),
    )
    assert denied.status_code in {403, 404}


def test_no_charge_category_rejects_estimate_submission(client):
    society = Society.objects.create(registration_code="NIV-NO-CHG")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(
        society=society,
        unit=unit,
        phone="+919876700001",
    )
    facility_manager = create_staff(
        society=society,
        phone="+919876700002",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    technician_user = User.objects.create_user(phone="+919876700003")
    with transaction.atomic():
        set_local_society_id(society.id)
        technician = TechnicianProfile.objects.create(
            society=society,
            user=technician_user,
            max_active_tickets=5,
        )
        common_area = CommonArea.objects.create(
            society=society,
            name="Main Lobby",
        )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.SERVICE,
        cost_responsibility=TicketCategory.CostResponsibility.NO_CHARGE,
    )
    submitted = submit_service_ticket(
        client=client,
        society=society,
        actor=facility_manager,
        category=category,
        subcategory=subcategory,
        unit=unit,
        key="nochg-est-submit",
    )
    assigned = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/assign-in-house/",
        {
            "expected_version": submitted["state_version"],
            "technician_id": str(technician.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "nochg-est-assign"),
    )
    accepted = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/accept/",
        {"expected_version": assigned.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "nochg-est-accept"),
    )
    started = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/start/",
        {"expected_version": accepted.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "nochg-est-start"),
    )

    est_res = client.post(
        f"/api/v1/service-tickets/{submitted['id']}/submit-estimate/",
        {
            "expected_version": started.json()["state_version"],
            "items": [{"description": "Light bulb", "quantity": 1, "unit_cost": 50}],
            "notes": "Attempting estimate on no-charge ticket",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "nochg-est-sub"),
    )
    assert est_res.status_code == 409
    assert est_res.json()["code"] == "ESTIMATES_NOT_PERMITTED"


def test_ticket_cancellation_cancels_pending_estimate(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-CAN-EST",
            phone_offset=6000,
        )
    )
    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "can-est-accept"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "can-est-start"),
    )
    est_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/submit-estimate/",
        {
            "expected_version": start_res.json()["state_version"],
            "items": [{"description": "Valve", "quantity": 1, "unit_cost": 500}],
            "notes": "Cost estimate",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "can-est-sub"),
    )
    pending_version = est_res.json()["state_version"]

    # FM cancels the ticket while estimate is pending
    cancel_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/cancel/",
        {
            "expected_version": pending_version,
            "reason": "Facility manager cancelled project.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "fm-cancel-ticket-with-estimate"),
    )
    assert cancel_res.status_code == 200, cancel_res.json()
    assert cancel_res.json()["status"] == Ticket.Status.CANCELLED

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        estimate = TicketEstimate.objects.get(ticket=ticket)
        technician.refresh_from_db()
        assert ticket.status == Ticket.Status.CANCELLED
        assert estimate.status == TicketEstimate.Status.CANCELLED
        assert technician.current_active_tickets_count == 0


def test_stale_version_estimate_operations_rejected(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-STL-EST",
            phone_offset=6100,
        )
    )
    resident = User.objects.get(phone="+919876546100")
    with transaction.atomic():
        set_local_society_id(society.id)
        occupancy = UnitOccupancy.objects.get(society=society, user=resident)
        occupancy.can_approve_costs = True
        occupancy.save(update_fields=["can_approve_costs"])
    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "stl-est-accept"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "stl-est-start"),
    )

    # Stale submit
    stale_sub = client.post(
        f"/api/v1/service-tickets/{offered['id']}/submit-estimate/",
        {
            "expected_version": start_res.json()["state_version"] - 1,
            "items": [{"description": "Item", "quantity": 1, "unit_cost": 100}],
        },
        content_type="application/json",
        **request_headers(technician_user, society, "stale-sub-est"),
    )
    assert stale_sub.status_code == 409
    assert stale_sub.json()["code"] == "TICKET_VERSION_CONFLICT"

    # Valid submit
    valid_sub = client.post(
        f"/api/v1/service-tickets/{offered['id']}/submit-estimate/",
        {
            "expected_version": start_res.json()["state_version"],
            "items": [{"description": "Item", "quantity": 1, "unit_cost": 100}],
        },
        content_type="application/json",
        **request_headers(technician_user, society, "valid-sub-est"),
    )
    assert valid_sub.status_code == 200, valid_sub.json()
    pending_version = valid_sub.json()["state_version"]

    # Stale approve
    stale_app = client.post(
        f"/api/v1/service-tickets/{offered['id']}/approve-estimate/",
        {
            "expected_version": pending_version - 1,
        },
        content_type="application/json",
        **request_headers(resident, society, "stale-app-est"),
    )
    assert stale_app.status_code == 409
    assert stale_app.json()["code"] == "TICKET_VERSION_CONFLICT"


def _create_resolved_service_ticket(*, client, registration_code, phone_offset):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code=registration_code,
            phone_offset=phone_offset,
        )
    )
    resident = User.objects.get(phone=f"+91987654{phone_offset:04d}")
    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, f"res-accept-{phone_offset}"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, f"res-start-{phone_offset}"),
    )
    otp_code = f"{phone_offset:06d}"
    with patch(
        "apps.tickets.services.secrets.randbelow",
        return_value=int(otp_code),
    ):
        req_res = client.post(
            f"/api/v1/service-tickets/{offered['id']}/request-completion/",
            {
                "expected_version": start_res.json()["state_version"],
                "work_notes": "Completed plumbing work successfully.",
            },
            content_type="application/json",
            **request_headers(technician_user, society, f"res-req-comp-{phone_offset}"),
        )

    ver_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/verify-completion/",
        {
            "expected_version": req_res.json()["state_version"],
            "otp": otp_code,
        },
        content_type="application/json",
        **request_headers(resident, society, f"res-ver-comp-{phone_offset}"),
    )
    assert ver_res.status_code == 200, ver_res.json()
    return society, facility_manager, resident, ver_res.json()


def test_resident_reopens_resolved_service_ticket(client):
    society, facility_manager, resident, resolved_ticket = (
        _create_resolved_service_ticket(
            client=client,
            registration_code="NIV-REOPEN-RES",
            phone_offset=6200,
        )
    )
    resolved_version = resolved_ticket["state_version"]

    endpoint = f"/api/v1/service-tickets/{resolved_ticket['id']}/reopen/"
    payload = {
        "expected_version": resolved_version,
        "reason": "Water is still dripping slowly under the sink.",
    }
    headers = request_headers(resident, society, "resident-reopen-ticket")

    first = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.SUPERVISOR_TRIAGE
    assert first.json()["state_version"] == resolved_version + 1

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=resolved_ticket["id"])
        cycles = list(SLACycle.objects.filter(ticket=ticket).order_by("cycle_number"))
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_REOPENED,
        )
        assert ticket.status == Ticket.Status.SUPERVISOR_TRIAGE
        assert len(cycles) == 2
        assert cycles[0].outcome == SLACycle.Outcome.RESOLVED
        assert cycles[1].cycle_number == 2
        assert cycles[1].ended_at is None
        assert cycles[1].resolution_deadline is not None
        assert event.ticket_version == ticket.state_version
        assert event.actor_id == resident.id
        assert event.actor_persona == "resident"
        assert event.reason == payload["reason"]


def test_facility_manager_reopens_closed_service_ticket(client):
    society, facility_manager, resident, resolved_ticket = (
        _create_resolved_service_ticket(
            client=client,
            registration_code="NIV-REOPEN-FM",
            phone_offset=6300,
        )
    )
    close_res = client.post(
        f"/api/v1/service-tickets/{resolved_ticket['id']}/close/",
        {
            "expected_version": resolved_ticket["state_version"],
            "reason": "Administrative closing after 7 days.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "fm-close-ticket"),
    )
    assert close_res.status_code == 200, close_res.json()
    closed_version = close_res.json()["state_version"]

    reopen_res = client.post(
        f"/api/v1/service-tickets/{resolved_ticket['id']}/reopen/",
        {
            "expected_version": closed_version,
            "reason": "Resident complained via office front-desk.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "fm-reopen-closed-ticket"),
    )
    assert reopen_res.status_code == 200, reopen_res.json()
    assert reopen_res.json()["status"] == Ticket.Status.SUPERVISOR_TRIAGE
    assert reopen_res.json()["state_version"] == closed_version + 1


def test_facility_manager_closes_resolved_ticket(client):
    society, facility_manager, resident, resolved_ticket = (
        _create_resolved_service_ticket(
            client=client,
            registration_code="NIV-CLOSE-FM",
            phone_offset=6400,
        )
    )
    resolved_version = resolved_ticket["state_version"]

    endpoint = f"/api/v1/service-tickets/{resolved_ticket['id']}/close/"
    payload = {
        "expected_version": resolved_version,
        "reason": "Auto-close window elapsed.",
    }
    headers = request_headers(facility_manager, society, "fm-close-resolved")

    first = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.CLOSED
    assert first.json()["state_version"] == resolved_version + 1

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=resolved_ticket["id"])
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_CLOSED,
        )
        assert ticket.status == Ticket.Status.CLOSED
        assert event.ticket_version == ticket.state_version
        assert event.actor_id == facility_manager.id
        assert event.actor_persona == "staff"


def test_resident_closes_resolved_ticket(client):
    society, facility_manager, resident, resolved_ticket = (
        _create_resolved_service_ticket(
            client=client,
            registration_code="NIV-CLOSE-RES",
            phone_offset=6500,
        )
    )
    res = client.post(
        f"/api/v1/service-tickets/{resolved_ticket['id']}/close/",
        {
            "expected_version": resolved_ticket["state_version"],
            "reason": "Resident satisfied with work.",
        },
        content_type="application/json",
        **request_headers(resident, society, "resident-close-resolved"),
    )
    assert res.status_code == 200, res.json()
    assert res.json()["status"] == Ticket.Status.CLOSED


def test_governance_ticket_close_and_reopen_transitions_to_under_review(client):
    society = Society.objects.create(registration_code="NIV-GOV-REOPEN")
    unit = create_unit(society=society, code="A", door_number="101")
    resident = create_resident(society=society, unit=unit, phone="+919876710001")
    facility_manager = create_staff(
        society=society,
        phone="+919876710002",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.GOVERNANCE,
    )
    create_sla_binding(
        society=society,
        category=category,
        priority=subcategory.default_priority,
    )
    create_business_calendar(society=society)

    draft = client.post(
        "/api/v1/governance-tickets/",
        ticket_payload(category=category, subcategory=subcategory, title="Balcony safety net policy"),
        content_type="application/json",
        **request_headers(resident, society, "gov-draft"),
    ).json()
    submitted = client.post(
        f"/api/v1/governance-tickets/{draft['id']}/submit/",
        {"expected_version": 1},
        content_type="application/json",
        **request_headers(resident, society, "gov-submit"),
    ).json()
    reviewed = client.post(
        f"/api/v1/governance-tickets/{submitted['id']}/begin-review/",
        {"expected_version": submitted["state_version"]},
        content_type="application/json",
        **request_headers(facility_manager, society, "gov-review"),
    ).json()
    action = client.post(
        f"/api/v1/governance-tickets/{submitted['id']}/record-action/",
        {
            "expected_version": reviewed["state_version"],
            "summary": "Committee reviewed guideline draft.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "gov-action"),
    ).json()

    # Manually transition governance ticket to RESOLVED for testing reopen
    with transaction.atomic():
        set_local_society_id(society.id)
        gov_ticket = Ticket.objects.get(id=submitted["id"])
        gov_ticket.status = Ticket.Status.RESOLVED
        gov_ticket.state_version += 1
        gov_ticket.save(update_fields=("status", "state_version"))
        resolved_version = gov_ticket.state_version

    close_res = client.post(
        f"/api/v1/governance-tickets/{submitted['id']}/close/",
        {
            "expected_version": resolved_version,
            "reason": "Administrative closure after recorded action.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "gov-close"),
    )
    assert close_res.status_code == 200, close_res.json()
    assert close_res.json()["status"] == Ticket.Status.CLOSED

    reopen_res = client.post(
        f"/api/v1/governance-tickets/{submitted['id']}/reopen/",
        {
            "expected_version": close_res.json()["state_version"],
            "reason": "New guidelines require further review.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "gov-reopen"),
    )
    assert reopen_res.status_code == 200, reopen_res.json()
    assert reopen_res.json()["status"] == Ticket.Status.UNDER_REVIEW


def test_unauthorized_actor_cannot_reopen_ticket(client):
    society, facility_manager, resident, resolved_ticket = (
        _create_resolved_service_ticket(
            client=client,
            registration_code="NIV-UNAUTH-REOPEN",
            phone_offset=6600,
        )
    )
    unit_b = create_unit(society=society, code="B", door_number="202")
    other_resident = create_resident(society=society, unit=unit_b, phone="+919876720099")

    denied = client.post(
        f"/api/v1/service-tickets/{resolved_ticket['id']}/reopen/",
        {
            "expected_version": resolved_ticket["state_version"],
            "reason": "Unauthorized attempt.",
        },
        content_type="application/json",
        **request_headers(other_resident, society, "unauth-reopen-attempt"),
    )
    assert denied.status_code in {403, 404}


def test_cannot_reopen_in_progress_or_submitted_ticket(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-INVALID-REOPEN",
            phone_offset=6700,
        )
    )
    resident = User.objects.get(phone="+919876546700")

    conflict = client.post(
        f"/api/v1/service-tickets/{offered['id']}/reopen/",
        {
            "expected_version": offered["state_version"],
            "reason": "Attempting reopen on assigned ticket.",
        },
        content_type="application/json",
        **request_headers(resident, society, "invalid-reopen-attempt"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "TICKET_STATE_CONFLICT"


def test_stale_version_reopen_close_rejected(client):
    society, facility_manager, resident, resolved_ticket = (
        _create_resolved_service_ticket(
            client=client,
            registration_code="NIV-STALE-REOPEN",
            phone_offset=6800,
        )
    )
    stale_reopen = client.post(
        f"/api/v1/service-tickets/{resolved_ticket['id']}/reopen/",
        {
            "expected_version": resolved_ticket["state_version"] - 1,
            "reason": "Stale version reopen attempt.",
        },
        content_type="application/json",
        **request_headers(resident, society, "stale-reopen"),
    )
    assert stale_reopen.status_code == 409
    assert stale_reopen.json()["code"] == "TICKET_VERSION_CONFLICT"

    stale_close = client.post(
        f"/api/v1/service-tickets/{resolved_ticket['id']}/close/",
        {
            "expected_version": resolved_ticket["state_version"] - 1,
            "reason": "Stale version close attempt.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "stale-close"),
    )
    assert stale_close.status_code == 409
    assert stale_close.json()["code"] == "TICKET_VERSION_CONFLICT"


def _create_triage_service_ticket(*, client, registration_code, phone_offset):
    society, facility_manager, resident, resolved = _create_resolved_service_ticket(
        client=client,
        registration_code=registration_code,
        phone_offset=phone_offset,
    )
    reopen_res = client.post(
        f"/api/v1/service-tickets/{resolved['id']}/reopen/",
        {
            "expected_version": resolved["state_version"],
            "reason": "Work needs further attention.",
        },
        content_type="application/json",
        **request_headers(resident, society, f"triage-reopen-{phone_offset}"),
    )
    assert reopen_res.status_code == 200, reopen_res.json()
    return society, facility_manager, resident, reopen_res.json()


def test_facility_manager_reassigns_triage_ticket_to_in_house_technician(client):
    society, facility_manager, resident, triage_ticket = (
        _create_triage_service_ticket(
            client=client,
            registration_code="NIV-TR1",
            phone_offset=7100,
        )
    )
    triage_version = triage_ticket["state_version"]

    tech_user_2 = User.objects.create_user(phone="+919876547199")
    with transaction.atomic():
        set_local_society_id(society.id)
        tech_2 = TechnicianProfile.objects.create(
            society=society,
            user=tech_user_2,
            is_active=True,
        )

    endpoint = f"/api/v1/service-tickets/{triage_ticket['id']}/reassign-triage/"
    payload = {
        "expected_version": triage_version,
        "target_type": TicketAssignment.TargetType.IN_HOUSE,
        "technician_id": str(tech_2.id),
    }
    headers = request_headers(facility_manager, society, "fm-reassign-ih")

    first = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.ASSIGNED
    assert first.json()["state_version"] == triage_version + 1

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=triage_ticket["id"])
        tech_2.refresh_from_db()
        assignment = TicketAssignment.objects.get(id=first.json()["assignment_id"])
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_TRIAGE_REASSIGNED,
        )
        assert ticket.status == Ticket.Status.ASSIGNED
        assert assignment.target_type == TicketAssignment.TargetType.IN_HOUSE
        assert assignment.technician_id == tech_2.id
        assert assignment.state == TicketAssignment.State.OFFERED
        assert tech_2.current_active_tickets_count == 1
        assert event.ticket_version == ticket.state_version
        assert event.actor_id == facility_manager.id
        assert event.actor_persona == "staff"


def test_facility_manager_reassigns_triage_ticket_to_vendor(client):
    society, facility_manager, resident, triage_ticket = (
        _create_triage_service_ticket(
            client=client,
            registration_code="NIV-TR2",
            phone_offset=7200,
        )
    )
    triage_version = triage_ticket["state_version"]

    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name="Apex Facility Services",
            contact_person="Apex Contact",
            phone_number="+919876547288",
            email="apex@example.com",
        )
        contract = VendorContract.objects.create(
            society=society,
            vendor=vendor,
            starts_on=timezone.localdate(),
            ends_on=timezone.localdate() + timedelta(days=365),
        )

    endpoint = f"/api/v1/service-tickets/{triage_ticket['id']}/reassign-triage/"
    payload = {
        "expected_version": triage_version,
        "target_type": TicketAssignment.TargetType.VENDOR,
        "vendor_contract_id": str(contract.id),
    }
    headers = request_headers(facility_manager, society, "fm-reassign-vend")

    res = client.post(endpoint, payload, content_type="application/json", **headers)
    assert res.status_code == 200, res.json()
    assert res.json()["status"] == Ticket.Status.ASSIGNED

    with transaction.atomic():
        set_local_society_id(society.id)
        contract.refresh_from_db()
        assert contract.current_active_tickets_count == 1


def test_triage_reassignment_uses_business_calendar_deadline(client, monkeypatch):
    society, facility_manager, _, triage_ticket = _create_triage_service_ticket(
        client=client,
        registration_code="NIV-TR-CALENDAR",
        phone_offset=7250,
    )
    technician_user = User.objects.create_user(
        phone=f"+919{uuid.uuid4().int % 1_000_000_000:09d}"
    )
    with transaction.atomic():
        set_local_society_id(society.id)
        technician = TechnicianProfile.objects.create(
            society=society,
            user=technician_user,
            is_active=True,
        )
        ticket = Ticket.objects.get(id=triage_ticket["id"])
        active_cycle = SLACycle.objects.get(ticket=ticket, ended_at__isnull=True)
        active_cycle.ended_at = timezone.now()
        active_cycle.outcome = SLACycle.Outcome.CANCELLED
        active_cycle.save(update_fields=("ended_at", "outcome"))

    calendar_deadline = timezone.now() + timedelta(days=3)
    calculator_calls = []

    def calculate_deadline(**kwargs):
        calculator_calls.append(kwargs)
        return calendar_deadline

    monkeypatch.setattr(
        "apps.tickets.services.business_calendar_deadline_calculator",
        calculate_deadline,
    )
    response = client.post(
        f"/api/v1/service-tickets/{triage_ticket['id']}/reassign-triage/",
        {
            "expected_version": triage_ticket["state_version"],
            "target_type": TicketAssignment.TargetType.IN_HOUSE,
            "technician_id": str(technician.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "fm-reassign-calendar"),
    )

    assert response.status_code == 200, response.json()
    assert len(calculator_calls) == 1
    assert calculator_calls[0]["duration"] == timedelta(hours=4)
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=triage_ticket["id"])
        cycle = SLACycle.objects.get(ticket=ticket, ended_at__isnull=True)

    assert cycle.cycle_type == SLACycle.CycleType.REOPEN
    assert cycle.resolution_deadline == calendar_deadline


def test_facility_manager_override_cannot_resume_rejected_estimate_without_assignment(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-OV1",
            phone_offset=7300,
        )
    )
    resident = User.objects.get(phone="+919876547300")
    with transaction.atomic():
        set_local_society_id(society.id)
        occupancy = UnitOccupancy.objects.get(society=society, user=resident)
        occupancy.can_approve_costs = True
        occupancy.save(update_fields=["can_approve_costs"])
    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "or-accept"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "or-start"),
    )
    submit_est_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/submit-estimate/",
        {
            "expected_version": start_res.json()["state_version"],
            "items": [{"description": "Valve Replacement", "quantity": 1, "unit_cost": 250.00}],
        },
        content_type="application/json",
        **request_headers(technician_user, society, "or-sub-est"),
    )
    reject_est_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/reject-estimate/",
        {
            "expected_version": submit_est_res.json()["state_version"],
            "reason": "Cost is too high for simple valve.",
        },
        content_type="application/json",
        **request_headers(resident, society, "or-rej-est"),
    )
    assert reject_est_res.status_code == 200
    assert reject_est_res.json()["status"] == Ticket.Status.SUPERVISOR_TRIAGE
    triage_version = reject_est_res.json()["state_version"]

    endpoint = f"/api/v1/service-tickets/{offered['id']}/override-resume/"
    payload = {
        "expected_version": triage_version,
        "reason": "Resident agreed to standard society parts coverage.",
    }
    headers = request_headers(
        facility_manager,
        society,
        "fm-override-resume",
        step_up=True,
    )

    conflict = client.post(endpoint, payload, content_type="application/json", **headers)

    assert conflict.status_code == 409
    assert conflict.json()["code"] == "TICKET_STATE_CONFLICT"


def test_override_resume_rejected_if_no_active_assignment(client):
    society, facility_manager, resident, triage_ticket = (
        _create_triage_service_ticket(
            client=client,
            registration_code="NIV-OV2",
            phone_offset=7400,
        )
    )
    conflict = client.post(
        f"/api/v1/service-tickets/{triage_ticket['id']}/override-resume/",
        {
            "expected_version": triage_ticket["state_version"],
            "reason": "Attempting override resume without active assignment.",
        },
        content_type="application/json",
        **request_headers(
            facility_manager,
            society,
            "no-assign-resume",
            step_up=True,
        ),
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "TICKET_STATE_CONFLICT"


def test_facility_manager_supervisor_completion_override(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-SC1",
            phone_offset=7500,
        )
    )
    accept_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/accept/",
        {"expected_version": offered["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "sco-accept"),
    )
    start_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/start/",
        {"expected_version": accept_res.json()["state_version"]},
        content_type="application/json",
        **request_headers(technician_user, society, "sco-start"),
    )
    req_res = client.post(
        f"/api/v1/service-tickets/{offered['id']}/request-completion/",
        {
            "expected_version": start_res.json()["state_version"],
            "work_notes": "Plumbing repairs complete.",
        },
        content_type="application/json",
        **request_headers(technician_user, society, "sco-req-comp"),
    )
    assert req_res.status_code == 200
    pending_version = req_res.json()["state_version"]

    endpoint = f"/api/v1/service-tickets/{offered['id']}/supervisor-complete/"
    payload = {
        "expected_version": pending_version,
        "reason": "Resident travelling abroad and unreachable by SMS.",
        "proof_notes": "Resident confirmed satisfactory completion via email to management office.",
    }
    headers = request_headers(
        facility_manager,
        society,
        "fm-supervisor-complete",
        step_up=True,
    )

    first = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["status"] == Ticket.Status.RESOLVED
    assert first.json()["state_version"] == pending_version + 1

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=offered["id"])
        technician.refresh_from_db()
        challenge = TicketCompletionChallenge.objects.get(ticket=ticket)
        cycle = SLACycle.objects.filter(ticket=ticket).first()
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_RESOLVED_OVERRIDE,
        )
        assert ticket.status == Ticket.Status.RESOLVED
        assert challenge.consumed_at is not None
        assert technician.current_active_tickets_count == 0
        assert cycle.outcome == SLACycle.Outcome.RESOLVED
        assert event.ticket_version == ticket.state_version
        assert event.actor_id == facility_manager.id
        assert event.actor_persona == "staff"
        assert event.reason == payload["reason"]
        assert event.metadata["proof_notes"] == payload["proof_notes"]


def test_supervisor_overrides_require_fresh_step_up(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-SU-STEP-UP",
            phone_offset=7550,
        )
    )

    missing_step_up = client.post(
        f"/api/v1/service-tickets/{offered['id']}/override-resume/",
        {
            "expected_version": offered["state_version"],
            "reason": "Attempting supervisor resume without step-up authentication.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "missing-step-up-resume"),
    )
    stale_step_up = client.post(
        f"/api/v1/service-tickets/{offered['id']}/supervisor-complete/",
        {
            "expected_version": offered["state_version"],
            "reason": "Attempting supervisor completion with stale authentication.",
            "proof_notes": "Management reviewed the ticket.",
        },
        content_type="application/json",
        **request_headers(
            facility_manager,
            society,
            "stale-step-up-completion",
            step_up=True,
            step_up_at=timezone.now() - timedelta(minutes=6),
        ),
    )

    assert missing_step_up.status_code == 403
    assert stale_step_up.status_code == 403
    with transaction.atomic():
        set_local_society_id(society.id)
        assert (
            IdempotencyRecord.objects.filter(
                society=society,
                principal=facility_manager,
                idempotency_key__in={
                    "missing-step-up-resume",
                    "stale-step-up-completion",
                },
            ).exists()
            is False
        )


def test_unauthorized_actors_denied_supervisor_overrides(client):
    society, facility_manager, resident, triage_ticket = (
        _create_triage_service_ticket(
            client=client,
            registration_code="NIV-SU1",
            phone_offset=7600,
        )
    )
    triage_version = triage_ticket["state_version"]

    reassign_denied = client.post(
        f"/api/v1/service-tickets/{triage_ticket['id']}/reassign-triage/",
        {
            "expected_version": triage_version,
            "target_type": TicketAssignment.TargetType.IN_HOUSE,
            "technician_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **request_headers(resident, society, "resident-reassign-attempt"),
    )
    assert reassign_denied.status_code in {403, 404}

    resume_denied = client.post(
        f"/api/v1/service-tickets/{triage_ticket['id']}/override-resume/",
        {
            "expected_version": triage_version,
            "reason": "Resident attempting override resume.",
        },
        content_type="application/json",
        **request_headers(resident, society, "resident-resume-attempt"),
    )
    assert resume_denied.status_code in {403, 404}


def test_supervisor_overrides_invalid_source_state_conflict(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-SI1",
            phone_offset=7700,
        )
    )
    reassign_conflict = client.post(
        f"/api/v1/service-tickets/{offered['id']}/reassign-triage/",
        {
            "expected_version": offered["state_version"],
            "target_type": TicketAssignment.TargetType.IN_HOUSE,
            "technician_id": str(technician.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "invalid-reassign-state"),
    )
    assert reassign_conflict.status_code == 409
    assert reassign_conflict.json()["code"] == "TICKET_STATE_CONFLICT"

    resume_conflict = client.post(
        f"/api/v1/service-tickets/{offered['id']}/override-resume/",
        {
            "expected_version": offered["state_version"],
            "reason": "Attempting override on offered ticket.",
        },
        content_type="application/json",
        **request_headers(
            facility_manager,
            society,
            "invalid-resume-state",
            step_up=True,
        ),
    )
    assert resume_conflict.status_code == 409
    assert resume_conflict.json()["code"] == "TICKET_STATE_CONFLICT"

    complete_conflict = client.post(
        f"/api/v1/service-tickets/{offered['id']}/supervisor-complete/",
        {
            "expected_version": offered["state_version"],
            "reason": "Attempting supervisor complete on offered ticket.",
            "proof_notes": "Proof notes.",
        },
        content_type="application/json",
        **request_headers(
            facility_manager,
            society,
            "invalid-complete-state",
            step_up=True,
        ),
    )
    assert complete_conflict.status_code == 409
    assert complete_conflict.json()["code"] == "TICKET_STATE_CONFLICT"


def test_stale_version_supervisor_overrides_rejected(client):
    society, facility_manager, resident, triage_ticket = (
        _create_triage_service_ticket(
            client=client,
            registration_code="NIV-SS1",
            phone_offset=7800,
        )
    )
    stale_reassign = client.post(
        f"/api/v1/service-tickets/{triage_ticket['id']}/reassign-triage/",
        {
            "expected_version": triage_ticket["state_version"] - 1,
            "target_type": TicketAssignment.TargetType.IN_HOUSE,
            "technician_id": str(uuid.uuid4()),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "stale-reassign"),
    )
    assert stale_reassign.status_code == 409
    assert stale_reassign.json()["code"] == "TICKET_VERSION_CONFLICT"

    stale_resume = client.post(
        f"/api/v1/service-tickets/{triage_ticket['id']}/override-resume/",
        {
            "expected_version": triage_ticket["state_version"] - 1,
            "reason": "Stale resume attempt.",
        },
        content_type="application/json",
        **request_headers(
            facility_manager,
            society,
            "stale-resume",
            step_up=True,
        ),
    )
    assert stale_resume.status_code == 409
    assert stale_resume.json()["code"] == "TICKET_VERSION_CONFLICT"


def test_resident_submits_ticket_feedback_on_resolved_ticket(client):
    society, facility_manager, resident, resolved = _create_resolved_service_ticket(
        client=client,
        registration_code="NIV-FB1",
        phone_offset=8100,
    )
    resolved_version = resolved["state_version"]
    endpoint = f"/api/v1/service-tickets/{resolved['id']}/rate/"
    payload = {
        "expected_version": resolved_version,
        "overall_rating": 5,
        "timeliness_rating": 5,
        "quality_rating": 4,
        "technician_behavior_rating": 5,
        "tags": ["Punctual", "Clean Workmanship"],
        "comment": "Exceptional service, fixed immediately!",
    }
    headers = request_headers(resident, society, "resident-rate-ticket")

    first = client.post(endpoint, payload, content_type="application/json", **headers)
    replay = client.post(endpoint, payload, content_type="application/json", **headers)

    assert first.status_code == 200, first.json()
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["state_version"] == resolved_version + 1
    feedback_data = first.json()["feedback"]
    assert feedback_data["overall_rating"] == 5
    assert feedback_data["timeliness_rating"] == 5
    assert feedback_data["quality_rating"] == 4
    assert feedback_data["technician_behavior_rating"] == 5
    assert feedback_data["tags"] == ["Punctual", "Clean Workmanship"]
    assert feedback_data["comment"] == "Exceptional service, fixed immediately!"
    assert feedback_data["technician_id"] is not None

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=resolved["id"])
        fb = TicketFeedback.objects.get(ticket=ticket)
        event = TicketEvent.objects.get(
            ticket=ticket,
            event_type=TicketEvent.EventType.TICKET_RATED,
        )
        assert fb.society_id == society.id
        assert fb.resident_id == resident.id
        assert fb.overall_rating == 5
        assert fb.timeliness_rating == 5
        assert fb.quality_rating == 4
        assert fb.technician_behavior_rating == 5
        assert fb.tags == ["Punctual", "Clean Workmanship"]
        assert fb.technician_id is not None
        assert event.ticket_version == ticket.state_version
        assert event.actor_id == resident.id
        assert event.actor_persona == "resident"
        assert event.metadata["overall_rating"] == 5
        assert event.metadata["tags"] == ["Punctual", "Clean Workmanship"]

    detail_res = client.get(
        f"/api/v1/service-tickets/{resolved['id']}/feedback/",
        **request_headers(resident, society),
    )
    assert detail_res.status_code == 200
    assert detail_res.json()["overall_rating"] == 5
    assert detail_res.json()["tags"] == ["Punctual", "Clean Workmanship"]


def test_resident_submits_ticket_feedback_on_closed_ticket(client):
    society, facility_manager, resident, resolved = _create_resolved_service_ticket(
        client=client,
        registration_code="NIV-FB2",
        phone_offset=8200,
    )
    close_res = client.post(
        f"/api/v1/service-tickets/{resolved['id']}/close/",
        {"expected_version": resolved["state_version"]},
        content_type="application/json",
        **request_headers(resident, society, "close-before-rate"),
    )
    assert close_res.status_code == 200
    closed_ticket = close_res.json()

    rate_res = client.post(
        f"/api/v1/service-tickets/{closed_ticket['id']}/rate/",
        {
            "expected_version": closed_ticket["state_version"],
            "overall_rating": 4,
            "comment": "Good job after closure.",
        },
        content_type="application/json",
        **request_headers(resident, society, "rate-closed-ticket"),
    )
    assert rate_res.status_code == 200
    assert rate_res.json()["feedback"]["overall_rating"] == 4


def test_duplicate_feedback_rejected(client):
    society, facility_manager, resident, resolved = _create_resolved_service_ticket(
        client=client,
        registration_code="NIV-FB3",
        phone_offset=8300,
    )
    rate_res = client.post(
        f"/api/v1/service-tickets/{resolved['id']}/rate/",
        {
            "expected_version": resolved["state_version"],
            "overall_rating": 5,
        },
        content_type="application/json",
        **request_headers(resident, society, "rate-once"),
    )
    assert rate_res.status_code == 200
    version = rate_res.json()["state_version"]

    duplicate_rate = client.post(
        f"/api/v1/service-tickets/{resolved['id']}/rate/",
        {
            "expected_version": version,
            "overall_rating": 3,
        },
        content_type="application/json",
        **request_headers(resident, society, "rate-again-different-key"),
    )
    assert duplicate_rate.status_code == 409
    assert duplicate_rate.json()["code"] == "FEEDBACK_ALREADY_EXISTS"


def test_feedback_rejected_on_unresolved_ticket(client):
    society, facility_manager, technician_user, technician, offered = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-FB4",
            phone_offset=8400,
        )
    )
    resident = User.objects.get(phone="+919876548400")
    conflict = client.post(
        f"/api/v1/service-tickets/{offered['id']}/rate/",
        {
            "expected_version": offered["state_version"],
            "overall_rating": 5,
        },
        content_type="application/json",
        **request_headers(resident, society, "rate-offered-ticket"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "TICKET_STATE_CONFLICT"


def test_unauthorized_user_denied_feedback(client):
    society, facility_manager, resident, resolved = _create_resolved_service_ticket(
        client=client,
        registration_code="NIV-FB5",
        phone_offset=8500,
    )
    unit_b = create_unit(society=society, code="B", door_number="202")
    other_resident = create_resident(society=society, unit=unit_b, phone="+919876548599")

    denied = client.post(
        f"/api/v1/service-tickets/{resolved['id']}/rate/",
        {
            "expected_version": resolved["state_version"],
            "overall_rating": 5,
        },
        content_type="application/json",
        **request_headers(other_resident, society, "other-resident-rate"),
    )
    assert denied.status_code in {403, 404}


def test_stale_version_feedback_rejected(client):
    society, facility_manager, resident, resolved = _create_resolved_service_ticket(
        client=client,
        registration_code="NIV-FB6",
        phone_offset=8600,
    )
    stale = client.post(
        f"/api/v1/service-tickets/{resolved['id']}/rate/",
        {
            "expected_version": resolved["state_version"] - 1,
            "overall_rating": 5,
        },
        content_type="application/json",
        **request_headers(resident, society, "stale-rate"),
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "TICKET_VERSION_CONFLICT"


def test_feedback_rating_range_validation(client):
    society, facility_manager, resident, resolved = _create_resolved_service_ticket(
        client=client,
        registration_code="NIV-FB7",
        phone_offset=8700,
    )
    invalid_rating = client.post(
        f"/api/v1/service-tickets/{resolved['id']}/rate/",
        {
            "expected_version": resolved["state_version"],
            "overall_rating": 6,
        },
        content_type="application/json",
        **request_headers(resident, society, "invalid-rating-range"),
    )
    assert invalid_rating.status_code == 400


def test_facility_manager_merges_duplicate_service_ticket(client):
    society, facility_manager, technician_user1, technician1, offered_a = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-MR1",
            phone_offset=8800,
        )
    )
    with transaction.atomic():
        set_local_society_id(society.id)
        category = TicketCategory.objects.get(
            society=society,
            workflow_type=Ticket.WorkflowType.SERVICE,
        )
        subcategory = TicketSubCategory.objects.get(
            society=society,
            category=category,
        )
    unit_b = create_unit(society=society, code="B", door_number="102")
    resident_b = create_resident(society=society, unit=unit_b, phone="+919876548810")
    technician_user2 = User.objects.create_user(phone="+919876548811")
    with transaction.atomic():
        set_local_society_id(society.id)
        technician2 = TechnicianProfile.objects.create(
            society=society,
            user=technician_user2,
            max_active_tickets=5,
        )
    submitted_b = submit_service_ticket(
        client=client,
        society=society,
        actor=resident_b,
        category=category,
        subcategory=subcategory,
        unit=unit_b,
        key="ticket-b-merge",
    )

    assign_b = client.post(
        f"/api/v1/service-tickets/{submitted_b['id']}/assign-in-house/",
        {
            "expected_version": submitted_b["state_version"],
            "technician_id": str(technician2.id),
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "assign-ticket-b"),
    )
    assert assign_b.status_code == 200
    offered_b = assign_b.json()

    with transaction.atomic():
        set_local_society_id(society.id)
        technician2.refresh_from_db()
        assert technician2.current_active_tickets_count == 1

    merge_endpoint = f"/api/v1/service-tickets/{offered_a['id']}/merge/"
    merge_payload = {
        "expected_primary_version": offered_a["state_version"],
        "expected_secondary_version": offered_b["state_version"],
        "secondary_ticket_id": offered_b["id"],
        "reason": "Duplicate leak report from same block.",
    }
    fm_headers = request_headers(facility_manager, society, "merge-b-into-a")

    first_merge = client.post(merge_endpoint, merge_payload, content_type="application/json", **fm_headers)
    replay_merge = client.post(merge_endpoint, merge_payload, content_type="application/json", **fm_headers)

    assert first_merge.status_code == 200, first_merge.json()
    assert replay_merge.status_code == 200
    assert replay_merge.json() == first_merge.json()

    result_data = first_merge.json()
    assert result_data["secondary_ticket"]["status"] == Ticket.Status.MERGED
    assert result_data["primary_ticket"]["state_version"] == offered_a["state_version"] + 1
    assert result_data["secondary_ticket"]["state_version"] == offered_b["state_version"] + 1

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket_a = Ticket.objects.get(id=offered_a["id"])
        ticket_b = Ticket.objects.get(id=offered_b["id"])
        merge_rec = TicketMergeRecord.objects.get(
            primary_ticket=ticket_a,
            secondary_ticket=ticket_b,
        )
        assert merge_rec.is_active is True
        assert merge_rec.reason == "Duplicate leak report from same block."
        assert merge_rec.previous_secondary_status == Ticket.Status.ASSIGNED

        technician2.refresh_from_db()
        assert technician2.current_active_tickets_count == 0

        sla_cycle = SLACycle.objects.get(ticket=ticket_b, ended_at__isnull=False)
        assert sla_cycle.outcome == SLACycle.Outcome.MERGED

        event_b = TicketEvent.objects.get(
            ticket=ticket_b,
            event_type=TicketEvent.EventType.TICKET_MERGED,
        )
        assert event_b.actor_id == facility_manager.id
        assert event_b.metadata["primary_ticket_id"] == str(ticket_a.id)

        event_a = TicketEvent.objects.get(
            ticket=ticket_a,
            event_type=TicketEvent.EventType.TICKET_MERGE_ATTACHED,
        )
        assert event_a.actor_id == facility_manager.id
        assert event_a.metadata["secondary_ticket_id"] == str(ticket_b.id)

    history_res = client.get(
        f"/api/v1/service-tickets/{offered_a['id']}/merges/",
        **request_headers(facility_manager, society),
    )
    assert history_res.status_code == 200
    assert len(history_res.json()) == 1
    assert history_res.json()[0]["secondary_ticket_id"] == str(offered_b["id"])


def test_facility_manager_unmerges_service_ticket(client, monkeypatch):
    society, facility_manager, technician_user1, technician1, offered_a = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-MR2",
            phone_offset=8900,
        )
    )
    category, subcategory = get_service_classification(society=society)
    unit_b = create_unit(society=society, code="B", door_number="102")
    resident_b = create_resident(society=society, unit=unit_b, phone="+919876548910")
    submitted_b = submit_service_ticket(
        client=client,
        society=society,
        actor=resident_b,
        category=category,
        subcategory=subcategory,
        unit=unit_b,
        key="ticket-b-unmerge-test",
    )

    merge_res = client.post(
        f"/api/v1/service-tickets/{offered_a['id']}/merge/",
        {
            "expected_primary_version": offered_a["state_version"],
            "expected_secondary_version": submitted_b["state_version"],
            "secondary_ticket_id": submitted_b["id"],
            "reason": "Initial mistaken duplicate.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "merge-before-unmerge"),
    )
    assert merge_res.status_code == 200
    merge_data = merge_res.json()
    primary_ver = merge_data["primary_ticket"]["state_version"]
    secondary_ver = merge_data["secondary_ticket"]["state_version"]

    unmerge_endpoint = f"/api/v1/service-tickets/{offered_a['id']}/unmerge/"
    unmerge_payload = {
        "expected_primary_version": primary_ver,
        "expected_secondary_version": secondary_ver,
        "secondary_ticket_id": submitted_b["id"],
        "reason": "Resident clarified separate issue in different room.",
    }
    unmerge_headers = request_headers(
        facility_manager,
        society,
        "unmerge-b-from-a",
        step_up=True,
    )
    expected_deadline = timezone.now() + timedelta(days=17)
    calculator_calls = []

    def calculate_deadline(**kwargs):
        calculator_calls.append(kwargs)
        return expected_deadline

    monkeypatch.setattr(
        "apps.tickets.services.business_calendar_deadline_calculator",
        calculate_deadline,
    )

    first_unmerge = client.post(unmerge_endpoint, unmerge_payload, content_type="application/json", **unmerge_headers)
    replay_unmerge = client.post(unmerge_endpoint, unmerge_payload, content_type="application/json", **unmerge_headers)

    assert first_unmerge.status_code == 200, first_unmerge.json()
    assert replay_unmerge.status_code == 200
    assert replay_unmerge.json() == first_unmerge.json()

    unmerge_data = first_unmerge.json()
    assert unmerge_data["secondary_ticket"]["status"] == Ticket.Status.SUPERVISOR_TRIAGE
    assert unmerge_data["merge_record"]["is_active"] is False

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket_b = Ticket.objects.get(id=submitted_b["id"])
        merge_rec = TicketMergeRecord.objects.get(
            primary_ticket_id=offered_a["id"],
            secondary_ticket=ticket_b,
        )
        assert merge_rec.is_active is False
        assert merge_rec.unmerge_reason == "Resident clarified separate issue in different room."
        assert merge_rec.unmerged_by_id == facility_manager.id
        assert merge_rec.unmerged_at is not None

        reopen_cycle = SLACycle.objects.get(ticket=ticket_b, ended_at__isnull=True)
        assert reopen_cycle.cycle_type == SLACycle.CycleType.REOPEN
        assert reopen_cycle.resolution_deadline == expected_deadline
        reopen_duration = reopen_cycle.snapshot.reopen_resolution_duration

        event_unmerged = TicketEvent.objects.filter(
            ticket=ticket_b,
            event_type=TicketEvent.EventType.TICKET_UNMERGED,
        ).first()
        assert event_unmerged is not None
        assert event_unmerged.actor_id == facility_manager.id

    assert len(calculator_calls) == 1
    assert calculator_calls[0]["duration"] == reopen_duration
    assert calculator_calls[0]["society_id"] == society.id


def test_unmerge_requires_fresh_step_up_within_facility_manager_recovery_window(client):
    society, facility_manager, technician_user, technician, offered_a = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-MR-STEP-UP",
            phone_offset=8950,
        )
    )
    category, subcategory = get_service_classification(society=society)
    unit_b = create_unit(society=society, code="B", door_number="102")
    resident_b = create_resident(society=society, unit=unit_b, phone="+919876548960")
    submitted_b = submit_service_ticket(
        client=client,
        society=society,
        actor=resident_b,
        category=category,
        subcategory=subcategory,
        unit=unit_b,
        key="ticket-b-unmerge-step-up",
    )
    merged = client.post(
        f"/api/v1/service-tickets/{offered_a['id']}/merge/",
        {
            "expected_primary_version": offered_a["state_version"],
            "expected_secondary_version": submitted_b["state_version"],
            "secondary_ticket_id": submitted_b["id"],
            "reason": "Initial mistaken duplicate.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "merge-before-unmerge-step-up"),
    )
    assert merged.status_code == 200, merged.json()

    merged_data = merged.json()
    unmerge_endpoint = f"/api/v1/service-tickets/{offered_a['id']}/unmerge/"
    unmerge_payload = {
        "expected_primary_version": merged_data["primary_ticket"]["state_version"],
        "expected_secondary_version": merged_data["secondary_ticket"]["state_version"],
        "secondary_ticket_id": submitted_b["id"],
        "reason": "Recovery request for a distinct ticket.",
    }
    missing_step_up = client.post(
        unmerge_endpoint,
        unmerge_payload,
        content_type="application/json",
        **request_headers(facility_manager, society, "missing-unmerge-step-up"),
    )
    stale_step_up = client.post(
        unmerge_endpoint,
        unmerge_payload,
        content_type="application/json",
        **request_headers(
            facility_manager,
            society,
            "stale-unmerge-step-up",
            step_up=True,
            step_up_at=timezone.now() - timedelta(minutes=6),
        ),
    )

    assert missing_step_up.status_code == 403
    assert stale_step_up.status_code == 403

    with transaction.atomic():
        set_local_society_id(society.id)
        merge_record = TicketMergeRecord.objects.get(
            primary_ticket_id=offered_a["id"],
            secondary_ticket_id=submitted_b["id"],
        )
        merge_record.merged_at = timezone.now() - timedelta(hours=24, seconds=1)
        merge_record.save(update_fields=("merged_at",))

    expired_facility_manager = client.post(
        unmerge_endpoint,
        unmerge_payload,
        content_type="application/json",
        **request_headers(
            facility_manager,
            society,
            "expired-unmerge-recovery-window",
            step_up=True,
        ),
    )

    assert expired_facility_manager.status_code == 403
    with transaction.atomic():
        set_local_society_id(society.id)
        merge_record.refresh_from_db()
        assert merge_record.is_active is True
        assert (
            IdempotencyRecord.objects.filter(
                society=society,
                principal=facility_manager,
                idempotency_key__in={
                    "missing-unmerge-step-up",
                    "stale-unmerge-step-up",
                    "expired-unmerge-recovery-window",
                },
            ).exists()
            is False
        )


def test_facility_manager_merges_and_unmerges_governance_ticket(client):
    society = Society.objects.create(registration_code="NIV-MR3")
    facility_manager = create_staff(
        society=society,
        phone="+919876559000",
        role=StaffMembership.Role.FACILITY_MANAGER,
    )
    unit_a = create_unit(society=society, code="A", door_number="101")
    resident_a = create_resident(society=society, unit=unit_a, phone="+919876549001")
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.GOVERNANCE,
    )
    create_sla_binding(society=society, category=category, priority=TicketSubCategory.Priority.P2)
    create_business_calendar(society=society)

    create_gov_a = client.post(
        "/api/v1/governance-tickets/",
        {
            "title": "AGM Resolution Proposal 1",
            "description": "Proposal for solar panel installation.",
            "category": str(category.id),
            "subcategory": str(subcategory.id),
            "priority": "P2",
        },
        content_type="application/json",
        **request_headers(resident_a, society, "create-gov-a"),
    )
    assert create_gov_a.status_code == 201, create_gov_a.json()
    submit_gov_a = client.post(
        f"/api/v1/governance-tickets/{create_gov_a.json()['id']}/submit/",
        {"expected_version": create_gov_a.json()["state_version"]},
        content_type="application/json",
        **request_headers(resident_a, society, "submit-gov-a"),
    )
    assert submit_gov_a.status_code == 200, submit_gov_a.json()
    gov_a = submit_gov_a.json()

    create_gov_b = client.post(
        "/api/v1/governance-tickets/",
        {
            "title": "AGM Resolution Proposal 2 - Solar",
            "description": "Duplicate solar resolution proposal.",
            "category": str(category.id),
            "subcategory": str(subcategory.id),
            "priority": "P2",
        },
        content_type="application/json",
        **request_headers(resident_a, society, "create-gov-b"),
    )
    assert create_gov_b.status_code == 201, create_gov_b.json()
    submit_gov_b = client.post(
        f"/api/v1/governance-tickets/{create_gov_b.json()['id']}/submit/",
        {"expected_version": create_gov_b.json()["state_version"]},
        content_type="application/json",
        **request_headers(resident_a, society, "submit-gov-b"),
    )
    assert submit_gov_b.status_code == 200, submit_gov_b.json()
    gov_b = submit_gov_b.json()

    merge_gov = client.post(
        f"/api/v1/governance-tickets/{gov_a['id']}/merge/",
        {
            "expected_primary_version": gov_a["state_version"],
            "expected_secondary_version": gov_b["state_version"],
            "secondary_ticket_id": gov_b["id"],
            "reason": "Duplicate governance resolution.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "merge-gov"),
    )
    assert merge_gov.status_code == 200
    merged_data = merge_gov.json()
    assert merged_data["secondary_ticket"]["status"] == Ticket.Status.MERGED

    unmerge_gov = client.post(
        f"/api/v1/governance-tickets/{gov_a['id']}/unmerge/",
        {
            "expected_primary_version": merged_data["primary_ticket"]["state_version"],
            "expected_secondary_version": merged_data["secondary_ticket"]["state_version"],
            "secondary_ticket_id": gov_b["id"],
            "reason": "Resolutions were distinct sub-items.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "unmerge-gov", step_up=True),
    )
    assert unmerge_gov.status_code == 200
    assert unmerge_gov.json()["secondary_ticket"]["status"] == Ticket.Status.UNDER_REVIEW


def test_merge_rejected_for_cross_workflow_tickets(client):
    society, facility_manager, tech_user, tech, service_ticket = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-MR4",
            phone_offset=9100,
        )
    )
    resident_a = User.objects.get(phone="+919876549100")
    category, subcategory = create_classification(
        society=society,
        workflow_type=Ticket.WorkflowType.GOVERNANCE,
    )
    create_sla_binding(society=society, category=category, priority=TicketSubCategory.Priority.P2)
    create_gov = client.post(
        "/api/v1/governance-tickets/",
        {
            "title": "Governance Issue",
            "description": "Governance description.",
            "category": str(category.id),
            "subcategory": str(subcategory.id),
            "priority": "P2",
        },
        content_type="application/json",
        **request_headers(resident_a, society, "create-gov-cross"),
    )
    assert create_gov.status_code == 201, create_gov.json()
    submit_gov = client.post(
        f"/api/v1/governance-tickets/{create_gov.json()['id']}/submit/",
        {"expected_version": create_gov.json()["state_version"]},
        content_type="application/json",
        **request_headers(resident_a, society, "submit-gov-cross"),
    )
    assert submit_gov.status_code == 200, submit_gov.json()
    gov_ticket = submit_gov.json()

    cross_merge = client.post(
        f"/api/v1/service-tickets/{service_ticket['id']}/merge/",
        {
            "expected_primary_version": service_ticket["state_version"],
            "expected_secondary_version": gov_ticket["state_version"],
            "secondary_ticket_id": gov_ticket["id"],
            "reason": "Attempting cross-workflow merge.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "cross-merge"),
    )
    assert cross_merge.status_code == 409
    assert cross_merge.json()["code"] == "TICKET_WORKFLOW_MISMATCH"


def test_merge_rejected_if_secondary_already_terminal(client):
    society, facility_manager, resident, resolved_primary = _create_resolved_service_ticket(
        client=client,
        registration_code="NIV-MR5",
        phone_offset=9200,
    )
    category, subcategory = get_service_classification(society=society)
    unit = get_society_unit(society=society)
    submitted_b = submit_service_ticket(
        client=client,
        society=society,
        actor=resident,
        category=category,
        subcategory=subcategory,
        unit=unit,
        key="ticket-b-terminal-test",
    )
    cancel_res = client.post(
        f"/api/v1/service-tickets/{submitted_b['id']}/cancel/",
        {"expected_version": submitted_b["state_version"], "reason": "No longer needed."},
        content_type="application/json",
        **request_headers(resident, society, "cancel-b"),
    )
    assert cancel_res.status_code == 200
    cancelled_b = cancel_res.json()

    submitted_a = submit_service_ticket(
        client=client,
        society=society,
        actor=resident,
        category=category,
        subcategory=subcategory,
        unit=unit,
        key="ticket-a-terminal-test",
    )

    terminal_merge = client.post(
        f"/api/v1/service-tickets/{submitted_a['id']}/merge/",
        {
            "expected_primary_version": submitted_a["state_version"],
            "expected_secondary_version": cancelled_b["state_version"],
            "secondary_ticket_id": cancelled_b["id"],
            "reason": "Attempting terminal merge.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "terminal-merge"),
    )
    assert terminal_merge.status_code == 409
    assert terminal_merge.json()["code"] == "TICKET_STATE_CONFLICT"


def test_merge_self_rejected(client):
    society, facility_manager, tech_user, tech, service_ticket = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-MR7",
            phone_offset=9400,
        )
    )
    self_merge = client.post(
        f"/api/v1/service-tickets/{service_ticket['id']}/merge/",
        {
            "expected_primary_version": service_ticket["state_version"],
            "expected_secondary_version": service_ticket["state_version"],
            "secondary_ticket_id": service_ticket["id"],
            "reason": "Self merge attempt.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "self-merge"),
    )
    assert self_merge.status_code == 409
    assert self_merge.json()["code"] == "CANNOT_MERGE_SELF"


def test_unauthorized_actor_denied_merge(client):
    society, facility_manager, tech_user, tech, service_ticket_a = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-MR8",
            phone_offset=9500,
        )
    )
    resident = User.objects.get(phone="+919876549500")
    denied_merge = client.post(
        f"/api/v1/service-tickets/{service_ticket_a['id']}/merge/",
        {
            "expected_primary_version": service_ticket_a["state_version"],
            "expected_secondary_version": 1,
            "secondary_ticket_id": str(uuid.uuid4()),
            "reason": "Resident trying to merge.",
        },
        content_type="application/json",
        **request_headers(resident, society, "resident-merge"),
    )
    assert denied_merge.status_code in {403, 404}


def test_stale_version_merge_rejected(client):
    society, facility_manager, tech_user, tech, service_ticket_a = (
        create_offered_in_house_assignment(
            client=client,
            registration_code="NIV-MR9",
            phone_offset=9600,
        )
    )
    category, subcategory = get_service_classification(society=society)
    resident = User.objects.get(phone="+919876549600")
    unit = get_society_unit(society=society)
    ticket_b = submit_service_ticket(
        client=client,
        society=society,
        actor=resident,
        category=category,
        subcategory=subcategory,
        unit=unit,
        key="ticket-b-stale-test",
    )
    stale_merge = client.post(
        f"/api/v1/service-tickets/{service_ticket_a['id']}/merge/",
        {
            "expected_primary_version": service_ticket_a["state_version"] - 1,
            "expected_secondary_version": ticket_b["state_version"],
            "secondary_ticket_id": ticket_b["id"],
            "reason": "Stale merge.",
        },
        content_type="application/json",
        **request_headers(facility_manager, society, "stale-merge"),
    )
    assert stale_merge.status_code == 409
    assert stale_merge.json()["code"] == "TICKET_VERSION_CONFLICT"







