import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import F
from django.utils import timezone

from apps.identity.models import User
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import Block, CommonArea, Society, Unit
from apps.tickets.models import (
    GOVERNANCE_TICKET_STATUSES,
    SERVICE_TICKET_STATUSES,
    Ticket,
    TicketCategory,
    TicketSubCategory,
)

pytestmark = pytest.mark.django_db(transaction=True)


def create_category(*, society, workflow_type=TicketCategory.WorkflowType.SERVICE):
    is_service = workflow_type == TicketCategory.WorkflowType.SERVICE
    with transaction.atomic():
        set_local_society_id(society.id)
        category = TicketCategory.objects.create(
            society=society,
            name="Plumbing" if is_service else "Campus Governance",
            normalized_name="plumbing" if is_service else "campus governance",
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
            name="Pipe Burst" if is_service else "Parking Policy",
            normalized_name="pipe burst" if is_service else "parking policy",
            default_priority=TicketSubCategory.Priority.P1,
        )
    return category, subcategory


def create_unit(*, society, code="A", door_number="101"):
    with transaction.atomic():
        set_local_society_id(society.id)
        block = Block.objects.create(society=society, name=code, code=code)
        return Unit.objects.create(
            society=society,
            block=block,
            door_number=door_number,
        )


def create_draft_ticket(*, society, creator, category, subcategory, unit=None):
    with transaction.atomic():
        set_local_society_id(society.id)
        return Ticket.objects.create(
            society=society,
            creator=creator,
            category=category,
            subcategory=subcategory,
            workflow_type=category.workflow_type,
            unit=unit,
            title="Water leak",
            description="Water is leaking below the kitchen sink.",
            priority=subcategory.default_priority,
        )


def test_ticket_core_uses_canonical_statuses_and_initial_version():
    society = Society.objects.create(registration_code="NIV-TICKET-CORE")
    creator = User.objects.create_user(phone="+919876543500")
    category, subcategory = create_category(society=society)
    unit = create_unit(society=society)

    ticket = create_draft_ticket(
        society=society,
        creator=creator,
        category=category,
        subcategory=subcategory,
        unit=unit,
    )

    assert ticket.status == Ticket.Status.DRAFT
    assert ticket.state_version == 1
    assert ticket.ticket_number == ""
    assert "SUPERVISOR_TRIAGE" in SERVICE_TICKET_STATUSES
    assert "UNDER_REVIEW" not in SERVICE_TICKET_STATUSES
    assert "UNDER_REVIEW" in GOVERNANCE_TICKET_STATUSES
    assert "ASSIGNED" not in GOVERNANCE_TICKET_STATUSES


def test_category_and_ticket_model_validation_enforces_workflow_policy():
    society = Society.objects.create(registration_code="NIV-TICKET-POLICY")
    creator = User.objects.create_user(phone="+919876543501")
    category, subcategory = create_category(society=society)
    invalid_category = TicketCategory(
        society=society,
        name="Invalid Service",
        workflow_type=TicketCategory.WorkflowType.SERVICE,
        allows_no_location=True,
        cost_responsibility=TicketCategory.CostResponsibility.NO_CHARGE,
        completion_policy=TicketCategory.CompletionPolicy.GOVERNANCE_RESOLUTION,
    )
    ticket = Ticket(
        society=society,
        creator=creator,
        category=category,
        subcategory=subcategory,
        workflow_type=Ticket.WorkflowType.SERVICE,
        title="Missing location",
        description="No target was supplied.",
        priority=TicketSubCategory.Priority.P2,
        status=Ticket.Status.UNDER_REVIEW,
    )

    with pytest.raises(ValidationError) as category_error:
        invalid_category.full_clean()
    with pytest.raises(ValidationError) as ticket_error:
        ticket.full_clean()

    assert "allows_no_location" in category_error.value.message_dict
    assert "completion_policy" in category_error.value.message_dict
    assert "unit" in ticket_error.value.message_dict
    assert "status" in ticket_error.value.message_dict


def test_database_rejects_service_ticket_without_exactly_one_location():
    society = Society.objects.create(registration_code="NIV-TICKET-LOCATION")
    creator = User.objects.create_user(phone="+919876543502")
    category, subcategory = create_category(society=society)
    unit = create_unit(society=society)
    with transaction.atomic():
        set_local_society_id(society.id)
        common_area = CommonArea.objects.create(
            society=society,
            name="Clubhouse",
            normalized_name="clubhouse",
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        set_local_society_id(society.id)
        Ticket.objects.create(
            society=society,
            creator=creator,
            category=category,
            subcategory=subcategory,
            workflow_type=Ticket.WorkflowType.SERVICE,
            title="Missing location",
            description="No location.",
            priority=TicketSubCategory.Priority.P2,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        set_local_society_id(society.id)
        Ticket.objects.create(
            society=society,
            creator=creator,
            category=category,
            subcategory=subcategory,
            workflow_type=Ticket.WorkflowType.SERVICE,
            unit=unit,
            common_area=common_area,
            title="Two locations",
            description="Both targets supplied.",
            priority=TicketSubCategory.Priority.P2,
        )


def test_database_rejects_cross_society_and_cross_category_relationships():
    society = Society.objects.create(registration_code="NIV-TICKET-FK-A")
    other_society = Society.objects.create(registration_code="NIV-TICKET-FK-B")
    creator = User.objects.create_user(phone="+919876543503")
    category, subcategory = create_category(society=society)
    other_category, other_subcategory = create_category(society=other_society)
    unit = create_unit(society=society)

    with pytest.raises(IntegrityError), transaction.atomic():
        set_local_society_id(society.id)
        Ticket.objects.create(
            society_id=society.id,
            creator=creator,
            category_id=other_category.id,
            subcategory_id=other_subcategory.id,
            workflow_type=Ticket.WorkflowType.SERVICE,
            unit=unit,
            title="Cross tenant",
            description="Invalid category tenant.",
            priority=TicketSubCategory.Priority.P1,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        set_local_society_id(society.id)
        Ticket.objects.create(
            society=society,
            creator=creator,
            category=category,
            subcategory=other_subcategory,
            workflow_type=Ticket.WorkflowType.SERVICE,
            unit=unit,
            title="Cross category",
            description="Invalid subcategory.",
            priority=TicketSubCategory.Priority.P1,
        )

    assert subcategory.category_id == category.id


def test_ticket_tables_force_rls_and_scope_reads():
    society = Society.objects.create(registration_code="NIV-TICKET-RLS-A")
    other_society = Society.objects.create(registration_code="NIV-TICKET-RLS-B")
    creator = User.objects.create_user(phone="+919876543504")
    category, subcategory = create_category(society=society)
    other_category, other_subcategory = create_category(society=other_society)
    unit = create_unit(society=society)
    other_unit = create_unit(society=other_society)
    selected = create_draft_ticket(
        society=society,
        creator=creator,
        category=category,
        subcategory=subcategory,
        unit=unit,
    )
    create_draft_ticket(
        society=other_society,
        creator=creator,
        category=other_category,
        subcategory=other_subcategory,
        unit=other_unit,
    )

    with transaction.atomic():
        set_local_society_id(society.id)
        assert list(Ticket.objects.values_list("id", flat=True)) == [selected.id]
        assert TicketCategory.objects.count() == 1
        assert TicketSubCategory.objects.count() == 1

    assert Ticket.objects.count() == 0
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relname, relforcerowsecurity
            FROM pg_class
            WHERE relname IN (
                'tickets_ticket_category',
                'tickets_ticket_subcategory',
                'tickets_ticket'
            )
            ORDER BY relname
            """
        )
        assert cursor.fetchall() == [
            ("tickets_ticket", True),
            ("tickets_ticket_category", True),
            ("tickets_ticket_subcategory", True),
        ]


def test_ticket_update_requires_version_increment_and_number_is_immutable():
    society = Society.objects.create(registration_code="NIV-TICKET-VERSION")
    creator = User.objects.create_user(phone="+919876543505")
    category, subcategory = create_category(society=society)
    unit = create_unit(society=society)
    ticket = create_draft_ticket(
        society=society,
        creator=creator,
        category=category,
        subcategory=subcategory,
        unit=unit,
    )

    with pytest.raises(DatabaseError), transaction.atomic():
        set_local_society_id(society.id)
        Ticket.objects.filter(id=ticket.id).update(title="Unversioned update")

    with transaction.atomic():
        set_local_society_id(society.id)
        Ticket.objects.filter(id=ticket.id).update(
            title="Versioned update",
            state_version=F("state_version") + 1,
        )
        Ticket.objects.filter(id=ticket.id).update(
            status=Ticket.Status.SUBMITTED,
            ticket_number="NIV-2026-000001",
            submitted_at=timezone.now(),
            state_version=F("state_version") + 1,
        )

    with pytest.raises(DatabaseError), transaction.atomic():
        set_local_society_id(society.id)
        Ticket.objects.filter(id=ticket.id).update(
            ticket_number="NIV-2026-000002",
            state_version=F("state_version") + 1,
        )


def test_submitted_ticket_cannot_be_hard_deleted():
    society = Society.objects.create(registration_code="NIV-TICKET-ARCHIVE")
    creator = User.objects.create_user(phone="+919876543506")
    category, subcategory = create_category(society=society)
    unit = create_unit(society=society)
    ticket = create_draft_ticket(
        society=society,
        creator=creator,
        category=category,
        subcategory=subcategory,
        unit=unit,
    )
    with transaction.atomic():
        set_local_society_id(society.id)
        Ticket.objects.filter(id=ticket.id).update(
            status=Ticket.Status.SUBMITTED,
            ticket_number="NIV-2026-000003",
            submitted_at=timezone.now(),
            state_version=F("state_version") + 1,
        )

    with pytest.raises(DatabaseError), transaction.atomic():
        set_local_society_id(society.id)
        Ticket.objects.filter(id=ticket.id).delete()