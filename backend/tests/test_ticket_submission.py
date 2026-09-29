import uuid

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.identity.models import User
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import Block, Society, Unit, UnitOccupancy
from apps.tickets.models import (
    IdempotencyRecord,
    Ticket,
    TicketCategory,
    TicketEvent,
    TicketNumberSequence,
    TicketSubCategory,
)
from apps.tickets.services import (
    IdempotencyKeyReused,
    IdempotencyRequestInProgress,
    TicketSubmissionForbidden,
    _canonical_request_hash,
    submit_ticket,
)

pytestmark = pytest.mark.django_db(transaction=True)

SUBMIT_ROUTE = "/api/v1/service-tickets/{id}/submit"


def create_resident_draft(*, registration_code, phone, door_number="101"):
    society = Society.objects.create(registration_code=registration_code)
    resident = User.objects.create_user(phone=phone)
    with transaction.atomic():
        set_local_society_id(society.id)
        block = Block.objects.create(society=society, name="Alpha", code="A")
        unit = Unit.objects.create(
            society=society,
            block=block,
            door_number=door_number,
        )
        membership = UnitOccupancy.objects.create(
            society=society,
            unit=unit,
            user=resident,
            occupancy_type=UnitOccupancy.OccupancyType.OWNER,
        )
        category = TicketCategory.objects.create(
            society=society,
            name="Plumbing",
            normalized_name="plumbing",
            workflow_type=TicketCategory.WorkflowType.SERVICE,
            allows_unit_location=True,
            cost_responsibility=TicketCategory.CostResponsibility.RESIDENT_UNIT,
            completion_policy=TicketCategory.CompletionPolicy.RESIDENT_CONFIRMATION,
        )
        subcategory = TicketSubCategory.objects.create(
            society=society,
            category=category,
            name="Pipe Burst",
            normalized_name="pipe burst",
            default_priority=TicketSubCategory.Priority.P1,
        )
        ticket = Ticket.objects.create(
            society=society,
            creator=resident,
            category=category,
            subcategory=subcategory,
            workflow_type=Ticket.WorkflowType.SERVICE,
            unit=unit,
            title="Kitchen pipe burst",
            description="Water is leaking below the sink.",
            priority=subcategory.default_priority,
        )
    return society, resident, membership, ticket


def submit(*, society, resident, membership, ticket, key, create_sla_cycle=None):
    return submit_ticket(
        society_id=society.id,
        ticket_id=ticket.id,
        actor=resident,
        membership=membership,
        expected_version=1,
        idempotency_key=key,
        route_template=SUBMIT_ROUTE,
        correlation_id=uuid.uuid4(),
        create_sla_cycle=create_sla_cycle or (lambda **kwargs: uuid.uuid4()),
    )


def test_submit_allocates_number_updates_version_and_appends_event():
    society, resident, membership, ticket = create_resident_draft(
        registration_code="NIV-SUBMIT",
        phone="+919876543510",
    )
    sla_cycle_id = uuid.uuid4()

    result = submit(
        society=society,
        resident=resident,
        membership=membership,
        ticket=ticket,
        key="submit-success",
        create_sla_cycle=lambda **kwargs: sla_cycle_id,
    )

    assert result.response_status == 200
    assert result.replayed is False
    assert result.response_body["ticket_number"].endswith("-000001")
    assert result.response_body["status"] == Ticket.Status.SUBMITTED
    assert result.response_body["state_version"] == 2
    assert result.response_body["sla_cycle_id"] == str(sla_cycle_id)
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket.refresh_from_db()
        event = TicketEvent.objects.get(ticket=ticket)
        record = IdempotencyRecord.objects.get(idempotency_key="submit-success")
        sequence = TicketNumberSequence.objects.get(calendar_year=timezone.now().year)
    assert ticket.ticket_number == result.response_body["ticket_number"]
    assert event.previous_status == Ticket.Status.DRAFT
    assert event.new_status == Ticket.Status.SUBMITTED
    assert event.ticket_version == 2
    assert event.actor_persona == "resident"
    assert event.metadata == {"sla_cycle_id": str(sla_cycle_id)}
    assert record.status == IdempotencyRecord.Status.COMPLETED
    assert record.response_body == result.response_body
    assert sequence.current_value == 1


def test_same_idempotency_key_and_hash_replays_without_duplicate_execution():
    society, resident, membership, ticket = create_resident_draft(
        registration_code="NIV-REPLAY",
        phone="+919876543511",
    )
    calls = []

    def create_sla_cycle(**kwargs):
        calls.append(kwargs)
        return uuid.uuid4()

    first = submit(
        society=society,
        resident=resident,
        membership=membership,
        ticket=ticket,
        key="submit-replay",
        create_sla_cycle=create_sla_cycle,
    )
    replay = submit(
        society=society,
        resident=resident,
        membership=membership,
        ticket=ticket,
        key="submit-replay",
        create_sla_cycle=create_sla_cycle,
    )

    assert replay.replayed is True
    assert replay.response_body == first.response_body
    assert len(calls) == 1
    with transaction.atomic():
        set_local_society_id(society.id)
        assert TicketEvent.objects.count() == 1
        assert TicketNumberSequence.objects.get().current_value == 1


def test_reused_key_with_different_hash_is_rejected():
    society, resident, membership, ticket = create_resident_draft(
        registration_code="NIV-REUSED",
        phone="+919876543512",
    )
    submit(
        society=society,
        resident=resident,
        membership=membership,
        ticket=ticket,
        key="reused-key",
    )

    with pytest.raises(IdempotencyKeyReused):
        submit_ticket(
            society_id=society.id,
            ticket_id=ticket.id,
            actor=resident,
            membership=membership,
            expected_version=2,
            idempotency_key="reused-key",
            route_template=SUBMIT_ROUTE,
            correlation_id=uuid.uuid4(),
            create_sla_cycle=lambda **kwargs: uuid.uuid4(),
        )


def test_existing_in_progress_request_returns_retryable_conflict():
    society, resident, membership, ticket = create_resident_draft(
        registration_code="NIV-PENDING",
        phone="+919876543513",
    )
    with transaction.atomic():
        set_local_society_id(society.id)
        IdempotencyRecord.objects.create(
            society=society,
            principal=resident,
            http_method="POST",
            route_template=SUBMIT_ROUTE,
            idempotency_key="pending-key",
            request_hash=_canonical_request_hash(
                ticket_id=ticket.id,
                expected_version=1,
            ),
            expires_at=timezone.now() + timezone.timedelta(hours=72),
        )

    with pytest.raises(IdempotencyRequestInProgress):
        submit(
            society=society,
            resident=resident,
            membership=membership,
            ticket=ticket,
            key="pending-key",
        )


def test_stale_version_conflict_is_persisted_and_replayed():
    society, resident, membership, ticket = create_resident_draft(
        registration_code="NIV-CONFLICT",
        phone="+919876543514",
    )
    with transaction.atomic():
        set_local_society_id(society.id)
        Ticket.objects.filter(id=ticket.id).update(
            title="Changed draft",
            state_version=2,
        )

    first = submit(
        society=society,
        resident=resident,
        membership=membership,
        ticket=ticket,
        key="stale-version",
    )
    replay = submit(
        society=society,
        resident=resident,
        membership=membership,
        ticket=ticket,
        key="stale-version",
    )

    assert first.response_status == 409
    assert first.response_body["code"] == "TICKET_VERSION_CONFLICT"
    assert first.response_body["current_version"] == 2
    assert replay.replayed is True
    assert replay.response_body == first.response_body


def test_unauthorized_resident_does_not_claim_idempotency_key():
    society, resident, membership, ticket = create_resident_draft(
        registration_code="NIV-FORBIDDEN",
        phone="+919876543515",
    )
    other_resident = User.objects.create_user(phone="+919876543516")
    with transaction.atomic():
        set_local_society_id(society.id)
        other_membership = UnitOccupancy.objects.create(
            society=society,
            unit=membership.unit,
            user=other_resident,
            occupancy_type=UnitOccupancy.OccupancyType.FAMILY,
        )

    with pytest.raises(TicketSubmissionForbidden):
        submit_ticket(
            society_id=society.id,
            ticket_id=ticket.id,
            actor=other_resident,
            membership=other_membership,
            expected_version=1,
            idempotency_key="forbidden-key",
            route_template=SUBMIT_ROUTE,
            correlation_id=uuid.uuid4(),
            create_sla_cycle=lambda **kwargs: uuid.uuid4(),
        )

    with transaction.atomic():
        set_local_society_id(society.id)
        assert IdempotencyRecord.objects.count() == 0


def test_missing_sla_cycle_rolls_back_number_event_and_ticket_transition():
    society, resident, membership, ticket = create_resident_draft(
        registration_code="NIV-NO-SLA",
        phone="+919876543517",
    )

    result = submit(
        society=society,
        resident=resident,
        membership=membership,
        ticket=ticket,
        key="missing-sla",
        create_sla_cycle=lambda **kwargs: None,
    )

    assert result.response_status == 409
    assert result.response_body["code"] == "SLA_CYCLE_REQUIRED"
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket.refresh_from_db()
        assert ticket.status == Ticket.Status.DRAFT
        assert ticket.ticket_number == ""
        assert TicketNumberSequence.objects.count() == 0
        assert TicketEvent.objects.count() == 0


def test_ticket_events_are_immutable_and_all_new_tables_force_rls():
    society, resident, membership, ticket = create_resident_draft(
        registration_code="NIV-EVENT-RLS",
        phone="+919876543518",
    )
    submit(
        society=society,
        resident=resident,
        membership=membership,
        ticket=ticket,
        key="event-rls",
    )

    with pytest.raises(DatabaseError), transaction.atomic():
        set_local_society_id(society.id)
        TicketEvent.objects.update(reason="mutated")
    assert TicketEvent.objects.count() == 0

    with transaction.atomic():
        set_local_society_id(society.id)
        assert TicketEvent.objects.count() == 1
        assert TicketNumberSequence.objects.count() == 1
        assert IdempotencyRecord.objects.count() == 1
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relname, relforcerowsecurity
            FROM pg_class
            WHERE relname IN (
                'tickets_ticket_number_sequence',
                'tickets_ticket_event',
                'tickets_idempotency_record'
            )
            ORDER BY relname
            """
        )
        assert cursor.fetchall() == [
            ("tickets_idempotency_record", True),
            ("tickets_ticket_event", True),
            ("tickets_ticket_number_sequence", True),
        ]