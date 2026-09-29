from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response

from apps.authentication.services import send_membership_invitation_email
from apps.platform_access.authentication import TenantOrPlatformSupportAuthentication
from apps.platform_access.mixins import PlatformSessionResponseMixin
from apps.tenancy.models import (
    Block,
    CommitteeMembership,
    CommonArea,
    MembershipInvitation,
    TechnicianProfile,
    Unit,
    UnitOccupancy,
    Vendor,
    VendorContract,
    VendorStaffMembership,
)
from apps.tenancy.permissions import CanManageDirectory, CanManageMemberships
from apps.tenancy.serializers import (
    BlockSerializer,
    CommitteeMembershipSerializer,
    CommonAreaSerializer,
    MembershipInvitationSerializer,
    SocietySerializer,
    TechnicianProfileSerializer,
    UnitOccupancySerializer,
    UnitSerializer,
    VendorContractSerializer,
    VendorSerializer,
    VendorStaffMembershipSerializer,
)


class CurrentSocietyView(PlatformSessionResponseMixin, generics.RetrieveAPIView):
    authentication_classes = (TenantOrPlatformSupportAuthentication,)
    permission_classes = (CanManageDirectory,)
    serializer_class = SocietySerializer
    allow_platform_session_read = True

    def get_object(self):
        return self.request.society


class TenantDirectoryListCreateView(
    PlatformSessionResponseMixin,
    generics.ListCreateAPIView,
):
    authentication_classes = (TenantOrPlatformSupportAuthentication,)
    permission_classes = (CanManageDirectory,)
    allow_platform_session_read = False

    def get_queryset(self):
        return self.queryset.filter(society=self.request.society)

    def perform_create(self, serializer):
        serializer.save(society=self.request.society)

    def create(self, request, *args, **kwargs):
        if hasattr(request, "support_session"):
            return self.deny_platform_session_mutation(request)
        return super().create(request, *args, **kwargs)


class BlockListCreateView(TenantDirectoryListCreateView):
    queryset = Block.objects.all()
    serializer_class = BlockSerializer
    allow_platform_session_read = True


class UnitListCreateView(TenantDirectoryListCreateView):
    queryset = Unit.objects.select_related("block")
    serializer_class = UnitSerializer
    allow_platform_session_read = True


class CommonAreaListCreateView(TenantDirectoryListCreateView):
    queryset = CommonArea.objects.all()
    serializer_class = CommonAreaSerializer
    allow_platform_session_read = True


class TenantMembershipListCreateView(
    PlatformSessionResponseMixin,
    generics.ListCreateAPIView,
):
    authentication_classes = (TenantOrPlatformSupportAuthentication,)
    permission_classes = (CanManageMemberships,)

    def get_queryset(self):
        return self.queryset.filter(society=self.request.society)

    def perform_create(self, serializer):
        serializer.save(society=self.request.society)


class UnitOccupancyListCreateView(TenantMembershipListCreateView):
    queryset = UnitOccupancy.objects.select_related("unit", "user")
    serializer_class = UnitOccupancySerializer


class CommitteeMembershipListCreateView(TenantMembershipListCreateView):
    queryset = CommitteeMembership.objects.select_related("user")
    serializer_class = CommitteeMembershipSerializer


class TechnicianProfileListCreateView(TenantMembershipListCreateView):
    queryset = TechnicianProfile.objects.select_related("user")
    serializer_class = TechnicianProfileSerializer


class VendorListCreateView(TenantMembershipListCreateView):
    queryset = Vendor.objects.all()
    serializer_class = VendorSerializer


class VendorContractListCreateView(TenantMembershipListCreateView):
    queryset = VendorContract.objects.select_related("vendor")
    serializer_class = VendorContractSerializer


class VendorStaffMembershipListCreateView(TenantMembershipListCreateView):
    queryset = VendorStaffMembership.objects.select_related(
        "vendor",
        "contract",
        "user",
    )
    serializer_class = VendorStaffMembershipSerializer


class MembershipInvitationListCreateView(
    PlatformSessionResponseMixin,
    generics.ListCreateAPIView,
):
    authentication_classes = (TenantOrPlatformSupportAuthentication,)
    permission_classes = (CanManageMemberships,)
    serializer_class = MembershipInvitationSerializer

    def get_queryset(self):
        MembershipInvitation.objects.filter(
            society=self.request.society,
            status=MembershipInvitation.Status.PENDING,
            expires_at__lte=timezone.now(),
        ).update(status=MembershipInvitation.Status.EXPIRED)
        return MembershipInvitation.objects.filter(society=self.request.society).select_related(
            "unit", "created_by", "revoked_by"
        )

    def perform_create(self, serializer):
        invitation = serializer.save(
            society=self.request.society,
            created_by=self.request.user,
        )
        if settings.PUBLIC_AUTH_EMAIL_BACKEND != "disabled":
            transaction.on_commit(
                lambda: send_membership_invitation_email(invitation=invitation)
            )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        data = dict(serializer.data)
        data["invitation_token"] = serializer.instance.raw_token
        return Response(
            data,
            status=status.HTTP_201_CREATED,
            headers=self.get_success_headers(serializer.data),
        )


class MembershipInvitationRevokeView(
    PlatformSessionResponseMixin,
    generics.GenericAPIView,
):
    authentication_classes = (TenantOrPlatformSupportAuthentication,)
    permission_classes = (CanManageMemberships,)
    serializer_class = MembershipInvitationSerializer
    queryset = MembershipInvitation.objects.all()

    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            invitation = get_object_or_404(
                self.get_queryset().select_for_update(),
                id=kwargs["pk"],
                society=request.society,
            )
            if invitation.status == MembershipInvitation.Status.REVOKED:
                return Response(self.get_serializer(invitation).data)
            if not invitation.is_actionable():
                if invitation.status == MembershipInvitation.Status.PENDING:
                    invitation.status = MembershipInvitation.Status.EXPIRED
                    invitation.save(update_fields=("status", "updated_at"))
                return Response(
                    {"detail": "Only pending, unexpired invitations can be revoked."},
                    status=status.HTTP_409_CONFLICT,
                )

            invitation.status = MembershipInvitation.Status.REVOKED
            invitation.revoked_at = timezone.now()
            invitation.revoked_by = request.user
            invitation.save(update_fields=("status", "revoked_at", "revoked_by", "updated_at"))
        return Response(self.get_serializer(invitation).data)
