from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from apps.platform_access.audit import record_platform_access_event
from apps.platform_access.models import (
    PlatformAccessEvent,
    PlatformRoleGrant,
    PlatformSupportSession,
)


class ActiveSupportSessionExists(APIException):
    status_code = 409
    default_detail = "End the active support session before starting another one."
    default_code = "active_support_session_exists"


def _current_grants(*, user, requested_role, instant):
    grants = PlatformRoleGrant.objects.select_for_update().filter(
        user=user,
        role__in=(
            PlatformRoleGrant.Role.PLATFORM_SUPPORT,
            PlatformRoleGrant.Role.PLATFORM_AUDITOR,
        ),
        status=PlatformRoleGrant.Status.ACTIVE,
        starts_at__lte=instant,
    )
    grants = grants.filter(Q(ends_at__isnull=True) | Q(ends_at__gt=instant))
    if requested_role:
        grants = grants.filter(role=requested_role)
    return list(grants[:2])


def _expire_open_sessions(*, user, instant, correlation_id):
    expired_sessions = list(
        PlatformSupportSession.objects.select_for_update()
        .select_related("user", "role_grant", "society")
        .filter(user=user, ended_at__isnull=True, expires_at__lte=instant)
    )
    for session in expired_sessions:
        session.ended_at = instant
        session.end_reason = PlatformSupportSession.EndReason.EXPIRED
        session.save(update_fields=("ended_at", "end_reason"))
        record_platform_access_event(
            session=session,
            event_type=PlatformAccessEvent.EventType.SESSION_EXPIRED,
            outcome=PlatformAccessEvent.Outcome.SUCCEEDED,
            route_or_action="support_session_expiry",
            correlation_id=correlation_id,
        )


@transaction.atomic
def list_current_support_sessions(*, user, correlation_id):
    user = get_user_model().objects.select_for_update().get(pk=user.pk)
    _expire_open_sessions(
        user=user,
        instant=timezone.now(),
        correlation_id=correlation_id,
    )
    return list(
        PlatformSupportSession.objects.select_related("user", "role_grant", "society")
        .filter(user=user, ended_at__isnull=True)
        .order_by("-started_at", "id")
    )


@transaction.atomic
def create_support_session(
    *,
    user,
    validated_token,
    society,
    case_reference,
    reason,
    duration_minutes,
    requested_role,
    correlation_id,
):
    user = get_user_model().objects.select_for_update().get(pk=user.pk)
    instant = timezone.now()
    _expire_open_sessions(
        user=user,
        instant=instant,
        correlation_id=correlation_id,
    )
    if PlatformSupportSession.objects.filter(
        user=user,
        ended_at__isnull=True,
    ).exists():
        raise ActiveSupportSessionExists()

    grants = _current_grants(
        user=user,
        requested_role=requested_role,
        instant=instant,
    )
    if not grants:
        raise PermissionDenied("A current support or auditor grant is required.")
    if len(grants) > 1:
        raise ValidationError(
            {"platform_role": "Select the platform role for this support session."}
        )
    grant = grants[0]

    session = PlatformSupportSession.objects.create(
        user=user,
        role_grant=grant,
        platform_role=grant.role,
        society=society,
        session_version=validated_token["session_version"],
        case_reference=case_reference,
        reason=reason,
        requested_duration_minutes=duration_minutes,
        started_at=instant,
        expires_at=instant + timedelta(minutes=duration_minutes),
    )
    event_metadata = {"requested_duration_minutes": duration_minutes}
    record_platform_access_event(
        session=session,
        event_type=PlatformAccessEvent.EventType.SESSION_REQUESTED,
        outcome=PlatformAccessEvent.Outcome.SUCCEEDED,
        route_or_action="POST /api/v1/platform/support-sessions/",
        correlation_id=correlation_id,
        metadata=event_metadata,
    )
    record_platform_access_event(
        session=session,
        event_type=PlatformAccessEvent.EventType.SESSION_STARTED,
        outcome=PlatformAccessEvent.Outcome.SUCCEEDED,
        route_or_action="POST /api/v1/platform/support-sessions/",
        correlation_id=correlation_id,
        metadata=event_metadata,
    )
    return session


@transaction.atomic
def end_support_session(*, user, session_id, correlation_id):
    session = (
        PlatformSupportSession.objects.select_for_update()
        .select_related("user", "role_grant", "society")
        .filter(id=session_id, user=user)
        .first()
    )
    if session is None:
        raise PermissionDenied("Support session not found.")
    if session.ended_at is not None:
        return session

    instant = timezone.now()
    if session.expires_at <= instant:
        session.end_reason = PlatformSupportSession.EndReason.EXPIRED
        event_type = PlatformAccessEvent.EventType.SESSION_EXPIRED
    else:
        session.ended_by = user
        session.end_reason = PlatformSupportSession.EndReason.ENDED_BY_USER
        event_type = PlatformAccessEvent.EventType.SESSION_ENDED
    session.ended_at = instant
    session.save(update_fields=("ended_at", "ended_by", "end_reason"))
    record_platform_access_event(
        session=session,
        event_type=event_type,
        outcome=PlatformAccessEvent.Outcome.SUCCEEDED,
        route_or_action=f"DELETE /api/v1/platform/support-sessions/{session.id}/",
        correlation_id=correlation_id,
    )
    return session