import hashlib
import json
import re
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from apps.identity.models import User
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import (
    Block,
    Society,
    StaffMembership,
    TechnicianProfile,
    Unit,
    UnitOccupancy,
)
from apps.tickets.models import (
    BusinessCalendar,
    SLAPolicyBinding,
    SLAPolicySnapshot,
    Ticket,
    TicketCompletionChallenge,
    TicketSubCategory,
    TicketCategory,
)
from apps.tickets.services import (
    PersistInitialSLACycle,
    accept_in_house_assignment,
    assign_in_house_technician,
    business_calendar_deadline_calculator,
    create_ticket_draft,
    request_service_ticket_completion,
    start_ticket_work,
    submit_ticket,
    verify_service_ticket_completion,
)


class Command(BaseCommand):
    _FIXTURE_OTP = "451827"

    help = (
        "Create or reuse a marker-isolated resolved service ticket for local browser validation."
    )

    def add_arguments(self, parser):
        parser.add_argument("--enable", action="store_true")
        parser.add_argument("--society-code", default="NIVASOPS-DEV")
        parser.add_argument("--marker", default="browser-lifecycle")

    def handle(self, *args, **options):
        if not settings.DEBUG or not getattr(settings, "ALLOW_DEV_LIFECYCLE_FIXTURE", False):
            raise CommandError(
                "Development lifecycle fixtures require DEBUG=true and "
                "ALLOW_DEV_LIFECYCLE_FIXTURE=true."
            )
        if not options["enable"]:
            raise CommandError("Pass --enable to create a development lifecycle fixture.")

        marker = self._normalize_marker(options["marker"])
        society_code = options["society_code"].strip().upper()
        self._require_completion_schema()
        with transaction.atomic():
            society, _ = Society.objects.get_or_create(registration_code=society_code)
            fixture = self._create_or_reuse_fixture(society=society, marker=marker)
        self.stdout.write(json.dumps(fixture))

    @staticmethod
    def _require_completion_schema():
        required_table = TicketCompletionChallenge._meta.db_table
        if required_table not in connection.introspection.table_names():
            raise CommandError(
                f"Development lifecycle fixture requires database table '{required_table}'. "
                "Apply the required ticket migrations to an authorized non-production database first."
            )

    @staticmethod
    def _normalize_marker(value):
        marker = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", marker):
            raise CommandError(
                "Marker must contain 1-32 lowercase letters, digits, or hyphens "
                "and begin with a letter or digit."
            )
        return marker

    @staticmethod
    def _phone_for(marker, persona):
        digest = hashlib.sha256(f"{marker}:{persona}".encode()).hexdigest()
        return f"+919{int(digest[:8], 16) % 1_000_000_000:09d}"

    @staticmethod
    def _email_for(marker, persona):
        return f"dev-lifecycle-{marker}-{persona}@example.test"

    @staticmethod
    def _user_for(phone, email):
        user = User.objects.filter(phone=phone).first()
        if user is None:
            return User.objects.create_user(
                phone=phone,
                email=email,
                email_verified_at=timezone.now(),
            )
        if user.email_verified_at is None:
            user.email = email
            user.email_verified_at = timezone.now()
            user.save(update_fields=["email", "email_verified_at"])
        return user

    def _create_or_reuse_fixture(self, *, society, marker):
        short_marker = hashlib.sha256(marker.encode()).hexdigest()[:10].upper()
        description = f"[DEV-LIFECYCLE:{marker}] Browser validation fixture."
        resident = self._user_for(
            self._phone_for(marker, "resident"),
            self._email_for(marker, "resident"),
        )
        facility_manager = self._user_for(
            self._phone_for(marker, "facility-manager"),
            self._email_for(marker, "facility-manager"),
        )
        technician_user = self._user_for(
            self._phone_for(marker, "technician"),
            self._email_for(marker, "technician"),
        )

        with transaction.atomic():
            set_local_society_id(society.id)
            block, _ = Block.objects.get_or_create(
                society=society,
                code=f"DL{short_marker}",
                defaults={"name": f"Dev Lifecycle {marker}"},
            )
            unit, _ = Unit.objects.get_or_create(
                society=society,
                block=block,
                door_number=f"DL-{short_marker}",
            )
            resident_membership, _ = UnitOccupancy.objects.get_or_create(
                society=society,
                unit=unit,
                user=resident,
                defaults={
                    "occupancy_type": UnitOccupancy.OccupancyType.OWNER,
                    "is_primary_contact": True,
                },
            )
            facility_membership, _ = StaffMembership.objects.get_or_create(
                society=society,
                user=facility_manager,
                defaults={"role": StaffMembership.Role.FACILITY_MANAGER},
            )
            technician, _ = TechnicianProfile.objects.get_or_create(
                society=society,
                user=technician_user,
                defaults={"max_active_tickets": 1},
            )
            category_name = f"Dev Lifecycle {marker}"
            category, _ = TicketCategory.objects.get_or_create(
                society=society,
                normalized_name=category_name.casefold(),
                defaults={
                    "name": category_name,
                    "workflow_type": Ticket.WorkflowType.SERVICE,
                    "allows_unit_location": True,
                    "allows_common_area_location": False,
                    "allows_no_location": False,
                    "cost_responsibility": TicketCategory.CostResponsibility.RESIDENT_UNIT,
                    "completion_policy": TicketCategory.CompletionPolicy.RESIDENT_CONFIRMATION,
                },
            )
            subcategory_name = "Browser validation"
            subcategory, _ = TicketSubCategory.objects.get_or_create(
                society=society,
                category=category,
                normalized_name=subcategory_name.casefold(),
                defaults={
                    "name": subcategory_name,
                    "default_priority": TicketSubCategory.Priority.P2,
                },
            )
            calendar = BusinessCalendar.objects.filter(
                society=society,
                is_active=True,
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
            snapshot, _ = SLAPolicySnapshot.objects.get_or_create(
                society=society,
                policy_key=f"dev-lifecycle-{short_marker.lower()}",
                policy_version=1,
                defaults={
                    "calendar_version": calendar.version,
                    "society_timezone": society.timezone,
                    "acceptance_duration": timedelta(hours=2),
                    "initial_resolution_duration": timedelta(hours=8),
                    "reopen_resolution_duration": timedelta(hours=4),
                    "l3_delay": timedelta(hours=2),
                    "estimate_decision_duration": timedelta(hours=24),
                },
            )
            SLAPolicyBinding.objects.get_or_create(
                society=society,
                category=category,
                priority=subcategory.default_priority,
                defaults={"snapshot": snapshot},
            )
            ticket = Ticket.objects.filter(
                society=society,
                creator=resident,
                description=description,
            ).first()
            if ticket is not None:
                if ticket.status != Ticket.Status.RESOLVED:
                    raise CommandError(
                        f"Fixture marker '{marker}' already has a {ticket.status} ticket; "
                        "use a new marker rather than altering it."
                    )
                return self._result(marker=marker, ticket=ticket, resident=resident,
                                    facility_manager=facility_manager, technician=technician)

            correlation_id = uuid.uuid4()
            draft = create_ticket_draft(
                society=society,
                actor=resident,
                membership=resident_membership,
                workflow_type=Ticket.WorkflowType.SERVICE,
                category=category,
                subcategory=subcategory,
                unit=unit,
                common_area=None,
                title=f"Development lifecycle fixture {marker}",
                description=description,
                priority=subcategory.default_priority,
                idempotency_key=f"dev-lifecycle-{short_marker}-draft",
                route_template="dev-lifecycle-fixture/draft",
                correlation_id=correlation_id,
            )
            submitted = submit_ticket(
                society_id=society.id,
                ticket_id=draft.response_body["id"],
                actor=resident,
                membership=resident_membership,
                expected_version=draft.response_body["state_version"],
                idempotency_key=f"dev-lifecycle-{short_marker}-submit",
                route_template="dev-lifecycle-fixture/submit",
                correlation_id=correlation_id,
                create_sla_cycle=PersistInitialSLACycle(
                    calculate_deadline=business_calendar_deadline_calculator
                ),
            )
            assigned = assign_in_house_technician(
                society_id=society.id,
                ticket_id=draft.response_body["id"],
                technician_id=technician.id,
                actor=facility_manager,
                membership=facility_membership,
                expected_version=submitted.response_body["state_version"],
                idempotency_key=f"dev-lifecycle-{short_marker}-assign",
                route_template="dev-lifecycle-fixture/assign",
                correlation_id=correlation_id,
            )
            accepted = accept_in_house_assignment(
                society_id=society.id,
                ticket_id=draft.response_body["id"],
                actor=technician_user,
                membership=technician,
                expected_version=assigned.response_body["state_version"],
                idempotency_key=f"dev-lifecycle-{short_marker}-accept",
                route_template="dev-lifecycle-fixture/accept",
                correlation_id=correlation_id,
            )
            in_progress = start_ticket_work(
                society_id=society.id,
                ticket_id=draft.response_body["id"],
                actor=technician_user,
                membership=technician,
                expected_version=accepted.response_body["state_version"],
                idempotency_key=f"dev-lifecycle-{short_marker}-start",
                route_template="dev-lifecycle-fixture/start",
                correlation_id=correlation_id,
            )
            with patch(
                "apps.tickets.services.secrets.randbelow",
                return_value=int(self._FIXTURE_OTP),
            ):
                pending_confirmation = request_service_ticket_completion(
                    society_id=society.id,
                    ticket_id=draft.response_body["id"],
                    actor=technician_user,
                    membership=technician,
                    expected_version=in_progress.response_body["state_version"],
                    work_notes="Development fixture work completed.",
                    idempotency_key=f"dev-lifecycle-{short_marker}-completion",
                    route_template="dev-lifecycle-fixture/request-completion",
                    correlation_id=correlation_id,
                )
            verified = verify_service_ticket_completion(
                society_id=society.id,
                ticket_id=draft.response_body["id"],
                actor=resident,
                membership=resident_membership,
                expected_version=pending_confirmation.response_body["state_version"],
                otp=self._FIXTURE_OTP,
                idempotency_key=f"dev-lifecycle-{short_marker}-verify",
                route_template="dev-lifecycle-fixture/verify-completion",
                correlation_id=correlation_id,
            )
            ticket = Ticket.objects.get(id=verified.response_body["id"])
            return self._result(marker=marker, ticket=ticket, resident=resident,
                                facility_manager=facility_manager, technician=technician)

    @staticmethod
    def _result(*, marker, ticket, resident, facility_manager, technician):
        return {
            "marker": marker,
            "society_id": str(ticket.society_id),
            "ticket_id": str(ticket.id),
            "ticket_number": ticket.ticket_number,
            "status": ticket.status,
            "state_version": ticket.state_version,
            "resident_user_id": str(resident.id),
            "facility_manager_user_id": str(facility_manager.id),
            "technician_id": str(technician.id),
        }