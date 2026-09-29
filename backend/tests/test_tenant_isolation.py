import uuid

import pytest
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.transaction import TransactionManagementError

from apps.identity.models import User
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import Block, Society, StaffMembership, Unit
from apps.tickets.models import (
    Ticket,
    TicketCategory,
    TicketEstimate,
    TicketFeedback,
    TicketSubCategory,
)

LIFECYCLE_TABLE_POLICIES = {
    "tickets_ticket_completion_challenge": "tickets_challenge_society_isolation",
    "tickets_ticket_estimate": "tickets_estimate_society_isolation",
    "tickets_ticket_estimate_line_item": "tickets_estimate_item_society_isolation",
    "tickets_ticket_feedback": "tickets_feedback_society_isolation",
    "tickets_ticket_merge_record": "tickets_merge_society_isolation",
}

LIFECYCLE_TABLE_CONSTRAINTS = {
    "tickets_ticket_completion_challenge": {
        "tickets_challenge_society_ticket_fk",
        "tickets_challenge_society_assignment_fk",
    },
    "tickets_ticket_estimate": {
        "tickets_estimate_society_ticket_fk",
        "tickets_estimate_society_assignment_fk",
        "tickets_estimate_amounts_valid",
    },
    "tickets_ticket_estimate_line_item": {
        "tickets_estimate_item_society_estimate_fk",
        "tickets_estimate_item_amounts_valid",
    },
    "tickets_ticket_feedback": {
        "tickets_feedback_society_ticket_fk",
        "tickets_feedback_society_technician_fk",
        "tickets_feedback_society_vendor_contract_fk",
    },
    "tickets_ticket_merge_record": {
        "tickets_merge_society_primary_ticket_fk",
        "tickets_merge_society_secondary_ticket_fk",
    },
}


@pytest.fixture
def tenant_records(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        society_a = Society.objects.create(registration_code="NIV-RLS-A")
        society_b = Society.objects.create(registration_code="NIV-RLS-B")
        user_a = User.objects.create_user(phone="+919876543201")
        user_b = User.objects.create_user(phone="+919876543202")

        with transaction.atomic():
            set_local_society_id(society_a.id)
            StaffMembership.objects.create(
                society=society_a,
                user=user_a,
                role=StaffMembership.Role.FACILITY_MANAGER,
            )

        with transaction.atomic():
            set_local_society_id(society_b.id)
            StaffMembership.objects.create(
                society=society_b,
                user=user_b,
                role=StaffMembership.Role.HELPDESK_OPERATOR,
            )

    return society_a, society_b, user_b


def create_lifecycle_ticket(*, society, creator, suffix):
    with transaction.atomic():
        set_local_society_id(society.id)
        block = Block.objects.create(
            society=society,
            name=f"Lifecycle block {suffix}",
            code=suffix,
        )
        unit = Unit.objects.create(society=society, block=block, door_number="101")
        category = TicketCategory.objects.create(
            society=society,
            name=f"Lifecycle plumbing {suffix}",
            normalized_name=f"lifecycle plumbing {suffix}".casefold(),
            workflow_type=Ticket.WorkflowType.SERVICE,
            allows_unit_location=True,
            cost_responsibility=TicketCategory.CostResponsibility.SOCIETY,
            completion_policy=TicketCategory.CompletionPolicy.RESIDENT_CONFIRMATION,
        )
        subcategory = TicketSubCategory.objects.create(
            society=society,
            category=category,
            name=f"Lifecycle leak {suffix}",
            normalized_name=f"lifecycle leak {suffix}".casefold(),
            default_priority=TicketSubCategory.Priority.P2,
        )
        return Ticket.objects.create(
            society=society,
            creator=creator,
            category=category,
            subcategory=subcategory,
            workflow_type=Ticket.WorkflowType.SERVICE,
            unit=unit,
            title="Lifecycle integrity test",
            description="Database enforcement fixture.",
            priority=TicketSubCategory.Priority.P2,
        )


@pytest.fixture
def lifecycle_enforcement_records(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        society_a = Society.objects.create(registration_code="NIV-LIFECYCLE-A")
        society_b = Society.objects.create(registration_code="NIV-LIFECYCLE-B")
        user_a = User.objects.create_user(phone="+919876543211")
        user_b = User.objects.create_user(phone="+919876543212")
        ticket_a = create_lifecycle_ticket(
            society=society_a,
            creator=user_a,
            suffix="LCA",
        )
        ticket_b = create_lifecycle_ticket(
            society=society_b,
            creator=user_b,
            suffix="LCB",
        )

    return society_a, society_b, user_a, user_b, ticket_a, ticket_b


def estimate_values(*, society, ticket, created_by, total_amount="10.00"):
    return {
        "society": society,
        "ticket": ticket,
        "created_by": created_by,
        "status": TicketEstimate.Status.DRAFT,
        "cost_responsibility": TicketCategory.CostResponsibility.SOCIETY,
        "subtotal_amount": "10.00",
        "tax_amount": "0.00",
        "total_amount": total_amount,
    }


@pytest.mark.django_db(transaction=True)
def test_rls_policy_is_enabled_and_forced():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE oid = 'tenancy_staff_membership'::regclass
            """
        )
        rls_enabled, rls_forced = cursor.fetchone()
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM pg_policies
            WHERE schemaname = current_schema()
              AND tablename = 'tenancy_staff_membership'
              AND policyname = 'tenancy_staff_society_isolation'
            """
        )
        policy_count = cursor.fetchone()[0]
        cursor.execute(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        role_bypasses_rls = cursor.fetchone()[0]
        constraints = connection.introspection.get_constraints(
            cursor, "tenancy_staff_membership"
        )

    assert rls_enabled is True
    assert rls_forced is True
    assert policy_count == 1
    assert role_bypasses_rls is False
    assert constraints["tenancy_staff_society_id_uniq"]["unique"] is True
    assert constraints["tenancy_staff_society_id_uniq"]["columns"] == ["society_id", "id"]


@pytest.mark.django_db(transaction=True)
def test_lifecycle_ticket_tables_have_tenant_integrity_guards():
    with connection.cursor() as cursor:
        for table_name, policy_name in LIFECYCLE_TABLE_POLICIES.items():
            cursor.execute(
                """
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE oid = %s::regclass
                """,
                [table_name],
            )
            rls_enabled, rls_forced = cursor.fetchone()
            cursor.execute(
                """
                SELECT policyname
                FROM pg_policies
                WHERE schemaname = current_schema()
                  AND tablename = %s
                """,
                [table_name],
            )
            policies = {row[0] for row in cursor.fetchall()}
            cursor.execute(
                "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass",
                [table_name],
            )
            constraints = {row[0] for row in cursor.fetchall()}

            assert rls_enabled is True
            assert rls_forced is True
            assert policies == {policy_name}
            assert LIFECYCLE_TABLE_CONSTRAINTS[table_name] <= constraints

        cursor.execute(
            """
            SELECT tgname
            FROM pg_trigger
            WHERE tgrelid = 'tickets_ticket_feedback'::regclass
              AND NOT tgisinternal
            """
        )
        triggers = {row[0] for row in cursor.fetchall()}

    assert "tickets_feedback_immutable" in triggers


@pytest.mark.django_db(transaction=True)
def test_lifecycle_estimate_rls_rejects_cross_society_write(
    lifecycle_enforcement_records,
):
    society_a, society_b, _, user_b, _, ticket_b = lifecycle_enforcement_records

    with pytest.raises(DatabaseError, match="row-level security"):
        with transaction.atomic():
            set_local_society_id(society_a.id)
            TicketEstimate.objects.create(
                **estimate_values(
                    society=society_b,
                    ticket=ticket_b,
                    created_by=user_b,
                )
            )


@pytest.mark.django_db(transaction=True)
def test_lifecycle_estimate_composite_ticket_fk_rejects_cross_society_ticket(
    lifecycle_enforcement_records,
):
    society_a, _, user_a, _, _, ticket_b = lifecycle_enforcement_records

    with pytest.raises(IntegrityError, match="tickets_estimate_society_ticket_fk"):
        with transaction.atomic():
            set_local_society_id(society_a.id)
            TicketEstimate.objects.create(
                **estimate_values(
                    society=society_a,
                    ticket=ticket_b,
                    created_by=user_a,
                )
            )


@pytest.mark.django_db(transaction=True)
def test_lifecycle_estimate_amount_check_rejects_mismatched_total(
    lifecycle_enforcement_records,
):
    society_a, _, user_a, _, ticket_a, _ = lifecycle_enforcement_records

    with pytest.raises(IntegrityError, match="tickets_estimate_amounts_valid"):
        with transaction.atomic():
            set_local_society_id(society_a.id)
            TicketEstimate.objects.create(
                **estimate_values(
                    society=society_a,
                    ticket=ticket_a,
                    created_by=user_a,
                    total_amount="9.99",
                )
            )


@pytest.mark.django_db(transaction=True)
def test_lifecycle_feedback_rejects_mutation(lifecycle_enforcement_records):
    society_a, _, user_a, _, ticket_a, _ = lifecycle_enforcement_records

    with transaction.atomic():
        set_local_society_id(society_a.id)
        feedback = TicketFeedback.objects.create(
            society=society_a,
            ticket=ticket_a,
            resident=user_a,
            overall_rating=5,
            comment="Original feedback.",
        )

    with pytest.raises(DatabaseError, match="Ticket feedback is immutable"):
        with transaction.atomic():
            set_local_society_id(society_a.id)
            TicketFeedback.objects.filter(id=feedback.id).update(comment="Changed feedback.")

    with pytest.raises(DatabaseError, match="Ticket feedback is immutable"):
        with transaction.atomic():
            set_local_society_id(society_a.id)
            TicketFeedback.objects.filter(id=feedback.id).delete()


@pytest.mark.django_db(transaction=True)
def test_rls_limits_reads_and_writes_to_transaction_tenant(tenant_records):
    society_a, society_b, user_b = tenant_records

    assert StaffMembership.objects.count() == 0

    with transaction.atomic():
        set_local_society_id(society_a.id)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT society_id FROM tenancy_staff_membership ORDER BY society_id"
            )
            visible_societies = [row[0] for row in cursor.fetchall()]

    assert visible_societies == [society_a.id]

    connection.ensure_connection()
    reused_connection = connection.connection
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('app.society_id', true)")
            retained_tenant_context = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM tenancy_staff_membership")
            visible_memberships = cursor.fetchone()[0]

    assert connection.connection is reused_connection
    assert not retained_tenant_context
    assert visible_memberships == 0

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.society_id', 'not-a-uuid', true)")
        assert StaffMembership.objects.count() == 0

    with pytest.raises(DatabaseError, match="row-level security"):
        with transaction.atomic():
            set_local_society_id(society_a.id)
            StaffMembership.objects.create(
                society=society_b,
                user=user_b,
                role=StaffMembership.Role.ESTATE_SUPERVISOR,
            )

    assert StaffMembership.objects.count() == 0

    with pytest.raises(RuntimeError, match="force rollback"):
        with transaction.atomic():
            set_local_society_id(society_b.id)
            assert StaffMembership.objects.count() == 1
            raise RuntimeError("force rollback")

    assert StaffMembership.objects.count() == 0

    connection.close()

    assert StaffMembership.objects.count() == 0


def test_tenant_context_rejects_invalid_uuid_before_database_access():
    with pytest.raises(ValueError, match="valid UUID"):
        set_local_society_id("not-a-uuid")


@pytest.mark.django_db(transaction=True)
def test_tenant_context_requires_atomic_transaction():
    with pytest.raises(TransactionManagementError, match="transaction.atomic"):
        set_local_society_id(uuid.UUID("36aa20f9-7b9e-4f99-8d32-7218d661449a"))