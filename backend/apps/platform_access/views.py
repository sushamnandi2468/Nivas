from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.platform_access.audit import (
    correlation_id_for_request,
    schedule_support_session_start_denial,
)
from apps.platform_access.authentication import (
    PlatformJWTAuthentication,
    validate_platform_step_up,
)
from apps.platform_access.models import PlatformRoleGrant
from apps.platform_access.permissions import IsPlatformAdmin
from apps.platform_access.serializers import (
    PlatformRoleGrantSerializer,
    PlatformSupportSessionCreateSerializer,
    PlatformSupportSessionSerializer,
)
from apps.platform_access.services import (
    create_support_session,
    end_support_session,
    list_current_support_sessions,
)


class PlatformRoleGrantListCreateView(generics.ListCreateAPIView):
    authentication_classes = (PlatformJWTAuthentication,)
    permission_classes = (IsPlatformAdmin,)
    queryset = PlatformRoleGrant.objects.select_related(
        "user",
        "requested_by",
        "approved_by",
        "revoked_by",
    )
    serializer_class = PlatformRoleGrantSerializer

    def perform_create(self, serializer):
        serializer.save(requested_by=self.request.user)


class PlatformRoleGrantApproveView(generics.GenericAPIView):
    authentication_classes = (PlatformJWTAuthentication,)
    permission_classes = (IsPlatformAdmin,)
    queryset = PlatformRoleGrant.objects.all()
    serializer_class = PlatformRoleGrantSerializer

    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            grant = get_object_or_404(
                self.get_queryset().select_for_update(),
                id=kwargs["pk"],
            )
            if grant.status != PlatformRoleGrant.Status.PENDING:
                return Response(
                    {"detail": "Only pending grants can be approved."},
                    status=status.HTTP_409_CONFLICT,
                )
            if grant.requested_by_id == request.user.id:
                raise PermissionDenied(
                    "A different platform administrator must approve this grant."
                )

            instant = timezone.now()
            if grant.ends_at is not None and grant.ends_at <= instant:
                return Response(
                    {"detail": "Expired grants cannot be approved."},
                    status=status.HTTP_409_CONFLICT,
                )

            grant.status = PlatformRoleGrant.Status.ACTIVE
            grant.approved_by = request.user
            grant.approved_at = instant
            try:
                grant.full_clean()
            except DjangoValidationError as exc:
                return Response(exc.message_dict, status=status.HTTP_400_BAD_REQUEST)
            grant.save(
                update_fields=("status", "approved_by", "approved_at", "updated_at")
            )
        return Response(self.get_serializer(grant).data)


class PlatformRoleGrantRevokeView(generics.GenericAPIView):
    authentication_classes = (PlatformJWTAuthentication,)
    permission_classes = (IsPlatformAdmin,)
    queryset = PlatformRoleGrant.objects.all()
    serializer_class = PlatformRoleGrantSerializer

    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            grant = get_object_or_404(
                self.get_queryset().select_for_update(),
                id=kwargs["pk"],
            )
            if grant.status == PlatformRoleGrant.Status.REVOKED:
                return Response(self.get_serializer(grant).data)

            grant.status = PlatformRoleGrant.Status.REVOKED
            grant.revoked_by = request.user
            grant.revoked_at = timezone.now()
            grant.save(update_fields=("status", "revoked_by", "revoked_at", "updated_at"))
        return Response(self.get_serializer(grant).data)


class PlatformSupportSessionCreateView(generics.GenericAPIView):
    authentication_classes = (PlatformJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    serializer_class = PlatformSupportSessionCreateSerializer

    def get(self, request, *args, **kwargs):
        sessions = list_current_support_sessions(
            user=request.user,
            correlation_id=correlation_id_for_request(request),
        )
        return Response(
            PlatformSupportSessionSerializer(sessions, many=True).data,
            headers={
                "Cache-Control": "private, no-store",
                "X-Correlation-ID": str(request.correlation_id),
            },
        )

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            validate_platform_step_up(request.auth)
        except PermissionDenied:
            schedule_support_session_start_denial(
                request,
                user=request.user,
                validated_data=serializer.validated_data,
                reason_code="step_up_denied",
            )
            raise
        session = create_support_session(
            user=request.user,
            validated_token=request.auth,
            society=serializer.validated_data["society"],
            case_reference=serializer.validated_data["case_reference"],
            reason=serializer.validated_data["reason"],
            duration_minutes=serializer.validated_data["duration_minutes"],
            requested_role=serializer.validated_data.get("platform_role"),
            correlation_id=correlation_id_for_request(request),
        )
        return Response(
            PlatformSupportSessionSerializer(session).data,
            status=status.HTTP_201_CREATED,
            headers={
                "Cache-Control": "private, no-store",
                "X-Correlation-ID": str(request.correlation_id),
            },
        )


class PlatformSupportSessionEndView(generics.GenericAPIView):
    authentication_classes = (PlatformJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    serializer_class = PlatformSupportSessionSerializer

    def delete(self, request, *args, **kwargs):
        end_support_session(
            user=request.user,
            session_id=kwargs["pk"],
            correlation_id=correlation_id_for_request(request),
        )
        return Response(
            status=status.HTTP_204_NO_CONTENT,
            headers={
                "Cache-Control": "private, no-store",
                "X-Correlation-ID": str(request.correlation_id),
            },
        )