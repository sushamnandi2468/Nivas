import uuid
from datetime import date, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.tenancy.models import (
    CommonArea,
    Society,
    TechnicianProfile,
    Unit,
    VendorContract,
    VendorStaffMembership,
)

SERVICE_TICKET_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "ASSIGNED",
    "ACCEPTED",
    "IN_PROGRESS",
    "PENDING_ESTIMATE_APPROVAL",
    "PENDING_RESIDENT_CONFIRMATION",
    "SUPERVISOR_TRIAGE",
    "RESOLVED",
    "CLOSED",
    "CANCELLED",
    "MERGED",
)
GOVERNANCE_TICKET_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "IN_DISCUSSION",
    "ACTION_TAKEN",
    "RESOLVED",
    "CLOSED",
    "CANCELLED",
    "MERGED",
)


class TicketCategory(models.Model):
    class WorkflowType(models.TextChoices):
        SERVICE = "SERVICE", _("Service")
        GOVERNANCE = "GOVERNANCE", _("Governance")

    class CostResponsibility(models.TextChoices):
        RESIDENT_UNIT = "RESIDENT_UNIT", _("Resident unit")
        SOCIETY = "SOCIETY", _("Society")
        NO_CHARGE = "NO_CHARGE", _("No charge")

    class CompletionPolicy(models.TextChoices):
        RESIDENT_CONFIRMATION = "RESIDENT_CONFIRMATION", _("Resident confirmation")
        GOVERNANCE_RESOLUTION = "GOVERNANCE_RESOLUTION", _("Governance resolution")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="ticket_categories",
    )
    name = models.CharField(max_length=128)
    normalized_name = models.CharField(max_length=128, editable=False)
    workflow_type = models.CharField(max_length=16, choices=WorkflowType.choices)
    allows_unit_location = models.BooleanField(default=False)
    allows_common_area_location = models.BooleanField(default=False)
    allows_no_location = models.BooleanField(default=False)
    cost_responsibility = models.CharField(
        max_length=16,
        choices=CostResponsibility.choices,
    )
    completion_policy = models.CharField(
        max_length=32,
        choices=CompletionPolicy.choices,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tickets_ticket_category"
        ordering = ("society_id", "normalized_name")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_category_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "id", "workflow_type"),
                name="tickets_category_society_workflow_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "normalized_name"),
                name="tickets_category_society_name_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(allows_unit_location=True)
                    | Q(allows_common_area_location=True)
                    | Q(allows_no_location=True)
                ),
                name="tickets_category_has_location_policy",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        workflow_type="SERVICE",
                        completion_policy="RESIDENT_CONFIRMATION",
                        allows_no_location=False,
                    )
                    | Q(
                        workflow_type="GOVERNANCE",
                        completion_policy="GOVERNANCE_RESOLUTION",
                    )
                ),
                name="tickets_category_workflow_completion",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(cost_responsibility="RESIDENT_UNIT")
                    | Q(
                        workflow_type="SERVICE",
                        allows_unit_location=True,
                    )
                ),
                name="tickets_category_resident_cost_unit",
            ),
        )

    def __str__(self):
        return f"{self.society} - {self.name}"

    def clean_fields(self, exclude=None):
        self._normalize_name()
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        self._normalize_name()
        errors = {}
        if not any(
            (
                self.allows_unit_location,
                self.allows_common_area_location,
                self.allows_no_location,
            )
        ):
            errors["allows_unit_location"] = _("At least one location type is required.")
        if self.workflow_type == self.WorkflowType.SERVICE:
            if self.allows_no_location:
                errors["allows_no_location"] = _("Service categories require a location.")
            if self.completion_policy != self.CompletionPolicy.RESIDENT_CONFIRMATION:
                errors["completion_policy"] = _(
                    "Service categories require resident confirmation."
                )
        elif self.completion_policy != self.CompletionPolicy.GOVERNANCE_RESOLUTION:
            errors["completion_policy"] = _(
                "Governance categories require governance resolution."
            )
        if (
            self.cost_responsibility == self.CostResponsibility.RESIDENT_UNIT
            and (
                self.workflow_type != self.WorkflowType.SERVICE
                or not self.allows_unit_location
            )
        ):
            errors["cost_responsibility"] = _(
                "Resident-unit costs require a service category that permits units."
            )
        if errors:
            raise ValidationError(errors)

    def _normalize_name(self):
        self.name = " ".join(self.name.split())
        self.normalized_name = self.name.casefold()


class TicketSubCategory(models.Model):
    class Priority(models.TextChoices):
        P1 = "P1", _("P1 Critical")
        P2 = "P2", _("P2 High")
        P3 = "P3", _("P3 Medium")
        P4 = "P4", _("P4 Low")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="ticket_subcategories",
    )
    category = models.ForeignKey(
        TicketCategory,
        on_delete=models.PROTECT,
        related_name="subcategories",
    )
    name = models.CharField(max_length=128)
    normalized_name = models.CharField(max_length=128, editable=False)
    default_priority = models.CharField(
        max_length=2,
        choices=Priority.choices,
        default=Priority.P3,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tickets_ticket_subcategory"
        ordering = ("society_id", "category_id", "normalized_name")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "category", "id"),
                name="tickets_subcategory_society_category_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "category", "normalized_name"),
                name="tickets_subcategory_society_name_uniq",
            ),
        )

    def __str__(self):
        return f"{self.category} - {self.name}"

    def clean_fields(self, exclude=None):
        self._normalize_name()
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        self._normalize_name()
        if (
            self.category_id
            and self.society_id
            and self.category.society_id != self.society_id
        ):
            raise ValidationError(
                {"category": _("Category must belong to the selected society.")}
            )

    def _normalize_name(self):
        self.name = " ".join(self.name.split())
        self.normalized_name = self.name.casefold()


class Ticket(models.Model):
    class WorkflowType(models.TextChoices):
        SERVICE = "SERVICE", _("Service")
        GOVERNANCE = "GOVERNANCE", _("Governance")

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        SUBMITTED = "SUBMITTED", _("Submitted")
        ASSIGNED = "ASSIGNED", _("Assigned")
        ACCEPTED = "ACCEPTED", _("Accepted")
        IN_PROGRESS = "IN_PROGRESS", _("In progress")
        PENDING_ESTIMATE_APPROVAL = (
            "PENDING_ESTIMATE_APPROVAL",
            _("Pending estimate approval"),
        )
        PENDING_RESIDENT_CONFIRMATION = (
            "PENDING_RESIDENT_CONFIRMATION",
            _("Pending resident confirmation"),
        )
        SUPERVISOR_TRIAGE = "SUPERVISOR_TRIAGE", _("Supervisor triage")
        UNDER_REVIEW = "UNDER_REVIEW", _("Under review")
        IN_DISCUSSION = "IN_DISCUSSION", _("In discussion")
        ACTION_TAKEN = "ACTION_TAKEN", _("Action taken")
        RESOLVED = "RESOLVED", _("Resolved")
        CLOSED = "CLOSED", _("Closed")
        CANCELLED = "CANCELLED", _("Cancelled")
        MERGED = "MERGED", _("Merged")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    ticket_number = models.CharField(max_length=32, blank=True, default="")
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_tickets",
    )
    category = models.ForeignKey(
        TicketCategory,
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    subcategory = models.ForeignKey(
        TicketSubCategory,
        on_delete=models.PROTECT,
        related_name="tickets",
    )
    workflow_type = models.CharField(max_length=16, choices=WorkflowType.choices)
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="tickets",
        blank=True,
        null=True,
    )
    common_area = models.ForeignKey(
        CommonArea,
        on_delete=models.PROTECT,
        related_name="tickets",
        blank=True,
        null=True,
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    priority = models.CharField(
        max_length=2,
        choices=TicketSubCategory.Priority.choices,
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    state_version = models.PositiveIntegerField(default=1)
    submitted_at = models.DateTimeField(blank=True, null=True)
    archived_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    SERVICE_STATUSES = SERVICE_TICKET_STATUSES
    GOVERNANCE_STATUSES = GOVERNANCE_TICKET_STATUSES

    class Meta:
        db_table = "tickets_ticket"
        ordering = ("society_id", "-created_at", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_ticket_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "ticket_number"),
                condition=~Q(ticket_number=""),
                name="tickets_ticket_society_number_uniq",
            ),
            models.CheckConstraint(
                condition=Q(state_version__gte=1),
                name="tickets_ticket_positive_version",
            ),
            models.CheckConstraint(
                condition=Q(unit__isnull=True) | Q(common_area__isnull=True),
                name="tickets_ticket_at_most_one_location",
            ),
            models.CheckConstraint(
                condition=(
                    Q(workflow_type="GOVERNANCE")
                    | Q(unit__isnull=False)
                    | Q(common_area__isnull=False)
                ),
                name="tickets_service_requires_location",
            ),
            models.CheckConstraint(
                condition=(
                    Q(workflow_type="SERVICE", status__in=SERVICE_TICKET_STATUSES)
                    | Q(
                        workflow_type="GOVERNANCE",
                        status__in=GOVERNANCE_TICKET_STATUSES,
                    )
                ),
                name="tickets_ticket_workflow_status",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="DRAFT",
                        ticket_number="",
                        submitted_at__isnull=True,
                    )
                    | (
                        ~Q(status="DRAFT")
                        & ~Q(ticket_number="")
                        & Q(submitted_at__isnull=False)
                    )
                ),
                name="tickets_ticket_submission_metadata",
            ),
        )

    def __str__(self):
        return self.ticket_number or str(self.id)

    def clean(self):
        super().clean()
        errors = {}
        if self.category_id and self.society_id:
            if self.category.society_id != self.society_id:
                errors["category"] = _("Category must belong to the selected society.")
            elif self.category.workflow_type != self.workflow_type:
                errors["workflow_type"] = _("Workflow must match the selected category.")
        if self.subcategory_id and self.category_id:
            if self.subcategory.category_id != self.category_id:
                errors["subcategory"] = _("Subcategory must belong to the category.")
            elif self.subcategory.society_id != self.society_id:
                errors["subcategory"] = _(
                    "Subcategory must belong to the selected society."
                )
        if self.unit_id and self.society_id and self.unit.society_id != self.society_id:
            errors["unit"] = _("Unit must belong to the selected society.")
        if (
            self.common_area_id
            and self.society_id
            and self.common_area.society_id != self.society_id
        ):
            errors["common_area"] = _(
                "Common area must belong to the selected society."
            )
        if self.unit_id and self.common_area_id:
            errors["common_area"] = _("A ticket may target only one location.")
        if (
            self.workflow_type == self.WorkflowType.SERVICE
            and not self.unit_id
            and not self.common_area_id
        ):
            errors["unit"] = _("Service tickets require exactly one location.")
        if self.category_id:
            if self.unit_id and not self.category.allows_unit_location:
                errors["unit"] = _("Category does not permit unit locations.")
            if self.common_area_id and not self.category.allows_common_area_location:
                errors["common_area"] = _(
                    "Category does not permit common-area locations."
                )
            if (
                not self.unit_id
                and not self.common_area_id
                and not self.category.allows_no_location
            ):
                errors["unit"] = _("Category requires a location.")
        allowed_statuses = (
            self.SERVICE_STATUSES
            if self.workflow_type == self.WorkflowType.SERVICE
            else self.GOVERNANCE_STATUSES
        )
        if self.status not in allowed_statuses:
            errors["status"] = _("Status is not valid for this workflow.")
        if self.status == self.Status.DRAFT:
            if self.ticket_number or self.submitted_at is not None:
                errors["ticket_number"] = _("Draft tickets cannot have submission metadata.")
        elif not self.ticket_number or self.submitted_at is None:
            errors["ticket_number"] = _("Submitted tickets require submission metadata.")
        if errors:
            raise ValidationError(errors)


class TicketAssignment(models.Model):
    class TargetType(models.TextChoices):
        IN_HOUSE = "IN_HOUSE", _("In-house technician")
        VENDOR = "VENDOR", _("Vendor contract")

    class State(models.TextChoices):
        OFFERED = "OFFERED", _("Offered")
        ACCEPTED = "ACCEPTED", _("Accepted")
        ENDED = "ENDED", _("Ended")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="ticket_assignments",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    target_type = models.CharField(max_length=16, choices=TargetType.choices)
    technician = models.ForeignKey(
        TechnicianProfile,
        on_delete=models.PROTECT,
        related_name="ticket_assignments",
        blank=True,
        null=True,
    )
    vendor_contract = models.ForeignKey(
        VendorContract,
        on_delete=models.PROTECT,
        related_name="ticket_assignments",
        blank=True,
        null=True,
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_tickets",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    acceptance_deadline = models.DateTimeField()
    state = models.CharField(max_length=16, choices=State.choices, default=State.OFFERED)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="accepted_ticket_assignments",
        blank=True,
        null=True,
    )
    accepted_at = models.DateTimeField(blank=True, null=True)
    ended_at = models.DateTimeField(blank=True, null=True)
    ended_reason = models.TextField(blank=True)

    class Meta:
        db_table = "tickets_ticket_assignment"
        ordering = ("society_id", "ticket_id", "assigned_at", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_assignment_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "ticket"),
                condition=~Q(state="ENDED"),
                name="tickets_assignment_one_active_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        target_type="IN_HOUSE",
                        technician__isnull=False,
                        vendor_contract__isnull=True,
                    )
                    | Q(
                        target_type="VENDOR",
                        technician__isnull=True,
                        vendor_contract__isnull=False,
                    )
                ),
                name="tickets_assignment_exactly_one_target",
            ),
            models.CheckConstraint(
                condition=(
                    Q(state="ENDED", ended_at__isnull=False, ended_reason__gt="")
                    | Q(
                        ~Q(state="ENDED"),
                        ended_at__isnull=True,
                        ended_reason="",
                    )
                ),
                name="tickets_assignment_end_metadata",
            ),
            models.CheckConstraint(
                condition=(
                    Q(state="OFFERED", accepted_at__isnull=True, accepted_by__isnull=True)
                    | Q(
                        state="ACCEPTED",
                        accepted_at__isnull=False,
                        accepted_by__isnull=False,
                    )
                    | Q(
                        state="ENDED",
                        accepted_at__isnull=True,
                        accepted_by__isnull=True,
                    )
                    | Q(
                        state="ENDED",
                        accepted_at__isnull=False,
                        accepted_by__isnull=False,
                    )
                ),
                name="tickets_assignment_acceptance_metadata",
            ),
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.target_type == self.TargetType.IN_HOUSE:
            if self.technician_id is None or self.vendor_contract_id is not None:
                errors["target_type"] = _(
                    "In-house assignments require a technician and no vendor contract."
                )
        elif self.target_type == self.TargetType.VENDOR:
            if self.technician_id is not None or self.vendor_contract_id is None:
                errors["target_type"] = _(
                    "Vendor assignments require a vendor contract and no technician."
                )
        if self.technician_id and self.society_id and self.technician.society_id != self.society_id:
            errors["technician"] = _("Technician must belong to the selected society.")
        if (
            self.vendor_contract_id
            and self.society_id
            and self.vendor_contract.society_id != self.society_id
        ):
            errors["vendor_contract"] = _(
                "Vendor contract must belong to the selected society."
            )
        if errors:
            raise ValidationError(errors)


class VendorStaffAllocation(models.Model):
    class State(models.TextChoices):
        ALLOCATED = "ALLOCATED", _("Allocated")
        ACCEPTED = "ACCEPTED", _("Accepted")
        ENDED = "ENDED", _("Ended")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="vendor_staff_allocations",
    )
    assignment = models.ForeignKey(
        TicketAssignment,
        on_delete=models.PROTECT,
        related_name="vendor_staff_allocations",
    )
    staff_membership = models.ForeignKey(
        VendorStaffMembership,
        on_delete=models.PROTECT,
        related_name="ticket_allocations",
    )
    allocated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="allocated_vendor_staff",
    )
    allocated_at = models.DateTimeField(auto_now_add=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.ALLOCATED)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="accepted_vendor_allocations",
        blank=True,
        null=True,
    )
    accepted_at = models.DateTimeField(blank=True, null=True)
    ended_at = models.DateTimeField(blank=True, null=True)
    ended_reason = models.TextField(blank=True)

    class Meta:
        db_table = "tickets_vendor_staff_allocation"
        ordering = ("society_id", "assignment_id", "allocated_at", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_vendor_alloc_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "assignment"),
                condition=~Q(state="ENDED"),
                name="tickets_vendor_alloc_one_active_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(state="ENDED", ended_at__isnull=False, ended_reason__gt="")
                    | Q(
                        ~Q(state="ENDED"),
                        ended_at__isnull=True,
                        ended_reason="",
                    )
                ),
                name="tickets_vendor_alloc_end_metadata",
            ),
            models.CheckConstraint(
                condition=(
                    Q(state="ALLOCATED", accepted_at__isnull=True, accepted_by__isnull=True)
                    | Q(
                        state="ACCEPTED",
                        accepted_at__isnull=False,
                        accepted_by__isnull=False,
                    )
                    | (
                        Q(state="ENDED")
                        & (
                            Q(accepted_at__isnull=True, accepted_by__isnull=True)
                            | Q(
                                accepted_at__isnull=False,
                                accepted_by__isnull=False,
                            )
                        )
                    )
                ),
                name="tickets_vendor_alloc_acceptance_metadata",
            ),
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.assignment_id and self.assignment.target_type != TicketAssignment.TargetType.VENDOR:
            errors["assignment"] = _(
                "Vendor staff allocations require a vendor-targeted assignment."
            )
        if (
            self.assignment_id
            and self.society_id
            and self.assignment.society_id != self.society_id
        ):
            errors["assignment"] = _("Assignment must belong to the selected society.")
        if (
            self.staff_membership_id
            and self.society_id
            and self.staff_membership.society_id != self.society_id
        ):
            errors["staff_membership"] = _(
                "Vendor staff membership must belong to the selected society."
            )
        if errors:
            raise ValidationError(errors)


class TicketCompletionChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="ticket_completion_challenges",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.PROTECT,
        related_name="completion_challenges",
    )
    assignment = models.ForeignKey(
        TicketAssignment,
        on_delete=models.PROTECT,
        related_name="completion_challenges",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_completion_challenges",
    )
    worker_notes = models.TextField()
    otp_hash = models.CharField(max_length=128)
    delivery_capsule_name = models.CharField(max_length=127, blank=True, default="")
    expires_at = models.DateTimeField()
    attempts_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    is_consumed = models.BooleanField(default=False)
    consumed_at = models.DateTimeField(blank=True, null=True)
    consumed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="consumed_completion_challenges",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tickets_ticket_completion_challenge"
        ordering = ("society_id", "ticket_id", "-created_at")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_challenge_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "ticket", "id"),
                name="tickets_challenge_society_ticket_id_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_consumed=True, consumed_at__isnull=False, consumed_by__isnull=False)
                    | Q(is_consumed=False, consumed_at__isnull=True, consumed_by__isnull=True)
                ),
                name="tickets_challenge_consumed_metadata",
            ),
        )

    def clean(self):
        super().clean()
        errors = {}
        if (
            self.ticket_id
            and self.society_id
            and self.ticket.society_id != self.society_id
        ):
            errors["ticket"] = _("Ticket must belong to the selected society.")
        if (
            self.assignment_id
            and self.society_id
            and self.assignment.society_id != self.society_id
        ):
            errors["assignment"] = _("Assignment must belong to the selected society.")
        if errors:
            raise ValidationError(errors)


class TicketEstimate(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        SUBMITTED = "SUBMITTED", _("Submitted")
        APPROVED = "APPROVED", _("Approved")
        REJECTED = "REJECTED", _("Rejected")
        WITHDRAWN = "WITHDRAWN", _("Withdrawn")
        EXPIRED = "EXPIRED", _("Expired")
        CANCELLED = "CANCELLED", _("Cancelled")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="ticket_estimates",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.PROTECT,
        related_name="estimates",
    )
    assignment = models.ForeignKey(
        TicketAssignment,
        on_delete=models.PROTECT,
        related_name="estimates",
        blank=True,
        null=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_ticket_estimates",
    )
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.SUBMITTED,
    )
    cost_responsibility = models.CharField(
        max_length=16,
        choices=TicketCategory.CostResponsibility.choices,
    )
    currency = models.CharField(max_length=3, default="INR")
    subtotal_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True, default="")
    decision_reason = models.TextField(blank=True, default="")
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="decided_ticket_estimates",
        blank=True,
        null=True,
    )
    decided_at = models.DateTimeField(blank=True, null=True)
    decision_deadline = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tickets_ticket_estimate"
        ordering = ("society_id", "ticket_id", "-version")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_estimate_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "ticket", "version"),
                name="tickets_estimate_society_ticket_version_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "ticket"),
                condition=Q(status="SUBMITTED"),
                name="tickets_estimate_one_pending_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status__in=["APPROVED", "REJECTED", "WITHDRAWN"], decided_at__isnull=False, decided_by__isnull=False)
                    | Q(~Q(status__in=["APPROVED", "REJECTED", "WITHDRAWN"]))
                ),
                name="tickets_estimate_decided_metadata",
            ),
            models.CheckConstraint(
                condition=(
                    Q(subtotal_amount__gte=0)
                    & Q(tax_amount__gte=0)
                    & Q(total_amount__gte=0)
                    & Q(total_amount=F("subtotal_amount") + F("tax_amount"))
                ),
                name="tickets_estimate_amounts_valid",
            ),
        )

    def clean(self):
        super().clean()
        errors = {}
        if (
            self.ticket_id
            and self.society_id
            and self.ticket.society_id != self.society_id
        ):
            errors["ticket"] = _("Ticket must belong to the selected society.")
        if (
            self.assignment_id
            and self.society_id
            and self.assignment.society_id != self.society_id
        ):
            errors["assignment"] = _("Assignment must belong to the selected society.")
        if errors:
            raise ValidationError(errors)


class TicketEstimateLineItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="ticket_estimate_line_items",
    )
    estimate = models.ForeignKey(
        TicketEstimate,
        on_delete=models.CASCADE,
        related_name="items",
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tickets_ticket_estimate_line_item"
        ordering = ("society_id", "estimate_id", "created_at", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_estimate_item_society_id_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(quantity__gt=0)
                    & Q(unit_cost__gte=0)
                    & Q(total_cost__gte=0)
                    & Q(total_cost=F("quantity") * F("unit_cost"))
                ),
                name="tickets_estimate_item_amounts_valid",
            ),
        )

    def clean(self):
        super().clean()
        errors = {}
        if (
            self.estimate_id
            and self.society_id
            and self.estimate.society_id != self.society_id
        ):
            errors["estimate"] = _("Estimate must belong to the selected society.")
        if errors:
            raise ValidationError(errors)


class TicketNumberSequence(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="ticket_number_sequences",
    )
    calendar_year = models.PositiveSmallIntegerField()
    current_value = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tickets_ticket_number_sequence"
        ordering = ("society_id", "calendar_year")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "calendar_year"),
                name="tickets_sequence_society_year_uniq",
            ),
        )

    def __str__(self):
        return f"{self.society} - {self.calendar_year} - {self.current_value}"


class BusinessCalendar(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="business_calendars",
    )
    version = models.PositiveIntegerField()
    timezone = models.CharField(max_length=64)
    working_intervals = models.JSONField(default=list, blank=True)
    holidays = models.JSONField(default=list, blank=True)
    is_emergency_24x7 = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    retired_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_business_calendar"
        ordering = ("society_id", "-version")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_calendar_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "version"),
                name="tickets_calendar_society_version_uniq",
            ),
            models.UniqueConstraint(
                fields=("society",),
                condition=Q(is_active=True),
                name="tickets_calendar_active_uniq",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="tickets_calendar_positive_version",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_active=False) | Q(is_active=True, retired_at__isnull=True)
                ),
                name="tickets_calendar_retirement_state",
            ),
        )

    def __str__(self):
        return f"{self.society} - calendar v{self.version}"

    def clean(self):
        super().clean()
        errors = {}
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            errors["timezone"] = _("Enter a valid IANA timezone.")
        if self.society_id and self.timezone != self.society.timezone:
            errors["timezone"] = _("Calendar timezone must match the society timezone.")

        intervals_by_weekday = {}
        if not isinstance(self.working_intervals, list):
            errors["working_intervals"] = _("Working intervals must be a list.")
        else:
            for interval in self.working_intervals:
                try:
                    weekday = interval["weekday"]
                    if isinstance(weekday, bool) or not 0 <= weekday <= 6:
                        raise ValueError
                    start = time.fromisoformat(interval["start"])
                    end = time.fromisoformat(interval["end"])
                    if start >= end:
                        raise ValueError
                except (KeyError, TypeError, ValueError):
                    errors["working_intervals"] = _(
                        "Each interval requires weekday 0-6 and start/end HH:MM values."
                    )
                    break
                intervals_by_weekday.setdefault(weekday, []).append((start, end))
            for intervals in intervals_by_weekday.values():
                intervals.sort()
                if any(
                    current_start < previous_end
                    for (_, previous_end), (current_start, _) in zip(
                        intervals,
                        intervals[1:],
                        strict=False,
                    )
                ):
                    errors["working_intervals"] = _("Working intervals cannot overlap.")
                    break
        if not self.is_emergency_24x7 and not self.working_intervals:
            errors["working_intervals"] = _(
                "At least one working interval is required for a business-hours calendar."
            )

        if not isinstance(self.holidays, list):
            errors["holidays"] = _("Holidays must be a list of ISO dates.")
        else:
            try:
                parsed_holidays = [date.fromisoformat(value) for value in self.holidays]
            except (TypeError, ValueError):
                errors["holidays"] = _("Holidays must be a list of ISO dates.")
            else:
                if len(parsed_holidays) != len(set(parsed_holidays)):
                    errors["holidays"] = _("Holiday dates must be unique.")
        if errors:
            raise ValidationError(errors)


class SLAPolicySnapshot(models.Model):
    class PauseReason(models.TextChoices):
        APPROVER_DECISION = "APPROVER_DECISION", _("Approver decision")
        RESIDENT_ACCESS_UNAVAILABLE = (
            "RESIDENT_ACCESS_UNAVAILABLE",
            _("Resident access unavailable"),
        )
        EXTERNAL_DEPENDENCY = "EXTERNAL_DEPENDENCY", _("External dependency")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="sla_policy_snapshots",
    )
    policy_key = models.CharField(max_length=128)
    policy_version = models.PositiveIntegerField()
    calendar_version = models.PositiveIntegerField()
    society_timezone = models.CharField(max_length=64)
    acceptance_duration = models.DurationField()
    initial_resolution_duration = models.DurationField()
    reopen_resolution_duration = models.DurationField()
    l3_delay = models.DurationField()
    permitted_pause_reasons = models.JSONField(default=list, blank=True)
    estimate_decision_duration = models.DurationField()
    max_assignment_failures = models.PositiveSmallIntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_sla_policy_snapshot"
        ordering = ("society_id", "policy_key", "-policy_version")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_sla_snapshot_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "policy_key", "policy_version"),
                name="tickets_sla_snapshot_policy_version_uniq",
            ),
            models.CheckConstraint(
                condition=Q(policy_version__gte=1, calendar_version__gte=1),
                name="tickets_sla_snapshot_positive_versions",
            ),
            models.CheckConstraint(
                condition=(
                    Q(acceptance_duration__gt=timedelta(0))
                    & Q(initial_resolution_duration__gt=timedelta(0))
                    & Q(reopen_resolution_duration__gt=timedelta(0))
                    & Q(l3_delay__gte=timedelta(0))
                    & Q(estimate_decision_duration__gt=timedelta(0))
                ),
                name="tickets_sla_snapshot_valid_durations",
            ),
            models.CheckConstraint(
                condition=Q(max_assignment_failures__gte=1),
                name="tickets_sla_snapshot_positive_failures",
            ),
        )

    def __str__(self):
        return f"{self.policy_key} - v{self.policy_version}"

    def clean(self):
        super().clean()
        errors = {}
        try:
            ZoneInfo(self.society_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            errors["society_timezone"] = _("Enter a valid IANA timezone.")
        allowed_pause_reasons = set(self.PauseReason.values)
        pause_reasons = self.permitted_pause_reasons
        if (
            not isinstance(pause_reasons, list)
            or len(pause_reasons) != len(set(pause_reasons))
            or any(reason not in allowed_pause_reasons for reason in pause_reasons)
        ):
            errors["permitted_pause_reasons"] = _(
                "Pause reasons must be a unique list of supported values."
            )
        if errors:
            raise ValidationError(errors)


class SLAPolicyBinding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="sla_policy_bindings",
    )
    category = models.ForeignKey(
        TicketCategory,
        on_delete=models.PROTECT,
        related_name="sla_policy_bindings",
    )
    priority = models.CharField(
        max_length=2,
        choices=TicketSubCategory.Priority.choices,
    )
    snapshot = models.ForeignKey(
        SLAPolicySnapshot,
        on_delete=models.PROTECT,
        related_name="bindings",
    )
    is_active = models.BooleanField(default=True)
    retired_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_sla_policy_binding"
        ordering = ("society_id", "category_id", "priority", "-created_at")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "category", "priority"),
                condition=Q(is_active=True),
                name="tickets_sla_binding_active_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_active=True, retired_at__isnull=True)
                    | Q(is_active=False, retired_at__isnull=False)
                ),
                name="tickets_sla_binding_retirement_state",
            ),
        )

    def __str__(self):
        return f"{self.category} - {self.priority} - {self.snapshot}"

    def clean(self):
        super().clean()
        errors = {}
        if self.category_id and self.society_id:
            if self.category.society_id != self.society_id:
                errors["category"] = _("Category must belong to the selected society.")
        if self.snapshot_id and self.society_id:
            if self.snapshot.society_id != self.society_id:
                errors["snapshot"] = _("Snapshot must belong to the selected society.")
        if errors:
            raise ValidationError(errors)


class SLACycle(models.Model):
    class CycleType(models.TextChoices):
        INITIAL = "INITIAL", _("Initial")
        REOPEN = "REOPEN", _("Reopen")

    class Outcome(models.TextChoices):
        RESOLVED = "RESOLVED", _("Resolved")
        CLOSED = "CLOSED", _("Closed")
        CANCELLED = "CANCELLED", _("Cancelled")
        MERGED = "MERGED", _("Merged")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="sla_cycles",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.PROTECT,
        related_name="sla_cycles",
    )
    snapshot = models.ForeignKey(
        SLAPolicySnapshot,
        on_delete=models.PROTECT,
        related_name="cycles",
    )
    cycle_number = models.PositiveSmallIntegerField()
    cycle_type = models.CharField(max_length=8, choices=CycleType.choices)
    started_at = models.DateTimeField()
    acceptance_deadline = models.DateTimeField(blank=True, null=True)
    resolution_deadline = models.DateTimeField()
    pause_reason = models.CharField(
        max_length=32,
        choices=SLAPolicySnapshot.PauseReason.choices,
        blank=True,
        default="",
    )
    paused_at = models.DateTimeField(blank=True, null=True)
    total_paused_duration = models.DurationField(default=timedelta)
    l1_escalated_at = models.DateTimeField(blank=True, null=True)
    l2_escalated_at = models.DateTimeField(blank=True, null=True)
    l3_escalated_at = models.DateTimeField(blank=True, null=True)
    assignment_failure_count = models.PositiveSmallIntegerField(default=0)
    assignee_rejection_count = models.PositiveSmallIntegerField(default=0)
    acceptance_timeout_count = models.PositiveSmallIntegerField(default=0)
    ended_at = models.DateTimeField(blank=True, null=True)
    outcome = models.CharField(
        max_length=16,
        choices=Outcome.choices,
        blank=True,
        default="",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_sla_cycle"
        ordering = ("society_id", "ticket_id", "cycle_number")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_sla_cycle_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "ticket", "cycle_number"),
                name="tickets_sla_cycle_ticket_number_uniq",
            ),
            models.CheckConstraint(
                condition=Q(cycle_number__gte=1),
                name="tickets_sla_cycle_positive_number",
            ),
            models.CheckConstraint(
                condition=Q(resolution_deadline__gt=models.F("started_at")),
                name="tickets_sla_cycle_resolution_after_start",
            ),
            models.CheckConstraint(
                condition=(
                    Q(pause_reason="", paused_at__isnull=True)
                    | (~Q(pause_reason="") & Q(paused_at__isnull=False))
                ),
                name="tickets_sla_cycle_pause_state",
            ),
            models.CheckConstraint(
                condition=(
                    Q(outcome="", ended_at__isnull=True)
                    | (~Q(outcome="") & Q(ended_at__isnull=False))
                ),
                name="tickets_sla_cycle_outcome_state",
            ),
            models.CheckConstraint(
                condition=Q(total_paused_duration__gte=timedelta(0)),
                name="tickets_sla_cycle_nonnegative_pause",
            ),
            models.CheckConstraint(
                condition=Q(
                    assignment_failure_count__gte=(
                        models.F("assignee_rejection_count")
                        + models.F("acceptance_timeout_count")
                    )
                ),
                name="tickets_sla_cycle_failure_counters",
            ),
        )
        indexes = (
            models.Index(
                fields=("society", "resolution_deadline"),
                condition=Q(ended_at__isnull=True, paused_at__isnull=True),
                name="tickets_sla_cycle_due",
            ),
        )

    def __str__(self):
        return f"{self.ticket_id} - SLA cycle {self.cycle_number}"

    def clean(self):
        super().clean()
        errors = {}
        if self.ticket_id and self.society_id:
            if self.ticket.society_id != self.society_id:
                errors["ticket"] = _("Ticket must belong to the selected society.")
        if self.snapshot_id and self.society_id:
            if self.snapshot.society_id != self.society_id:
                errors["snapshot"] = _("Snapshot must belong to the selected society.")
            elif (
                self.pause_reason
                and self.pause_reason not in self.snapshot.permitted_pause_reasons
            ):
                errors["pause_reason"] = _("Snapshot does not permit this pause reason.")
        if errors:
            raise ValidationError(errors)


class TicketEvent(models.Model):
    class EventType(models.TextChoices):
        TICKET_SUBMITTED = "TICKET_SUBMITTED", _("Ticket submitted")
        TICKET_CANCELLED = "TICKET_CANCELLED", _("Ticket cancelled")
        TICKET_ASSIGNED = "TICKET_ASSIGNED", _("Ticket assigned")
        TICKET_ASSIGNMENT_ACCEPTED = "TICKET_ASSIGNMENT_ACCEPTED", _(
            "Ticket assignment accepted"
        )
        TICKET_ASSIGNMENT_REJECTED = "TICKET_ASSIGNMENT_REJECTED", _(
            "Ticket assignment rejected"
        )
        VENDOR_WORKER_ALLOCATED = "VENDOR_WORKER_ALLOCATED", _(
            "Vendor worker allocated"
        )
        VENDOR_WORKER_REPLACED = "VENDOR_WORKER_REPLACED", _(
            "Vendor worker replaced"
        )
        TICKET_WORK_STARTED = "TICKET_WORK_STARTED", _(
            "Ticket work started"
        )
        TICKET_COMPLETION_REQUESTED = "TICKET_COMPLETION_REQUESTED", _(
            "Ticket completion requested"
        )
        TICKET_RESOLVED = "TICKET_RESOLVED", _(
            "Ticket resolved"
        )
        TICKET_ESTIMATE_SUBMITTED = "TICKET_ESTIMATE_SUBMITTED", _(
            "Ticket estimate submitted"
        )
        TICKET_ESTIMATE_APPROVED = "TICKET_ESTIMATE_APPROVED", _(
            "Ticket estimate approved"
        )
        TICKET_ESTIMATE_REJECTED = "TICKET_ESTIMATE_REJECTED", _(
            "Ticket estimate rejected"
        )
        TICKET_ESTIMATE_WITHDRAWN = "TICKET_ESTIMATE_WITHDRAWN", _(
            "Ticket estimate withdrawn"
        )
        TICKET_REOPENED = "TICKET_REOPENED", _(
            "Ticket reopened"
        )
        TICKET_CLOSED = "TICKET_CLOSED", _(
            "Ticket closed"
        )
        TICKET_TRIAGE_REASSIGNED = "TICKET_TRIAGE_REASSIGNED", _(
            "Ticket triage reassigned"
        )
        TICKET_TRIAGE_RESUMED_OVERRIDE = "TICKET_TRIAGE_RESUMED_OVERRIDE", _(
            "Ticket triage resumed by supervisor override"
        )
        TICKET_RESOLVED_OVERRIDE = "TICKET_RESOLVED_OVERRIDE", _(
            "Ticket resolved by supervisor override"
        )
        TICKET_RATED = "TICKET_RATED", _(
            "Ticket rated"
        )
        TICKET_MERGED = "TICKET_MERGED", _(
            "Ticket merged"
        )
        TICKET_MERGE_ATTACHED = "TICKET_MERGE_ATTACHED", _(
            "Secondary ticket merged into this ticket"
        )
        TICKET_UNMERGED = "TICKET_UNMERGED", _(
            "Ticket unmerged"
        )
        GOVERNANCE_REVIEW_BEGUN = "GOVERNANCE_REVIEW_BEGUN", _(
            "Governance review begun"
        )
        GOVERNANCE_DISCUSSION_OPENED = "GOVERNANCE_DISCUSSION_OPENED", _(
            "Governance discussion opened"
        )
        GOVERNANCE_ACTION_RECORDED = "GOVERNANCE_ACTION_RECORDED", _(
            "Governance action recorded"
        )
        TICKET_ATTACHMENT_UPLOAD_SLOT_ISSUED = (
            "TICKET_ATTACHMENT_UPLOAD_SLOT_ISSUED",
            _("Ticket attachment upload slot issued"),
        )
        TICKET_ATTACHMENT_PROMOTED = (
            "TICKET_ATTACHMENT_PROMOTED",
            _("Ticket attachment promoted to available"),
        )
        TICKET_ATTACHMENT_REJECTED = (
            "TICKET_ATTACHMENT_REJECTED",
            _("Ticket attachment rejected"),
        )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="ticket_events",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.PROTECT,
        related_name="events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_events",
    )
    actor_persona = models.CharField(max_length=32)
    ticket_version = models.PositiveIntegerField()
    previous_status = models.CharField(max_length=32, choices=Ticket.Status.choices)
    new_status = models.CharField(max_length=32, choices=Ticket.Status.choices)
    event_type = models.CharField(max_length=64, choices=EventType.choices)
    reason = models.TextField(blank=True)
    correlation_id = models.UUIDField()
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_ticket_event"
        ordering = ("occurred_at", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_event_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "ticket", "ticket_version"),
                name="tickets_event_ticket_version_uniq",
            ),
            models.CheckConstraint(
                condition=Q(ticket_version__gte=2),
                name="tickets_event_transition_version",
            ),
        )
        indexes = (
            models.Index(
                fields=("society", "ticket", "occurred_at"),
                name="tickets_event_ticket_time",
            ),
            models.Index(
                fields=("society", "actor", "occurred_at"),
                name="tickets_event_actor_time",
            ),
        )

    def __str__(self):
        return f"{self.ticket_id} - v{self.ticket_version} - {self.event_type}"


class TicketOutboxEvent(models.Model):
    class EventType(models.TextChoices):
        SERVICE_COMPLETION_NOTIFICATION_REQUESTED = (
            "SERVICE_COMPLETION_NOTIFICATION_REQUESTED",
            _("Service completion notification requested"),
        )

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        CLAIMED = "CLAIMED", _("Claimed")
        SUBMITTED = "SUBMITTED", _("Submitted")
        DELIVERED = "DELIVERED", _("Delivered")
        DEAD_LETTER = "DEAD_LETTER", _("Dead letter")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="ticket_outbox_events",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.PROTECT,
        related_name="outbox_events",
    )
    ticket_event = models.ForeignKey(
        TicketEvent,
        on_delete=models.PROTECT,
        related_name="outbox_events",
    )
    completion_challenge = models.ForeignKey(
        TicketCompletionChallenge,
        on_delete=models.PROTECT,
        related_name="outbox_events",
    )
    event_type = models.CharField(max_length=64, choices=EventType.choices)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    state_version = models.PositiveIntegerField(default=1)
    attempts_count = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=8)
    available_at = models.DateTimeField(default=timezone.now)
    last_attempted_at = models.DateTimeField(blank=True, null=True)
    claimed_at = models.DateTimeField(blank=True, null=True)
    claim_token = models.UUIDField(blank=True, null=True)
    claim_expires_at = models.DateTimeField(blank=True, null=True)
    provider_message_id = models.CharField(max_length=255, blank=True)
    submitted_at = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)
    dead_lettered_at = models.DateTimeField(blank=True, null=True)
    last_error_code = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_ticket_outbox_event"
        ordering = ("society_id", "created_at", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_outbox_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "ticket_event"),
                name="tickets_outbox_society_event_uniq",
            ),
            models.CheckConstraint(
                condition=Q(state_version__gte=1),
                name="tickets_outbox_positive_version",
            ),
            models.CheckConstraint(
                condition=(
                    Q(attempts_count__lte=F("max_attempts"))
                    & Q(max_attempts__gte=1)
                ),
                name="tickets_outbox_attempt_bounds",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="CLAIMED",
                        claimed_at__isnull=False,
                        claim_token__isnull=False,
                        claim_expires_at__isnull=False,
                    )
                    | Q(
                        ~Q(status="CLAIMED"),
                        claimed_at__isnull=True,
                        claim_token__isnull=True,
                        claim_expires_at__isnull=True,
                    )
                ),
                name="tickets_outbox_claim_state",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="DELIVERED",
                        delivered_at__isnull=False,
                        dead_lettered_at__isnull=True,
                    )
                    | Q(
                        status="SUBMITTED",
                        submitted_at__isnull=False,
                        provider_message_id__gt="",
                        delivered_at__isnull=True,
                        dead_lettered_at__isnull=True,
                    )
                    | Q(
                        status="DEAD_LETTER",
                        delivered_at__isnull=True,
                        dead_lettered_at__isnull=False,
                    )
                    | Q(
                        status__in=["PENDING", "CLAIMED"],
                        submitted_at__isnull=True,
                        provider_message_id="",
                        delivered_at__isnull=True,
                        dead_lettered_at__isnull=True,
                    )
                ),
                name="tickets_outbox_terminal_state",
            ),
        )
        indexes = (
            models.Index(
                fields=("society", "event_type", "created_at"),
                name="tickets_outbox_pending_idx",
            ),
            models.Index(
                fields=("society", "status", "available_at"),
                name="tickets_outbox_claim_due_idx",
            ),
            models.Index(
                fields=("society", "status", "claim_expires_at"),
                name="tickets_outbox_claim_lease_idx",
            ),
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.ticket_id and self.society_id and self.ticket.society_id != self.society_id:
            errors["ticket"] = _("Ticket must belong to the selected society.")
        if (
            self.ticket_event_id
            and self.society_id
            and self.ticket_event.society_id != self.society_id
        ):
            errors["ticket_event"] = _(
                "Ticket event must belong to the selected society."
            )
        if (
            self.completion_challenge_id
            and self.society_id
            and self.completion_challenge.society_id != self.society_id
        ):
            errors["completion_challenge"] = _(
                "Completion challenge must belong to the selected society."
            )
        if errors:
            raise ValidationError(errors)


class GovernanceReviewAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="governance_review_assignments",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.PROTECT,
        related_name="governance_review_assignments",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="governance_reviews",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_governance_reviews",
    )
    reviewer_persona = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField()
    ended_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "tickets_governance_review_assignment"
        ordering = ("society_id", "ticket_id", "assigned_at", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_governance_review_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "ticket"),
                condition=Q(is_active=True),
                name="tickets_governance_review_one_active_uniq",
            ),
            models.CheckConstraint(
                condition=Q(ended_at__isnull=True) | Q(ended_at__gte=models.F("assigned_at")),
                name="tickets_governance_review_valid_period",
            ),
        )
        indexes = (
            models.Index(
                fields=("society", "reviewer", "is_active"),
                name="tickets_gov_review_reviewer",
            ),
        )

    def __str__(self):
        return f"{self.ticket_id} - {self.reviewer_id}"

    def clean(self):
        super().clean()
        if (
            self.ticket_id
            and self.society_id
            and self.ticket.society_id != self.society_id
        ):
            raise ValidationError(
                {"ticket": _("Ticket must belong to the selected society.")}
            )


class GovernanceDiscussion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="governance_discussions",
    )
    ticket = models.OneToOneField(
        Ticket,
        on_delete=models.PROTECT,
        related_name="governance_discussion",
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="opened_governance_discussions",
    )
    purpose = models.TextField()
    opened_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_governance_discussion"
        ordering = ("society_id", "opened_at", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_gov_discussion_society_id_uniq",
            ),
        )

    def __str__(self):
        return f"{self.ticket_id} - discussion"

    def clean(self):
        super().clean()
        if (
            self.ticket_id
            and self.society_id
            and self.ticket.society_id != self.society_id
        ):
            raise ValidationError(
                {"ticket": _("Ticket must belong to the selected society.")}
            )


class GovernanceDiscussionParticipant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="governance_discussion_participants",
    )
    discussion = models.ForeignKey(
        GovernanceDiscussion,
        on_delete=models.PROTECT,
        related_name="participants",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="governance_discussion_participations",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_governance_discussion_participant"
        ordering = ("society_id", "discussion_id", "joined_at", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_gov_disc_part_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "discussion", "user"),
                name="tickets_gov_disc_part_user_uniq",
            ),
        )

    def __str__(self):
        return f"{self.discussion_id} - {self.user_id}"

    def clean(self):
        super().clean()
        if (
            self.discussion_id
            and self.society_id
            and self.discussion.society_id != self.society_id
        ):
            raise ValidationError(
                {"discussion": _("Discussion must belong to the selected society.")}
            )


class GovernanceActionRecord(models.Model):
    class EvidencePolicy(models.TextChoices):
        NO_EXTERNAL_EVIDENCE = "NO_EXTERNAL_EVIDENCE", _(
            "External evidence is not yet supported"
        )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="governance_action_records",
    )
    ticket = models.OneToOneField(
        Ticket,
        on_delete=models.PROTECT,
        related_name="governance_action_record",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_governance_actions",
    )
    summary = models.TextField()
    evidence_policy = models.CharField(
        max_length=32,
        choices=EvidencePolicy.choices,
        default=EvidencePolicy.NO_EXTERNAL_EVIDENCE,
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_governance_action_record"
        ordering = ("society_id", "recorded_at", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_gov_action_society_id_uniq",
            ),
        )

    def __str__(self):
        return f"{self.ticket_id} - action"

    def clean(self):
        super().clean()
        if (
            self.ticket_id
            and self.society_id
            and self.ticket.society_id != self.society_id
        ):
            raise ValidationError(
                {"ticket": _("Ticket must belong to the selected society.")}
            )


class TicketComment(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = "PUBLIC", _("Public")
        INTERNAL = "INTERNAL", _("Internal")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="ticket_comments",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.PROTECT,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_comments",
    )
    author_persona = models.CharField(max_length=32)
    visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tickets_ticket_comment"
        ordering = ("created_at", "id")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_comment_society_id_uniq",
            ),
        )
        indexes = (
            models.Index(
                fields=("society", "ticket", "created_at"),
                name="tickets_comment_ticket_time",
            ),
        )

    def __str__(self):
        return f"{self.ticket_id} - {self.author_persona} - {self.created_at}"

    def clean(self):
        super().clean()
        if (
            self.ticket_id
            and self.society_id
            and self.ticket.society_id != self.society_id
        ):
            raise ValidationError(
                {"ticket": _("Ticket must belong to the selected society.")}
            )


class IdempotencyRecord(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS", _("In progress")
        COMPLETED = "COMPLETED", _("Completed")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="idempotency_records",
    )
    principal = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="idempotency_records",
    )
    http_method = models.CharField(max_length=8)
    route_template = models.CharField(max_length=255)
    idempotency_key = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
    )
    response_status = models.PositiveSmallIntegerField(blank=True, null=True)
    response_body = models.JSONField(default=dict, blank=True)
    response_headers = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tickets_idempotency_record"
        ordering = ("society_id", "created_at", "id")
        constraints = (
            models.UniqueConstraint(
                fields=(
                    "society",
                    "principal",
                    "http_method",
                    "route_template",
                    "idempotency_key",
                ),
                name="tickets_idempotency_scope_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="IN_PROGRESS", response_status__isnull=True)
                    | Q(status="COMPLETED", response_status__isnull=False)
                ),
                name="tickets_idempotency_response_state",
            ),
        )
        indexes = (
            models.Index(
                fields=("society", "expires_at"),
                name="tickets_idempotency_expiry",
            ),
        )

    def __str__(self):
        return f"{self.principal_id} - {self.http_method} - {self.idempotency_key}"


class TicketFeedback(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="ticket_feedbacks",
    )
    ticket = models.OneToOneField(
        Ticket,
        on_delete=models.PROTECT,
        related_name="feedback",
    )
    resident = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_ticket_feedbacks",
    )
    technician = models.ForeignKey(
        TechnicianProfile,
        on_delete=models.SET_NULL,
        related_name="ticket_feedbacks",
        blank=True,
        null=True,
    )
    vendor_contract = models.ForeignKey(
        VendorContract,
        on_delete=models.SET_NULL,
        related_name="ticket_feedbacks",
        blank=True,
        null=True,
    )
    overall_rating = models.PositiveSmallIntegerField()
    timeliness_rating = models.PositiveSmallIntegerField(blank=True, null=True)
    quality_rating = models.PositiveSmallIntegerField(blank=True, null=True)
    technician_behavior_rating = models.PositiveSmallIntegerField(blank=True, null=True)
    tags = models.JSONField(default=list, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tickets_ticket_feedback"
        ordering = ("society_id", "ticket_id", "-created_at")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_feedback_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "ticket"),
                name="tickets_feedback_society_ticket_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "ticket", "id"),
                name="tickets_feedback_society_ticket_id_uniq",
            ),
            models.CheckConstraint(
                condition=Q(overall_rating__gte=1, overall_rating__lte=5),
                name="tickets_feedback_overall_rating_range",
            ),
            models.CheckConstraint(
                condition=Q(timeliness_rating__isnull=True)
                | Q(timeliness_rating__gte=1, timeliness_rating__lte=5),
                name="tickets_feedback_timeliness_rating_range",
            ),
            models.CheckConstraint(
                condition=Q(quality_rating__isnull=True)
                | Q(quality_rating__gte=1, quality_rating__lte=5),
                name="tickets_feedback_quality_rating_range",
            ),
            models.CheckConstraint(
                condition=Q(technician_behavior_rating__isnull=True)
                | Q(technician_behavior_rating__gte=1, technician_behavior_rating__lte=5),
                name="tickets_feedback_behavior_rating_range",
            ),
        )

    def __str__(self):
        return f"{self.ticket.ticket_number} - {self.overall_rating} stars ({self.resident})"

    def clean(self):
        super().clean()
        errors = {}
        if self.ticket_id and self.society_id and self.ticket.society_id != self.society_id:
            errors["ticket"] = _("Ticket must belong to the selected society.")
        if (
            self.technician_id
            and self.society_id
            and self.technician.society_id != self.society_id
        ):
            errors["technician"] = _("Technician must belong to the selected society.")
        if (
            self.vendor_contract_id
            and self.society_id
            and self.vendor_contract.society_id != self.society_id
        ):
            errors["vendor_contract"] = _(
                "Vendor contract must belong to the selected society."
            )
        if errors:
            raise ValidationError(errors)


class TicketMergeRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="ticket_merge_records",
    )
    primary_ticket = models.ForeignKey(
        Ticket,
        on_delete=models.PROTECT,
        related_name="merged_secondary_records",
    )
    secondary_ticket = models.ForeignKey(
        Ticket,
        on_delete=models.PROTECT,
        related_name="merge_records",
    )
    merged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="performed_ticket_merges",
    )
    merged_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()
    previous_secondary_status = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)
    unmerged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="performed_ticket_unmerges",
        blank=True,
        null=True,
    )
    unmerged_at = models.DateTimeField(blank=True, null=True)
    unmerge_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tickets_ticket_merge_record"
        ordering = ("society_id", "primary_ticket_id", "-merged_at")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_merge_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "primary_ticket", "id"),
                name="tickets_merge_society_primary_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "secondary_ticket", "id"),
                name="tickets_merge_society_secondary_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "secondary_ticket"),
                condition=Q(is_active=True),
                name="tickets_merge_one_active_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_active=True, unmerged_at__isnull=True, unmerged_by__isnull=True, unmerge_reason="")
                    | Q(is_active=False, unmerged_at__isnull=False, unmerged_by__isnull=False, unmerge_reason__gt="")
                ),
                name="tickets_merge_unmerge_metadata",
            ),
        )

    def __str__(self):
        return f"{self.secondary_ticket} -> {self.primary_ticket} (Active: {self.is_active})"

    def clean(self):
        super().clean()
        errors = {}
        if self.primary_ticket_id and self.society_id and self.primary_ticket.society_id != self.society_id:
            errors["primary_ticket"] = _("Primary ticket must belong to the selected society.")
        if self.secondary_ticket_id and self.society_id and self.secondary_ticket.society_id != self.society_id:
            errors["secondary_ticket"] = _("Secondary ticket must belong to the selected society.")
        if self.primary_ticket_id and self.secondary_ticket_id and self.primary_ticket_id == self.secondary_ticket_id:
            errors["secondary_ticket"] = _("Cannot merge a ticket into itself.")
        if errors:
            raise ValidationError(errors)


class TicketAttachment(models.Model):
    class Status(models.TextChoices):
        PENDING_UPLOAD = "PENDING_UPLOAD", _("Pending upload")
        QUARANTINED = "QUARANTINED", _("Quarantined")
        AVAILABLE = "AVAILABLE", _("Available")
        REJECTED = "REJECTED", _("Rejected")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="ticket_attachments",
    )
    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.PROTECT,
        related_name="attachments",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_attachments",
    )
    uploader_persona = models.CharField(max_length=32)
    original_filename = models.CharField(max_length=255)
    declared_content_type = models.CharField(max_length=128)
    declared_byte_size = models.BigIntegerField()
    storage_key = models.CharField(max_length=255, unique=True)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING_UPLOAD,
    )
    checksum_sha256 = models.CharField(max_length=64, blank=True, null=True)
    actual_content_type = models.CharField(max_length=128, blank=True, null=True)
    actual_byte_size = models.BigIntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tickets_ticket_attachment"
        ordering = ("society_id", "ticket_id", "-created_at")
        constraints = (
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_attachment_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "storage_key"),
                name="tickets_attachment_society_storage_key_uniq",
            ),
            models.CheckConstraint(
                condition=Q(declared_byte_size__gt=0),
                name="tickets_attachment_declared_byte_size_positive",
            ),
            models.CheckConstraint(
                condition=Q(actual_byte_size__isnull=True)
                | Q(actual_byte_size__gt=0),
                name="tickets_attachment_actual_byte_size_positive",
            ),
        )
        indexes = (
            models.Index(
                fields=("society", "ticket", "created_at"),
                name="tickets_attach_ticket_idx",
            ),
            models.Index(
                fields=("society", "status"),
                name="tickets_attach_status_idx",
            ),
        )

    def __str__(self):
        return f"{self.ticket_id} - {self.original_filename} ({self.status})"

    def clean(self):
        super().clean()
        if (
            self.ticket_id
            and self.society_id
            and self.ticket.society_id != self.society_id
        ):
            raise ValidationError(
                {"ticket": _("Ticket must belong to the selected society.")}
            )