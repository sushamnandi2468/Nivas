from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.tenancy.models import (
    CommitteeMembership,
    StaffMembership,
    TechnicianProfile,
    UnitOccupancy,
    VendorStaffMembership,
)
from apps.tickets.models import Ticket, TicketAssignment, VendorStaffAllocation


class CanAccessTickets(BasePermission):
    message = "Your society role cannot access this ticket resource."

    def has_permission(self, request, view):
        membership = request.membership
        workflow_type = view.workflow_type
        if request.method in SAFE_METHODS:
            return (
                isinstance(membership, StaffMembership | UnitOccupancy)
                or isinstance(membership, CommitteeMembership)
                and workflow_type == Ticket.WorkflowType.GOVERNANCE
            )
        if isinstance(membership, UnitOccupancy):
            return True
        if isinstance(membership, CommitteeMembership):
            return workflow_type == Ticket.WorkflowType.GOVERNANCE
        return isinstance(membership, StaffMembership) and membership.role in {
            StaffMembership.Role.FACILITY_MANAGER,
            StaffMembership.Role.HELPDESK_OPERATOR,
        }

    def has_object_permission(self, request, view, ticket):
        membership = request.membership
        if isinstance(membership, StaffMembership):
            if request.method in SAFE_METHODS:
                return True
            return membership.role in {
                StaffMembership.Role.FACILITY_MANAGER,
                StaffMembership.Role.HELPDESK_OPERATOR,
            }
        if isinstance(membership, UnitOccupancy):
            if ticket.creator_id != request.user.id:
                return (
                    request.method in SAFE_METHODS
                    and ticket.workflow_type == Ticket.WorkflowType.SERVICE
                    and ticket.unit_id == membership.unit_id
                )
            return (
                ticket.workflow_type != Ticket.WorkflowType.SERVICE
                or ticket.unit_id is None
                or ticket.unit_id == membership.unit_id
            )
        return (
            isinstance(membership, CommitteeMembership)
            and ticket.workflow_type == Ticket.WorkflowType.GOVERNANCE
            and ticket.creator_id == request.user.id
        )


class CanAccessTicketAttachments(BasePermission):
    message = "Your society role cannot access this ticket attachment resource."

    def has_permission(self, request, view):
        membership = request.membership
        workflow_type = getattr(view, "workflow_type", None)
        if isinstance(membership, UnitOccupancy):
            return True
        if isinstance(membership, StaffMembership):
            return membership.role in {
                StaffMembership.Role.FACILITY_MANAGER,
                StaffMembership.Role.HELPDESK_OPERATOR,
            }
        if isinstance(membership, CommitteeMembership):
            return workflow_type == Ticket.WorkflowType.GOVERNANCE
        if isinstance(membership, TechnicianProfile):
            return workflow_type == Ticket.WorkflowType.SERVICE and membership.is_active
        if isinstance(membership, VendorStaffMembership):
            return (
                workflow_type == Ticket.WorkflowType.SERVICE
                and membership.role == VendorStaffMembership.Role.WORKER
                and membership.is_current()
            )
        return False

    def has_object_permission(self, request, view, ticket):
        membership = request.membership
        if isinstance(membership, StaffMembership):
            return membership.role in {
                StaffMembership.Role.FACILITY_MANAGER,
                StaffMembership.Role.HELPDESK_OPERATOR,
            }
        if isinstance(membership, UnitOccupancy):
            if ticket.workflow_type == Ticket.WorkflowType.SERVICE:
                return (
                    ticket.creator_id == request.user.id
                    or ticket.unit_id == membership.unit_id
                )
            return ticket.creator_id == request.user.id
        if isinstance(membership, CommitteeMembership):
            return (
                ticket.workflow_type == Ticket.WorkflowType.GOVERNANCE
                and ticket.creator_id == request.user.id
            )
        if isinstance(membership, TechnicianProfile):
            if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
                return False
            return TicketAssignment.objects.filter(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.IN_HOUSE,
                technician=membership,
                state__in=(
                    TicketAssignment.State.OFFERED,
                    TicketAssignment.State.ACCEPTED,
                ),
            ).exists()
        if isinstance(membership, VendorStaffMembership):
            if (
                ticket.workflow_type != Ticket.WorkflowType.SERVICE
                or membership.role != VendorStaffMembership.Role.WORKER
            ):
                return False
            return VendorStaffAllocation.objects.filter(
                assignment__ticket=ticket,
                assignment__target_type=TicketAssignment.TargetType.VENDOR,
                assignment__state__in=(
                    TicketAssignment.State.OFFERED,
                    TicketAssignment.State.ACCEPTED,
                ),
                staff_membership=membership,
                state__in=(
                    VendorStaffAllocation.State.ALLOCATED,
                    VendorStaffAllocation.State.ACCEPTED,
                ),
            ).exists()
        return False


class CanAllocateVendorWorker(BasePermission):
    message = "Only active vendor dispatchers can allocate ticket workers."

    def has_permission(self, request, view):
        membership = request.membership
        return (
            isinstance(membership, VendorStaffMembership)
            and membership.role == VendorStaffMembership.Role.DISPATCHER
            and membership.is_current()
        )


class CanAcceptVendorWorker(BasePermission):
    message = "Only the active allocated vendor worker can accept this ticket."

    def has_permission(self, request, view):
        membership = request.membership
        return (
            isinstance(membership, VendorStaffMembership)
            and membership.role == VendorStaffMembership.Role.WORKER
            and membership.is_current()
        )


class CanAcceptVendorWorkerOnBehalf(BasePermission):
    message = "Only an active vendor dispatcher can accept on a worker's behalf."

    def has_permission(self, request, view):
        membership = request.membership
        return (
            isinstance(membership, VendorStaffMembership)
            and membership.role == VendorStaffMembership.Role.DISPATCHER
            and membership.is_current()
        )


class CanAccessTicketEstimates(BasePermission):
    message = "Your society role cannot access estimates for this ticket."

    def has_permission(self, request, view):
        membership = getattr(request, "membership", None)
        workflow_type = getattr(view, "workflow_type", Ticket.WorkflowType.SERVICE)
        if isinstance(membership, UnitOccupancy):
            return True
        if isinstance(membership, StaffMembership):
            return membership.role in {
                StaffMembership.Role.FACILITY_MANAGER,
                StaffMembership.Role.HELPDESK_OPERATOR,
            }
        if isinstance(membership, CommitteeMembership):
            return membership.is_current()
        if isinstance(membership, TechnicianProfile):
            return workflow_type == Ticket.WorkflowType.SERVICE and membership.is_active
        if isinstance(membership, VendorStaffMembership):
            return (
                workflow_type == Ticket.WorkflowType.SERVICE
                and membership.role == VendorStaffMembership.Role.WORKER
                and membership.is_current()
            )
        return False

    def has_object_permission(self, request, view, ticket):
        membership = request.membership
        if isinstance(membership, StaffMembership):
            return membership.role in {
                StaffMembership.Role.FACILITY_MANAGER,
                StaffMembership.Role.HELPDESK_OPERATOR,
            }
        if isinstance(membership, UnitOccupancy):
            if ticket.workflow_type == Ticket.WorkflowType.SERVICE:
                return (
                    ticket.creator_id == request.user.id
                    or ticket.unit_id == membership.unit_id
                )
            return ticket.creator_id == request.user.id
        if isinstance(membership, CommitteeMembership):
            return membership.is_current()
        if isinstance(membership, TechnicianProfile):
            if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
                return False
            return TicketAssignment.objects.filter(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.IN_HOUSE,
                technician=membership,
                state__in=(
                    TicketAssignment.State.OFFERED,
                    TicketAssignment.State.ACCEPTED,
                ),
            ).exists()
        if isinstance(membership, VendorStaffMembership):
            if (
                ticket.workflow_type != Ticket.WorkflowType.SERVICE
                or membership.role != VendorStaffMembership.Role.WORKER
            ):
                return False
            return VendorStaffAllocation.objects.filter(
                assignment__ticket=ticket,
                assignment__target_type=TicketAssignment.TargetType.VENDOR,
                assignment__state__in=(
                    TicketAssignment.State.OFFERED,
                    TicketAssignment.State.ACCEPTED,
                ),
                staff_membership=membership,
                state__in=(
                    VendorStaffAllocation.State.ALLOCATED,
                    VendorStaffAllocation.State.ACCEPTED,
                ),
            ).exists()
        return False
