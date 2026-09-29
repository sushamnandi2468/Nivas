from django.db import transaction
from django.db.models import Q
from django.http import Http404
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.platform_access.audit import correlation_id_for_request
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import (
    CommitteeMembership,
    CommonArea,
    StaffMembership,
    TechnicianProfile,
    Unit,
    UnitOccupancy,
    VendorStaffMembership,
)
from apps.tickets.attachment_storage import AttachmentStorageConfigurationError
from apps.tickets.models import (
    Ticket,
    TicketAssignment,
    TicketAttachment,
    TicketCategory,
    TicketComment,
    TicketEstimate,
    TicketFeedback,
    TicketMergeRecord,
    VendorStaffAllocation,
)
from apps.tickets.permissions import (
    CanAcceptVendorWorker,
    CanAcceptVendorWorkerOnBehalf,
    CanAccessTicketAttachments,
    CanAccessTicketEstimates,
    CanAccessTickets,
    CanAllocateVendorWorker,
)
from apps.tickets.serializers import (
    TicketAcceptVendorWorkerOnBehalfSerializer,
    TicketAcceptVendorWorkerSerializer,
    TicketAllocateVendorWorkerSerializer,
    TicketApproveEstimateSerializer,
    TicketEstimateReadSerializer,
    TicketAssignInHouseSerializer,
    TicketAssignVendorSerializer,
    TicketAttachmentSerializer,
    TicketAttachmentUploadSlotRequestSerializer,
    TicketBeginGovernanceReviewSerializer,
    TicketCancelSerializer,
    TicketCloseSerializer,
    TicketCommentCreateSerializer,
    TicketCommentSerializer,
    TicketFeedbackSerializer,
    TicketFeedbackSubmitSerializer,
    TicketMergeRecordSerializer,
    TicketMergeSerializer,
    TicketOpenGovernanceDiscussionSerializer,
    TicketOverrideResumeSerializer,
    TicketReassignFromTriageSerializer,
    TicketRecordGovernanceActionSerializer,
    TicketRejectEstimateSerializer,
    TicketRejectInHouseAssignmentSerializer,
    TicketRejectVendorAssignmentSerializer,
    TicketReopenSerializer,
    TicketReplaceVendorWorkerSerializer,
    TicketRequestCompletionSerializer,
    TicketRespondToInHouseAssignmentSerializer,
    TicketSerializer,
    TicketStartWorkSerializer,
    TicketSubmitEstimateSerializer,
    TicketSubmitSerializer,
    TicketSupervisorCompletionSerializer,
    TicketUnmergeSerializer,
    TicketVerifyCompletionSerializer,
    TicketWithdrawEstimateSerializer,
)
from apps.tickets.services import (
    IdempotencyRequestInProgress,
    PersistInitialSLACycle,
    TicketAttachmentForbidden,
    TicketAttachmentValidationForbidden,
    TicketCancellationForbidden,
    TicketCloseForbidden,
    TicketCommentForbidden,
    TicketCompletionRequestForbidden,
    TicketCompletionVerificationForbidden,
    TicketCreationForbidden,
    TicketEstimateDecisionForbidden,
    TicketEstimateSubmissionForbidden,
    TicketEstimateWithdrawalForbidden,
    TicketFeedbackForbidden,
    TicketGovernanceActionForbidden,
    TicketGovernanceDiscussionForbidden,
    TicketGovernanceReviewForbidden,
    TicketInHouseAssignmentForbidden,
    TicketInHouseAssignmentResponseForbidden,
    TicketMergeForbidden,
    TicketReopenForbidden,
    TicketStartWorkForbidden,
    TicketSubmissionConflict,
    TicketSubmissionForbidden,
    TicketSupervisorCompletionForbidden,
    TicketTriageReassignmentForbidden,
    TicketTriageResumeForbidden,
    TicketUnmergeForbidden,
    TicketVendorAssignmentForbidden,
    TicketVendorAssignmentRejectionForbidden,
    TicketVendorWorkerAcceptanceForbidden,
    TicketVendorWorkerAllocationForbidden,
    accept_in_house_assignment,
    accept_vendor_worker_allocation,
    accept_vendor_worker_allocation_on_behalf,
    allocate_vendor_worker,
    approve_ticket_estimate,
    assign_in_house_technician,
    assign_vendor_contract,
    authorize_internal_ticket_comments,
    begin_governance_review,
    business_calendar_deadline_calculator,
    cancel_submitted_ticket,
    close_ticket,
    complete_and_promote_attachment,
    create_ticket_comment,
    create_ticket_draft,
    issue_ticket_attachment_upload_slot,
    merge_ticket,
    open_governance_discussion,
    override_complete_service_ticket,
    override_resume_service_ticket_from_triage,
    reassign_service_ticket_from_triage,
    record_governance_action,
    reject_in_house_assignment,
    reject_ticket_estimate,
    reject_vendor_assignment,
    reopen_ticket,
    replace_vendor_worker,
    request_service_ticket_completion,
    start_ticket_work,
    submit_ticket,
    submit_ticket_estimate,
    submit_ticket_feedback,
    unmerge_ticket,
    verify_service_ticket_completion,
    withdraw_ticket_estimate,
)


def _idempotency_key(request):
    value = request.headers.get("Idempotency-Key")
    if not value or len(value) > 255:
        raise ValidationError(
            {"Idempotency-Key": "A non-empty value of at most 255 characters is required."}
        )
    return value


def _conflict_response(conflict, correlation_id):
    headers = {"X-Correlation-ID": str(correlation_id)}
    if isinstance(conflict, IdempotencyRequestInProgress):
        headers["Retry-After"] = "1"
    return Response(
        conflict.response_body(correlation_id),
        status=status.HTTP_409_CONFLICT,
        headers=headers,
    )


class TicketQuerysetMixin:
    permission_classes = (CanAccessTickets,)
    serializer_class = TicketSerializer
    queryset = Ticket.objects.select_related(
        "category",
        "subcategory",
        "unit",
        "common_area",
        "creator",
    )

    def get_queryset(self):
        queryset = self.queryset.filter(
            society=self.request.society,
            workflow_type=self.workflow_type,
        )
        membership = self.request.membership
        if isinstance(membership, StaffMembership):
            return queryset
        if isinstance(membership, UnitOccupancy):
            if self.workflow_type == Ticket.WorkflowType.SERVICE:
                return queryset.filter(
                    Q(creator=self.request.user) | Q(unit_id=membership.unit_id)
                )
            return queryset.filter(creator=self.request.user)
        if isinstance(membership, CommitteeMembership):
            return queryset.filter(creator=self.request.user)
        return queryset.none()


class TicketOptionsView(APIView):
    permission_classes = (CanAccessTickets,)
    workflow_type = Ticket.WorkflowType.SERVICE

    def get(self, request):
        membership = request.membership
        categories = TicketCategory.objects.filter(
            society=request.society,
            is_active=True,
        ).prefetch_related("subcategories")
        if isinstance(membership, UnitOccupancy):
            units = Unit.objects.filter(id=membership.unit_id, is_active=True)
        elif isinstance(membership, StaffMembership):
            units = Unit.objects.filter(society=request.society, is_active=True)
        else:
            units = Unit.objects.none()
        common_areas = CommonArea.objects.filter(
            society=request.society,
            is_active=True,
        )
        return Response(
            {
                "society": {
                    "id": str(request.society.id),
                    "registration_code": request.society.registration_code,
                    "timezone": request.society.timezone,
                },
                "units": [
                    {
                        "id": str(unit.id),
                        "door_number": unit.door_number,
                        "block": unit.block.code,
                    }
                    for unit in units.select_related("block")
                ],
                "common_areas": [
                    {"id": str(area.id), "name": area.name}
                    for area in common_areas
                ],
                "categories": [
                    {
                        "id": str(category.id),
                        "name": category.name,
                        "workflow_type": category.workflow_type,
                        "allows_unit_location": category.allows_unit_location,
                        "allows_common_area_location": (
                            category.allows_common_area_location
                        ),
                        "allows_no_location": category.allows_no_location,
                        "subcategories": [
                            {
                                "id": str(subcategory.id),
                                "name": subcategory.name,
                                "default_priority": subcategory.default_priority,
                            }
                            for subcategory in category.subcategories.all()
                            if subcategory.is_active
                        ],
                    }
                    for category in categories
                ],
            }
        )


class TicketListCreateView(TicketQuerysetMixin, generics.ListCreateAPIView):
    route_template = ""

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        validated = serializer.validated_data
        try:
            result = create_ticket_draft(
                society=request.society,
                actor=request.user,
                membership=request.membership,
                workflow_type=self.workflow_type,
                category=validated["category"],
                subcategory=validated["subcategory"],
                unit=validated.get("unit"),
                common_area=validated.get("common_area"),
                title=validated["title"],
                description=validated["description"],
                priority=validated["priority"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketCreationForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketDetailView(TicketQuerysetMixin, generics.RetrieveAPIView):
    pass


class TicketSubmitView(TicketQuerysetMixin, generics.GenericAPIView):
    serializer_class = TicketSubmitSerializer
    route_template = ""
    deadline_calculator = staticmethod(business_calendar_deadline_calculator)

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = submit_ticket(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
                create_sla_cycle=PersistInitialSLACycle(
                    calculate_deadline=self.deadline_calculator
                ),
            )
        except TicketSubmissionForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketCancelView(TicketQuerysetMixin, generics.GenericAPIView):
    serializer_class = TicketCancelSerializer
    route_template = ""

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = cancel_submitted_ticket(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                reason=serializer.validated_data["reason"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketCancellationForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketBeginGovernanceReviewView(TicketQuerysetMixin, generics.GenericAPIView):
    serializer_class = TicketBeginGovernanceReviewSerializer
    route_template = ""

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = begin_governance_review(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketGovernanceReviewForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketAssignInHouseView(TicketQuerysetMixin, generics.GenericAPIView):
    serializer_class = TicketAssignInHouseSerializer
    route_template = ""

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = assign_in_house_technician(
                society_id=request.society.id,
                ticket_id=ticket.id,
                technician_id=serializer.validated_data["technician_id"],
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketInHouseAssignmentForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketAssignVendorView(TicketQuerysetMixin, generics.GenericAPIView):
    serializer_class = TicketAssignVendorSerializer
    route_template = ""

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = assign_vendor_contract(
                society_id=request.society.id,
                ticket_id=ticket.id,
                vendor_contract_id=serializer.validated_data["vendor_contract_id"],
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketVendorAssignmentForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketAllocateVendorWorkerView(generics.GenericAPIView):
    permission_classes = (CanAllocateVendorWorker,)
    serializer_class = TicketAllocateVendorWorkerSerializer
    route_template = ""

    def get_queryset(self):
        membership = self.request.membership
        if not isinstance(membership, VendorStaffMembership):
            return Ticket.objects.none()
        return Ticket.objects.filter(
            society=self.request.society,
            workflow_type=Ticket.WorkflowType.SERVICE,
            assignments__target_type=TicketAssignment.TargetType.VENDOR,
            assignments__state=TicketAssignment.State.OFFERED,
            assignments__vendor_contract_id=membership.contract_id,
        ).distinct()

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = allocate_vendor_worker(
                society_id=request.society.id,
                ticket_id=ticket.id,
                staff_membership_id=serializer.validated_data["staff_membership_id"],
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketVendorWorkerAllocationForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketReplaceVendorWorkerView(TicketAllocateVendorWorkerView):
    serializer_class = TicketReplaceVendorWorkerSerializer

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = replace_vendor_worker(
                society_id=request.society.id,
                ticket_id=ticket.id,
                staff_membership_id=serializer.validated_data["staff_membership_id"],
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                reason=serializer.validated_data["reason"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketVendorWorkerAllocationForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketRespondToInHouseAssignmentView(generics.GenericAPIView):
    serializer_class = TicketRespondToInHouseAssignmentSerializer
    route_template = ""

    def get_queryset(self):
        return Ticket.objects.filter(
            society=self.request.society,
            workflow_type=Ticket.WorkflowType.SERVICE,
            assignments__target_type=TicketAssignment.TargetType.IN_HOUSE,
            assignments__technician__user=self.request.user,
        ).distinct()

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = self.respond(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
                **self.response_kwargs(serializer),
            )
        except TicketInHouseAssignmentResponseForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )

    def response_kwargs(self, serializer):
        return {}


class TicketAcceptInHouseAssignmentView(TicketRespondToInHouseAssignmentView):
    respond = staticmethod(accept_in_house_assignment)


class TicketAcceptVendorWorkerView(generics.GenericAPIView):
    permission_classes = (CanAcceptVendorWorker,)
    serializer_class = TicketAcceptVendorWorkerSerializer
    route_template = ""

    def get_queryset(self):
        return Ticket.objects.filter(
            society=self.request.society,
            workflow_type=Ticket.WorkflowType.SERVICE,
            assignments__target_type=TicketAssignment.TargetType.VENDOR,
            assignments__vendor_staff_allocations__staff_membership__user=self.request.user,
        ).distinct()

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = accept_vendor_worker_allocation(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketVendorWorkerAcceptanceForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketAcceptVendorWorkerOnBehalfView(generics.GenericAPIView):
    permission_classes = (CanAcceptVendorWorkerOnBehalf,)
    serializer_class = TicketAcceptVendorWorkerOnBehalfSerializer
    route_template = ""

    def get_queryset(self):
        return Ticket.objects.filter(
            society=self.request.society,
            workflow_type=Ticket.WorkflowType.SERVICE,
            assignments__target_type=TicketAssignment.TargetType.VENDOR,
            assignments__vendor_contract_id=self.request.membership.contract_id,
            assignments__vendor_staff_allocations__isnull=False,
        ).distinct()

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = accept_vendor_worker_allocation_on_behalf(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                reason=serializer.validated_data["reason"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketVendorWorkerAcceptanceForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketRejectInHouseAssignmentView(TicketRespondToInHouseAssignmentView):
    serializer_class = TicketRejectInHouseAssignmentSerializer
    respond = staticmethod(reject_in_house_assignment)

    def response_kwargs(self, serializer):
        return {"reason": serializer.validated_data["reason"]}


class TicketStartWorkView(generics.GenericAPIView):
    serializer_class = TicketStartWorkSerializer
    route_template = ""

    def get_queryset(self):
        membership = self.request.membership
        from apps.tenancy.models import TechnicianProfile

        if isinstance(membership, TechnicianProfile):
            return Ticket.objects.filter(
                society=self.request.society,
                workflow_type=Ticket.WorkflowType.SERVICE,
                assignments__target_type=TicketAssignment.TargetType.IN_HOUSE,
                assignments__technician=membership,
            ).distinct()
        if (
            isinstance(membership, VendorStaffMembership)
            and membership.role == VendorStaffMembership.Role.WORKER
        ):
            return Ticket.objects.filter(
                society=self.request.society,
                workflow_type=Ticket.WorkflowType.SERVICE,
                assignments__target_type=TicketAssignment.TargetType.VENDOR,
                assignments__vendor_staff_allocations__staff_membership=membership,
            ).distinct()
        return Ticket.objects.none()

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = start_ticket_work(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketStartWorkForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketRejectVendorAssignmentView(generics.GenericAPIView):
    permission_classes = (CanAllocateVendorWorker,)
    serializer_class = TicketRejectVendorAssignmentSerializer
    route_template = ""

    def get_queryset(self):
        membership = self.request.membership
        if not isinstance(membership, VendorStaffMembership):
            return Ticket.objects.none()
        return Ticket.objects.filter(
            society=self.request.society,
            workflow_type=Ticket.WorkflowType.SERVICE,
            assignments__target_type=TicketAssignment.TargetType.VENDOR,
            assignments__vendor_contract_id=membership.contract_id,
            assignments__vendor_staff_allocations__isnull=False,
        ).distinct()

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = reject_vendor_assignment(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                reason=serializer.validated_data["reason"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketVendorAssignmentRejectionForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketRequestCompletionView(generics.GenericAPIView):
    serializer_class = TicketRequestCompletionSerializer
    route_template = ""

    def get_queryset(self):
        membership = self.request.membership
        from apps.tenancy.models import TechnicianProfile

        if isinstance(membership, TechnicianProfile):
            return Ticket.objects.filter(
                society=self.request.society,
                workflow_type=Ticket.WorkflowType.SERVICE,
                assignments__target_type=TicketAssignment.TargetType.IN_HOUSE,
                assignments__technician=membership,
            ).distinct()
        if (
            isinstance(membership, VendorStaffMembership)
            and membership.role == VendorStaffMembership.Role.WORKER
        ):
            return Ticket.objects.filter(
                society=self.request.society,
                workflow_type=Ticket.WorkflowType.SERVICE,
                assignments__target_type=TicketAssignment.TargetType.VENDOR,
                assignments__vendor_staff_allocations__staff_membership=membership,
            ).distinct()
        return Ticket.objects.none()

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = request_service_ticket_completion(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                work_notes=serializer.validated_data["work_notes"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketCompletionRequestForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketVerifyCompletionView(TicketQuerysetMixin, generics.GenericAPIView):
    serializer_class = TicketVerifyCompletionSerializer
    route_template = ""

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = verify_service_ticket_completion(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                otp=serializer.validated_data["otp"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketCompletionVerificationForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketOpenGovernanceDiscussionView(TicketQuerysetMixin, generics.GenericAPIView):
    serializer_class = TicketOpenGovernanceDiscussionSerializer
    route_template = ""

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = open_governance_discussion(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                purpose=serializer.validated_data["purpose"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketGovernanceDiscussionForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketRecordGovernanceActionView(TicketQuerysetMixin, generics.GenericAPIView):
    serializer_class = TicketRecordGovernanceActionSerializer
    route_template = ""

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = record_governance_action(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                summary=serializer.validated_data["summary"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketGovernanceActionForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketCommentListCreateView(TicketQuerysetMixin, generics.GenericAPIView):
    route_template = ""

    def get(self, request, *args, **kwargs):
        ticket = self.get_object()
        comments = TicketComment.objects.filter(
            society=request.society,
            ticket=ticket,
            visibility=TicketComment.Visibility.PUBLIC,
        ).select_related("author")
        serializer = TicketCommentSerializer(
            comments,
            many=True,
            context={"request": request},
        )
        return Response(serializer.data)

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = TicketCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = create_ticket_comment(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                body=serializer.validated_data["body"],
                expected_version=serializer.validated_data["expected_version"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
                visibility=TicketComment.Visibility.PUBLIC,
            )
        except TicketCommentForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketInternalCommentListCreateView(TicketQuerysetMixin, generics.GenericAPIView):
    route_template = ""

    def get(self, request, *args, **kwargs):
        ticket = self.get_object()
        try:
            authorize_internal_ticket_comments(
                ticket=ticket,
                actor=request.user,
                membership=request.membership,
            )
        except TicketCommentForbidden as error:
            raise PermissionDenied(str(error)) from error
        comments = TicketComment.objects.filter(
            society=request.society,
            ticket=ticket,
            visibility=TicketComment.Visibility.INTERNAL,
        ).select_related("author")
        serializer = TicketCommentSerializer(
            comments,
            many=True,
            context={"request": request},
        )
        return Response(serializer.data)

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = TicketCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = create_ticket_comment(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                body=serializer.validated_data["body"],
                expected_version=serializer.validated_data["expected_version"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
                visibility=TicketComment.Visibility.INTERNAL,
            )
        except TicketCommentForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketAttachmentUploadSlotView(generics.GenericAPIView):
    permission_classes = (CanAccessTicketAttachments,)
    serializer_class = TicketAttachmentUploadSlotRequestSerializer
    workflow_type: Ticket.WorkflowType = Ticket.WorkflowType.SERVICE
    route_template: str = ""

    def get_queryset(self):
        request = self.request
        membership = getattr(request, "membership", None)
        society = getattr(request, "society", None)
        if society is None or membership is None:
            return Ticket.objects.none()

        base_qs = Ticket.objects.filter(
            society=society,
            workflow_type=self.workflow_type,
        )
        if isinstance(membership, StaffMembership):
            if membership.role in {
                StaffMembership.Role.FACILITY_MANAGER,
                StaffMembership.Role.HELPDESK_OPERATOR,
            }:
                return base_qs
            return base_qs.none()
        if isinstance(membership, UnitOccupancy):
            if self.workflow_type == Ticket.WorkflowType.SERVICE:
                return base_qs.filter(
                    Q(creator=request.user) | Q(unit_id=membership.unit_id)
                )
            return base_qs.filter(creator=request.user)
        if isinstance(membership, CommitteeMembership):
            if self.workflow_type == Ticket.WorkflowType.GOVERNANCE:
                return base_qs.filter(creator=request.user)
            return base_qs.none()
        if isinstance(membership, TechnicianProfile):
            if self.workflow_type == Ticket.WorkflowType.SERVICE:
                return base_qs.filter(
                    assignments__target_type=TicketAssignment.TargetType.IN_HOUSE,
                    assignments__technician=membership,
                    assignments__state__in=(
                        TicketAssignment.State.OFFERED,
                        TicketAssignment.State.ACCEPTED,
                    ),
                ).distinct()
            return base_qs.none()
        if isinstance(membership, VendorStaffMembership):
            if (
                self.workflow_type == Ticket.WorkflowType.SERVICE
                and membership.role == VendorStaffMembership.Role.WORKER
            ):
                return base_qs.filter(
                    assignments__target_type=TicketAssignment.TargetType.VENDOR,
                    assignments__state__in=(
                        TicketAssignment.State.OFFERED,
                        TicketAssignment.State.ACCEPTED,
                    ),
                    assignments__vendor_staff_allocations__staff_membership=membership,
                    assignments__vendor_staff_allocations__state__in=(
                        VendorStaffAllocation.State.ALLOCATED,
                        VendorStaffAllocation.State.ACCEPTED,
                    ),
                ).distinct()
            return base_qs.none()
        return base_qs.none()

    def get(self, request, *args, **kwargs):
        ticket = self.get_object()
        with transaction.atomic():
            set_local_society_id(request.society.id)
            attachments = (
                TicketAttachment.objects.filter(
                    society=request.society,
                    ticket=ticket,
                )
                .select_related("uploaded_by")
                .order_by("created_at")
            )
            serializer = TicketAttachmentSerializer(attachments, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = issue_ticket_attachment_upload_slot(
                society_id=request.society.id,
                ticket_id=ticket.id,
                workflow_type=self.workflow_type,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                filename=serializer.validated_data["filename"],
                content_type=serializer.validated_data["content_type"],
                byte_size=serializer.validated_data["byte_size"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketAttachmentForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketAttachmentValidationForbidden as error:
            raise ValidationError({"detail": str(error)}) from error
        except AttachmentStorageConfigurationError as error:
            return Response(
                {
                    "code": "ATTACHMENT_STORAGE_UNAVAILABLE",
                    "message": str(error),
                    "correlation_id": str(correlation_id),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
                headers={"X-Correlation-ID": str(correlation_id)},
            )
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )



class ServiceTicketListCreateView(TicketListCreateView):
    workflow_type = Ticket.WorkflowType.SERVICE
    route_template = "/api/v1/service-tickets"


class ServiceTicketDetailView(TicketDetailView):
    workflow_type = Ticket.WorkflowType.SERVICE


class ServiceTicketSubmitView(TicketSubmitView):
    workflow_type = Ticket.WorkflowType.SERVICE
    route_template = "/api/v1/service-tickets/{id}/submit"


class ServiceTicketCancelView(TicketCancelView):
    workflow_type = Ticket.WorkflowType.SERVICE
    route_template = "/api/v1/service-tickets/{id}/cancel"


class ServiceTicketAssignInHouseView(TicketAssignInHouseView):
    workflow_type = Ticket.WorkflowType.SERVICE
    route_template = "/api/v1/service-tickets/{id}/assign-in-house"


class ServiceTicketAssignVendorView(TicketAssignVendorView):
    workflow_type = Ticket.WorkflowType.SERVICE
    route_template = "/api/v1/service-tickets/{id}/assign-vendor"


class ServiceTicketAllocateVendorWorkerView(TicketAllocateVendorWorkerView):
    route_template = "/api/v1/service-tickets/{id}/allocate-vendor-worker"


class ServiceTicketReplaceVendorWorkerView(TicketReplaceVendorWorkerView):
    route_template = "/api/v1/service-tickets/{id}/replace-vendor-worker"


class ServiceTicketAcceptInHouseAssignmentView(TicketAcceptInHouseAssignmentView):
    route_template = "/api/v1/service-tickets/{id}/accept"


class ServiceTicketAcceptVendorWorkerView(TicketAcceptVendorWorkerView):
    route_template = "/api/v1/service-tickets/{id}/accept-vendor-worker"


class ServiceTicketAcceptVendorWorkerOnBehalfView(
    TicketAcceptVendorWorkerOnBehalfView
):
    route_template = "/api/v1/service-tickets/{id}/accept-vendor-worker-on-behalf"


class ServiceTicketRejectInHouseAssignmentView(TicketRejectInHouseAssignmentView):
    route_template = "/api/v1/service-tickets/{id}/reject"


class ServiceTicketStartWorkView(TicketStartWorkView):
    route_template = "/api/v1/service-tickets/{id}/start"


class ServiceTicketRejectVendorAssignmentView(TicketRejectVendorAssignmentView):
    route_template = "/api/v1/service-tickets/{id}/reject-vendor-assignment"


class ServiceTicketRequestCompletionView(TicketRequestCompletionView):
    route_template = "/api/v1/service-tickets/{id}/request-completion"


class ServiceTicketVerifyCompletionView(TicketVerifyCompletionView):
    workflow_type = Ticket.WorkflowType.SERVICE
    route_template = "/api/v1/service-tickets/{id}/verify-completion"


class ServiceTicketSubmitEstimateView(generics.GenericAPIView):
    serializer_class = TicketSubmitEstimateSerializer
    route_template = "/api/v1/service-tickets/{id}/submit-estimate"

    def get_queryset(self):
        membership = self.request.membership
        from apps.tenancy.models import TechnicianProfile

        if isinstance(membership, TechnicianProfile):
            return Ticket.objects.filter(
                society=self.request.society,
                workflow_type=Ticket.WorkflowType.SERVICE,
                assignments__target_type=TicketAssignment.TargetType.IN_HOUSE,
                assignments__technician=membership,
            ).distinct()
        if (
            isinstance(membership, VendorStaffMembership)
            and membership.role == VendorStaffMembership.Role.WORKER
        ):
            return Ticket.objects.filter(
                society=self.request.society,
                workflow_type=Ticket.WorkflowType.SERVICE,
                assignments__target_type=TicketAssignment.TargetType.VENDOR,
                assignments__vendor_staff_allocations__staff_membership=membership,
            ).distinct()
        if (
            isinstance(membership, StaffMembership)
            and membership.role == StaffMembership.Role.FACILITY_MANAGER
        ):
            return Ticket.objects.filter(
                society=self.request.society,
                workflow_type=Ticket.WorkflowType.SERVICE,
            )
        return Ticket.objects.none()

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = submit_ticket_estimate(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                items=serializer.validated_data["items"],
                tax_amount=serializer.validated_data.get("tax_amount", 0),
                notes=serializer.validated_data.get("notes", ""),
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketEstimateSubmissionForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class ServiceTicketApproveEstimateView(TicketQuerysetMixin, generics.GenericAPIView):
    workflow_type = Ticket.WorkflowType.SERVICE
    serializer_class = TicketApproveEstimateSerializer
    route_template = "/api/v1/service-tickets/{id}/approve-estimate"

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = approve_ticket_estimate(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                notes=serializer.validated_data.get("notes", ""),
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketEstimateDecisionForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class ServiceTicketRejectEstimateView(TicketQuerysetMixin, generics.GenericAPIView):
    workflow_type = Ticket.WorkflowType.SERVICE
    serializer_class = TicketRejectEstimateSerializer
    route_template = "/api/v1/service-tickets/{id}/reject-estimate"

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = reject_ticket_estimate(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                reason=serializer.validated_data["reason"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketEstimateDecisionForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class ServiceTicketWithdrawEstimateView(generics.GenericAPIView):
    serializer_class = TicketWithdrawEstimateSerializer
    route_template = "/api/v1/service-tickets/{id}/withdraw-estimate"

    def get_queryset(self):
        membership = self.request.membership
        from apps.tenancy.models import TechnicianProfile

        if isinstance(membership, TechnicianProfile):
            return Ticket.objects.filter(
                society=self.request.society,
                workflow_type=Ticket.WorkflowType.SERVICE,
                assignments__target_type=TicketAssignment.TargetType.IN_HOUSE,
                assignments__technician=membership,
            ).distinct()
        if (
            isinstance(membership, VendorStaffMembership)
            and membership.role == VendorStaffMembership.Role.WORKER
        ):
            return Ticket.objects.filter(
                society=self.request.society,
                workflow_type=Ticket.WorkflowType.SERVICE,
                assignments__target_type=TicketAssignment.TargetType.VENDOR,
                assignments__vendor_staff_allocations__staff_membership=membership,
            ).distinct()
        if (
            isinstance(membership, StaffMembership)
            and membership.role == StaffMembership.Role.FACILITY_MANAGER
        ):
            return Ticket.objects.filter(
                society=self.request.society,
                workflow_type=Ticket.WorkflowType.SERVICE,
            )
        return Ticket.objects.none()

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = withdraw_ticket_estimate(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                reason=serializer.validated_data["reason"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except (TicketEstimateWithdrawalForbidden, TicketEstimateSubmissionForbidden) as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class ServiceTicketEstimateListView(generics.GenericAPIView):
    permission_classes = (CanAccessTicketEstimates,)
    workflow_type = Ticket.WorkflowType.SERVICE

    def get_ticket(self):
        ticket_id = self.kwargs["pk"]
        society = self.request.society
        try:
            ticket = Ticket.objects.get(
                society=society,
                workflow_type=self.workflow_type,
                id=ticket_id,
            )
        except Ticket.DoesNotExist as exc:
            raise Http404("Ticket not found.") from exc
        self.check_object_permissions(self.request, ticket)
        return ticket

    def get(self, request, *args, **kwargs):
        with transaction.atomic():
            set_local_society_id(request.society.id)
            ticket = self.get_ticket()
            estimates = (
                TicketEstimate.objects.filter(
                    society=request.society,
                    ticket=ticket,
                )
                .select_related("ticket", "created_by", "decided_by", "ticket__category")
                .prefetch_related("items")
                .order_by("-version")
            )
            serializer = TicketEstimateReadSerializer(
                estimates,
                many=True,
                context={"request": request},
            )
            return Response(serializer.data)


class TicketReopenView(TicketQuerysetMixin, generics.GenericAPIView):
    serializer_class = TicketReopenSerializer

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = reopen_ticket(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                reason=serializer.validated_data["reason"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketReopenForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class TicketCloseView(TicketQuerysetMixin, generics.GenericAPIView):
    serializer_class = TicketCloseSerializer

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = close_ticket(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                reason=serializer.validated_data.get("reason", ""),
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketCloseForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class ServiceTicketReopenView(TicketReopenView):
    workflow_type = Ticket.WorkflowType.SERVICE
    route_template = "/api/v1/service-tickets/{id}/reopen"


class ServiceTicketCloseView(TicketCloseView):
    workflow_type = Ticket.WorkflowType.SERVICE
    route_template = "/api/v1/service-tickets/{id}/close"


class ServiceTicketReassignFromTriageView(TicketQuerysetMixin, generics.GenericAPIView):
    workflow_type = Ticket.WorkflowType.SERVICE
    serializer_class = TicketReassignFromTriageSerializer
    route_template = "/api/v1/service-tickets/{id}/reassign-triage"

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = reassign_service_ticket_from_triage(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                target_type=serializer.validated_data["target_type"],
                technician_id=serializer.validated_data.get("technician_id"),
                vendor_contract_id=serializer.validated_data.get("vendor_contract_id"),
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketTriageReassignmentForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class ServiceTicketOverrideResumeView(TicketQuerysetMixin, generics.GenericAPIView):
    workflow_type = Ticket.WorkflowType.SERVICE
    serializer_class = TicketOverrideResumeSerializer
    route_template = "/api/v1/service-tickets/{id}/override-resume"

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = override_resume_service_ticket_from_triage(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                validated_token=request.auth,
                expected_version=serializer.validated_data["expected_version"],
                reason=serializer.validated_data["reason"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketTriageResumeForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class ServiceTicketSupervisorCompletionView(TicketQuerysetMixin, generics.GenericAPIView):
    workflow_type = Ticket.WorkflowType.SERVICE
    serializer_class = TicketSupervisorCompletionSerializer
    route_template = "/api/v1/service-tickets/{id}/supervisor-complete"

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = override_complete_service_ticket(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                validated_token=request.auth,
                expected_version=serializer.validated_data["expected_version"],
                reason=serializer.validated_data["reason"],
                proof_notes=serializer.validated_data["proof_notes"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketSupervisorCompletionForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class ServiceTicketCommentListCreateView(TicketCommentListCreateView):
    workflow_type = Ticket.WorkflowType.SERVICE
    route_template = "/api/v1/tickets/service/{id}/comments"


class ServiceTicketInternalCommentListCreateView(TicketInternalCommentListCreateView):
    workflow_type = Ticket.WorkflowType.SERVICE
    route_template = "/api/v1/tickets/service/{id}/internal-comments"


class ServiceTicketAttachmentUploadSlotView(TicketAttachmentUploadSlotView):
    workflow_type = Ticket.WorkflowType.SERVICE
    route_template = "/api/v1/tickets/service/{id}/attachments/upload-slot"


class ServiceTicketAttachmentListView(TicketAttachmentUploadSlotView):
    workflow_type = Ticket.WorkflowType.SERVICE
    route_template = "/api/v1/tickets/service/{id}/attachments"


class TicketAttachmentCompleteView(generics.GenericAPIView):
    permission_classes = (CanAccessTicketAttachments,)
    serializer_class = TicketAttachmentSerializer
    workflow_type: Ticket.WorkflowType | None = Ticket.WorkflowType.SERVICE
    route_template: str = ""

    def post(self, request, *args, **kwargs):
        attachment_id = kwargs.get("attachment_pk") or kwargs.get("pk")
        ticket_id = kwargs.get("ticket_pk")
        with transaction.atomic():
            set_local_society_id(request.society.id)
            filter_kwargs = {"id": attachment_id, "society": request.society}
            if ticket_id:
                filter_kwargs["ticket_id"] = ticket_id
            try:
                attachment = TicketAttachment.objects.select_related("ticket", "uploaded_by").get(
                    **filter_kwargs
                )
            except TicketAttachment.DoesNotExist:
                raise Http404("Ticket attachment does not exist.")

            if self.workflow_type and attachment.ticket.workflow_type != self.workflow_type:
                raise PermissionDenied("Ticket workflow type does not match requested route.")

            membership = request.membership
            is_uploader = attachment.uploaded_by_id == request.user.id
            is_staff = isinstance(membership, StaffMembership) and membership.role in {
                StaffMembership.Role.FACILITY_MANAGER,
                StaffMembership.Role.HELPDESK_OPERATOR,
            }
            if not is_uploader and not is_staff:
                raise PermissionDenied("Only the uploader or operations staff can complete upload.")

            if attachment.status in {
                TicketAttachment.Status.AVAILABLE,
                TicketAttachment.Status.REJECTED,
            }:
                return Response(self.get_serializer(attachment).data, status=status.HTTP_200_OK)

            correlation_id = correlation_id_for_request(request)
            promoted_attachment = complete_and_promote_attachment(
                society_id=request.society.id,
                attachment_id=attachment.id,
                actor=request.user,
                correlation_id=correlation_id,
            )
            return Response(self.get_serializer(promoted_attachment).data, status=status.HTTP_200_OK)


class ServiceTicketAttachmentCompleteView(TicketAttachmentCompleteView):
    workflow_type = Ticket.WorkflowType.SERVICE
    route_template = "/api/v1/tickets/service/{ticket_pk}/attachments/{attachment_pk}/complete"


class AttachmentDirectCompleteView(TicketAttachmentCompleteView):
    workflow_type = None
    route_template = "/api/v1/attachments/{pk}/complete"


class GovernanceTicketListCreateView(TicketListCreateView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    route_template = "/api/v1/governance-tickets"


class GovernanceTicketDetailView(TicketDetailView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE


class GovernanceTicketSubmitView(TicketSubmitView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    route_template = "/api/v1/governance-tickets/{id}/submit"


class GovernanceTicketCancelView(TicketCancelView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    route_template = "/api/v1/governance-tickets/{id}/cancel"


class GovernanceTicketBeginReviewView(TicketBeginGovernanceReviewView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    route_template = "/api/v1/governance-tickets/{id}/begin-review"


class GovernanceTicketOpenDiscussionView(TicketOpenGovernanceDiscussionView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    route_template = "/api/v1/governance-tickets/{id}/open-discussion"


class GovernanceTicketRecordActionView(TicketRecordGovernanceActionView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    route_template = "/api/v1/governance-tickets/{id}/record-action"


class GovernanceTicketReopenView(TicketReopenView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    route_template = "/api/v1/governance-tickets/{id}/reopen"


class GovernanceTicketCloseView(TicketCloseView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    route_template = "/api/v1/governance-tickets/{id}/close"


class GovernanceTicketCommentListCreateView(TicketCommentListCreateView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    route_template = "/api/v1/tickets/governance/{id}/comments"


class GovernanceTicketInternalCommentListCreateView(
    TicketInternalCommentListCreateView
):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    route_template = "/api/v1/tickets/governance/{id}/internal-comments"


class GovernanceTicketAttachmentUploadSlotView(TicketAttachmentUploadSlotView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    route_template = "/api/v1/tickets/governance/{id}/attachments/upload-slot"


class GovernanceTicketAttachmentListView(TicketAttachmentUploadSlotView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    route_template = "/api/v1/tickets/governance/{id}/attachments"


class GovernanceTicketAttachmentCompleteView(TicketAttachmentCompleteView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    route_template = "/api/v1/tickets/governance/{ticket_pk}/attachments/{attachment_pk}/complete"



class ServiceTicketRateView(TicketQuerysetMixin, generics.GenericAPIView):
    workflow_type = Ticket.WorkflowType.SERVICE
    serializer_class = TicketFeedbackSubmitSerializer
    route_template = "/api/v1/service-tickets/{id}/rate"

    def post(self, request, *args, **kwargs):
        ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = submit_ticket_feedback(
                society_id=request.society.id,
                ticket_id=ticket.id,
                actor=request.user,
                membership=request.membership,
                expected_version=serializer.validated_data["expected_version"],
                overall_rating=serializer.validated_data["overall_rating"],
                timeliness_rating=serializer.validated_data.get("timeliness_rating"),
                quality_rating=serializer.validated_data.get("quality_rating"),
                technician_behavior_rating=serializer.validated_data.get("technician_behavior_rating"),
                tags=serializer.validated_data.get("tags"),
                comment=serializer.validated_data.get("comment", ""),
                idempotency_key=_idempotency_key(request),
                correlation_id=correlation_id,
            )
        except TicketFeedbackForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class ServiceTicketFeedbackDetailView(TicketQuerysetMixin, generics.GenericAPIView):
    workflow_type = Ticket.WorkflowType.SERVICE
    serializer_class = TicketFeedbackSerializer

    def get(self, request, *args, **kwargs):
        ticket = self.get_object()
        feedback = TicketFeedback.objects.filter(
            society_id=request.society.id,
            ticket=ticket,
        ).first()
        if feedback is None:
            raise Http404("No feedback found for this ticket.")
        serializer = self.get_serializer(feedback)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ServiceTicketMergeView(TicketQuerysetMixin, generics.GenericAPIView):
    workflow_type = Ticket.WorkflowType.SERVICE
    serializer_class = TicketMergeSerializer
    route_template = "/api/v1/service-tickets/{id}/merge/"

    def post(self, request, *args, **kwargs):
        primary_ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = merge_ticket(
                society_id=request.society.id,
                primary_ticket_id=primary_ticket.id,
                secondary_ticket_id=serializer.validated_data["secondary_ticket_id"],
                actor=request.user,
                membership=request.membership,
                expected_primary_version=serializer.validated_data["expected_primary_version"],
                expected_secondary_version=serializer.validated_data["expected_secondary_version"],
                reason=serializer.validated_data["reason"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketMergeForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class GovernanceTicketMergeView(TicketQuerysetMixin, generics.GenericAPIView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    serializer_class = TicketMergeSerializer
    route_template = "/api/v1/governance-tickets/{id}/merge/"

    def post(self, request, *args, **kwargs):
        primary_ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = merge_ticket(
                society_id=request.society.id,
                primary_ticket_id=primary_ticket.id,
                secondary_ticket_id=serializer.validated_data["secondary_ticket_id"],
                actor=request.user,
                membership=request.membership,
                expected_primary_version=serializer.validated_data["expected_primary_version"],
                expected_secondary_version=serializer.validated_data["expected_secondary_version"],
                reason=serializer.validated_data["reason"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketMergeForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class ServiceTicketUnmergeView(TicketQuerysetMixin, generics.GenericAPIView):
    workflow_type = Ticket.WorkflowType.SERVICE
    serializer_class = TicketUnmergeSerializer
    route_template = "/api/v1/service-tickets/{id}/unmerge/"

    def post(self, request, *args, **kwargs):
        primary_ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = unmerge_ticket(
                society_id=request.society.id,
                primary_ticket_id=primary_ticket.id,
                secondary_ticket_id=serializer.validated_data["secondary_ticket_id"],
                actor=request.user,
                membership=request.membership,
                validated_token=request.auth,
                expected_primary_version=serializer.validated_data["expected_primary_version"],
                expected_secondary_version=serializer.validated_data["expected_secondary_version"],
                reason=serializer.validated_data["reason"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketUnmergeForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class GovernanceTicketUnmergeView(TicketQuerysetMixin, generics.GenericAPIView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    serializer_class = TicketUnmergeSerializer
    route_template = "/api/v1/governance-tickets/{id}/unmerge/"

    def post(self, request, *args, **kwargs):
        primary_ticket = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        correlation_id = correlation_id_for_request(request)
        try:
            result = unmerge_ticket(
                society_id=request.society.id,
                primary_ticket_id=primary_ticket.id,
                secondary_ticket_id=serializer.validated_data["secondary_ticket_id"],
                actor=request.user,
                membership=request.membership,
                validated_token=request.auth,
                expected_primary_version=serializer.validated_data["expected_primary_version"],
                expected_secondary_version=serializer.validated_data["expected_secondary_version"],
                reason=serializer.validated_data["reason"],
                idempotency_key=_idempotency_key(request),
                route_template=self.route_template,
                correlation_id=correlation_id,
            )
        except TicketUnmergeForbidden as error:
            raise PermissionDenied(str(error)) from error
        except TicketSubmissionConflict as conflict:
            return _conflict_response(conflict, correlation_id)
        return Response(
            result.response_body,
            status=result.response_status,
            headers=result.response_headers,
        )


class ServiceTicketMergeHistoryView(TicketQuerysetMixin, generics.GenericAPIView):
    workflow_type = Ticket.WorkflowType.SERVICE
    serializer_class = TicketMergeRecordSerializer

    def get(self, request, *args, **kwargs):
        ticket = self.get_object()
        records = TicketMergeRecord.objects.filter(
            Q(primary_ticket=ticket) | Q(secondary_ticket=ticket),
            society_id=request.society.id,
        ).order_by("-merged_at")
        serializer = self.get_serializer(records, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class GovernanceTicketMergeHistoryView(TicketQuerysetMixin, generics.GenericAPIView):
    workflow_type = Ticket.WorkflowType.GOVERNANCE
    serializer_class = TicketMergeRecordSerializer

    def get(self, request, *args, **kwargs):
        ticket = self.get_object()
        records = TicketMergeRecord.objects.filter(
            Q(primary_ticket=ticket) | Q(secondary_ticket=ticket),
            society_id=request.society.id,
        ).order_by("-merged_at")
        serializer = self.get_serializer(records, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)