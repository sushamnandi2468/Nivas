from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.identity.models import User
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import (
    Block,
    Society,
    TechnicianProfile,
    Unit,
    Vendor,
    VendorContract,
    VendorStaffMembership,
)
from apps.tickets.models import (
    Ticket,
    TicketAssignment,
    TicketCategory,
    TicketSubCategory,
    VendorStaffAllocation,
)

pytestmark = pytest.mark.django_db(transaction=True)


def create_service_ticket(*, society, creator, suffix):
    with transaction.atomic():
        set_local_society_id(society.id)
        block = Block.objects.create(society=society, name=f"Block {suffix}", code=suffix)
        unit = Unit.objects.create(society=society, block=block, door_number="101")
        category = TicketCategory.objects.create(
            society=society,
            name=f"Plumbing {suffix}",
            normalized_name=f"plumbing {suffix}".casefold(),
            workflow_type=Ticket.WorkflowType.SERVICE,
            allows_unit_location=True,
            cost_responsibility=TicketCategory.CostResponsibility.SOCIETY,
            completion_policy=TicketCategory.CompletionPolicy.RESIDENT_CONFIRMATION,
        )
        subcategory = TicketSubCategory.objects.create(
            society=society,
            category=category,
            name=f"Leak {suffix}",
            normalized_name=f"leak {suffix}".casefold(),
            default_priority=TicketSubCategory.Priority.P2,
        )
        return Ticket.objects.create(
            society=society,
            ticket_number=f"NIV-{suffix}-1",
            creator=creator,
            category=category,
            subcategory=subcategory,
            workflow_type=Ticket.WorkflowType.SERVICE,
            unit=unit,
            title="Water leak",
            description="A verified test request.",
            priority=TicketSubCategory.Priority.P2,
            status=Ticket.Status.SUBMITTED,
            submitted_at=timezone.now(),
        )


def test_ticket_assignment_allows_one_active_target_per_ticket():
    society = Society.objects.create(registration_code="NIV-ASSIGN-ACTIVE")
    manager = User.objects.create_user(phone="+919876543340")
    technician_user = User.objects.create_user(phone="+919876543341")
    ticket = create_service_ticket(society=society, creator=manager, suffix="ACTIVE")

    with transaction.atomic():
        set_local_society_id(society.id)
        technician = TechnicianProfile.objects.create(society=society, user=technician_user)
        TicketAssignment.objects.create(
            society=society,
            ticket=ticket,
            target_type=TicketAssignment.TargetType.IN_HOUSE,
            technician=technician,
            assigned_by=manager,
            acceptance_deadline=timezone.now() + timedelta(hours=2),
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        set_local_society_id(society.id)
        TicketAssignment.objects.create(
            society=society,
            ticket=ticket,
            target_type=TicketAssignment.TargetType.IN_HOUSE,
            technician=technician,
            assigned_by=manager,
            acceptance_deadline=timezone.now() + timedelta(hours=2),
        )


def test_vendor_staff_allocation_allows_one_active_worker_per_assignment():
    society = Society.objects.create(registration_code="NIV-VENDOR-ALLOC")
    manager = User.objects.create_user(phone="+919876543342")
    worker = User.objects.create_user(phone="+919876543343")
    ticket = create_service_ticket(society=society, creator=manager, suffix="VENDOR")

    with transaction.atomic():
        set_local_society_id(society.id)
        vendor = Vendor.objects.create(
            society=society,
            company_name="Reliable Plumbing",
            contact_person="Vendor Contact",
            phone_number="+919876543344",
        )
        contract = VendorContract.objects.create(
            society=society,
            vendor=vendor,
            starts_on=timezone.localdate(),
            ends_on=timezone.localdate() + timedelta(days=30),
        )
        staff_membership = VendorStaffMembership.objects.create(
            society=society,
            vendor=vendor,
            contract=contract,
            user=worker,
            role=VendorStaffMembership.Role.WORKER,
        )
        assignment = TicketAssignment.objects.create(
            society=society,
            ticket=ticket,
            target_type=TicketAssignment.TargetType.VENDOR,
            vendor_contract=contract,
            assigned_by=manager,
            acceptance_deadline=timezone.now() + timedelta(hours=2),
        )
        VendorStaffAllocation.objects.create(
            society=society,
            assignment=assignment,
            staff_membership=staff_membership,
            allocated_by=manager,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        set_local_society_id(society.id)
        VendorStaffAllocation.objects.create(
            society=society,
            assignment=assignment,
            staff_membership=staff_membership,
            allocated_by=manager,
        )


def test_ticket_assignment_tables_force_rls_and_scope_reads_to_society():
    society = Society.objects.create(registration_code="NIV-ASSIGN-RLS-A")
    other_society = Society.objects.create(registration_code="NIV-ASSIGN-RLS-B")
    manager = User.objects.create_user(phone="+919876543345")
    other_manager = User.objects.create_user(phone="+919876543346")
    ticket = create_service_ticket(society=society, creator=manager, suffix="RLSA")
    other_ticket = create_service_ticket(
        society=other_society,
        creator=other_manager,
        suffix="RLSB",
    )

    with transaction.atomic():
        set_local_society_id(society.id)
        technician = TechnicianProfile.objects.create(society=society, user=manager)
        assignment = TicketAssignment.objects.create(
            society=society,
            ticket=ticket,
            target_type=TicketAssignment.TargetType.IN_HOUSE,
            technician=technician,
            assigned_by=manager,
            acceptance_deadline=timezone.now() + timedelta(hours=2),
        )

    with transaction.atomic():
        set_local_society_id(other_society.id)
        other_technician = TechnicianProfile.objects.create(
            society=other_society,
            user=other_manager,
        )
        TicketAssignment.objects.create(
            society=other_society,
            ticket=other_ticket,
            target_type=TicketAssignment.TargetType.IN_HOUSE,
            technician=other_technician,
            assigned_by=other_manager,
            acceptance_deadline=timezone.now() + timedelta(hours=2),
        )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE oid IN (
                'tickets_ticket_assignment'::regclass,
                'tickets_vendor_staff_allocation'::regclass
            )
            ORDER BY relname
            """
        )
        assert cursor.fetchall() == [(True, True), (True, True)]

    with transaction.atomic():
        set_local_society_id(society.id)
        assignment_ids = list(TicketAssignment.objects.values_list("id", flat=True))

    assert assignment_ids == [assignment.id]