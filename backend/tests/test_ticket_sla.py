import uuid
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone

from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import Society
from apps.tickets.models import (
    BusinessCalendar,
    IdempotencyRecord,
    SLACycle,
    SLAPolicyBinding,
    SLAPolicySnapshot,
    Ticket,
    TicketEvent,
    TicketNumberSequence,
)
from apps.tickets.services import PersistInitialSLACycle, submit_ticket
from tests.test_ticket_submission import create_resident_draft

pytestmark = pytest.mark.django_db(transaction=True)

SUBMIT_ROUTE = "/api/v1/service-tickets/{id}/submit"


def create_snapshot(*, society, policy_key="service-default", policy_version=1):
    with transaction.atomic():
        set_local_society_id(society.id)
        return SLAPolicySnapshot.objects.create(
            society=society,
            policy_key=policy_key,
            policy_version=policy_version,
            calendar_version=1,
            society_timezone=society.timezone,
            acceptance_duration=timedelta(hours=2),
            initial_resolution_duration=timedelta(hours=8),
            reopen_resolution_duration=timedelta(hours=4),
            l3_delay=timedelta(hours=2),
            permitted_pause_reasons=[
                SLAPolicySnapshot.PauseReason.RESIDENT_ACCESS_UNAVAILABLE,
            ],
            estimate_decision_duration=timedelta(hours=24),
        )


def create_calendar(*, society, version=1, is_active=True):
    with transaction.atomic():
        set_local_society_id(society.id)
        calendar = BusinessCalendar(
            society=society,
            version=version,
            timezone=society.timezone,
            working_intervals=[
                {"weekday": weekday, "start": "09:00", "end": "17:00"}
                for weekday in range(5)
            ],
            is_active=is_active,
        )
        calendar.full_clean()
        calendar.save()
        return calendar


def bind_snapshot(*, ticket, snapshot):
    with transaction.atomic():
        set_local_society_id(ticket.society_id)
        return SLAPolicyBinding.objects.create(
            society=ticket.society,
            category=ticket.category,
            priority=ticket.priority,
            snapshot=snapshot,
        )


def submit_with_persisted_sla(*, society, resident, membership, ticket, calculator):
    return submit_ticket(
        society_id=society.id,
        ticket_id=ticket.id,
        actor=resident,
        membership=membership,
        expected_version=1,
        idempotency_key=f"sla-submit-{uuid.uuid4()}",
        route_template=SUBMIT_ROUTE,
        correlation_id=uuid.uuid4(),
        create_sla_cycle=PersistInitialSLACycle(calculate_deadline=calculator),
    )


def test_submission_persists_initial_cycle_from_active_snapshot():
    society, resident, membership, ticket = create_resident_draft(
        registration_code="NIV-SLA-SUBMIT",
        phone="+919876543520",
    )
    snapshot = create_snapshot(society=society)
    bind_snapshot(ticket=ticket, snapshot=snapshot)
    calculator_calls = []

    def calculate_deadline(**kwargs):
        calculator_calls.append(kwargs)
        return kwargs["started_at"] + timedelta(hours=10)

    result = submit_with_persisted_sla(
        society=society,
        resident=resident,
        membership=membership,
        ticket=ticket,
        calculator=calculate_deadline,
    )

    assert result.response_status == 200
    with transaction.atomic():
        set_local_society_id(society.id)
        cycle = SLACycle.objects.get(id=result.response_body["sla_cycle_id"])
    assert cycle.ticket_id == ticket.id
    assert cycle.snapshot_id == snapshot.id
    assert cycle.cycle_number == 1
    assert cycle.cycle_type == SLACycle.CycleType.INITIAL
    assert cycle.acceptance_deadline is None
    assert cycle.resolution_deadline == cycle.started_at + timedelta(hours=10)
    assert cycle.assignment_failure_count == 0
    assert calculator_calls == [
        {
            "started_at": cycle.started_at,
            "duration": timedelta(hours=8),
            "society_id": society.id,
            "society_timezone": society.timezone,
            "calendar_version": 1,
        }
    ]


def test_missing_policy_rolls_back_submission_and_persists_conflict():
    society, resident, membership, ticket = create_resident_draft(
        registration_code="NIV-SLA-MISSING",
        phone="+919876543521",
    )

    result = submit_with_persisted_sla(
        society=society,
        resident=resident,
        membership=membership,
        ticket=ticket,
        calculator=lambda **kwargs: kwargs["started_at"] + timedelta(hours=8),
    )

    assert result.response_status == 409
    assert result.response_body["code"] == "SLA_POLICY_UNAVAILABLE"
    with transaction.atomic():
        set_local_society_id(society.id)
        ticket.refresh_from_db()
        record = IdempotencyRecord.objects.get()
        assert ticket.status == Ticket.Status.DRAFT
        assert SLACycle.objects.count() == 0
        assert TicketNumberSequence.objects.count() == 0
        assert TicketEvent.objects.count() == 0
    assert record.status == IdempotencyRecord.Status.COMPLETED
    assert record.response_body == result.response_body


def test_snapshot_validation_rejects_unknown_timezone_and_pause_reason():
    society = Society.objects.create(registration_code="NIV-SLA-VALIDATE")
    snapshot = SLAPolicySnapshot(
        society=society,
        policy_key="invalid",
        policy_version=1,
        calendar_version=1,
        society_timezone="Not/A-Timezone",
        acceptance_duration=timedelta(hours=1),
        initial_resolution_duration=timedelta(hours=2),
        reopen_resolution_duration=timedelta(hours=1),
        l3_delay=timedelta(0),
        permitted_pause_reasons=["NOT_SUPPORTED"],
        estimate_decision_duration=timedelta(hours=1),
    )

    with pytest.raises(ValidationError) as error:
        snapshot.full_clean()

    assert "society_timezone" in error.value.message_dict
    assert "permitted_pause_reasons" in error.value.message_dict


def test_business_calendar_validation_rejects_overlaps_and_duplicate_holidays():
    society = Society.objects.create(registration_code="NIV-CALENDAR-VALIDATE")
    calendar = BusinessCalendar(
        society=society,
        version=1,
        timezone=society.timezone,
        working_intervals=[
            {"weekday": 0, "start": "09:00", "end": "13:00"},
            {"weekday": 0, "start": "12:00", "end": "17:00"},
        ],
        holidays=["2026-08-31", "2026-08-31"],
    )

    with pytest.raises(ValidationError) as error:
        calendar.full_clean()

    assert "working_intervals" in error.value.message_dict
    assert "holidays" in error.value.message_dict


def test_used_calendar_is_immutable_and_can_be_replaced_atomically():
    society = Society.objects.create(registration_code="NIV-CALENDAR-HISTORY")
    calendar = create_calendar(society=society)
    replacement = create_calendar(society=society, version=2, is_active=False)
    create_snapshot(society=society)

    with pytest.raises(DatabaseError), transaction.atomic():
        set_local_society_id(society.id)
        BusinessCalendar.objects.filter(id=calendar.id).update(holidays=["2026-08-31"])

    with transaction.atomic():
        set_local_society_id(society.id)
        BusinessCalendar.objects.filter(id=calendar.id).update(
            is_active=False,
            retired_at=timezone.now(),
        )
        BusinessCalendar.objects.filter(id=replacement.id).update(is_active=True)

    with transaction.atomic():
        set_local_society_id(society.id)
        calendar.refresh_from_db()
        replacement.refresh_from_db()
        assert calendar.is_active is False
        assert calendar.retired_at is not None
        assert replacement.is_active is True
        assert replacement.retired_at is None


def test_sla_tables_enforce_tenant_relationships_rls_and_history():
    society, resident, membership, ticket = create_resident_draft(
        registration_code="NIV-SLA-TENANT-A",
        phone="+919876543522",
    )
    other_society = Society.objects.create(registration_code="NIV-SLA-TENANT-B")
    create_calendar(society=society)
    snapshot = create_snapshot(society=society)
    other_snapshot = create_snapshot(society=other_society)

    with pytest.raises(IntegrityError), transaction.atomic():
        set_local_society_id(society.id)
        SLAPolicyBinding.objects.create(
            society=society,
            category=ticket.category,
            priority=ticket.priority,
            snapshot_id=other_snapshot.id,
        )

    bind_snapshot(ticket=ticket, snapshot=snapshot)
    result = submit_with_persisted_sla(
        society=society,
        resident=resident,
        membership=membership,
        ticket=ticket,
        calculator=lambda **kwargs: kwargs["started_at"] + timedelta(hours=8),
    )

    with pytest.raises(DatabaseError), transaction.atomic():
        set_local_society_id(society.id)
        SLAPolicySnapshot.objects.filter(id=snapshot.id).update(policy_version=2)
    with pytest.raises(DatabaseError), transaction.atomic():
        set_local_society_id(society.id)
        SLACycle.objects.filter(id=result.response_body["sla_cycle_id"]).delete()

    assert SLAPolicySnapshot.objects.count() == 0
    assert SLAPolicyBinding.objects.count() == 0
    assert SLACycle.objects.count() == 0
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relname, relforcerowsecurity
            FROM pg_class
            WHERE relname IN (
                'tickets_sla_policy_snapshot',
                'tickets_sla_policy_binding',
                'tickets_sla_cycle',
                'tickets_business_calendar'
            )
            ORDER BY relname
            """
        )
        assert cursor.fetchall() == [
            ("tickets_business_calendar", True),
            ("tickets_sla_cycle", True),
            ("tickets_sla_policy_binding", True),
            ("tickets_sla_policy_snapshot", True),
        ]