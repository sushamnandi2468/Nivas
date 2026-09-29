import uuid

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as APIValidationError
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.authentication.tokens import validate_session_token
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import (
    CommitteeMembership,
    Society,
    StaffMembership,
    TechnicianProfile,
    UnitOccupancy,
    VendorStaffMembership,
)


class TenantJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        authenticated = super().authenticate(request)
        if authenticated is None:
            return None

        user, validated_token = authenticated
        validate_session_token(user=user, token=validated_token)
        society_id = self._parse_society_id(request.headers.get("X-Society-ID"))
        society = Society.objects.filter(id=society_id, is_active=True).first()
        if society is None:
            raise NotFound("Society not found.")

        set_local_society_id(society_id)
        instant = timezone.now()
        membership, persona = self._resolve_membership(
            society_id=society_id,
            user_id=user.id,
            instant=instant,
        )
        if membership is None:
            raise PermissionDenied("No active membership in this society.")

        request.society = society
        request.membership = membership
        request.persona = persona
        return user, validated_token

    @staticmethod
    def _resolve_membership(*, society_id, user_id, instant):
        current_period = Q(ends_at__isnull=True) | Q(ends_at__gt=instant)
        membership_specs = (
            (StaffMembership, "staff", {}),
            (
                UnitOccupancy,
                "resident",
                {"unit__is_active": True},
            ),
            (CommitteeMembership, "committee", {}),
            (TechnicianProfile, "technician", {}),
            (
                VendorStaffMembership,
                "vendor",
                {
                    "vendor__is_active": True,
                    "contract__is_active": True,
                    "contract__starts_on__lte": timezone.localdate(instant),
                    "contract__ends_on__gte": timezone.localdate(instant),
                },
            ),
        )
        for model, persona, extra_filters in membership_specs:
            membership = (
                model.objects.filter(
                    society_id=society_id,
                    user_id=user_id,
                    is_active=True,
                    starts_at__lte=instant,
                    **extra_filters,
                )
                .filter(current_period)
                .first()
            )
            if membership is not None:
                return membership, persona

        return None, None

    @staticmethod
    def _parse_society_id(raw_society_id):
        if not raw_society_id:
            raise APIValidationError({"X-Society-ID": "This header is required."})

        try:
            return uuid.UUID(raw_society_id)
        except (AttributeError, TypeError, ValueError) as exc:
            raise APIValidationError({"X-Society-ID": "Enter a valid UUID."}) from exc

