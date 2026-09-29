import hashlib
import hmac
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField

from apps.identity.models import validate_iana_timezone


def default_invitation_expiry():
    return timezone.now() + timedelta(days=3)


class Society(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    registration_code = models.CharField(max_length=64, unique=True)
    timezone = models.CharField(
        max_length=64,
        default="Asia/Kolkata",
        validators=[validate_iana_timezone],
    )
    locale = models.CharField(max_length=16, default="en-IN")
    currency = models.CharField(max_length=3, default="INR")
    is_active = models.BooleanField(default=True)
    retention_policy = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenancy_society"
        ordering = ("registration_code",)

    def __str__(self):
        return self.registration_code

    def clean_fields(self, exclude=None):
        self._normalize_codes()
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        self._normalize_codes()

    def _normalize_codes(self):
        self.registration_code = self.registration_code.strip().upper()
        self.currency = self.currency.strip().upper()


class StaffMembership(models.Model):
    class Role(models.TextChoices):
        FACILITY_MANAGER = "FACILITY_MANAGER", _("Facility manager")
        ESTATE_SUPERVISOR = "ESTATE_SUPERVISOR", _("Estate supervisor")
        HELPDESK_OPERATOR = "HELPDESK_OPERATOR", _("Helpdesk operator")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="staff_memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="staff_memberships",
    )
    role = models.CharField(max_length=32, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenancy_staff_membership"
        ordering = ("society_id", "user_id", "starts_at")
        constraints = [
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tenancy_staff_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "user"),
                condition=Q(is_active=True),
                name="tenancy_staff_one_active_uniq",
            ),
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gt=F("starts_at")),
                name="tenancy_staff_valid_period",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.society} - {self.get_role_display()}"

    def clean(self):
        super().clean()
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": _("End time must be later than start time.")})

    def is_current(self, at=None):
        instant = at or timezone.now()
        return (
            self.is_active
            and self.starts_at <= instant
            and (self.ends_at is None or instant < self.ends_at)
            and self.society.is_active
            and self.user.is_active
        )


class Block(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="blocks",
    )
    name = models.CharField(max_length=128)
    code = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenancy_block"
        ordering = ("society_id", "code")
        constraints = [
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tenancy_block_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "code"),
                name="tenancy_block_society_code_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.society} - {self.code}"

    def clean_fields(self, exclude=None):
        self._normalize_fields()
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        self._normalize_fields()

    def _normalize_fields(self):
        self.name = " ".join(self.name.split())
        self.code = self.code.strip().upper()


class Unit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="units",
    )
    block = models.ForeignKey(
        Block,
        on_delete=models.PROTECT,
        related_name="units",
    )
    door_number = models.CharField(max_length=32)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenancy_unit"
        ordering = ("society_id", "block_id", "door_number")
        constraints = [
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tenancy_unit_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "block", "door_number"),
                name="tenancy_unit_society_block_door_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.block.code} - {self.door_number}"

    def clean_fields(self, exclude=None):
        self.door_number = self.door_number.strip().upper()
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        self.door_number = self.door_number.strip().upper()
        if self.block_id and self.society_id and self.block.society_id != self.society_id:
            raise ValidationError({"block": _("Block must belong to the selected society.")})


class CommonArea(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="common_areas",
    )
    name = models.CharField(max_length=128)
    normalized_name = models.CharField(max_length=128, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenancy_common_area"
        ordering = ("society_id", "normalized_name")
        constraints = [
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tenancy_common_area_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "normalized_name"),
                name="tenancy_common_area_society_name_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.society} - {self.name}"

    def clean_fields(self, exclude=None):
        self._normalize_name()
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        self._normalize_name()

    def _normalize_name(self):
        self.name = " ".join(self.name.split())
        self.normalized_name = self.name.casefold()


class UnitOccupancy(models.Model):
    class OccupancyType(models.TextChoices):
        OWNER = "OWNER", _("Owner")
        TENANT = "TENANT", _("Tenant")
        FAMILY = "FAMILY", _("Family member")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="unit_occupancies",
    )
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="occupancies",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="unit_occupancies",
    )
    occupancy_type = models.CharField(max_length=16, choices=OccupancyType.choices)
    is_primary_contact = models.BooleanField(default=False)
    can_approve_costs = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenancy_unit_occupancy"
        ordering = ("society_id", "unit_id", "starts_at")
        constraints = [
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tenancy_occupancy_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "unit", "user"),
                condition=Q(is_active=True),
                name="tenancy_occupancy_one_active_uniq",
            ),
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gt=F("starts_at")),
                name="tenancy_occupancy_valid_period",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.unit} - {self.get_occupancy_type_display()}"

    def clean(self):
        super().clean()
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": _("End time must be later than start time.")})
        if self.unit_id and self.society_id and self.unit.society_id != self.society_id:
            raise ValidationError({"unit": _("Unit must belong to the selected society.")})

    def is_current(self, at=None):
        instant = at or timezone.now()
        return (
            self.is_active
            and self.starts_at <= instant
            and (self.ends_at is None or instant < self.ends_at)
            and self.unit.is_active
            and self.society.is_active
            and self.user.is_active
        )


class CommitteeMembership(models.Model):
    class Role(models.TextChoices):
        PRESIDENT = "PRESIDENT", _("President")
        SECRETARY = "SECRETARY", _("Secretary")
        TREASURER = "TREASURER", _("Treasurer")
        MEMBER = "MEMBER", _("Member")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="committee_memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="committee_memberships",
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenancy_committee_membership"
        ordering = ("society_id", "user_id", "starts_at")
        constraints = [
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tenancy_committee_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "user"),
                condition=Q(is_active=True),
                name="tenancy_committee_one_active_uniq",
            ),
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gt=F("starts_at")),
                name="tenancy_committee_valid_period",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.society} - {self.get_role_display()}"

    def clean(self):
        super().clean()
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": _("End time must be later than start time.")})

    def is_current(self, at=None):
        instant = at or timezone.now()
        return (
            self.is_active
            and self.starts_at <= instant
            and (self.ends_at is None or instant < self.ends_at)
            and self.society.is_active
            and self.user.is_active
        )


class TechnicianProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="technician_profiles",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="technician_profiles",
    )
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(blank=True, null=True)
    max_active_tickets = models.PositiveIntegerField(default=5)
    current_active_tickets_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenancy_technician_profile"
        ordering = ("society_id", "user_id", "starts_at")
        constraints = [
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tenancy_technician_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "user"),
                condition=Q(is_active=True),
                name="tenancy_technician_one_active_uniq",
            ),
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gt=F("starts_at")),
                name="tenancy_technician_valid_period",
            ),
            models.CheckConstraint(
                condition=Q(max_active_tickets__gt=0),
                name="tenancy_technician_positive_capacity",
            ),
            models.CheckConstraint(
                condition=Q(current_active_tickets_count__lte=F("max_active_tickets")),
                name="tenancy_technician_capacity_not_exceeded",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.society} - Technician"

    def clean(self):
        super().clean()
        errors = {}
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            errors["ends_at"] = _("End time must be later than start time.")
        if self.max_active_tickets <= 0:
            errors["max_active_tickets"] = _("Capacity must be greater than zero.")
        if self.current_active_tickets_count > self.max_active_tickets:
            errors["current_active_tickets_count"] = _("Current workload cannot exceed capacity.")
        if errors:
            raise ValidationError(errors)

    def is_current(self, at=None):
        instant = at or timezone.now()
        return (
            self.is_active
            and self.starts_at <= instant
            and (self.ends_at is None or instant < self.ends_at)
            and self.society.is_active
            and self.user.is_active
        )


class Vendor(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="vendors",
    )
    company_name = models.CharField(max_length=255)
    normalized_company_name = models.CharField(max_length=255, editable=False)
    contact_person = models.CharField(max_length=128)
    phone_number = PhoneNumberField(region=None)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenancy_vendor"
        ordering = ("society_id", "normalized_company_name")
        constraints = [
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tenancy_vendor_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "normalized_company_name"),
                name="tenancy_vendor_society_name_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.society} - {self.company_name}"

    def clean_fields(self, exclude=None):
        self._normalize_fields()
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        self._normalize_fields()

    def _normalize_fields(self):
        self.company_name = " ".join(self.company_name.split())
        self.normalized_company_name = self.company_name.casefold()
        self.contact_person = " ".join(self.contact_person.split())
        self.email = self.email.strip().lower()


class VendorContract(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="vendor_contracts",
    )
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name="contracts",
    )
    starts_on = models.DateField()
    ends_on = models.DateField()
    is_active = models.BooleanField(default=True)
    max_active_tickets = models.PositiveIntegerField(blank=True, null=True)
    current_active_tickets_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenancy_vendor_contract"
        ordering = ("society_id", "vendor_id", "starts_on")
        constraints = [
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tenancy_vendor_contract_society_id_uniq",
            ),
            models.CheckConstraint(
                condition=Q(ends_on__gte=F("starts_on")),
                name="tenancy_vendor_contract_valid_period",
            ),
            models.CheckConstraint(
                condition=Q(max_active_tickets__isnull=True) | Q(max_active_tickets__gt=0),
                name="tenancy_vendor_contract_positive_capacity",
            ),
            models.CheckConstraint(
                condition=Q(max_active_tickets__isnull=True)
                | Q(current_active_tickets_count__lte=F("max_active_tickets")),
                name="tenancy_vendor_contract_capacity_not_exceeded",
            ),
        ]

    def __str__(self):
        return f"{self.vendor} - {self.starts_on} to {self.ends_on}"

    def clean(self):
        super().clean()
        errors = {}
        if self.ends_on < self.starts_on:
            errors["ends_on"] = _("End date cannot be earlier than start date.")
        if self.vendor_id and self.society_id and self.vendor.society_id != self.society_id:
            errors["vendor"] = _("Vendor must belong to the selected society.")
        if self.max_active_tickets is not None and self.max_active_tickets <= 0:
            errors["max_active_tickets"] = _(
                "Capacity must be greater than zero or omitted for unlimited capacity."
            )
        if (
            self.max_active_tickets is not None
            and self.current_active_tickets_count > self.max_active_tickets
        ):
            errors["current_active_tickets_count"] = _("Current workload cannot exceed capacity.")
        if errors:
            raise ValidationError(errors)

    def is_current(self, on_date=None):
        day = on_date or timezone.localdate()
        return (
            self.is_active
            and self.starts_on <= day <= self.ends_on
            and self.vendor.is_active
            and self.society.is_active
        )


class VendorStaffMembership(models.Model):
    class Role(models.TextChoices):
        DISPATCHER = "DISPATCHER", _("Dispatcher")
        WORKER = "WORKER", _("Worker")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="vendor_staff_memberships",
    )
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name="staff_memberships",
    )
    contract = models.ForeignKey(
        VendorContract,
        on_delete=models.PROTECT,
        related_name="staff_memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="vendor_staff_memberships",
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenancy_vendor_staff_membership"
        ordering = ("society_id", "vendor_id", "user_id", "starts_at")
        constraints = [
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tenancy_vendor_staff_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "contract", "user"),
                condition=Q(is_active=True),
                name="tenancy_vendor_staff_one_active_uniq",
            ),
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gt=F("starts_at")),
                name="tenancy_vendor_staff_valid_period",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.contract} - {self.get_role_display()}"

    def clean(self):
        super().clean()
        errors = {}
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            errors["ends_at"] = _("End time must be later than start time.")
        if self.vendor_id and self.society_id and self.vendor.society_id != self.society_id:
            errors["vendor"] = _("Vendor must belong to the selected society.")
        if self.contract_id and self.society_id:
            if self.contract.society_id != self.society_id:
                errors["contract"] = _("Contract must belong to the selected society.")
            elif self.vendor_id and self.contract.vendor_id != self.vendor_id:
                errors["contract"] = _("Contract must belong to the selected vendor.")
        if errors:
            raise ValidationError(errors)

    def is_current(self, at=None):
        instant = at or timezone.now()
        return (
            self.is_active
            and self.starts_at <= instant
            and (self.ends_at is None or instant < self.ends_at)
            and self.contract.is_current(timezone.localdate(instant))
            and self.user.is_active
        )


class MembershipInvitation(models.Model):
    class Persona(models.TextChoices):
        STAFF = "STAFF", _("Staff")
        RESIDENT = "RESIDENT", _("Resident")
        COMMITTEE = "COMMITTEE", _("Committee")

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        ACCEPTED = "ACCEPTED", _("Accepted")
        REVOKED = "REVOKED", _("Revoked")
        EXPIRED = "EXPIRED", _("Expired")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    society = models.ForeignKey(
        Society,
        on_delete=models.PROTECT,
        related_name="membership_invitations",
    )
    invitee_phone = PhoneNumberField(region=None)
    invitee_email = models.EmailField(blank=True, default="")
    persona = models.CharField(max_length=16, choices=Persona.choices)
    unit = models.ForeignKey(
        Unit,
        on_delete=models.PROTECT,
        related_name="membership_invitations",
        blank=True,
        null=True,
    )
    occupancy_type = models.CharField(  # noqa: DJ001
        max_length=16,
        choices=UnitOccupancy.OccupancyType.choices,
        blank=True,
        null=True,
    )
    staff_role = models.CharField(  # noqa: DJ001
        max_length=32,
        choices=StaffMembership.Role.choices,
        blank=True,
        null=True,
    )
    committee_role = models.CharField(  # noqa: DJ001
        max_length=16,
        choices=CommitteeMembership.Role.choices,
        blank=True,
        null=True,
    )
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    expires_at = models.DateTimeField(default=default_invitation_expiry)
    accepted_at = models.DateTimeField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_membership_invitations",
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="accepted_membership_invitations",
        blank=True,
        null=True,
    )
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="revoked_membership_invitations",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenancy_membership_invitation"
        ordering = ("society_id", "-created_at")
        indexes = [
            models.Index(
                fields=("society", "status", "expires_at"),
                name="tenancy_invite_status_idx",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("society", "id"),
                name="tenancy_invite_society_id_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "invitee_phone", "persona", "unit"),
                condition=Q(status="PENDING", persona="RESIDENT"),
                name="tenancy_invite_pending_resident_uniq",
            ),
            models.UniqueConstraint(
                fields=("society", "invitee_phone", "persona"),
                condition=Q(status="PENDING") & ~Q(persona="RESIDENT"),
                name="tenancy_invite_pending_role_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        persona="RESIDENT",
                        unit__isnull=False,
                        occupancy_type__isnull=False,
                        staff_role__isnull=True,
                        committee_role__isnull=True,
                    )
                    | Q(
                        persona="STAFF",
                        unit__isnull=True,
                        occupancy_type__isnull=True,
                        staff_role__isnull=False,
                        committee_role__isnull=True,
                    )
                    | Q(
                        persona="COMMITTEE",
                        unit__isnull=True,
                        occupancy_type__isnull=True,
                        staff_role__isnull=True,
                        committee_role__isnull=False,
                    )
                ),
                name="tenancy_invite_payload_matches_persona",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="PENDING",
                        accepted_at__isnull=True,
                        accepted_by__isnull=True,
                        revoked_at__isnull=True,
                        revoked_by__isnull=True,
                    )
                    | Q(
                        status="ACCEPTED",
                        accepted_at__isnull=False,
                        accepted_by__isnull=False,
                        revoked_at__isnull=True,
                        revoked_by__isnull=True,
                    )
                    | Q(
                        status="REVOKED",
                        accepted_at__isnull=True,
                        accepted_by__isnull=True,
                        revoked_at__isnull=False,
                        revoked_by__isnull=False,
                    )
                    | Q(
                        status="EXPIRED",
                        accepted_at__isnull=True,
                        accepted_by__isnull=True,
                        revoked_at__isnull=True,
                        revoked_by__isnull=True,
                    )
                ),
                name="tenancy_invite_status_timestamps",
            ),
        ]

    def __str__(self):
        return f"{self.invitee_phone} - {self.society} - {self.persona}"

    def clean(self):
        super().clean()
        errors = {}
        if self.invitee_email:
            self.invitee_email = self.invitee_email.strip().casefold()
        if self.expires_at <= timezone.now():
            errors["expires_at"] = _("Expiry must be in the future.")

        payload_is_valid = {
            self.Persona.RESIDENT: bool(
                self.unit_id
                and self.occupancy_type
                and not self.staff_role
                and not self.committee_role
            ),
            self.Persona.STAFF: bool(
                not self.unit_id
                and not self.occupancy_type
                and self.staff_role
                and not self.committee_role
            ),
            self.Persona.COMMITTEE: bool(
                not self.unit_id
                and not self.occupancy_type
                and not self.staff_role
                and self.committee_role
            ),
        }.get(self.persona, False)
        if not payload_is_valid:
            errors["persona"] = _("Invitation details do not match the persona.")

        if self.unit_id and self.society_id and self.unit.society_id != self.society_id:
            errors["unit"] = _("Unit must belong to the selected society.")
        if errors:
            raise ValidationError(errors)

    def is_actionable(self, at=None):
        instant = at or timezone.now()
        return self.status == self.Status.PENDING and instant < self.expires_at

    @staticmethod
    def digest_token(raw_token):
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    def matches_token(self, raw_token):
        return hmac.compare_digest(self.token_digest, self.digest_token(raw_token))
