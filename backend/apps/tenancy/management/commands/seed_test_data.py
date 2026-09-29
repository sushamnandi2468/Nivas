import datetime
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

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
from apps.tickets.completion_delivery import retrieve_completion_otp_capsule
from apps.tickets.models import (
    BusinessCalendar,
    SLAPolicyBinding,
    SLAPolicySnapshot,
    Ticket,
    TicketCategory,
    TicketCompletionChallenge,
    TicketSubCategory,
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
    submit_ticket_feedback,
    verify_service_ticket_completion,
)


class Command(BaseCommand):
    help = "Seed rich multi-tenant societies, role-based users, vendors, calendars, and tickets for comprehensive testing."

    DEFAULT_PASSWORD = "TestPass@123"

    SOCIETY_PALM_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
    SOCIETY_GREEN_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

    def handle(self, *args, **options):
        self.stdout.write("Starting test data seeding...")

        # 1. Seed Palm Meadows
        palm_data = self._seed_palm_meadows()

        # 2. Seed Green Valley (cross-tenant isolation)
        green_data = self._seed_green_valley()

        self.stdout.write(self.style.SUCCESS("\nSuccessfully seeded test data!"))
        self.stdout.write(f"\n--- Palm Meadows Residency ---")
        self.stdout.write(f"Society ID: {self.SOCIETY_PALM_ID}")
        self.stdout.write(f"Registration Code: PALM-MEADOWS")
        self.stdout.write(f"Facility Manager: fm.palm@nivas.local")
        self.stdout.write(f"Resident (Owner A-101): resident.a101@nivas.local")
        self.stdout.write(f"Resident (Tenant A-102): resident.a102@nivas.local")
        self.stdout.write(f"Technician: tech.ramesh@nivas.local")
        self.stdout.write(f"Vendor Dispatcher: dispatcher.apex@nivas.local")
        self.stdout.write(f"Vendor Worker: worker.vikram@nivas.local")
        self.stdout.write(f"Committee President: president.palm@nivas.local")
        self.stdout.write(f"Password for all users: {self.DEFAULT_PASSWORD}\n")

        self.stdout.write(f"--- Green Valley Enclave (Cross-Tenant) ---")
        self.stdout.write(f"Society ID: {self.SOCIETY_GREEN_ID}")
        self.stdout.write(f"Registration Code: GREEN-VALLEY")
        self.stdout.write(f"Facility Manager: fm.green@nivas.local")
        self.stdout.write(f"Resident: resident.green@nivas.local")
        self.stdout.write(f"Password for all users: {self.DEFAULT_PASSWORD}\n")

    def _get_or_create_user(self, email: str, phone: str) -> User:
        email_clean = email.strip().casefold()
        user = User.objects.filter(email=email_clean).first()
        if user is None:
            user = User.objects.filter(phone=phone).first()
        if user is None:
            user = User.objects.create_user(
                phone=phone,
                email=email_clean,
                email_verified_at=timezone.now(),
                is_active=True,
            )
            user.set_password(self.DEFAULT_PASSWORD)
            user.save()
        else:
            user.email = email_clean
            user.phone = phone
            user.email_verified_at = timezone.now()
            user.is_active = True
            user.set_password(self.DEFAULT_PASSWORD)
            user.save()
        return user

    def _seed_palm_meadows(self):
        society, _ = Society.objects.get_or_create(
            id=self.SOCIETY_PALM_ID,
            defaults={
                "registration_code": "PALM-MEADOWS",
                "timezone": "Asia/Kolkata",
                "locale": "en-IN",
                "currency": "INR",
                "is_active": True,
            },
        )

        with transaction.atomic():
            set_local_society_id(society.id)

            # Blocks
            block_a, _ = Block.objects.get_or_create(
                society=society,
                code="BLK-A",
                defaults={"name": "Tower A - Palm Heights", "is_active": True},
            )
            block_b, _ = Block.objects.get_or_create(
                society=society,
                code="BLK-B",
                defaults={"name": "Tower B - Meadow View", "is_active": True},
            )

            # Units
            unit_a101, _ = Unit.objects.get_or_create(
                society=society, block=block_a, door_number="A-101", defaults={"is_active": True}
            )
            unit_a102, _ = Unit.objects.get_or_create(
                society=society, block=block_a, door_number="A-102", defaults={"is_active": True}
            )
            unit_b201, _ = Unit.objects.get_or_create(
                society=society, block=block_b, door_number="B-201", defaults={"is_active": True}
            )
            unit_b202, _ = Unit.objects.get_or_create(
                society=society, block=block_b, door_number="B-202", defaults={"is_active": True}
            )

            # Common Areas
            ca_clubhouse, _ = CommonArea.objects.get_or_create(
                society=society,
                normalized_name="clubhouse & community hall",
                defaults={"name": "Clubhouse & Community Hall", "is_active": True},
            )
            ca_pool, _ = CommonArea.objects.get_or_create(
                society=society,
                normalized_name="swimming pool deck",
                defaults={"name": "Swimming Pool Deck", "is_active": True},
            )
            ca_lobby, _ = CommonArea.objects.get_or_create(
                society=society,
                normalized_name="main entrance lobby",
                defaults={"name": "Main Entrance Lobby", "is_active": True},
            )

            # Users
            u_fm = self._get_or_create_user("fm.palm@nivas.local", "+919800000001")
            u_helpdesk = self._get_or_create_user("helpdesk.palm@nivas.local", "+919800000010")
            u_res_owner = self._get_or_create_user("resident.a101@nivas.local", "+919800000002")
            u_res_tenant = self._get_or_create_user("resident.a102@nivas.local", "+919800000003")
            u_res_b201 = self._get_or_create_user("resident.b201@nivas.local", "+919800000012")
            u_tech_ramesh = self._get_or_create_user("tech.ramesh@nivas.local", "+919800000004")
            u_tech_suresh = self._get_or_create_user("tech.suresh@nivas.local", "+919800000013")
            u_president = self._get_or_create_user("president.palm@nivas.local", "+919800000007")
            u_treasurer = self._get_or_create_user("treasurer.palm@nivas.local", "+919800000011")
            u_disp_apex = self._get_or_create_user("dispatcher.apex@nivas.local", "+919811111102")
            u_worker_vikram = self._get_or_create_user("worker.vikram@nivas.local", "+919811111103")

            # Memberships
            fm_membership, _ = StaffMembership.objects.get_or_create(
                society=society,
                user=u_fm,
                defaults={"role": StaffMembership.Role.FACILITY_MANAGER, "is_active": True},
            )
            helpdesk_membership, _ = StaffMembership.objects.get_or_create(
                society=society,
                user=u_helpdesk,
                defaults={"role": StaffMembership.Role.HELPDESK_OPERATOR, "is_active": True},
            )

            occ_a101, _ = UnitOccupancy.objects.get_or_create(
                society=society,
                unit=unit_a101,
                user=u_res_owner,
                defaults={
                    "occupancy_type": UnitOccupancy.OccupancyType.OWNER,
                    "is_primary_contact": True,
                    "can_approve_costs": True,
                    "is_active": True,
                },
            )
            occ_a102, _ = UnitOccupancy.objects.get_or_create(
                society=society,
                unit=unit_a102,
                user=u_res_tenant,
                defaults={
                    "occupancy_type": UnitOccupancy.OccupancyType.TENANT,
                    "is_primary_contact": True,
                    "can_approve_costs": False,
                    "is_active": True,
                },
            )
            occ_b201, _ = UnitOccupancy.objects.get_or_create(
                society=society,
                unit=unit_b201,
                user=u_res_b201,
                defaults={
                    "occupancy_type": UnitOccupancy.OccupancyType.OWNER,
                    "is_primary_contact": True,
                    "can_approve_costs": True,
                    "is_active": True,
                },
            )

            comm_pres, _ = CommitteeMembership.objects.get_or_create(
                society=society,
                user=u_president,
                defaults={"role": CommitteeMembership.Role.PRESIDENT, "is_active": True},
            )
            comm_treas, _ = CommitteeMembership.objects.get_or_create(
                society=society,
                user=u_treasurer,
                defaults={"role": CommitteeMembership.Role.TREASURER, "is_active": True},
            )

            tech_ramesh, _ = TechnicianProfile.objects.get_or_create(
                society=society,
                user=u_tech_ramesh,
                defaults={"max_active_tickets": 5, "is_active": True},
            )
            tech_suresh, _ = TechnicianProfile.objects.get_or_create(
                society=society,
                user=u_tech_suresh,
                defaults={"max_active_tickets": 4, "is_active": True},
            )

            # Vendor & Contract
            vendor_apex, _ = Vendor.objects.get_or_create(
                society=society,
                normalized_company_name="apex facility management pvt ltd",
                defaults={
                    "company_name": "Apex Facility Management Pvt Ltd",
                    "contact_person": "Sunil Verma",
                    "phone_number": "+919811111101",
                    "email": "contact@apexfacility.in",
                    "is_active": True,
                },
            )
            contract_apex, _ = VendorContract.objects.get_or_create(
                society=society,
                vendor=vendor_apex,
                starts_on=timezone.localdate() - timedelta(days=60),
                ends_on=timezone.localdate() + timedelta(days=300),
                defaults={"max_active_tickets": 10, "is_active": True},
            )
            v_staff_disp, _ = VendorStaffMembership.objects.get_or_create(
                society=society,
                vendor=vendor_apex,
                contract=contract_apex,
                user=u_disp_apex,
                defaults={"role": VendorStaffMembership.Role.DISPATCHER, "is_active": True},
            )
            v_staff_worker, _ = VendorStaffMembership.objects.get_or_create(
                society=society,
                vendor=vendor_apex,
                contract=contract_apex,
                user=u_worker_vikram,
                defaults={"role": VendorStaffMembership.Role.WORKER, "is_active": True},
            )

            # Business Calendar
            calendar = BusinessCalendar.objects.filter(society=society, is_active=True).first()
            if calendar is None:
                calendar = BusinessCalendar.objects.create(
                    society=society,
                    version=1,
                    timezone=society.timezone,
                    working_intervals=[
                        {"weekday": d, "start": "09:00", "end": "18:00"}
                        for d in range(6)
                    ],
                )

            # Categories & Subcategories
            cat_plumbing, _ = TicketCategory.objects.get_or_create(
                society=society,
                normalized_name="plumbing",
                defaults={
                    "name": "Plumbing",
                    "workflow_type": TicketCategory.WorkflowType.SERVICE,
                    "allows_unit_location": True,
                    "allows_common_area_location": True,
                    "allows_no_location": False,
                    "cost_responsibility": TicketCategory.CostResponsibility.RESIDENT_UNIT,
                    "completion_policy": TicketCategory.CompletionPolicy.RESIDENT_CONFIRMATION,
                    "is_active": True,
                },
            )
            subcat_leak, _ = TicketSubCategory.objects.get_or_create(
                society=society,
                category=cat_plumbing,
                normalized_name="pipe leak / burst",
                defaults={"name": "Pipe Leak / Burst", "default_priority": TicketSubCategory.Priority.P1, "is_active": True},
            )
            subcat_tap, _ = TicketSubCategory.objects.get_or_create(
                society=society,
                category=cat_plumbing,
                normalized_name="tap / faucet repair",
                defaults={"name": "Tap / Faucet Repair", "default_priority": TicketSubCategory.Priority.P3, "is_active": True},
            )

            cat_electrical, _ = TicketCategory.objects.get_or_create(
                society=society,
                normalized_name="electrical",
                defaults={
                    "name": "Electrical",
                    "workflow_type": TicketCategory.WorkflowType.SERVICE,
                    "allows_unit_location": True,
                    "allows_common_area_location": True,
                    "allows_no_location": False,
                    "cost_responsibility": TicketCategory.CostResponsibility.RESIDENT_UNIT,
                    "completion_policy": TicketCategory.CompletionPolicy.RESIDENT_CONFIRMATION,
                    "is_active": True,
                },
            )
            subcat_mcb, _ = TicketSubCategory.objects.get_or_create(
                society=society,
                category=cat_electrical,
                normalized_name="mcb trip / power outage",
                defaults={"name": "MCB Trip / Power Outage", "default_priority": TicketSubCategory.Priority.P1, "is_active": True},
            )
            subcat_switch, _ = TicketSubCategory.objects.get_or_create(
                society=society,
                category=cat_electrical,
                normalized_name="switchboard fault",
                defaults={"name": "Switchboard Fault", "default_priority": TicketSubCategory.Priority.P2, "is_active": True},
            )

            cat_common, _ = TicketCategory.objects.get_or_create(
                society=society,
                normalized_name="common area maintenance",
                defaults={
                    "name": "Common Area Maintenance",
                    "workflow_type": TicketCategory.WorkflowType.SERVICE,
                    "allows_unit_location": False,
                    "allows_common_area_location": True,
                    "allows_no_location": False,
                    "cost_responsibility": TicketCategory.CostResponsibility.SOCIETY,
                    "completion_policy": TicketCategory.CompletionPolicy.RESIDENT_CONFIRMATION,
                    "is_active": True,
                },
            )
            subcat_lift, _ = TicketSubCategory.objects.get_or_create(
                society=society,
                category=cat_common,
                normalized_name="elevator / lift malfunction",
                defaults={"name": "Elevator / Lift Malfunction", "default_priority": TicketSubCategory.Priority.P1, "is_active": True},
            )

            cat_gov, _ = TicketCategory.objects.get_or_create(
                society=society,
                normalized_name="civic & governance",
                defaults={
                    "name": "Civic & Governance",
                    "workflow_type": TicketCategory.WorkflowType.GOVERNANCE,
                    "allows_unit_location": False,
                    "allows_common_area_location": False,
                    "allows_no_location": True,
                    "cost_responsibility": TicketCategory.CostResponsibility.SOCIETY,
                    "completion_policy": TicketCategory.CompletionPolicy.GOVERNANCE_RESOLUTION,
                    "is_active": True,
                },
            )
            subcat_parking, _ = TicketSubCategory.objects.get_or_create(
                society=society,
                category=cat_gov,
                normalized_name="parking dispute",
                defaults={"name": "Parking Dispute", "default_priority": TicketSubCategory.Priority.P3, "is_active": True},
            )
            subcat_noise, _ = TicketSubCategory.objects.get_or_create(
                society=society,
                category=cat_gov,
                normalized_name="noise complaint",
                defaults={"name": "Noise Complaint", "default_priority": TicketSubCategory.Priority.P3, "is_active": True},
            )

            # SLA Snapshots & Bindings
            sla_snapshot, _ = SLAPolicySnapshot.objects.get_or_create(
                society=society,
                policy_key="palm-standard-sla",
                policy_version=1,
                defaults={
                    "calendar_version": calendar.version,
                    "society_timezone": society.timezone,
                    "acceptance_duration": timedelta(hours=2),
                    "initial_resolution_duration": timedelta(hours=12),
                    "reopen_resolution_duration": timedelta(hours=6),
                    "l3_delay": timedelta(hours=2),
                    "estimate_decision_duration": timedelta(hours=24),
                },
            )

            for cat in [cat_plumbing, cat_electrical, cat_common, cat_gov]:
                for prio in ["P1", "P2", "P3", "P4"]:
                    SLAPolicyBinding.objects.get_or_create(
                        society=society,
                        category=cat,
                        priority=prio,
                        defaults={"snapshot": sla_snapshot, "is_active": True},
                    )

            # 6. Seed Sample Tickets Across Lifecycle States
            # 6a. Draft Ticket
            t_draft_exists = Ticket.objects.filter(society=society, title="Leaking Kitchen Tap Draft").exists()
            if not t_draft_exists:
                create_ticket_draft(
                    society=society,
                    actor=u_res_owner,
                    membership=occ_a101,
                    workflow_type=Ticket.WorkflowType.SERVICE,
                    category=cat_plumbing,
                    subcategory=subcat_tap,
                    unit=unit_a101,
                    common_area=None,
                    title="Leaking Kitchen Tap Draft",
                    description="Tap dripping continuously since yesterday. Needs washer replacement.",
                    priority=TicketSubCategory.Priority.P3,
                    idempotency_key="seed-palm-ticket-draft",
                    route_template="seed/draft",
                    correlation_id=uuid.uuid4(),
                )

            # 6b. Submitted Ticket
            t_sub_exists = Ticket.objects.filter(society=society, title="Master Bedroom Switch Sparking").exists()
            if not t_sub_exists:
                t_sub_draft = create_ticket_draft(
                    society=society,
                    actor=u_res_tenant,
                    membership=occ_a102,
                    workflow_type=Ticket.WorkflowType.SERVICE,
                    category=cat_electrical,
                    subcategory=subcat_switch,
                    unit=unit_a102,
                    common_area=None,
                    title="Master Bedroom Switch Sparking",
                    description="Switchboard produces spark when turning on the AC switch.",
                    priority=TicketSubCategory.Priority.P2,
                    idempotency_key="seed-palm-sub-draft",
                    route_template="seed/draft",
                    correlation_id=uuid.uuid4(),
                )
                submit_ticket(
                    society_id=society.id,
                    ticket_id=t_sub_draft.response_body["id"],
                    actor=u_res_tenant,
                    membership=occ_a102,
                    expected_version=t_sub_draft.response_body["state_version"],
                    idempotency_key="seed-palm-sub-submit",
                    route_template="seed/submit",
                    correlation_id=uuid.uuid4(),
                    create_sla_cycle=PersistInitialSLACycle(
                        calculate_deadline=business_calendar_deadline_calculator
                    ),
                )

            # 6c. In-Progress Ticket (Assigned to Ramesh and Work Started)
            t_prog_exists = Ticket.objects.filter(society=society, title="Bathroom Main Pipe Leak").exists()
            if not t_prog_exists:
                t_prog_draft = create_ticket_draft(
                    society=society,
                    actor=u_res_b201,
                    membership=occ_b201,
                    workflow_type=Ticket.WorkflowType.SERVICE,
                    category=cat_plumbing,
                    subcategory=subcat_leak,
                    unit=unit_b201,
                    common_area=None,
                    title="Bathroom Main Pipe Leak",
                    description="Urgent water seepage in bathroom wall.",
                    priority=TicketSubCategory.Priority.P1,
                    idempotency_key="seed-palm-prog-draft",
                    route_template="seed/draft",
                    correlation_id=uuid.uuid4(),
                )
                t_prog_sub = submit_ticket(
                    society_id=society.id,
                    ticket_id=t_prog_draft.response_body["id"],
                    actor=u_res_b201,
                    membership=occ_b201,
                    expected_version=t_prog_draft.response_body["state_version"],
                    idempotency_key="seed-palm-prog-submit",
                    route_template="seed/submit",
                    correlation_id=uuid.uuid4(),
                    create_sla_cycle=PersistInitialSLACycle(
                        calculate_deadline=business_calendar_deadline_calculator
                    ),
                )
                t_prog_assigned = assign_in_house_technician(
                    society_id=society.id,
                    ticket_id=t_prog_draft.response_body["id"],
                    technician_id=tech_ramesh.id,
                    actor=u_fm,
                    membership=fm_membership,
                    expected_version=t_prog_sub.response_body["state_version"],
                    idempotency_key="seed-palm-prog-assign",
                    route_template="seed/assign",
                    correlation_id=uuid.uuid4(),
                )
                t_prog_accepted = accept_in_house_assignment(
                    society_id=society.id,
                    ticket_id=t_prog_draft.response_body["id"],
                    actor=u_tech_ramesh,
                    membership=tech_ramesh,
                    expected_version=t_prog_assigned.response_body["state_version"],
                    idempotency_key="seed-palm-prog-accept",
                    route_template="seed/accept",
                    correlation_id=uuid.uuid4(),
                )
                start_ticket_work(
                    society_id=society.id,
                    ticket_id=t_prog_draft.response_body["id"],
                    actor=u_tech_ramesh,
                    membership=tech_ramesh,
                    expected_version=t_prog_accepted.response_body["state_version"],
                    idempotency_key="seed-palm-prog-start",
                    route_template="seed/start",
                    correlation_id=uuid.uuid4(),
                )

            # 6d. Resolved Ticket with Feedback
            t_res_exists = Ticket.objects.filter(society=society, title="Balcony Light Fixture Replaced").exists()
            if not t_res_exists:
                t_res_draft = create_ticket_draft(
                    society=society,
                    actor=u_res_owner,
                    membership=occ_a101,
                    workflow_type=Ticket.WorkflowType.SERVICE,
                    category=cat_electrical,
                    subcategory=subcat_mcb,
                    unit=unit_a101,
                    common_area=None,
                    title="Balcony Light Fixture Replaced",
                    description="Balcony bulb holder was broken.",
                    priority=TicketSubCategory.Priority.P1,
                    idempotency_key="seed-palm-res-draft",
                    route_template="seed/draft",
                    correlation_id=uuid.uuid4(),
                )
                t_res_sub = submit_ticket(
                    society_id=society.id,
                    ticket_id=t_res_draft.response_body["id"],
                    actor=u_res_owner,
                    membership=occ_a101,
                    expected_version=t_res_draft.response_body["state_version"],
                    idempotency_key="seed-palm-res-submit",
                    route_template="seed/submit",
                    correlation_id=uuid.uuid4(),
                    create_sla_cycle=PersistInitialSLACycle(
                        calculate_deadline=business_calendar_deadline_calculator
                    ),
                )
                t_res_assigned = assign_in_house_technician(
                    society_id=society.id,
                    ticket_id=t_res_draft.response_body["id"],
                    technician_id=tech_ramesh.id,
                    actor=u_fm,
                    membership=fm_membership,
                    expected_version=t_res_sub.response_body["state_version"],
                    idempotency_key="seed-palm-res-assign",
                    route_template="seed/assign",
                    correlation_id=uuid.uuid4(),
                )
                t_res_accepted = accept_in_house_assignment(
                    society_id=society.id,
                    ticket_id=t_res_draft.response_body["id"],
                    actor=u_tech_ramesh,
                    membership=tech_ramesh,
                    expected_version=t_res_assigned.response_body["state_version"],
                    idempotency_key="seed-palm-res-accept",
                    route_template="seed/accept",
                    correlation_id=uuid.uuid4(),
                )
                t_res_started = start_ticket_work(
                    society_id=society.id,
                    ticket_id=t_res_draft.response_body["id"],
                    actor=u_tech_ramesh,
                    membership=tech_ramesh,
                    expected_version=t_res_accepted.response_body["state_version"],
                    idempotency_key="seed-palm-res-start",
                    route_template="seed/start",
                    correlation_id=uuid.uuid4(),
                )
                t_res_comp = request_service_ticket_completion(
                    society_id=society.id,
                    ticket_id=t_res_draft.response_body["id"],
                    actor=u_tech_ramesh,
                    membership=tech_ramesh,
                    expected_version=t_res_started.response_body["state_version"],
                    idempotency_key="seed-palm-res-complete-req",
                    route_template="seed/completion-request",
                    correlation_id=uuid.uuid4(),
                    work_notes="Replaced balcony holder with high durability brass fitting.",
                )
                # Verify completion with OTP
                challenge = TicketCompletionChallenge.objects.filter(
                    society_id=society.id, ticket_id=t_res_draft.response_body["id"]
                ).latest("created_at")
                otp_code = retrieve_completion_otp_capsule(capsule_name=challenge.delivery_capsule_name)
                t_res_verified = verify_service_ticket_completion(
                    society_id=society.id,
                    ticket_id=t_res_draft.response_body["id"],
                    actor=u_res_owner,
                    membership=occ_a101,
                    expected_version=t_res_comp.response_body["state_version"],
                    idempotency_key="seed-palm-res-verified",
                    route_template="seed/completion-verify",
                    correlation_id=uuid.uuid4(),
                    otp=otp_code,
                )
                submit_ticket_feedback(
                    society_id=society.id,
                    ticket_id=t_res_draft.response_body["id"],
                    actor=u_res_owner,
                    membership=occ_a101,
                    expected_version=t_res_verified.response_body["state_version"],
                    overall_rating=5,
                    comment="Excellent fast service by technician Ramesh.",
                    idempotency_key="seed-palm-res-feedback",
                    correlation_id=uuid.uuid4(),
                )

            # 6e. Governance Ticket
            t_gov_exists = Ticket.objects.filter(society=society, title="Late Night Noise in Clubhouse").exists()
            if not t_gov_exists:
                t_gov_draft = create_ticket_draft(
                    society=society,
                    actor=u_res_owner,
                    membership=occ_a101,
                    workflow_type=Ticket.WorkflowType.GOVERNANCE,
                    category=cat_gov,
                    subcategory=subcat_noise,
                    unit=None,
                    common_area=None,
                    title="Late Night Noise in Clubhouse",
                    description="Excessive music volume past 10:30 PM on weekends violates community guidelines.",
                    priority=TicketSubCategory.Priority.P3,
                    idempotency_key="seed-palm-gov-draft",
                    route_template="seed/draft",
                    correlation_id=uuid.uuid4(),
                )
                submit_ticket(
                    society_id=society.id,
                    ticket_id=t_gov_draft.response_body["id"],
                    actor=u_res_owner,
                    membership=occ_a101,
                    expected_version=t_gov_draft.response_body["state_version"],
                    idempotency_key="seed-palm-gov-submit",
                    route_template="seed/submit",
                    correlation_id=uuid.uuid4(),
                    create_sla_cycle=PersistInitialSLACycle(
                        calculate_deadline=business_calendar_deadline_calculator
                    ),
                )

        return society

    def _seed_green_valley(self):
        society, _ = Society.objects.get_or_create(
            id=self.SOCIETY_GREEN_ID,
            defaults={
                "registration_code": "GREEN-VALLEY",
                "timezone": "Asia/Kolkata",
                "locale": "en-IN",
                "currency": "INR",
                "is_active": True,
            },
        )

        with transaction.atomic():
            set_local_society_id(society.id)

            block_1, _ = Block.objects.get_or_create(
                society=society,
                code="BLK-1",
                defaults={"name": "Green Valley Block 1", "is_active": True},
            )
            unit_101, _ = Unit.objects.get_or_create(
                society=society, block=block_1, door_number="101", defaults={"is_active": True}
            )

            ca_garden, _ = CommonArea.objects.get_or_create(
                society=society,
                normalized_name="central garden",
                defaults={"name": "Central Garden", "is_active": True},
            )

            u_fm_green = self._get_or_create_user("fm.green@nivas.local", "+919800000008")
            u_res_green = self._get_or_create_user("resident.green@nivas.local", "+919800000009")

            StaffMembership.objects.get_or_create(
                society=society,
                user=u_fm_green,
                defaults={"role": StaffMembership.Role.FACILITY_MANAGER, "is_active": True},
            )
            UnitOccupancy.objects.get_or_create(
                society=society,
                unit=unit_101,
                user=u_res_green,
                defaults={
                    "occupancy_type": UnitOccupancy.OccupancyType.OWNER,
                    "is_primary_contact": True,
                    "can_approve_costs": True,
                    "is_active": True,
                },
            )

            calendar = BusinessCalendar.objects.filter(society=society, is_active=True).first()
            if calendar is None:
                calendar = BusinessCalendar.objects.create(
                    society=society,
                    version=1,
                    timezone=society.timezone,
                    working_intervals=[
                        {"weekday": d, "start": "09:00", "end": "18:00"}
                        for d in range(5)
                    ],
                )

            cat_plumb, _ = TicketCategory.objects.get_or_create(
                society=society,
                normalized_name="general maintenance",
                defaults={
                    "name": "General Maintenance",
                    "workflow_type": TicketCategory.WorkflowType.SERVICE,
                    "allows_unit_location": True,
                    "allows_common_area_location": True,
                    "allows_no_location": False,
                    "cost_responsibility": TicketCategory.CostResponsibility.RESIDENT_UNIT,
                    "completion_policy": TicketCategory.CompletionPolicy.RESIDENT_CONFIRMATION,
                    "is_active": True,
                },
            )
            subcat_gen, _ = TicketSubCategory.objects.get_or_create(
                society=society,
                category=cat_plumb,
                normalized_name="general check",
                defaults={"name": "General Check", "default_priority": TicketSubCategory.Priority.P3, "is_active": True},
            )

            sla_snap, _ = SLAPolicySnapshot.objects.get_or_create(
                society=society,
                policy_key="green-standard-sla",
                policy_version=1,
                defaults={
                    "calendar_version": calendar.version,
                    "society_timezone": society.timezone,
                    "acceptance_duration": timedelta(hours=4),
                    "initial_resolution_duration": timedelta(hours=24),
                    "reopen_resolution_duration": timedelta(hours=12),
                    "l3_delay": timedelta(hours=4),
                    "estimate_decision_duration": timedelta(hours=48),
                },
            )
            for prio in ["P1", "P2", "P3", "P4"]:
                SLAPolicyBinding.objects.get_or_create(
                    society=society,
                    category=cat_plumb,
                    priority=prio,
                    defaults={"snapshot": sla_snap, "is_active": True},
                )

        return society
