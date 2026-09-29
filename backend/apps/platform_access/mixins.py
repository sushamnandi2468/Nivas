from django.utils import timezone
from django.utils.cache import patch_vary_headers
from rest_framework import status
from rest_framework.response import Response

from apps.platform_access.audit import (
    correlation_id_for_request,
    record_platform_access_event,
)
from apps.platform_access.models import PlatformAccessEvent


class PlatformSessionResponseMixin:
    def deny_platform_session_mutation(self, request):
        session = request.support_session
        record_platform_access_event(
            session=session,
            event_type=PlatformAccessEvent.EventType.ACCESS_DENIED,
            outcome=PlatformAccessEvent.Outcome.DENIED,
            route_or_action=f"{request.method} {request.path}",
            correlation_id=correlation_id_for_request(request),
            metadata={"reason_code": "read_only_session"},
        )
        request.platform_access_event_recorded = True
        return Response(
            {"detail": "Platform support sessions are read-only."},
            status=status.HTTP_403_FORBIDDEN,
        )

    def finalize_response(self, request, response, *args, **kwargs):
        session = getattr(request, "support_session", None)
        if session is None:
            return super().finalize_response(request, response, *args, **kwargs)

        if response.status_code < 400 and not session.is_current(at=timezone.now()):
            request.platform_denial_reason = "inactive_before_response"
            response = Response(
                {"detail": "Support session is no longer active."},
                status=status.HTTP_403_FORBIDDEN,
            )

        response = super().finalize_response(request, response, *args, **kwargs)

        event_recorded = getattr(
            request,
            "platform_access_event_recorded",
            False,
        )
        if response.status_code < 400 and not event_recorded:
            record_platform_access_event(
                session=session,
                event_type=PlatformAccessEvent.EventType.TENANT_ROUTE_ACCESSED,
                outcome=PlatformAccessEvent.Outcome.SUCCEEDED,
                route_or_action=f"{request.method} {request.path}",
                correlation_id=correlation_id_for_request(request),
                metadata={"status_code": response.status_code},
            )
        elif response.status_code >= 400 and not event_recorded:
            record_platform_access_event(
                session=session,
                event_type=PlatformAccessEvent.EventType.ACCESS_DENIED,
                outcome=PlatformAccessEvent.Outcome.DENIED,
                route_or_action=f"{request.method} {request.path}",
                correlation_id=correlation_id_for_request(request),
                metadata={
                    "reason_code": getattr(
                        request,
                        "platform_denial_reason",
                        "request_denied",
                    ),
                    "status_code": response.status_code,
                },
            )

        response["Cache-Control"] = "private, no-store"
        response["X-NivasOps-Persona"] = request.persona
        response["X-NivasOps-Society-ID"] = str(session.society_id)
        response["X-NivasOps-Support-Case"] = session.case_reference
        response["X-NivasOps-Support-Read-Only"] = "true"
        response["X-NivasOps-Support-Expires-At"] = session.expires_at.isoformat()
        response["X-Correlation-ID"] = str(correlation_id_for_request(request))
        patch_vary_headers(
            response,
            ("Authorization", "X-Society-ID", "X-Support-Session-ID"),
        )
        return response