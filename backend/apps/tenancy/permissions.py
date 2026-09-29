from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.platform_access.audit import schedule_platform_access_denial
from apps.tenancy.models import StaffMembership


class CanManageDirectory(BasePermission):
    message = "Your society role cannot modify directory records."

    def has_permission(self, request, view):
        if hasattr(request, "support_session"):
            return getattr(view, "allow_platform_session_read", False)

        if request.method in SAFE_METHODS:
            return True

        return isinstance(
            request.membership,
            StaffMembership,
        ) and request.membership.role in {
            StaffMembership.Role.FACILITY_MANAGER,
            StaffMembership.Role.ESTATE_SUPERVISOR,
        }


class CanManageMemberships(BasePermission):
    message = "Only facility managers can manage society memberships."

    def has_permission(self, request, view):
        if hasattr(request, "support_session"):
            schedule_platform_access_denial(
                request,
                session=request.support_session,
                reason_code="route_not_allowlisted",
            )
            return False

        return (
            isinstance(request.membership, StaffMembership)
            and request.membership.role == StaffMembership.Role.FACILITY_MANAGER
        )