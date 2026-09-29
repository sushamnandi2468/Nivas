import uuid

from django.db.models import Q
from django.utils import timezone

from apps.platform_access.models import PlatformAccessEvent, PlatformRoleGrant


def correlation_id_for_request(request):
    existing = getattr(request, "correlation_id", None)
    if existing is not None:
        return existing

    try:
        correlation_id = uuid.UUID(request.headers.get("X-Correlation-ID", ""))
    except (AttributeError, TypeError, ValueError):
        correlation_id = uuid.uuid4()
    request.correlation_id = correlation_id
    return correlation_id


def record_platform_access_event(
    *,
    session,
    event_type,
    outcome,
    route_or_action,
    correlation_id,
    metadata=None,
):
    return PlatformAccessEvent.objects.create(
        actor=session.user,
        role_grant=session.role_grant,
        platform_role=session.platform_role,
        society=session.society,
        support_session_id=session.id,
        case_reference=session.case_reference,
        reason=session.reason,
        correlation_id=correlation_id,
        event_type=event_type,
        route_or_action=route_or_action,
        outcome=outcome,
        metadata=metadata or {},
    )


def schedule_platform_access_denial(request, *, session, reason_code):
    django_request = getattr(request, "_request", request)
    if hasattr(django_request, "platform_access_denial"):
        return
    request.platform_access_event_recorded = True
    django_request.platform_access_denial = {
        "actor_id": session.user_id,
        "role_grant_id": session.role_grant_id,
        "platform_role": session.platform_role,
        "society_id": session.society_id,
        "support_session_id": session.id,
        "case_reference": session.case_reference,
        "reason": session.reason,
        "correlation_id": correlation_id_for_request(request),
        "event_type": PlatformAccessEvent.EventType.ACCESS_DENIED,
        "route_or_action": f"{request.method} {request.path}",
        "outcome": PlatformAccessEvent.Outcome.DENIED,
        "metadata": {"reason_code": reason_code},
    }


def schedule_support_session_start_denial(
    request,
    *,
    user,
    validated_data,
    reason_code,
):
    instant = timezone.now()
    grants = PlatformRoleGrant.objects.filter(
        user=user,
        role__in=(
            PlatformRoleGrant.Role.PLATFORM_SUPPORT,
            PlatformRoleGrant.Role.PLATFORM_AUDITOR,
        ),
        status=PlatformRoleGrant.Status.ACTIVE,
        starts_at__lte=instant,
    ).filter(Q(ends_at__isnull=True) | Q(ends_at__gt=instant))
    requested_role = validated_data.get("platform_role")
    if requested_role:
        grants = grants.filter(role=requested_role)
    grants = list(grants[:2])
    if len(grants) != 1:
        return

    grant = grants[0]
    django_request = getattr(request, "_request", request)
    request.platform_access_event_recorded = True
    django_request.platform_access_denial = {
        "actor_id": user.id,
        "role_grant_id": grant.id,
        "platform_role": grant.role,
        "society_id": validated_data["society"].id,
        "support_session_id": uuid.uuid4(),
        "case_reference": validated_data["case_reference"],
        "reason": validated_data["reason"],
        "correlation_id": correlation_id_for_request(request),
        "event_type": PlatformAccessEvent.EventType.ACCESS_DENIED,
        "route_or_action": f"{request.method} {request.path}",
        "outcome": PlatformAccessEvent.Outcome.DENIED,
        "metadata": {
            "reason_code": reason_code,
            "requested_duration_minutes": validated_data["duration_minutes"],
        },
    }