import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class PlatformRoleGrant(models.Model):
    class Role(models.TextChoices):
        PLATFORM_SUPPORT = "PLATFORM_SUPPORT", "Platform support"
        PLATFORM_AUDITOR = "PLATFORM_AUDITOR", "Platform auditor"
        PLATFORM_ADMIN = "PLATFORM_ADMIN", "Platform administrator"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACTIVE = "ACTIVE", "Active"
        REVOKED = "REVOKED", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="platform_role_grants",
    )
    role = models.CharField(max_length=32, choices=Role.choices)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    reason = models.TextField()
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(blank=True, null=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_platform_role_grants",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_platform_role_grants",
        blank=True,
        null=True,
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="revoked_platform_role_grants",
        blank=True,
        null=True,
    )
    revoked_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "platform_role_grant"
        ordering = ("user_id", "role", "created_at")
        constraints = (
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gt=F("starts_at")),
                name="platform_role_grant_valid_period",
            ),
            models.CheckConstraint(
                condition=Q(approved_by__isnull=True)
                | ~Q(approved_by=F("requested_by")),
                name="platform_role_grant_four_eyes",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="PENDING",
                        approved_by__isnull=True,
                        approved_at__isnull=True,
                        revoked_by__isnull=True,
                        revoked_at__isnull=True,
                    )
                    | Q(
                        status="ACTIVE",
                        approved_by__isnull=False,
                        approved_at__isnull=False,
                        revoked_by__isnull=True,
                        revoked_at__isnull=True,
                    )
                    | Q(
                        status="REVOKED",
                        revoked_by__isnull=False,
                        revoked_at__isnull=False,
                    )
                ),
                name="platform_role_grant_status_metadata",
            ),
            models.UniqueConstraint(
                fields=("user", "role"),
                condition=Q(status__in=("PENDING", "ACTIVE")),
                name="platform_role_grant_open_unique",
            ),
        )

    def __str__(self):
        return f"{self.user} - {self.get_role_display()} - {self.get_status_display()}"

    def clean(self):
        super().clean()
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "End time must be later than start time."})

    def is_current(self, *, at=None):
        instant = at or timezone.now()
        return (
            self.status == self.Status.ACTIVE
            and self.user.is_active
            and self.starts_at <= instant
            and (self.ends_at is None or self.ends_at > instant)
        )


class PlatformAccessEvent(models.Model):
    class EventType(models.TextChoices):
        SESSION_REQUESTED = "SESSION_REQUESTED", "Session requested"
        SESSION_STARTED = "SESSION_STARTED", "Session started"
        TENANT_ROUTE_ACCESSED = "TENANT_ROUTE_ACCESSED", "Tenant route accessed"
        ACCESS_DENIED = "ACCESS_DENIED", "Access denied"
        SESSION_ENDED = "SESSION_ENDED", "Session ended"
        SESSION_EXPIRED = "SESSION_EXPIRED", "Session expired"
        RECOVERY_ACTION_ATTEMPTED = (
            "RECOVERY_ACTION_ATTEMPTED",
            "Recovery action attempted",
        )
        RECOVERY_ACTION_COMPLETED = (
            "RECOVERY_ACTION_COMPLETED",
            "Recovery action completed",
        )
        RECOVERY_ACTION_DENIED = (
            "RECOVERY_ACTION_DENIED",
            "Recovery action denied",
        )

    class Outcome(models.TextChoices):
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        DENIED = "DENIED", "Denied"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    occurred_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="platform_access_events",
    )
    role_grant = models.ForeignKey(
        PlatformRoleGrant,
        on_delete=models.PROTECT,
        related_name="access_events",
    )
    platform_role = models.CharField(max_length=32, choices=PlatformRoleGrant.Role.choices)
    society = models.ForeignKey(
        "tenancy.Society",
        on_delete=models.PROTECT,
        related_name="platform_access_events",
    )
    support_session_id = models.UUIDField()
    case_reference = models.CharField(max_length=128)
    reason = models.TextField()
    correlation_id = models.UUIDField()
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    route_or_action = models.CharField(max_length=255)
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "platform_access_event"
        ordering = ("occurred_at", "id")
        indexes = (
            models.Index(
                fields=("society", "occurred_at"),
                name="platform_event_society_time",
            ),
            models.Index(
                fields=("actor", "occurred_at"),
                name="platform_event_actor_time",
            ),
            models.Index(
                fields=("support_session_id", "occurred_at"),
                name="platform_event_session_time",
            ),
        )

    def __str__(self):
        return f"{self.event_type} - {self.actor_id} - {self.occurred_at}"


class PlatformSupportSession(models.Model):
    class EndReason(models.TextChoices):
        ENDED_BY_USER = "ENDED_BY_USER", "Ended by user"
        EXPIRED = "EXPIRED", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="platform_support_sessions",
    )
    role_grant = models.ForeignKey(
        PlatformRoleGrant,
        on_delete=models.PROTECT,
        related_name="support_sessions",
    )
    platform_role = models.CharField(max_length=32, choices=PlatformRoleGrant.Role.choices)
    society = models.ForeignKey(
        "tenancy.Society",
        on_delete=models.PROTECT,
        related_name="platform_support_sessions",
    )
    session_version = models.PositiveIntegerField()
    case_reference = models.CharField(max_length=128)
    reason = models.TextField()
    requested_duration_minutes = models.PositiveSmallIntegerField()
    started_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(blank=True, null=True)
    ended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ended_platform_support_sessions",
        blank=True,
        null=True,
    )
    end_reason = models.CharField(
        max_length=32,
        choices=EndReason.choices,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "platform_support_session"
        ordering = ("-started_at", "id")
        constraints = (
            models.CheckConstraint(
                condition=Q(
                    platform_role__in=(
                        PlatformRoleGrant.Role.PLATFORM_SUPPORT,
                        PlatformRoleGrant.Role.PLATFORM_AUDITOR,
                    )
                ),
                name="platform_session_eligible_role",
            ),
            models.CheckConstraint(
                condition=Q(requested_duration_minutes__gte=5)
                & Q(requested_duration_minutes__lte=30),
                name="platform_session_duration_range",
            ),
            models.CheckConstraint(
                condition=Q(expires_at__gte=F("started_at") + timedelta(minutes=5))
                & Q(expires_at__lte=F("started_at") + timedelta(minutes=30)),
                name="platform_session_valid_period",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        ended_at__isnull=True,
                        ended_by__isnull=True,
                        end_reason="",
                    )
                    | Q(
                        ended_at__isnull=False,
                        ended_at__gte=F("started_at"),
                    )
                    & ~Q(
                        end_reason="",
                    )
                ),
                name="platform_session_end_metadata",
            ),
            models.UniqueConstraint(
                fields=("user",),
                condition=Q(ended_at__isnull=True),
                name="platform_session_one_open_per_user",
            ),
        )

    def __str__(self):
        return f"{self.user_id} - {self.society_id} - {self.platform_role}"

    def is_current(self, *, at=None):
        instant = at or timezone.now()
        return (
            self.ended_at is None
            and self.started_at <= instant < self.expires_at
            and self.user.is_active
            and self.society.is_active
            and self.role_grant.is_current(at=instant)
            and self.role_grant.user_id == self.user_id
            and self.role_grant.role == self.platform_role
            and self.user.session_version == self.session_version
        )