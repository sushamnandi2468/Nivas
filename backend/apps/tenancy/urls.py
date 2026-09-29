from django.urls import path

from apps.tenancy.views import (
    BlockListCreateView,
    CommitteeMembershipListCreateView,
    CommonAreaListCreateView,
    CurrentSocietyView,
    MembershipInvitationListCreateView,
    MembershipInvitationRevokeView,
    TechnicianProfileListCreateView,
    UnitListCreateView,
    UnitOccupancyListCreateView,
    VendorContractListCreateView,
    VendorListCreateView,
    VendorStaffMembershipListCreateView,
)

urlpatterns = [
    path("society/", CurrentSocietyView.as_view(), name="current-society"),
    path("blocks/", BlockListCreateView.as_view(), name="block-list"),
    path("units/", UnitListCreateView.as_view(), name="unit-list"),
    path("common-areas/", CommonAreaListCreateView.as_view(), name="common-area-list"),
    path(
        "occupancies/",
        UnitOccupancyListCreateView.as_view(),
        name="unit-occupancy-list",
    ),
    path(
        "committee-memberships/",
        CommitteeMembershipListCreateView.as_view(),
        name="committee-membership-list",
    ),
    path(
        "technicians/",
        TechnicianProfileListCreateView.as_view(),
        name="technician-profile-list",
    ),
    path("vendors/", VendorListCreateView.as_view(), name="vendor-list"),
    path(
        "vendor-contracts/",
        VendorContractListCreateView.as_view(),
        name="vendor-contract-list",
    ),
    path(
        "vendor-staff-memberships/",
        VendorStaffMembershipListCreateView.as_view(),
        name="vendor-staff-membership-list",
    ),
    path(
        "membership-invitations/",
        MembershipInvitationListCreateView.as_view(),
        name="membership-invitation-list",
    ),
    path(
        "membership-invitations/<uuid:pk>/revoke/",
        MembershipInvitationRevokeView.as_view(),
        name="membership-invitation-revoke",
    ),
]
