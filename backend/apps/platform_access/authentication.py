import uuid
from datetime import UTC, datetime, timedelta

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.authentication.backends import TenantJWTAuthentication
from apps.platform_access.audit import schedule_platform_access_denial
from apps.platform_access.models import PlatformRoleGrant, PlatformSupportSession
from apps.tenancy.context import set_local_society_id


class PlatformJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        authenticated = super().authenticate(request)
        if authenticated is None:
            return None

        user, validated_token = authenticated
        TenantJWTAuthentication._validate_session(user, validated_token)
        return user, validated_token


def validate_platform_step_up(validated_token, *, at=None):
    instant = at or timezone.now()
    auth_time = validated_token.get("auth_time")
    if isinstance(auth_time, bool):
        raise PermissionDenied("Step-up authentication claims are invalid.")
    try:
        authenticated_at = datetime.fromtimestamp(int(auth_time), tz=UTC)
    except (TypeError, ValueError, OSError) as exc:
        raise PermissionDenied("Step-up authentication claims are invalid.") from exc

    if authenticated_at > instant:
        raise PermissionDenied("Step-up authentication claims are invalid.")
    if instant - authenticated_at > timedelta(minutes=5):
        raise PermissionDenied("Step-up authentication is stale.")

    authentication_methods = validated_token.get("amr")
    if not isinstance(authentication_methods, list) or not all(
        isinstance(method, str) for method in authentication_methods
    ):
        raise PermissionDenied("Step-up authentication claims are invalid.")
    if not {"mfa", "otp", "hwk"}.intersection(authentication_methods):
        raise PermissionDenied("An approved step-up method is required.")


class PlatformSupportSessionAuthentication(PlatformJWTAuthentication):
    def authenticate(self, request):
        authenticated = super().authenticate(request)
        if authenticated is None:
            return None

        user, validated_token = authenticated
        session_id = self._parse_support_session_id(
            request.headers.get("X-Support-Session-ID")
        )
        session = (
            PlatformSupportSession.objects.select_for_update().select_related(
                "user",
                "role_grant",
                "society",
            )
            .filter(id=session_id, user=user)
            .first()
        )
        if session is None:
            raise PermissionDenied("Support session is not available.")

        request.support_session = session
        if session.platform_role == PlatformRoleGrant.Role.PLATFORM_SUPPORT:
            request.persona = "platform_support"
        else:
            request.persona = "platform_auditor"

        instant = timezone.now()
        if not session.is_current(at=instant):
            request.platform_denial_reason = "inactive_support_session"
            schedule_platform_access_denial(
                request,
                session=session,
                reason_code=request.platform_denial_reason,
            )
            raise PermissionDenied("Support session is not active.")
        if session.platform_role not in {
            PlatformRoleGrant.Role.PLATFORM_SUPPORT,
            PlatformRoleGrant.Role.PLATFORM_AUDITOR,
        }:
            request.platform_denial_reason = "ineligible_platform_role"
            schedule_platform_access_denial(
                request,
                session=session,
                reason_code=request.platform_denial_reason,
            )
            raise PermissionDenied("Support session is not active.")

        society_id = TenantJWTAuthentication._parse_society_id(
            request.headers.get("X-Society-ID")
        )
        if society_id != session.society_id:
            request.platform_denial_reason = "society_mismatch"
            schedule_platform_access_denial(
                request,
                session=session,
                reason_code=request.platform_denial_reason,
            )
            raise PermissionDenied("Support session society does not match the request.")

        set_local_society_id(society_id)
        request.society = session.society
        request.membership = None
        return user, validated_token

    @staticmethod
    def _parse_support_session_id(raw_session_id):
        if not raw_session_id:
            raise ValidationError({"X-Support-Session-ID": "This header is required."})
        try:
            return uuid.UUID(raw_session_id)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValidationError(
                {"X-Support-Session-ID": "Enter a valid UUID."}
            ) from exc


class TenantOrPlatformSupportAuthentication(JWTAuthentication):
    def authenticate(self, request):
        if request.headers.get("X-Support-Session-ID"):
            return PlatformSupportSessionAuthentication().authenticate(request)
        return TenantJWTAuthentication().authenticate(request)