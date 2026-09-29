import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from django.contrib.auth.hashers import check_password, make_password
from django.db import IntegrityError, models as dj_models, transaction
from django.utils import timezone

from apps.identity.models import User
from apps.platform_access.authentication import validate_platform_step_up
from apps.tenancy.context import set_local_society_id, tenant_atomic
from apps.tenancy.models import (
    CommitteeMembership,
    StaffMembership,
    TechnicianProfile,
    UnitOccupancy,
    VendorContract,
    VendorStaffMembership,
)
from apps.tickets.models import (
    BusinessCalendar,
    GovernanceActionRecord,
    GovernanceDiscussion,
    GovernanceDiscussionParticipant,
    GovernanceReviewAssignment,
    IdempotencyRecord,
    SLACycle,
    SLAPolicyBinding,
    Ticket,
    TicketAssignment,
    TicketAttachment,
    TicketCategory,
    TicketComment,
    TicketCompletionChallenge,
    TicketEstimate,
    TicketEstimateLineItem,
    TicketEvent,
    TicketOutboxEvent,
    TicketFeedback,
    TicketMergeRecord,
    TicketNumberSequence,
    VendorStaffAllocation,
)
from apps.tickets.attachment_storage import (
    AttachmentStorageConfigurationError,
    AttachmentStorageError,
    AttachmentValidationError,
    generate_attachment_storage_key,
    issue_attachment_upload_slot,
    scan_and_promote_storage_object,
    validate_attachment_request,
)
from apps.tickets.completion_delivery import (
    CompletionOtpCapsuleUnavailable,
    delete_completion_otp_capsule,
    store_completion_otp_capsule,
)
from apps.tickets.sla_calendar import calculate_business_deadline

IDEMPOTENCY_RETENTION = timedelta(hours=72)
OUTBOX_CLAIM_LEASE = timedelta(minutes=5)


@dataclass(frozen=True)
class TicketCommandResult:
    response_status: int
    response_body: dict
    response_headers: dict
    replayed: bool = False


@dataclass(frozen=True)
class IdempotencyClaim:
    record_id: uuid.UUID | None = None
    replay: TicketCommandResult | None = None


class SLACycleCreator(Protocol):
    def __call__(self, *, ticket: Ticket, submitted_at) -> uuid.UUID: ...


class SLADeadlineCalculator(Protocol):
    def __call__(
        self,
        *,
        started_at,
        duration,
        society_id,
        society_timezone,
        calendar_version,
    ): ...


class TicketSubmissionForbidden(Exception):
    pass


class TicketCreationForbidden(Exception):
    pass


class TicketCommentForbidden(Exception):
    pass


class TicketCancellationForbidden(Exception):
    pass


class TicketGovernanceReviewForbidden(Exception):
    pass


class TicketGovernanceDiscussionForbidden(Exception):
    pass


class TicketGovernanceActionForbidden(Exception):
    pass


class TicketInHouseAssignmentForbidden(Exception):
    pass


class TicketInHouseAssignmentResponseForbidden(Exception):
    pass


class TicketVendorAssignmentForbidden(Exception):
    pass


class TicketVendorWorkerAllocationForbidden(Exception):
    pass


class TicketVendorWorkerAcceptanceForbidden(Exception):
    pass


class TicketStartWorkForbidden(Exception):
    pass


class TicketVendorAssignmentRejectionForbidden(Exception):
    pass


class TicketCompletionRequestForbidden(Exception):
    pass


class TicketCompletionVerificationForbidden(Exception):
    pass


class TicketOutboxClaimLost(Exception):
    pass


class TicketOutboxDeliveryConfirmationRejected(Exception):
    pass


class TicketEstimateSubmissionForbidden(Exception):
    pass


class TicketEstimateDecisionForbidden(Exception):
    pass


class TicketEstimateWithdrawalForbidden(Exception):
    pass


class TicketReopenForbidden(Exception):
    pass


class TicketCloseForbidden(Exception):
    pass


class TicketTriageReassignmentForbidden(Exception):
    pass


class TicketTriageResumeForbidden(Exception):
    pass


class TicketSupervisorCompletionForbidden(Exception):
    pass


class TicketFeedbackForbidden(Exception):
    pass


class TicketMergeForbidden(Exception):
    pass


class TicketUnmergeForbidden(Exception):
    pass


class TicketAttachmentForbidden(Exception):
    pass


class TicketAttachmentValidationForbidden(Exception):
    pass


class TicketAttachmentNotFoundError(Exception):
    pass


class TicketSubmissionConflict(Exception):
    def __init__(self, *, code, message, ticket=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.ticket = ticket

    def response_body(self, correlation_id):
        body = {
            "code": self.code,
            "message": self.message,
            "correlation_id": str(correlation_id),
        }
        if self.ticket is not None:
            body["current_state"] = self.ticket.status
            body["current_version"] = self.ticket.state_version
        return body


class PersistInitialSLACycle:
    def __init__(self, *, calculate_deadline: SLADeadlineCalculator):
        self.calculate_deadline = calculate_deadline

    def __call__(self, *, ticket, submitted_at):
        try:
            binding = SLAPolicyBinding.objects.select_related("snapshot").get(
                society=ticket.society,
                category=ticket.category,
                priority=ticket.priority,
                is_active=True,
            )
        except SLAPolicyBinding.DoesNotExist as error:
            raise TicketSubmissionConflict(
                code="SLA_POLICY_UNAVAILABLE",
                message="No active SLA policy applies to this ticket.",
                ticket=ticket,
            ) from error

        snapshot = binding.snapshot
        if snapshot.society_timezone != ticket.society.timezone:
            raise TicketSubmissionConflict(
                code="SLA_POLICY_TIMEZONE_MISMATCH",
                message="The SLA policy timezone does not match the society timezone.",
                ticket=ticket,
            )
        resolution_deadline = self.calculate_deadline(
            started_at=submitted_at,
            duration=snapshot.initial_resolution_duration,
            society_id=ticket.society_id,
            society_timezone=snapshot.society_timezone,
            calendar_version=snapshot.calendar_version,
        )
        if resolution_deadline is None or resolution_deadline <= submitted_at:
            raise TicketSubmissionConflict(
                code="SLA_DEADLINE_INVALID",
                message="The SLA calendar did not produce a valid resolution deadline.",
                ticket=ticket,
            )
        cycle = SLACycle.objects.create(
            society=ticket.society,
            ticket=ticket,
            snapshot=snapshot,
            cycle_number=1,
            cycle_type=SLACycle.CycleType.INITIAL,
            started_at=submitted_at,
            resolution_deadline=resolution_deadline,
        )
        return cycle.id


class IdempotencyKeyReused(TicketSubmissionConflict):
    def __init__(self):
        super().__init__(
            code="IDEMPOTENCY_KEY_REUSED",
            message="The idempotency key was already used with a different request.",
        )


class IdempotencyRequestInProgress(TicketSubmissionConflict):
    def __init__(self):
        super().__init__(
            code="IDEMPOTENCY_REQUEST_IN_PROGRESS",
            message="A request with this idempotency key is still executing.",
        )


def business_calendar_deadline_calculator(
    *,
    started_at,
    duration,
    society_id,
    society_timezone,
    calendar_version,
):
    try:
        calendar = BusinessCalendar.objects.get(
            society_id=society_id,
            version=calendar_version,
        )
    except BusinessCalendar.DoesNotExist as error:
        raise TicketSubmissionConflict(
            code="SLA_CALENDAR_UNAVAILABLE",
            message="The SLA policy's business calendar is unavailable.",
        ) from error
    if calendar.timezone != society_timezone:
        raise TicketSubmissionConflict(
            code="SLA_CALENDAR_TIMEZONE_MISMATCH",
            message="The SLA calendar timezone does not match the policy snapshot.",
        )
    try:
        return calculate_business_deadline(
            started_at=started_at,
            duration=duration,
            society_timezone=society_timezone,
            working_intervals=calendar.working_intervals,
            holidays=calendar.holidays,
            is_emergency_24x7=calendar.is_emergency_24x7,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise TicketSubmissionConflict(
            code="SLA_CALENDAR_INVALID",
            message="The SLA policy's business calendar is invalid.",
        ) from error


def _canonical_payload_hash(payload):
    serialized = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(serialized).hexdigest()


def _canonical_request_hash(*, ticket_id, expected_version, **attributes):
    return _canonical_payload_hash(
        {
            "expected_version": expected_version,
            "ticket_id": str(ticket_id),
            **attributes,
        }
    )


def _replay(record):
    return TicketCommandResult(
        response_status=record.response_status,
        response_body=record.response_body,
        response_headers=record.response_headers,
        replayed=True,
    )


def _evaluate_existing_claim(*, record, request_hash, instant):
    if record.expires_at <= instant:
        record.delete()
        return None
    if record.request_hash != request_hash:
        raise IdempotencyKeyReused
    if record.status == IdempotencyRecord.Status.IN_PROGRESS:
        raise IdempotencyRequestInProgress
    return IdempotencyClaim(replay=_replay(record))


def _claim_idempotency(
    *,
    society_id,
    principal,
    route_template,
    idempotency_key,
    request_hash,
):
    instant = timezone.now()
    scope = {
        "society_id": society_id,
        "principal": principal,
        "http_method": "POST",
        "route_template": route_template,
        "idempotency_key": idempotency_key,
    }
    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            record = (
                IdempotencyRecord.objects.select_for_update().filter(**scope).first()
            )
            if record is not None:
                existing = _evaluate_existing_claim(
                    record=record,
                    request_hash=request_hash,
                    instant=instant,
                )
                if existing is not None:
                    return existing
            record = IdempotencyRecord.objects.create(
                **scope,
                request_hash=request_hash,
                expires_at=instant + IDEMPOTENCY_RETENTION,
            )
            return IdempotencyClaim(record_id=record.id)
    except IntegrityError:
        with transaction.atomic():
            set_local_society_id(society_id)
            record = IdempotencyRecord.objects.select_for_update().get(**scope)
            existing = _evaluate_existing_claim(
                record=record,
                request_hash=request_hash,
                instant=instant,
            )
            if existing is None:
                raise
            return existing


def _discard_claim(*, society_id, record_id):
    with transaction.atomic():
        set_local_society_id(society_id)
        IdempotencyRecord.objects.filter(id=record_id).delete()


def _complete_claim(
    *,
    record,
    response_status,
    response_body,
    response_headers,
):
    record.status = IdempotencyRecord.Status.COMPLETED
    record.response_status = response_status
    record.response_body = response_body
    record.response_headers = response_headers
    record.save(
        update_fields=(
            "status",
            "response_status",
            "response_body",
            "response_headers",
            "updated_at",
        )
    )


def _complete_conflict(*, society_id, record_id, conflict, correlation_id):
    body = conflict.response_body(correlation_id)
    headers = {"X-Correlation-ID": str(correlation_id)}
    with transaction.atomic():
        set_local_society_id(society_id)
        record = IdempotencyRecord.objects.select_for_update().get(id=record_id)
        _complete_claim(
            record=record,
            response_status=409,
            response_body=body,
            response_headers=headers,
        )
    return TicketCommandResult(409, body, headers)


def claim_ticket_outbox_events(*, society_id, claim_token, batch_size=50, event_type=None):
    if not isinstance(batch_size, int) or not 1 <= batch_size <= 100:
        raise ValueError("batch_size must be between 1 and 100")
    if event_type is not None and event_type not in TicketOutboxEvent.EventType.values:
        raise ValueError("event_type must be a supported outbox event type")

    try:
        normalized_claim_token = uuid.UUID(str(claim_token))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("claim_token must be a valid UUID") from exc

    with transaction.atomic():
        set_local_society_id(society_id)
        instant = timezone.now()
        claim_expires_at = instant + OUTBOX_CLAIM_LEASE
        candidate_query = TicketOutboxEvent.objects.select_for_update(skip_locked=True)
        if event_type is not None:
            candidate_query = candidate_query.filter(event_type=event_type)
        candidates = list(
            candidate_query
            .filter(
                dj_models.Q(
                    status=TicketOutboxEvent.Status.PENDING,
                    available_at__lte=instant,
                )
                | dj_models.Q(
                    status=TicketOutboxEvent.Status.CLAIMED,
                    claim_expires_at__lte=instant,
                )
            )
            .order_by("available_at", "created_at", "id")[:batch_size]
        )
        claimed_events = []
        for event in candidates:
            if event.attempts_count >= event.max_attempts:
                event.status = TicketOutboxEvent.Status.DEAD_LETTER
                event.state_version += 1
                event.claimed_at = None
                event.claim_token = None
                event.claim_expires_at = None
                event.dead_lettered_at = instant
                event.last_error_code = "CLAIM_LEASE_EXPIRED"
                event.save(
                    update_fields=(
                        "status",
                        "state_version",
                        "claimed_at",
                        "claim_token",
                        "claim_expires_at",
                        "dead_lettered_at",
                        "last_error_code",
                    )
                )
                continue

            event.status = TicketOutboxEvent.Status.CLAIMED
            event.state_version += 1
            event.attempts_count += 1
            event.last_attempted_at = instant
            event.claimed_at = instant
            event.claim_token = normalized_claim_token
            event.claim_expires_at = claim_expires_at
            event.save(
                update_fields=(
                    "status",
                    "state_version",
                    "attempts_count",
                    "last_attempted_at",
                    "claimed_at",
                    "claim_token",
                    "claim_expires_at",
                )
            )
            claimed_events.append(event)

    return claimed_events


def mark_ticket_outbox_event_delivered(*, society_id, outbox_event_id, claim_token):
    try:
        normalized_outbox_event_id = uuid.UUID(str(outbox_event_id))
        normalized_claim_token = uuid.UUID(str(claim_token))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("outbox_event_id and claim_token must be valid UUIDs") from exc

    with transaction.atomic():
        set_local_society_id(society_id)
        instant = timezone.now()
        event = TicketOutboxEvent.objects.select_for_update().get(
            id=normalized_outbox_event_id
        )
        if (
            event.status != TicketOutboxEvent.Status.CLAIMED
            or event.claim_token != normalized_claim_token
            or event.claim_expires_at is None
            or event.claim_expires_at <= instant
        ):
            raise TicketOutboxClaimLost("Outbox event is no longer claimed by this worker.")

        event.status = TicketOutboxEvent.Status.DELIVERED
        event.state_version += 1
        event.claimed_at = None
        event.claim_token = None
        event.claim_expires_at = None
        event.delivered_at = instant
        event.save(
            update_fields=(
                "status",
                "state_version",
                "claimed_at",
                "claim_token",
                "claim_expires_at",
                "delivered_at",
            )
        )
    return event


def mark_ticket_outbox_event_submitted(
    *, society_id, outbox_event_id, claim_token, provider_message_id
):
    normalized_provider_message_id = str(provider_message_id).strip()
    if not normalized_provider_message_id or len(normalized_provider_message_id) > 255:
        raise ValueError("provider_message_id must be between 1 and 255 characters")
    try:
        normalized_outbox_event_id = uuid.UUID(str(outbox_event_id))
        normalized_claim_token = uuid.UUID(str(claim_token))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("outbox_event_id and claim_token must be valid UUIDs") from exc

    with transaction.atomic():
        set_local_society_id(society_id)
        instant = timezone.now()
        event = TicketOutboxEvent.objects.select_for_update().get(
            id=normalized_outbox_event_id
        )
        if (
            event.status != TicketOutboxEvent.Status.CLAIMED
            or event.claim_token != normalized_claim_token
            or event.claim_expires_at is None
            or event.claim_expires_at <= instant
        ):
            raise TicketOutboxClaimLost("Outbox event is no longer claimed by this worker.")

        event.status = TicketOutboxEvent.Status.SUBMITTED
        event.state_version += 1
        event.claimed_at = None
        event.claim_token = None
        event.claim_expires_at = None
        event.provider_message_id = normalized_provider_message_id
        event.submitted_at = instant
        event.save(
            update_fields=(
                "status",
                "state_version",
                "claimed_at",
                "claim_token",
                "claim_expires_at",
                "provider_message_id",
                "submitted_at",
            )
        )
    return event


def confirm_ticket_outbox_event_delivery(
    *, society_id, outbox_event_id, provider_message_id
):
    normalized_provider_message_id = str(provider_message_id).strip()
    if not normalized_provider_message_id or len(normalized_provider_message_id) > 255:
        raise ValueError("provider_message_id must be between 1 and 255 characters")
    try:
        normalized_outbox_event_id = uuid.UUID(str(outbox_event_id))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("outbox_event_id must be a valid UUID") from exc

    with transaction.atomic():
        set_local_society_id(society_id)
        event = TicketOutboxEvent.objects.select_for_update().get(
            id=normalized_outbox_event_id
        )
        if event.provider_message_id != normalized_provider_message_id:
            raise TicketOutboxDeliveryConfirmationRejected(
                "Provider message does not match the outbox event."
            )
        if event.status == TicketOutboxEvent.Status.DELIVERED:
            return event
        if event.status != TicketOutboxEvent.Status.SUBMITTED:
            raise TicketOutboxDeliveryConfirmationRejected(
                "Outbox event has not been submitted to the provider."
            )

        event.status = TicketOutboxEvent.Status.DELIVERED
        event.state_version += 1
        event.delivered_at = timezone.now()
        event.save(update_fields=("status", "state_version", "delivered_at"))
    return event


def dead_letter_ticket_outbox_event(
    *, society_id, outbox_event_id, claim_token, error_code
):
    normalized_error_code = str(error_code).strip()
    if not normalized_error_code or len(normalized_error_code) > 128:
        raise ValueError("error_code must be between 1 and 128 characters")
    try:
        normalized_outbox_event_id = uuid.UUID(str(outbox_event_id))
        normalized_claim_token = uuid.UUID(str(claim_token))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("outbox_event_id and claim_token must be valid UUIDs") from exc

    with transaction.atomic():
        set_local_society_id(society_id)
        instant = timezone.now()
        event = TicketOutboxEvent.objects.select_for_update().get(
            id=normalized_outbox_event_id
        )
        if (
            event.status != TicketOutboxEvent.Status.CLAIMED
            or event.claim_token != normalized_claim_token
            or event.claim_expires_at is None
            or event.claim_expires_at <= instant
        ):
            raise TicketOutboxClaimLost("Outbox event is no longer claimed by this worker.")

        event.status = TicketOutboxEvent.Status.DEAD_LETTER
        event.state_version += 1
        event.claimed_at = None
        event.claim_token = None
        event.claim_expires_at = None
        event.last_error_code = normalized_error_code
        event.dead_lettered_at = instant
        event.save(
            update_fields=(
                "status",
                "state_version",
                "claimed_at",
                "claim_token",
                "claim_expires_at",
                "last_error_code",
                "dead_lettered_at",
            )
        )
    return event


def release_ticket_outbox_event_for_retry(
    *,
    society_id,
    outbox_event_id,
    claim_token,
    error_code,
    retry_delay,
):
    if not isinstance(retry_delay, timedelta) or retry_delay.total_seconds() < 0:
        raise ValueError("retry_delay must be a non-negative timedelta")
    normalized_error_code = str(error_code).strip()
    if not normalized_error_code or len(normalized_error_code) > 128:
        raise ValueError("error_code must be between 1 and 128 characters")

    try:
        normalized_outbox_event_id = uuid.UUID(str(outbox_event_id))
        normalized_claim_token = uuid.UUID(str(claim_token))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("outbox_event_id and claim_token must be valid UUIDs") from exc

    with transaction.atomic():
        set_local_society_id(society_id)
        instant = timezone.now()
        event = TicketOutboxEvent.objects.select_for_update().get(
            id=normalized_outbox_event_id
        )
        if (
            event.status != TicketOutboxEvent.Status.CLAIMED
            or event.claim_token != normalized_claim_token
            or event.claim_expires_at is None
            or event.claim_expires_at <= instant
        ):
            raise TicketOutboxClaimLost("Outbox event is no longer claimed by this worker.")

        event.state_version += 1
        event.claimed_at = None
        event.claim_token = None
        event.claim_expires_at = None
        event.last_error_code = normalized_error_code
        if event.attempts_count >= event.max_attempts:
            event.status = TicketOutboxEvent.Status.DEAD_LETTER
            event.dead_lettered_at = instant
            event.save(
                update_fields=(
                    "status",
                    "state_version",
                    "claimed_at",
                    "claim_token",
                    "claim_expires_at",
                    "last_error_code",
                    "dead_lettered_at",
                )
            )
        else:
            event.status = TicketOutboxEvent.Status.PENDING
            event.available_at = instant + retry_delay
            event.save(
                update_fields=(
                    "status",
                    "state_version",
                    "claimed_at",
                    "claim_token",
                    "claim_expires_at",
                    "last_error_code",
                    "available_at",
                )
            )
    return event


def _persona_for_creator(*, society_id, actor, membership, workflow_type, unit):
    if membership.user_id != actor.id or membership.society_id != society_id:
        raise TicketCreationForbidden("Membership does not belong to the actor and society.")
    if not membership.is_current():
        raise TicketCreationForbidden("An active membership is required.")
    if isinstance(membership, UnitOccupancy):
        if unit is not None and membership.unit_id != unit.id:
            raise TicketCreationForbidden(
                "Residents may create tickets only for their own unit."
            )
        return "resident"
    if isinstance(membership, StaffMembership):
        if membership.role not in {
            StaffMembership.Role.FACILITY_MANAGER,
            StaffMembership.Role.HELPDESK_OPERATOR,
        }:
            raise TicketCreationForbidden("This staff role cannot create tickets.")
        return "staff"
    if isinstance(membership, CommitteeMembership):
        if workflow_type != Ticket.WorkflowType.GOVERNANCE:
            raise TicketCreationForbidden(
                "Committee members may create governance tickets only."
            )
        return "committee"
    raise TicketCreationForbidden("This tenant persona cannot create tickets.")


def _draft_response_body(ticket):
    return {
        "id": str(ticket.id),
        "society_id": str(ticket.society_id),
        "ticket_number": ticket.ticket_number,
        "creator_id": str(ticket.creator_id),
        "category": str(ticket.category_id),
        "subcategory": str(ticket.subcategory_id),
        "workflow_type": ticket.workflow_type,
        "unit": str(ticket.unit_id) if ticket.unit_id else None,
        "common_area": str(ticket.common_area_id) if ticket.common_area_id else None,
        "title": ticket.title,
        "description": ticket.description,
        "priority": ticket.priority,
        "status": ticket.status,
        "state_version": ticket.state_version,
        "submitted_at": None,
        "archived_at": None,
    }


def create_ticket_draft(
    *,
    society,
    actor,
    membership,
    workflow_type,
    category,
    subcategory,
    unit,
    common_area,
    title,
    description,
    priority,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    _persona_for_creator(
        society_id=society.id,
        actor=actor,
        membership=membership,
        workflow_type=workflow_type,
        unit=unit,
    )
    request_hash = _canonical_payload_hash(
        {
            "category": str(category.id),
            "common_area": str(common_area.id) if common_area else None,
            "description": description,
            "priority": priority,
            "subcategory": str(subcategory.id),
            "title": title,
            "unit": str(unit.id) if unit else None,
            "workflow_type": workflow_type,
        }
    )
    claim = _claim_idempotency(
        society_id=society.id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society.id)
            ticket = Ticket.objects.create(
                society=society,
                creator=actor,
                category=category,
                subcategory=subcategory,
                workflow_type=workflow_type,
                unit=unit,
                common_area=common_area,
                title=title,
                description=description,
                priority=priority,
            )
            body = _draft_response_body(ticket)
            headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=201,
                response_body=body,
                response_headers=headers,
            )
            return TicketCommandResult(201, body, headers)
    except Exception:
        _discard_claim(society_id=society.id, record_id=claim.record_id)
        raise


def _persona_for_internal_commenter(*, ticket, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketCommentForbidden("Membership does not belong to the actor and society.")
    if not membership.is_current():
        raise TicketCommentForbidden("An active membership is required.")
    if isinstance(membership, StaffMembership):
        if membership.role not in {
            StaffMembership.Role.FACILITY_MANAGER,
            StaffMembership.Role.HELPDESK_OPERATOR,
        }:
            raise TicketCommentForbidden(
                "This staff role cannot access internal ticket comments."
            )
        return "staff"
    if isinstance(membership, CommitteeMembership):
        if ticket.workflow_type != Ticket.WorkflowType.GOVERNANCE:
            raise TicketCommentForbidden(
                "Committee members may access internal comments only on governance tickets."
            )
        return "committee"
    raise TicketCommentForbidden("This tenant persona cannot access internal comments.")


def _persona_for_commenter(*, ticket, actor, membership, visibility):
    if visibility == TicketComment.Visibility.INTERNAL:
        return _persona_for_internal_commenter(
            ticket=ticket,
            actor=actor,
            membership=membership,
        )
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketCommentForbidden("Membership does not belong to the actor and society.")
    if not membership.is_current():
        raise TicketCommentForbidden("An active membership is required.")
    if isinstance(membership, UnitOccupancy):
        if ticket.creator_id != actor.id:
            raise TicketCommentForbidden(
                "Residents may comment only on tickets they created."
            )
        if (
            ticket.workflow_type == Ticket.WorkflowType.SERVICE
            and ticket.unit_id is not None
            and ticket.unit_id != membership.unit_id
        ):
            raise TicketCommentForbidden(
                "Residents may comment only on tickets for their own unit."
            )
        return "resident"
    if isinstance(membership, StaffMembership):
        if membership.role not in {
            StaffMembership.Role.FACILITY_MANAGER,
            StaffMembership.Role.HELPDESK_OPERATOR,
        }:
            raise TicketCommentForbidden("This staff role cannot comment on tickets.")
        return "staff"
    if isinstance(membership, CommitteeMembership):
        if (
            ticket.workflow_type != Ticket.WorkflowType.GOVERNANCE
            or ticket.creator_id != actor.id
        ):
            raise TicketCommentForbidden(
                "Committee members may comment only on governance tickets they created."
            )
        return "committee"
    raise TicketCommentForbidden("This tenant persona cannot comment on tickets.")


def authorize_internal_ticket_comments(*, ticket, actor, membership):
    _persona_for_internal_commenter(
        ticket=ticket,
        actor=actor,
        membership=membership,
    )


def _comment_response_body(comment, *, actor_id):
    return {
        "id": str(comment.id),
        "ticket_id": str(comment.ticket_id),
        "author_id": str(comment.author_id),
        "author_persona": comment.author_persona,
        "visibility": comment.visibility,
        "body": comment.body,
        "created_at": comment.created_at.isoformat().replace("+00:00", "Z"),
        "is_authored_by_requester": comment.author_id == actor_id,
    }


def create_ticket_comment(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    body,
    expected_version,
    idempotency_key,
    route_template,
    correlation_id,
    visibility,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _persona_for_commenter(
            ticket=ticket,
            actor=actor,
            membership=membership,
            visibility=visibility,
        )
    request_hash = _canonical_payload_hash(
        {
            "body": body,
            "expected_version": expected_version,
            "ticket_id": str(ticket_id),
            "visibility": visibility,
        }
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            actor_persona = _persona_for_commenter(
                ticket=ticket,
                actor=actor,
                membership=membership,
                visibility=visibility,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status == Ticket.Status.DRAFT:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Comments are available after the ticket is submitted.",
                    ticket=ticket,
                )
            comment = TicketComment.objects.create(
                society_id=society_id,
                ticket=ticket,
                author=actor,
                author_persona=actor_persona,
                visibility=visibility,
                body=body,
            )
            response_body = _comment_response_body(comment, actor_id=actor.id)
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=201,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(201, response_body, response_headers)
    except TicketCommentForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _persona_for_canceller(*, ticket, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketCancellationForbidden(
            "Membership does not belong to the actor and society."
        )
    if not membership.is_current():
        raise TicketCancellationForbidden("An active membership is required.")
    if ticket.status in {
        Ticket.Status.UNDER_REVIEW,
        Ticket.Status.IN_DISCUSSION,
    }:
        if (
            ticket.workflow_type == Ticket.WorkflowType.GOVERNANCE
            and isinstance(membership, StaffMembership)
            and membership.role == StaffMembership.Role.FACILITY_MANAGER
        ):
            return "staff"
        raise TicketCancellationForbidden(
            "Only facility managers can cancel governance tickets under review or discussion."
        )
    if isinstance(membership, StaffMembership) and membership.role == (
        StaffMembership.Role.FACILITY_MANAGER
    ):
        return "staff"
    if ticket.creator_id != actor.id:
        raise TicketCancellationForbidden("Only the ticket creator can cancel this ticket.")
    if isinstance(membership, UnitOccupancy):
        if (
            ticket.workflow_type == Ticket.WorkflowType.SERVICE
            and ticket.unit_id is not None
            and ticket.unit_id != membership.unit_id
        ):
            raise TicketCancellationForbidden(
                "Residents may cancel only tickets for their own unit."
            )
        return "resident"
    if isinstance(membership, CommitteeMembership):
        if ticket.workflow_type != Ticket.WorkflowType.GOVERNANCE:
            raise TicketCancellationForbidden(
                "Committee members may cancel only governance tickets they created."
            )
        return "committee"
    if isinstance(membership, StaffMembership):
        if membership.role != StaffMembership.Role.HELPDESK_OPERATOR:
            raise TicketCancellationForbidden("This staff role cannot cancel tickets.")
        return "staff"
    raise TicketCancellationForbidden("This tenant persona cannot cancel tickets.")


def cancel_submitted_ticket(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    reason,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _persona_for_canceller(ticket=ticket, actor=actor, membership=membership)
    request_hash = _canonical_payload_hash(
        {
            "expected_version": expected_version,
            "reason": reason,
            "ticket_id": str(ticket_id),
        }
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            actor_persona = _persona_for_canceller(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            cancellable_statuses = (
                {
                    Ticket.Status.SUBMITTED,
                    Ticket.Status.ASSIGNED,
                    Ticket.Status.ACCEPTED,
                    Ticket.Status.IN_PROGRESS,
                    Ticket.Status.PENDING_ESTIMATE_APPROVAL,
                    Ticket.Status.SUPERVISOR_TRIAGE,
                }
                if ticket.workflow_type == Ticket.WorkflowType.SERVICE
                else {
                    Ticket.Status.SUBMITTED,
                    Ticket.Status.UNDER_REVIEW,
                    Ticket.Status.IN_DISCUSSION,
                }
            )
            if ticket.status not in cancellable_statuses:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="The ticket is not in a state that permits cancellation.",
                    ticket=ticket,
                )
            if actor_persona == "resident" and ticket.status not in {
                Ticket.Status.SUBMITTED,
                Ticket.Status.ASSIGNED,
                Ticket.Status.ACCEPTED,
            }:
                raise TicketCancellationForbidden(
                    "Residents cannot cancel tickets after work has started. Contact the facility manager."
                )

            cancelled_at = timezone.now()
            sla_cycle = SLACycle.objects.select_for_update().get(
                ticket=ticket,
                ended_at__isnull=True,
            )
            sla_cycle.ended_at = cancelled_at
            sla_cycle.outcome = SLACycle.Outcome.CANCELLED
            sla_cycle.save(update_fields=("ended_at", "outcome"))

            TicketEstimate.objects.filter(
                ticket=ticket,
                status=TicketEstimate.Status.SUBMITTED,
            ).update(
                status=TicketEstimate.Status.CANCELLED,
                decision_reason="Ticket cancelled",
                updated_at=cancelled_at,
            )

            event_metadata = {}
            active_assignment = (
                TicketAssignment.objects.select_for_update()
                .filter(ticket=ticket)
                .exclude(state=TicketAssignment.State.ENDED)
                .first()
            )
            if active_assignment is not None:
                active_assignment.state = TicketAssignment.State.ENDED
                active_assignment.ended_at = cancelled_at
                active_assignment.ended_reason = reason
                active_assignment.save(
                    update_fields=("state", "ended_at", "ended_reason")
                )
                event_metadata["assignment_id"] = str(active_assignment.id)
                if active_assignment.target_type == TicketAssignment.TargetType.IN_HOUSE:
                    technician = TechnicianProfile.objects.select_for_update().get(
                        id=active_assignment.technician_id,
                        society_id=society_id,
                    )
                    if technician.current_active_tickets_count > 0:
                        technician.current_active_tickets_count -= 1
                        technician.save(
                            update_fields=("current_active_tickets_count", "updated_at")
                        )
                    event_metadata["technician_id"] = str(technician.id)
                elif active_assignment.target_type == TicketAssignment.TargetType.VENDOR:
                    vendor_contract = VendorContract.objects.select_for_update().get(
                        id=active_assignment.vendor_contract_id,
                        society_id=society_id,
                    )
                    if vendor_contract.current_active_tickets_count > 0:
                        vendor_contract.current_active_tickets_count -= 1
                        vendor_contract.save(
                            update_fields=("current_active_tickets_count", "updated_at")
                        )
                    event_metadata["vendor_contract_id"] = str(vendor_contract.id)
                    active_allocation = (
                        VendorStaffAllocation.objects.select_for_update()
                        .filter(assignment=active_assignment)
                        .exclude(state=VendorStaffAllocation.State.ENDED)
                        .first()
                    )
                    if active_allocation is not None:
                        active_allocation.state = VendorStaffAllocation.State.ENDED
                        active_allocation.ended_at = cancelled_at
                        active_allocation.ended_reason = reason
                        active_allocation.save(
                            update_fields=("state", "ended_at", "ended_reason")
                        )
                        event_metadata["vendor_staff_allocation_id"] = str(
                            active_allocation.id
                        )
                        event_metadata["staff_membership_id"] = str(
                            active_allocation.staff_membership_id
                        )

            previous_status = ticket.status
            ticket.status = Ticket.Status.CANCELLED
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))
            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_CANCELLED,
                reason=reason,
                correlation_id=correlation_id,
                metadata=event_metadata,
            )
            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketCancellationForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _persona_for_governance_reviewer(*, ticket, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketGovernanceReviewForbidden(
            "Membership does not belong to the actor and society."
        )
    if not membership.is_current():
        raise TicketGovernanceReviewForbidden("An active membership is required.")
    if ticket.workflow_type != Ticket.WorkflowType.GOVERNANCE:
        raise TicketGovernanceReviewForbidden(
            "Governance review is available only for governance tickets."
        )
    if not isinstance(membership, StaffMembership) or membership.role != (
        StaffMembership.Role.FACILITY_MANAGER
    ):
        raise TicketGovernanceReviewForbidden(
            "Only facility managers can begin governance review."
        )
    return "staff"


def begin_governance_review(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _persona_for_governance_reviewer(
            ticket=ticket,
            actor=actor,
            membership=membership,
        )
    request_hash = _canonical_request_hash(
        ticket_id=ticket_id,
        expected_version=expected_version,
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            actor_persona = _persona_for_governance_reviewer(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.SUBMITTED:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only submitted governance tickets can begin review.",
                    ticket=ticket,
                )

            review_started_at = timezone.now()
            assignment = GovernanceReviewAssignment.objects.create(
                society_id=society_id,
                ticket=ticket,
                reviewer=actor,
                assigned_by=actor,
                reviewer_persona=actor_persona,
                accepted_at=review_started_at,
            )
            previous_status = ticket.status
            ticket.status = Ticket.Status.UNDER_REVIEW
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))
            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.GOVERNANCE_REVIEW_BEGUN,
                correlation_id=correlation_id,
                metadata={
                    "review_assignment_id": str(assignment.id),
                    "reviewer_id": str(actor.id),
                },
            )
            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "review_assignment": {
                    "id": str(assignment.id),
                    "reviewer_id": str(assignment.reviewer_id),
                    "reviewer_persona": assignment.reviewer_persona,
                    "accepted_at": assignment.accepted_at.isoformat(),
                },
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketGovernanceReviewForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _persona_for_in_house_assignment(*, ticket, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketInHouseAssignmentForbidden(
            "Membership does not belong to the actor and society."
        )
    if not membership.is_current():
        raise TicketInHouseAssignmentForbidden("An active membership is required.")
    if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
        raise TicketInHouseAssignmentForbidden(
            "In-house assignment is available only for service tickets."
        )
    if not isinstance(membership, StaffMembership) or membership.role != (
        StaffMembership.Role.FACILITY_MANAGER
    ):
        raise TicketInHouseAssignmentForbidden(
            "Only facility managers can assign in-house technicians."
        )
    return "staff"


def assign_in_house_technician(
    *,
    society_id,
    ticket_id,
    technician_id,
    actor,
    membership,
    expected_version,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _persona_for_in_house_assignment(
            ticket=ticket,
            actor=actor,
            membership=membership,
        )
    request_hash = _canonical_request_hash(
        ticket_id=ticket_id,
        expected_version=expected_version,
        technician_id=str(technician_id),
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            actor_persona = _persona_for_in_house_assignment(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.SUBMITTED:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only submitted service tickets can be assigned.",
                    ticket=ticket,
                )
            try:
                technician = TechnicianProfile.objects.select_for_update().get(
                    id=technician_id,
                    society_id=society_id,
                )
            except TechnicianProfile.DoesNotExist as error:
                raise TicketSubmissionConflict(
                    code="TECHNICIAN_UNAVAILABLE",
                    message="The selected technician is unavailable.",
                    ticket=ticket,
                ) from error
            if not technician.is_current():
                raise TicketSubmissionConflict(
                    code="TECHNICIAN_UNAVAILABLE",
                    message="The selected technician is unavailable.",
                    ticket=ticket,
                )
            if (
                technician.current_active_tickets_count
                >= technician.max_active_tickets
            ):
                raise TicketSubmissionConflict(
                    code="TECHNICIAN_CAPACITY_UNAVAILABLE",
                    message="The selected technician has no remaining ticket capacity.",
                    ticket=ticket,
                )

            assignment_started_at = timezone.now()
            sla_cycle = SLACycle.objects.select_for_update().select_related("snapshot").get(
                ticket=ticket,
                ended_at__isnull=True,
            )
            acceptance_deadline = (
                assignment_started_at + sla_cycle.snapshot.acceptance_duration
            )
            assignment = TicketAssignment.objects.create(
                society_id=society_id,
                ticket=ticket,
                target_type=TicketAssignment.TargetType.IN_HOUSE,
                technician=technician,
                assigned_by=actor,
                acceptance_deadline=acceptance_deadline,
                state=TicketAssignment.State.OFFERED,
            )
            technician.current_active_tickets_count += 1
            technician.save(update_fields=("current_active_tickets_count", "updated_at"))
            sla_cycle.acceptance_deadline = acceptance_deadline
            sla_cycle.save(update_fields=("acceptance_deadline",))

            previous_status = ticket.status
            ticket.status = Ticket.Status.ASSIGNED
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))
            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_ASSIGNED,
                correlation_id=correlation_id,
                metadata={
                    "assignment_id": str(assignment.id),
                    "technician_id": str(technician.id),
                },
            )
            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "assignment": {
                    "id": str(assignment.id),
                    "technician_id": str(technician.id),
                    "state": assignment.state,
                    "acceptance_deadline": assignment.acceptance_deadline.isoformat(),
                },
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketInHouseAssignmentForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def assign_vendor_contract(
    *,
    society_id,
    ticket_id,
    vendor_contract_id,
    actor,
    membership,
    expected_version,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        try:
            _persona_for_in_house_assignment(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )
        except TicketInHouseAssignmentForbidden as error:
            raise TicketVendorAssignmentForbidden(str(error)) from error
    request_hash = _canonical_request_hash(
        ticket_id=ticket_id,
        expected_version=expected_version,
        vendor_contract_id=str(vendor_contract_id),
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            try:
                actor_persona = _persona_for_in_house_assignment(
                    ticket=ticket,
                    actor=actor,
                    membership=membership,
                )
            except TicketInHouseAssignmentForbidden as error:
                raise TicketVendorAssignmentForbidden(str(error)) from error
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.SUBMITTED:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only submitted service tickets can be assigned.",
                    ticket=ticket,
                )
            try:
                vendor_contract = VendorContract.objects.select_for_update().select_related(
                    "vendor", "society"
                ).get(id=vendor_contract_id, society_id=society_id)
            except VendorContract.DoesNotExist as error:
                raise TicketSubmissionConflict(
                    code="VENDOR_CONTRACT_UNAVAILABLE",
                    message="The selected vendor contract is unavailable.",
                    ticket=ticket,
                ) from error
            if not vendor_contract.is_current():
                raise TicketSubmissionConflict(
                    code="VENDOR_CONTRACT_UNAVAILABLE",
                    message="The selected vendor contract is unavailable.",
                    ticket=ticket,
                )
            if (
                vendor_contract.max_active_tickets is not None
                and vendor_contract.current_active_tickets_count
                >= vendor_contract.max_active_tickets
            ):
                raise TicketSubmissionConflict(
                    code="VENDOR_CAPACITY_UNAVAILABLE",
                    message="The selected vendor contract has no remaining ticket capacity.",
                    ticket=ticket,
                )

            assignment_started_at = timezone.now()
            sla_cycle = SLACycle.objects.select_for_update().select_related("snapshot").get(
                ticket=ticket,
                ended_at__isnull=True,
            )
            acceptance_deadline = (
                assignment_started_at + sla_cycle.snapshot.acceptance_duration
            )
            assignment = TicketAssignment.objects.create(
                society_id=society_id,
                ticket=ticket,
                target_type=TicketAssignment.TargetType.VENDOR,
                vendor_contract=vendor_contract,
                assigned_by=actor,
                acceptance_deadline=acceptance_deadline,
                state=TicketAssignment.State.OFFERED,
            )
            vendor_contract.current_active_tickets_count += 1
            vendor_contract.save(
                update_fields=("current_active_tickets_count", "updated_at")
            )
            sla_cycle.acceptance_deadline = acceptance_deadline
            sla_cycle.save(update_fields=("acceptance_deadline",))

            previous_status = ticket.status
            ticket.status = Ticket.Status.ASSIGNED
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))
            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_ASSIGNED,
                correlation_id=correlation_id,
                metadata={
                    "assignment_id": str(assignment.id),
                    "vendor_contract_id": str(vendor_contract.id),
                },
            )
            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "assignment": {
                    "id": str(assignment.id),
                    "vendor_contract_id": str(vendor_contract.id),
                    "state": assignment.state,
                    "acceptance_deadline": assignment.acceptance_deadline.isoformat(),
                },
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketVendorAssignmentForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _vendor_dispatcher_for_assignment(*, ticket, assignment, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketVendorWorkerAllocationForbidden(
            "Membership does not belong to the actor and society."
        )
    if not isinstance(membership, VendorStaffMembership) or not membership.is_current():
        raise TicketVendorWorkerAllocationForbidden(
            "An active vendor dispatcher membership is required."
        )
    if membership.role != VendorStaffMembership.Role.DISPATCHER:
        raise TicketVendorWorkerAllocationForbidden(
            "Only vendor dispatchers can allocate workers."
        )
    if (
        assignment.target_type != TicketAssignment.TargetType.VENDOR
        or assignment.vendor_contract_id != membership.contract_id
    ):
        raise TicketVendorWorkerAllocationForbidden(
            "Dispatcher membership does not match the vendor assignment."
        )
    return "vendor"


def allocate_vendor_worker(
    *,
    society_id,
    ticket_id,
    staff_membership_id,
    actor,
    membership,
    expected_version,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        try:
            assignment = TicketAssignment.objects.select_related("vendor_contract").get(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.VENDOR,
                state=TicketAssignment.State.OFFERED,
            )
        except TicketAssignment.DoesNotExist as error:
            raise TicketVendorWorkerAllocationForbidden(
                "No offered vendor assignment is available for this ticket."
            ) from error
        _vendor_dispatcher_for_assignment(
            ticket=ticket,
            assignment=assignment,
            actor=actor,
            membership=membership,
        )
    request_hash = _canonical_request_hash(
        ticket_id=ticket_id,
        expected_version=expected_version,
        staff_membership_id=str(staff_membership_id),
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            try:
                    assignment = (
                        TicketAssignment.objects.select_for_update().get(
                        ticket=ticket,
                        target_type=TicketAssignment.TargetType.VENDOR,
                        state=TicketAssignment.State.OFFERED,
                    )
                )
            except TicketAssignment.DoesNotExist as error:
                raise TicketSubmissionConflict(
                    code="VENDOR_ASSIGNMENT_UNAVAILABLE",
                    message="No offered vendor assignment is available for this ticket.",
                    ticket=ticket,
                ) from error
            actor_persona = _vendor_dispatcher_for_assignment(
                ticket=ticket,
                assignment=assignment,
                actor=actor,
                membership=membership,
            )
            if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
                raise TicketSubmissionConflict(
                    code="TICKET_WORKFLOW_CONFLICT",
                    message="Vendor worker allocation is available only for service tickets.",
                    ticket=ticket,
                )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.ASSIGNED:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only assigned tickets can receive a vendor worker allocation.",
                    ticket=ticket,
                )
            try:
                worker_membership = (
                    VendorStaffMembership.objects.select_for_update()
                    .select_related("contract")
                    .get(id=staff_membership_id, society_id=society_id)
                )
            except VendorStaffMembership.DoesNotExist as error:
                raise TicketSubmissionConflict(
                    code="VENDOR_WORKER_UNAVAILABLE",
                    message="The selected vendor worker is unavailable.",
                    ticket=ticket,
                ) from error
            if (
                worker_membership.role != VendorStaffMembership.Role.WORKER
                or not worker_membership.is_current()
                or worker_membership.contract_id != assignment.vendor_contract_id
            ):
                raise TicketSubmissionConflict(
                    code="VENDOR_WORKER_UNAVAILABLE",
                    message="The selected vendor worker is unavailable.",
                    ticket=ticket,
                )
            if VendorStaffAllocation.objects.filter(
                assignment=assignment,
            ).exclude(state=VendorStaffAllocation.State.ENDED).exists():
                raise TicketSubmissionConflict(
                    code="VENDOR_WORKER_ALREADY_ALLOCATED",
                    message="An active vendor worker allocation already exists.",
                    ticket=ticket,
                )

            allocation = VendorStaffAllocation.objects.create(
                society_id=society_id,
                assignment=assignment,
                staff_membership=worker_membership,
                allocated_by=actor,
            )
            ticket.state_version += 1
            ticket.save(update_fields=("state_version", "updated_at"))
            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=ticket.status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.VENDOR_WORKER_ALLOCATED,
                correlation_id=correlation_id,
                metadata={
                    "assignment_id": str(assignment.id),
                    "vendor_staff_allocation_id": str(allocation.id),
                    "staff_membership_id": str(worker_membership.id),
                },
            )
            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "allocation": {
                    "id": str(allocation.id),
                    "assignment_id": str(assignment.id),
                    "staff_membership_id": str(worker_membership.id),
                    "state": allocation.state,
                },
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketVendorWorkerAllocationForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def replace_vendor_worker(
    *,
    society_id,
    ticket_id,
    staff_membership_id,
    actor,
    membership,
    expected_version,
    reason,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        try:
            assignment = TicketAssignment.objects.get(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.VENDOR,
                state=TicketAssignment.State.OFFERED,
            )
        except TicketAssignment.DoesNotExist as error:
            raise TicketVendorWorkerAllocationForbidden(
                "No offered vendor assignment is available for this ticket."
            ) from error
        _vendor_dispatcher_for_assignment(
            ticket=ticket,
            assignment=assignment,
            actor=actor,
            membership=membership,
        )
    request_hash = _canonical_request_hash(
        ticket_id=ticket_id,
        expected_version=expected_version,
        staff_membership_id=str(staff_membership_id),
        reason=reason,
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            try:
                assignment = TicketAssignment.objects.select_for_update().get(
                    ticket=ticket,
                    target_type=TicketAssignment.TargetType.VENDOR,
                    state=TicketAssignment.State.OFFERED,
                )
                previous_allocation = VendorStaffAllocation.objects.select_for_update().get(
                    assignment=assignment,
                    state=VendorStaffAllocation.State.ALLOCATED,
                )
            except (TicketAssignment.DoesNotExist, VendorStaffAllocation.DoesNotExist) as error:
                raise TicketSubmissionConflict(
                    code="VENDOR_WORKER_ALLOCATION_UNAVAILABLE",
                    message="No allocated vendor worker is available to replace.",
                    ticket=ticket,
                ) from error
            actor_persona = _vendor_dispatcher_for_assignment(
                ticket=ticket,
                assignment=assignment,
                actor=actor,
                membership=membership,
            )
            if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
                raise TicketSubmissionConflict(
                    code="TICKET_WORKFLOW_CONFLICT",
                    message="Vendor worker replacement is available only for service tickets.",
                    ticket=ticket,
                )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.ASSIGNED:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only assigned tickets can replace a vendor worker.",
                    ticket=ticket,
                )
            try:
                worker_membership = VendorStaffMembership.objects.select_for_update().get(
                    id=staff_membership_id,
                    society_id=society_id,
                )
            except VendorStaffMembership.DoesNotExist as error:
                raise TicketSubmissionConflict(
                    code="VENDOR_WORKER_UNAVAILABLE",
                    message="The selected vendor worker is unavailable.",
                    ticket=ticket,
                ) from error
            if (
                worker_membership.role != VendorStaffMembership.Role.WORKER
                or not worker_membership.is_current()
                or worker_membership.contract_id != assignment.vendor_contract_id
            ):
                raise TicketSubmissionConflict(
                    code="VENDOR_WORKER_UNAVAILABLE",
                    message="The selected vendor worker is unavailable.",
                    ticket=ticket,
                )
            if worker_membership.id == previous_allocation.staff_membership_id:
                raise TicketSubmissionConflict(
                    code="VENDOR_WORKER_REPLACEMENT_SAME_WORKER",
                    message="The replacement worker must differ from the active worker.",
                    ticket=ticket,
                )

            replaced_at = timezone.now()
            previous_allocation.state = VendorStaffAllocation.State.ENDED
            previous_allocation.ended_at = replaced_at
            previous_allocation.ended_reason = reason
            previous_allocation.save(
                update_fields=("state", "ended_at", "ended_reason")
            )
            allocation = VendorStaffAllocation.objects.create(
                society_id=society_id,
                assignment=assignment,
                staff_membership=worker_membership,
                allocated_by=actor,
            )
            ticket.state_version += 1
            ticket.save(update_fields=("state_version", "updated_at"))
            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=ticket.status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.VENDOR_WORKER_REPLACED,
                reason=reason,
                correlation_id=correlation_id,
                metadata={
                    "assignment_id": str(assignment.id),
                    "replaced_vendor_staff_allocation_id": str(previous_allocation.id),
                    "vendor_staff_allocation_id": str(allocation.id),
                    "staff_membership_id": str(worker_membership.id),
                },
            )
            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "replaced_allocation_id": str(previous_allocation.id),
                "allocation": {
                    "id": str(allocation.id),
                    "assignment_id": str(assignment.id),
                    "staff_membership_id": str(worker_membership.id),
                    "state": allocation.state,
                },
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketVendorWorkerAllocationForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _vendor_worker_for_allocation(*, ticket, allocation, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketVendorWorkerAcceptanceForbidden(
            "Membership does not belong to the actor and society."
        )
    if (
        not isinstance(membership, VendorStaffMembership)
        or membership.role != VendorStaffMembership.Role.WORKER
        or not membership.is_current()
        or allocation.staff_membership_id != membership.id
    ):
        raise TicketVendorWorkerAcceptanceForbidden(
            "Only the active allocated vendor worker can accept this ticket."
        )
    return "vendor"


def accept_vendor_worker_allocation(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        try:
            assignment = TicketAssignment.objects.get(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.VENDOR,
            )
            allocation = VendorStaffAllocation.objects.filter(
                assignment=assignment,
                staff_membership=membership,
            ).order_by("-allocated_at").first()
            if allocation is None:
                raise VendorStaffAllocation.DoesNotExist
        except (TicketAssignment.DoesNotExist, VendorStaffAllocation.DoesNotExist) as error:
            raise TicketVendorWorkerAcceptanceForbidden(
                "No vendor worker allocation is available for this ticket."
            ) from error
        _vendor_worker_for_allocation(
            ticket=ticket,
            allocation=allocation,
            actor=actor,
            membership=membership,
        )
    request_hash = _canonical_request_hash(
        ticket_id=ticket_id,
        expected_version=expected_version,
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            try:
                assignment = TicketAssignment.objects.select_for_update().get(
                    ticket=ticket,
                    target_type=TicketAssignment.TargetType.VENDOR,
                    state=TicketAssignment.State.OFFERED,
                )
                allocation = VendorStaffAllocation.objects.select_for_update().get(
                    assignment=assignment,
                    state=VendorStaffAllocation.State.ALLOCATED,
                )
            except (TicketAssignment.DoesNotExist, VendorStaffAllocation.DoesNotExist) as error:
                raise TicketSubmissionConflict(
                    code="VENDOR_WORKER_ALLOCATION_UNAVAILABLE",
                    message="No active vendor worker allocation is available for this ticket.",
                    ticket=ticket,
                ) from error
            actor_persona = _vendor_worker_for_allocation(
                ticket=ticket,
                allocation=allocation,
                actor=actor,
                membership=membership,
            )
            worker_membership = VendorStaffMembership.objects.select_for_update().get(
                id=allocation.staff_membership_id,
                society_id=society_id,
            )
            if (
                worker_membership.role != VendorStaffMembership.Role.WORKER
                or not worker_membership.is_current()
                or worker_membership.contract_id != assignment.vendor_contract_id
            ):
                raise TicketSubmissionConflict(
                    code="VENDOR_WORKER_UNAVAILABLE",
                    message="The allocated vendor worker is unavailable.",
                    ticket=ticket,
                )
            if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
                raise TicketSubmissionConflict(
                    code="TICKET_WORKFLOW_CONFLICT",
                    message="Vendor worker acceptance is available only for service tickets.",
                    ticket=ticket,
                )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.ASSIGNED:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only assigned tickets can be accepted by a vendor worker.",
                    ticket=ticket,
                )
            accepted_at = timezone.now()
            if assignment.acceptance_deadline <= accepted_at:
                raise TicketSubmissionConflict(
                    code="ASSIGNMENT_ACCEPTANCE_EXPIRED",
                    message="The assignment acceptance deadline has passed.",
                    ticket=ticket,
                )
            sla_cycle = SLACycle.objects.select_for_update().get(
                ticket=ticket,
                ended_at__isnull=True,
            )

            assignment.state = TicketAssignment.State.ACCEPTED
            assignment.accepted_by = actor
            assignment.accepted_at = accepted_at
            assignment.save(update_fields=("state", "accepted_by", "accepted_at"))
            allocation.state = VendorStaffAllocation.State.ACCEPTED
            allocation.accepted_by = actor
            allocation.accepted_at = accepted_at
            allocation.save(update_fields=("state", "accepted_by", "accepted_at"))
            sla_cycle.acceptance_deadline = None
            sla_cycle.save(update_fields=("acceptance_deadline",))

            previous_status = ticket.status
            ticket.status = Ticket.Status.ACCEPTED
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))
            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_ASSIGNMENT_ACCEPTED,
                correlation_id=correlation_id,
                metadata={
                    "assignment_id": str(assignment.id),
                    "vendor_staff_allocation_id": str(allocation.id),
                    "staff_membership_id": str(worker_membership.id),
                },
            )
            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "assignment": {
                    "id": str(assignment.id),
                    "state": assignment.state,
                    "accepted_at": assignment.accepted_at.isoformat(),
                },
                "allocation": {
                    "id": str(allocation.id),
                    "state": allocation.state,
                    "accepted_at": allocation.accepted_at.isoformat(),
                },
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketVendorWorkerAcceptanceForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _vendor_dispatcher_for_worker_acceptance(*, ticket, assignment, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketVendorWorkerAcceptanceForbidden(
            "Membership does not belong to the actor and society."
        )
    if (
        not isinstance(membership, VendorStaffMembership)
        or membership.role != VendorStaffMembership.Role.DISPATCHER
        or not membership.is_current()
    ):
        raise TicketVendorWorkerAcceptanceForbidden(
            "Only an active vendor dispatcher can accept on a worker's behalf."
        )
    if (
        assignment.target_type != TicketAssignment.TargetType.VENDOR
        or assignment.vendor_contract_id != membership.contract_id
    ):
        raise TicketVendorWorkerAcceptanceForbidden(
            "Dispatcher membership does not match the vendor assignment."
        )
    return "vendor"


def accept_vendor_worker_allocation_on_behalf(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    reason,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        try:
            assignment = TicketAssignment.objects.get(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.VENDOR,
            )
            allocation = VendorStaffAllocation.objects.filter(
                assignment=assignment,
            ).order_by("-allocated_at").first()
            if allocation is None:
                raise VendorStaffAllocation.DoesNotExist
        except (TicketAssignment.DoesNotExist, VendorStaffAllocation.DoesNotExist) as error:
            raise TicketVendorWorkerAcceptanceForbidden(
                "No vendor worker allocation is available for this ticket."
            ) from error
        _vendor_dispatcher_for_worker_acceptance(
            ticket=ticket,
            assignment=assignment,
            actor=actor,
            membership=membership,
        )
    request_hash = _canonical_request_hash(
        ticket_id=ticket_id,
        expected_version=expected_version,
        reason=reason,
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            try:
                assignment = TicketAssignment.objects.select_for_update().get(
                    ticket=ticket,
                    target_type=TicketAssignment.TargetType.VENDOR,
                    state=TicketAssignment.State.OFFERED,
                )
                allocation = VendorStaffAllocation.objects.select_for_update().get(
                    assignment=assignment,
                    state=VendorStaffAllocation.State.ALLOCATED,
                )
            except (TicketAssignment.DoesNotExist, VendorStaffAllocation.DoesNotExist) as error:
                raise TicketSubmissionConflict(
                    code="VENDOR_WORKER_ALLOCATION_UNAVAILABLE",
                    message="No active vendor worker allocation is available for this ticket.",
                    ticket=ticket,
                ) from error
            actor_persona = _vendor_dispatcher_for_worker_acceptance(
                ticket=ticket,
                assignment=assignment,
                actor=actor,
                membership=membership,
            )
            worker_membership = VendorStaffMembership.objects.select_for_update().get(
                id=allocation.staff_membership_id,
                society_id=society_id,
            )
            if (
                worker_membership.role != VendorStaffMembership.Role.WORKER
                or not worker_membership.is_current()
                or worker_membership.contract_id != assignment.vendor_contract_id
            ):
                raise TicketSubmissionConflict(
                    code="VENDOR_WORKER_UNAVAILABLE",
                    message="The allocated vendor worker is unavailable.",
                    ticket=ticket,
                )
            if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
                raise TicketSubmissionConflict(
                    code="TICKET_WORKFLOW_CONFLICT",
                    message="Vendor worker acceptance is available only for service tickets.",
                    ticket=ticket,
                )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.ASSIGNED:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only assigned tickets can be accepted by a vendor dispatcher.",
                    ticket=ticket,
                )
            accepted_at = timezone.now()
            if assignment.acceptance_deadline <= accepted_at:
                raise TicketSubmissionConflict(
                    code="ASSIGNMENT_ACCEPTANCE_EXPIRED",
                    message="The assignment acceptance deadline has passed.",
                    ticket=ticket,
                )
            sla_cycle = SLACycle.objects.select_for_update().get(
                ticket=ticket,
                ended_at__isnull=True,
            )

            assignment.state = TicketAssignment.State.ACCEPTED
            assignment.accepted_by = actor
            assignment.accepted_at = accepted_at
            assignment.save(update_fields=("state", "accepted_by", "accepted_at"))
            allocation.state = VendorStaffAllocation.State.ACCEPTED
            allocation.accepted_by = actor
            allocation.accepted_at = accepted_at
            allocation.save(update_fields=("state", "accepted_by", "accepted_at"))
            sla_cycle.acceptance_deadline = None
            sla_cycle.save(update_fields=("acceptance_deadline",))

            previous_status = ticket.status
            ticket.status = Ticket.Status.ACCEPTED
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))
            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_ASSIGNMENT_ACCEPTED,
                reason=reason,
                correlation_id=correlation_id,
                metadata={
                    "assignment_id": str(assignment.id),
                    "vendor_staff_allocation_id": str(allocation.id),
                    "staff_membership_id": str(worker_membership.id),
                    "accepted_on_behalf": True,
                },
            )
            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "assignment": {
                    "id": str(assignment.id),
                    "state": assignment.state,
                    "accepted_at": assignment.accepted_at.isoformat(),
                },
                "allocation": {
                    "id": str(allocation.id),
                    "state": allocation.state,
                    "accepted_at": allocation.accepted_at.isoformat(),
                },
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketVendorWorkerAcceptanceForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _offered_in_house_assignment_for_technician(
    *, ticket, actor, membership, for_update=False, offered_only=True
):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketInHouseAssignmentResponseForbidden(
            "Membership does not belong to the actor and society."
        )
    if not isinstance(membership, TechnicianProfile) or not membership.is_current():
        raise TicketInHouseAssignmentResponseForbidden(
            "An active technician profile is required."
        )
    if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
        raise TicketInHouseAssignmentResponseForbidden(
            "Assignment responses are available only for service tickets."
        )
    assignments = TicketAssignment.objects.filter(
        society_id=ticket.society_id,
        ticket=ticket,
        target_type=TicketAssignment.TargetType.IN_HOUSE,
        technician=membership,
    )
    if offered_only:
        assignments = assignments.filter(state=TicketAssignment.State.OFFERED)
    if for_update:
        assignments = assignments.select_for_update(of=("self",))
    try:
        return assignments.get()
    except TicketAssignment.DoesNotExist as error:
        raise TicketInHouseAssignmentResponseForbidden(
            "No offered in-house assignment is available to this technician."
        ) from error


def _respond_to_in_house_assignment(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    idempotency_key,
    route_template,
    correlation_id,
    acceptance,
    rejection_reason="",
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _offered_in_house_assignment_for_technician(
            ticket=ticket,
            actor=actor,
            membership=membership,
            offered_only=False,
        )
    request_hash = _canonical_request_hash(
        ticket_id=ticket_id,
        expected_version=expected_version,
        acceptance=acceptance,
        rejection_reason=rejection_reason,
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            assignment = _offered_in_house_assignment_for_technician(
                ticket=ticket,
                actor=actor,
                membership=membership,
                for_update=True,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.ASSIGNED:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only assigned service tickets can receive an assignment response.",
                    ticket=ticket,
                )
            responded_at = timezone.now()
            if assignment.acceptance_deadline <= responded_at:
                raise TicketSubmissionConflict(
                    code="ASSIGNMENT_ACCEPTANCE_EXPIRED",
                    message="The assignment acceptance deadline has passed.",
                    ticket=ticket,
                )
            technician = TechnicianProfile.objects.select_for_update().get(
                id=assignment.technician_id,
                society_id=society_id,
            )
            sla_cycle = SLACycle.objects.select_for_update().select_related("snapshot").get(
                ticket=ticket,
                ended_at__isnull=True,
            )

            previous_status = ticket.status
            if acceptance:
                assignment.state = TicketAssignment.State.ACCEPTED
                assignment.accepted_by = actor
                assignment.accepted_at = responded_at
                assignment.save(update_fields=("state", "accepted_by", "accepted_at"))
                sla_cycle.acceptance_deadline = None
                sla_cycle.save(update_fields=("acceptance_deadline",))
                ticket.status = Ticket.Status.ACCEPTED
                event_type = TicketEvent.EventType.TICKET_ASSIGNMENT_ACCEPTED
                event_reason = ""
                response_assignment = {
                    "id": str(assignment.id),
                    "state": assignment.state,
                    "accepted_at": assignment.accepted_at.isoformat(),
                }
            else:
                if technician.current_active_tickets_count == 0:
                    raise TicketSubmissionConflict(
                        code="TECHNICIAN_CAPACITY_INCONSISTENT",
                        message="The assigned technician capacity requires reconciliation.",
                        ticket=ticket,
                    )
                assignment.state = TicketAssignment.State.ENDED
                assignment.ended_at = responded_at
                assignment.ended_reason = rejection_reason
                assignment.save(update_fields=("state", "ended_at", "ended_reason"))
                technician.current_active_tickets_count -= 1
                technician.save(update_fields=("current_active_tickets_count", "updated_at"))
                sla_cycle.assignment_failure_count += 1
                sla_cycle.assignee_rejection_count += 1
                sla_cycle.acceptance_deadline = None
                sla_cycle.save(
                    update_fields=(
                        "assignment_failure_count",
                        "assignee_rejection_count",
                        "acceptance_deadline",
                    )
                )
                ticket.status = (
                    Ticket.Status.SUPERVISOR_TRIAGE
                    if sla_cycle.assignment_failure_count
                    >= sla_cycle.snapshot.max_assignment_failures
                    else Ticket.Status.SUBMITTED
                )
                event_type = TicketEvent.EventType.TICKET_ASSIGNMENT_REJECTED
                event_reason = rejection_reason
                response_assignment = {
                    "id": str(assignment.id),
                    "state": assignment.state,
                    "ended_at": assignment.ended_at.isoformat(),
                    "ended_reason": assignment.ended_reason,
                }

            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))
            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona="technician",
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=event_type,
                reason=event_reason,
                correlation_id=correlation_id,
                metadata={
                    "assignment_id": str(assignment.id),
                    "technician_id": str(technician.id),
                },
            )
            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "assignment": response_assignment,
            }
            if not acceptance:
                response_body["assignment_failure_count"] = (
                    sla_cycle.assignment_failure_count
                )
                response_body["assignee_rejection_count"] = (
                    sla_cycle.assignee_rejection_count
                )
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketInHouseAssignmentResponseForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def accept_in_house_assignment(**kwargs):
    return _respond_to_in_house_assignment(acceptance=True, **kwargs)


def reject_in_house_assignment(*, reason, **kwargs):
    return _respond_to_in_house_assignment(
        acceptance=False,
        rejection_reason=reason,
        **kwargs,
    )


def _authorized_worker_for_start(*, ticket, actor, membership):
    """Authorize the actor to start work on an accepted service ticket.

    Returns (actor_persona, assignment, allocation_or_none).
    """
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketStartWorkForbidden(
            "Membership does not belong to the actor and society."
        )
    if not membership.is_current():
        raise TicketStartWorkForbidden("An active membership is required.")
    if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
        raise TicketStartWorkForbidden(
            "Starting work is available only for service tickets."
        )
    if isinstance(membership, TechnicianProfile):
        try:
            assignment = TicketAssignment.objects.get(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.IN_HOUSE,
                technician=membership,
                state=TicketAssignment.State.ACCEPTED,
            )
        except TicketAssignment.DoesNotExist as error:
            raise TicketStartWorkForbidden(
                "No accepted in-house assignment is available to this technician."
            ) from error
        return "technician", assignment, None
    if isinstance(membership, VendorStaffMembership):
        if membership.role != VendorStaffMembership.Role.WORKER:
            raise TicketStartWorkForbidden(
                "Only vendor workers can start work on a ticket."
            )
        try:
            assignment = TicketAssignment.objects.get(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.VENDOR,
                state=TicketAssignment.State.ACCEPTED,
            )
            allocation = VendorStaffAllocation.objects.get(
                assignment=assignment,
                staff_membership=membership,
                state=VendorStaffAllocation.State.ACCEPTED,
            )
        except (TicketAssignment.DoesNotExist, VendorStaffAllocation.DoesNotExist) as error:
            raise TicketStartWorkForbidden(
                "No accepted vendor worker allocation is available to this worker."
            ) from error
        return "vendor", assignment, allocation
    raise TicketStartWorkForbidden(
        "Only assigned technicians or named vendor workers can start work."
    )


def _authorized_worker_for_start_locked(*, ticket, actor, membership):
    """Same as _authorized_worker_for_start but with select_for_update locks."""
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketStartWorkForbidden(
            "Membership does not belong to the actor and society."
        )
    if not membership.is_current():
        raise TicketStartWorkForbidden("An active membership is required.")
    if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
        raise TicketStartWorkForbidden(
            "Starting work is available only for service tickets."
        )
    if isinstance(membership, TechnicianProfile):
        try:
            assignment = TicketAssignment.objects.select_for_update().get(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.IN_HOUSE,
                technician=membership,
                state=TicketAssignment.State.ACCEPTED,
            )
        except TicketAssignment.DoesNotExist as error:
            raise TicketStartWorkForbidden(
                "No accepted in-house assignment is available to this technician."
            ) from error
        return "technician", assignment, None
    if isinstance(membership, VendorStaffMembership):
        if membership.role != VendorStaffMembership.Role.WORKER:
            raise TicketStartWorkForbidden(
                "Only vendor workers can start work on a ticket."
            )
        try:
            assignment = TicketAssignment.objects.select_for_update().get(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.VENDOR,
                state=TicketAssignment.State.ACCEPTED,
            )
            allocation = VendorStaffAllocation.objects.select_for_update().get(
                assignment=assignment,
                staff_membership=membership,
                state=VendorStaffAllocation.State.ACCEPTED,
            )
        except (TicketAssignment.DoesNotExist, VendorStaffAllocation.DoesNotExist) as error:
            raise TicketStartWorkForbidden(
                "No accepted vendor worker allocation is available to this worker."
            ) from error
        return "vendor", assignment, allocation
    raise TicketStartWorkForbidden(
        "Only assigned technicians or named vendor workers can start work."
    )


def start_ticket_work(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _authorized_worker_for_start(
            ticket=ticket,
            actor=actor,
            membership=membership,
        )
    request_hash = _canonical_request_hash(
        ticket_id=ticket_id,
        expected_version=expected_version,
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            actor_persona, assignment, allocation = _authorized_worker_for_start_locked(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.ACCEPTED:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only accepted service tickets can start work.",
                    ticket=ticket,
                )

            previous_status = ticket.status
            ticket.status = Ticket.Status.IN_PROGRESS
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))
            metadata = {
                "assignment_id": str(assignment.id),
            }
            if allocation is not None:
                metadata["vendor_staff_allocation_id"] = str(allocation.id)
                metadata["staff_membership_id"] = str(allocation.staff_membership_id)
            else:
                metadata["technician_id"] = str(assignment.technician_id)
            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_WORK_STARTED,
                correlation_id=correlation_id,
                metadata=metadata,
            )
            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "assignment": {
                    "id": str(assignment.id),
                    "state": assignment.state,
                },
            }
            if allocation is not None:
                response_body["allocation"] = {
                    "id": str(allocation.id),
                    "state": allocation.state,
                }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketStartWorkForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _vendor_dispatcher_for_rejection(*, ticket, assignment, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketVendorAssignmentRejectionForbidden(
            "Membership does not belong to the actor and society."
        )
    if not isinstance(membership, VendorStaffMembership) or not membership.is_current():
        raise TicketVendorAssignmentRejectionForbidden(
            "An active vendor dispatcher membership is required."
        )
    if membership.role != VendorStaffMembership.Role.DISPATCHER:
        raise TicketVendorAssignmentRejectionForbidden(
            "Only vendor dispatchers can reject vendor assignments."
        )
    if (
        assignment.target_type != TicketAssignment.TargetType.VENDOR
        or assignment.vendor_contract_id != membership.contract_id
    ):
        raise TicketVendorAssignmentRejectionForbidden(
            "Dispatcher membership does not match the vendor assignment."
        )
    return "vendor"


def reject_vendor_assignment(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    reason,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        try:
            assignment = TicketAssignment.objects.select_related("vendor_contract").get(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.VENDOR,
            )
        except TicketAssignment.DoesNotExist as error:
            raise TicketVendorAssignmentRejectionForbidden(
                "No vendor assignment is available for this ticket."
            ) from error
        _vendor_dispatcher_for_rejection(
            ticket=ticket,
            assignment=assignment,
            actor=actor,
            membership=membership,
        )
    request_hash = _canonical_request_hash(
        ticket_id=ticket_id,
        expected_version=expected_version,
        reason=reason,
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            try:
                assignment = TicketAssignment.objects.select_for_update().get(
                    ticket=ticket,
                    target_type=TicketAssignment.TargetType.VENDOR,
                    state=TicketAssignment.State.OFFERED,
                )
                active_allocation = VendorStaffAllocation.objects.select_for_update().get(
                    assignment=assignment,
                    state=VendorStaffAllocation.State.ALLOCATED,
                )
            except (TicketAssignment.DoesNotExist, VendorStaffAllocation.DoesNotExist) as error:
                raise TicketSubmissionConflict(
                    code="VENDOR_ASSIGNMENT_UNAVAILABLE",
                    message="No offered vendor assignment with an active allocation is available.",
                    ticket=ticket,
                ) from error
            actor_persona = _vendor_dispatcher_for_rejection(
                ticket=ticket,
                assignment=assignment,
                actor=actor,
                membership=membership,
            )
            if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
                raise TicketSubmissionConflict(
                    code="TICKET_WORKFLOW_CONFLICT",
                    message="Vendor assignment rejection is available only for service tickets.",
                    ticket=ticket,
                )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.ASSIGNED:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only assigned service tickets can have their vendor assignment rejected.",
                    ticket=ticket,
                )

            rejected_at = timezone.now()

            # End the allocation
            active_allocation.state = VendorStaffAllocation.State.ENDED
            active_allocation.ended_at = rejected_at
            active_allocation.ended_reason = reason
            active_allocation.save(
                update_fields=("state", "ended_at", "ended_reason")
            )
            # End the assignment
            assignment.state = TicketAssignment.State.ENDED
            assignment.ended_at = rejected_at
            assignment.ended_reason = reason
            assignment.save(update_fields=("state", "ended_at", "ended_reason"))

            # Decrement vendor contract capacity
            vendor_contract = VendorContract.objects.select_for_update().get(
                id=assignment.vendor_contract_id,
                society_id=society_id,
            )
            if vendor_contract.current_active_tickets_count == 0:
                raise TicketSubmissionConflict(
                    code="VENDOR_CAPACITY_INCONSISTENT",
                    message="The vendor contract capacity requires reconciliation.",
                    ticket=ticket,
                )
            vendor_contract.current_active_tickets_count -= 1
            vendor_contract.save(
                update_fields=("current_active_tickets_count", "updated_at")
            )

            # Update SLA counters
            sla_cycle = SLACycle.objects.select_for_update().select_related("snapshot").get(
                ticket=ticket,
                ended_at__isnull=True,
            )
            sla_cycle.assignment_failure_count += 1
            sla_cycle.assignee_rejection_count += 1
            sla_cycle.acceptance_deadline = None
            sla_cycle.save(
                update_fields=(
                    "assignment_failure_count",
                    "assignee_rejection_count",
                    "acceptance_deadline",
                )
            )

            # Determine next status based on threshold
            previous_status = ticket.status
            ticket.status = (
                Ticket.Status.SUPERVISOR_TRIAGE
                if sla_cycle.assignment_failure_count
                >= sla_cycle.snapshot.max_assignment_failures
                else Ticket.Status.SUBMITTED
            )
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))
            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_ASSIGNMENT_REJECTED,
                reason=reason,
                correlation_id=correlation_id,
                metadata={
                    "assignment_id": str(assignment.id),
                    "vendor_contract_id": str(vendor_contract.id),
                    "vendor_staff_allocation_id": str(active_allocation.id),
                    "staff_membership_id": str(active_allocation.staff_membership_id),
                },
            )
            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "assignment": {
                    "id": str(assignment.id),
                    "state": assignment.state,
                    "ended_at": assignment.ended_at.isoformat(),
                    "ended_reason": assignment.ended_reason,
                },
                "assignment_failure_count": sla_cycle.assignment_failure_count,
                "assignee_rejection_count": sla_cycle.assignee_rejection_count,
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketVendorAssignmentRejectionForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _active_governance_reviewer(*, ticket, actor, membership, for_update=False):
    try:
        actor_persona = _persona_for_governance_reviewer(
            ticket=ticket,
            actor=actor,
            membership=membership,
        )
    except TicketGovernanceReviewForbidden as error:
        raise TicketGovernanceDiscussionForbidden(str(error)) from error
    assignments = GovernanceReviewAssignment.objects.filter(
        society_id=ticket.society_id,
        ticket=ticket,
        reviewer=actor,
        is_active=True,
    )
    if for_update:
        assignments = assignments.select_for_update()
    try:
        assignment = assignments.get()
    except GovernanceReviewAssignment.DoesNotExist as error:
        raise TicketGovernanceDiscussionForbidden(
            "Only the assigned governance reviewer can open discussion."
        ) from error
    return actor_persona, assignment


def open_governance_discussion(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    purpose,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _active_governance_reviewer(
            ticket=ticket,
            actor=actor,
            membership=membership,
        )
    request_hash = _canonical_request_hash(
        ticket_id=ticket_id,
        expected_version=expected_version,
        purpose=purpose,
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            actor_persona, assignment = _active_governance_reviewer(
                ticket=ticket,
                actor=actor,
                membership=membership,
                for_update=True,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.UNDER_REVIEW:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only governance tickets under review can open discussion.",
                    ticket=ticket,
                )

            discussion = GovernanceDiscussion.objects.create(
                society_id=society_id,
                ticket=ticket,
                opened_by=actor,
                purpose=purpose,
            )
            participant_ids = sorted({ticket.creator_id, assignment.reviewer_id})
            GovernanceDiscussionParticipant.objects.bulk_create(
                [
                    GovernanceDiscussionParticipant(
                        society_id=society_id,
                        discussion=discussion,
                        user_id=participant_id,
                    )
                    for participant_id in participant_ids
                ]
            )
            previous_status = ticket.status
            ticket.status = Ticket.Status.IN_DISCUSSION
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))
            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.GOVERNANCE_DISCUSSION_OPENED,
                reason=purpose,
                correlation_id=correlation_id,
                metadata={
                    "discussion_id": str(discussion.id),
                    "participant_ids": [str(participant_id) for participant_id in participant_ids],
                },
            )
            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "discussion": {
                    "id": str(discussion.id),
                    "purpose": discussion.purpose,
                    "participant_ids": [str(participant_id) for participant_id in participant_ids],
                },
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketGovernanceDiscussionForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _governance_action_authorization(*, ticket, actor, membership, for_update=False):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketGovernanceActionForbidden(
            "Membership does not belong to the actor and society."
        )
    if not membership.is_current():
        raise TicketGovernanceActionForbidden("An active membership is required.")
    if ticket.workflow_type != Ticket.WorkflowType.GOVERNANCE:
        raise TicketGovernanceActionForbidden(
            "Governance actions are available only for governance tickets."
        )
    if not isinstance(membership, StaffMembership) or membership.role != (
        StaffMembership.Role.FACILITY_MANAGER
    ):
        raise TicketGovernanceActionForbidden(
            "Only the assigned reviewer or a facility manager can record action."
        )
    assignments = GovernanceReviewAssignment.objects.filter(
        society_id=ticket.society_id,
        ticket=ticket,
        is_active=True,
    )
    if for_update:
        assignments = assignments.select_for_update()
    try:
        assignment = assignments.get()
    except GovernanceReviewAssignment.DoesNotExist as error:
        raise TicketGovernanceActionForbidden(
            "An active governance review assignment is required to record action."
        ) from error
    return "staff", assignment


def record_governance_action(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    summary,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _governance_action_authorization(
            ticket=ticket,
            actor=actor,
            membership=membership,
        )
    request_hash = _canonical_request_hash(
        ticket_id=ticket_id,
        expected_version=expected_version,
        summary=summary,
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            actor_persona, assignment = _governance_action_authorization(
                ticket=ticket,
                actor=actor,
                membership=membership,
                for_update=True,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status not in {
                Ticket.Status.UNDER_REVIEW,
                Ticket.Status.IN_DISCUSSION,
            }:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only governance tickets under review or discussion can record action.",
                    ticket=ticket,
                )

            action_record = GovernanceActionRecord.objects.create(
                society_id=society_id,
                ticket=ticket,
                recorded_by=actor,
                summary=summary,
            )
            previous_status = ticket.status
            ticket.status = Ticket.Status.ACTION_TAKEN
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))
            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.GOVERNANCE_ACTION_RECORDED,
                reason=summary,
                correlation_id=correlation_id,
                metadata={
                    "action_record_id": str(action_record.id),
                    "evidence_policy": action_record.evidence_policy,
                    "reviewer_id": str(assignment.reviewer_id),
                },
            )
            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "action_record": {
                    "id": str(action_record.id),
                    "recorded_by_id": str(action_record.recorded_by_id),
                    "summary": action_record.summary,
                    "evidence_policy": action_record.evidence_policy,
                    "recorded_at": action_record.recorded_at.isoformat(),
                },
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketGovernanceActionForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _persona_for_submitter(*, ticket, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketSubmissionForbidden("Membership does not belong to the actor and society.")
    if not membership.is_current():
        raise TicketSubmissionForbidden("An active membership is required.")
    if isinstance(membership, UnitOccupancy):
        if actor.id != ticket.creator_id:
            raise TicketSubmissionForbidden("Residents may submit only their own drafts.")
        if ticket.workflow_type == Ticket.WorkflowType.SERVICE:
            if ticket.unit_id is not None and membership.unit_id != ticket.unit_id:
                raise TicketSubmissionForbidden("Residents may submit only for their own unit.")
        return "resident"
    if isinstance(membership, StaffMembership):
        if membership.role not in {
            StaffMembership.Role.FACILITY_MANAGER,
            StaffMembership.Role.HELPDESK_OPERATOR,
        }:
            raise TicketSubmissionForbidden("This staff role cannot submit tickets.")
        return "staff"
    if isinstance(membership, CommitteeMembership):
        if ticket.workflow_type != Ticket.WorkflowType.GOVERNANCE:
            raise TicketSubmissionForbidden(
                "Committee members may submit governance tickets only."
            )
        return "committee"
    raise TicketSubmissionForbidden("This tenant persona cannot submit tickets.")


def _preflight_authorize(*, society_id, ticket_id, actor, membership):
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.select_related(
            "society",
            "category",
            "subcategory",
        ).get(id=ticket_id)
        return _persona_for_submitter(
            ticket=ticket,
            actor=actor,
            membership=membership,
        )


def _allocate_ticket_number(*, ticket, submitted_at):
    calendar_year = submitted_at.astimezone(ZoneInfo(ticket.society.timezone)).year
    sequence, _ = TicketNumberSequence.objects.get_or_create(
        society=ticket.society,
        calendar_year=calendar_year,
    )
    sequence = TicketNumberSequence.objects.select_for_update().get(id=sequence.id)
    sequence.current_value += 1
    sequence.save(update_fields=("current_value", "updated_at"))
    ticket_number = (
        f"{ticket.society.registration_code}-{calendar_year}-"
        f"{sequence.current_value:06d}"
    )
    if len(ticket_number) > Ticket._meta.get_field("ticket_number").max_length:
        raise TicketSubmissionConflict(
            code="TICKET_NUMBER_PREFIX_TOO_LONG",
            message="The society registration code is too long for ticket numbering.",
            ticket=ticket,
        )
    return ticket_number


def submit_ticket(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    idempotency_key,
    route_template,
    correlation_id,
    create_sla_cycle: SLACycleCreator,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    actor_persona = _preflight_authorize(
        society_id=society_id,
        ticket_id=ticket_id,
        actor=actor,
        membership=membership,
    )
    request_hash = _canonical_request_hash(
        ticket_id=ticket_id,
        expected_version=expected_version,
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = (
                Ticket.objects.select_for_update()
                .select_related("society", "category", "subcategory")
                .get(id=ticket_id)
            )
            actor_persona = _persona_for_submitter(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.DRAFT:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only draft tickets can be submitted.",
                    ticket=ticket,
                )
            if not ticket.category.is_active or not ticket.subcategory.is_active:
                raise TicketSubmissionConflict(
                    code="TICKET_CATEGORY_INACTIVE",
                    message="The ticket category and subcategory must be active.",
                    ticket=ticket,
                )

            submitted_at = timezone.now()
            sla_cycle_id = create_sla_cycle(
                ticket=ticket,
                submitted_at=submitted_at,
            )
            if not isinstance(sla_cycle_id, uuid.UUID):
                raise TicketSubmissionConflict(
                    code="SLA_CYCLE_REQUIRED",
                    message="Submission requires a persisted SLA cycle identifier.",
                    ticket=ticket,
                )
            previous_status = ticket.status
            ticket.ticket_number = _allocate_ticket_number(
                ticket=ticket,
                submitted_at=submitted_at,
            )
            ticket.status = Ticket.Status.SUBMITTED
            ticket.submitted_at = submitted_at
            ticket.state_version += 1
            ticket.save(
                update_fields=(
                    "ticket_number",
                    "status",
                    "submitted_at",
                    "state_version",
                    "updated_at",
                )
            )
            event = TicketEvent.objects.create(
                society=ticket.society,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_SUBMITTED,
                correlation_id=correlation_id,
                metadata={"sla_cycle_id": str(sla_cycle_id)},
            )
            body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "sla_cycle_id": str(sla_cycle_id),
            }
            headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=body,
                response_headers=headers,
            )
            return TicketCommandResult(200, body, headers)
    except TicketSubmissionForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )


def _authorized_worker_for_completion(*, ticket, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketCompletionRequestForbidden(
            "Membership does not belong to the actor and society."
        )
    if not membership.is_current():
        raise TicketCompletionRequestForbidden("An active membership is required.")
    if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
        raise TicketCompletionRequestForbidden(
            "Requesting completion is available only for service tickets."
        )
    if isinstance(membership, TechnicianProfile):
        try:
            assignment = TicketAssignment.objects.get(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.IN_HOUSE,
                technician=membership,
                state=TicketAssignment.State.ACCEPTED,
            )
        except TicketAssignment.DoesNotExist as error:
            raise TicketCompletionRequestForbidden(
                "No in-house assignment is available to this technician."
            ) from error
        return "technician", assignment, None
    if isinstance(membership, VendorStaffMembership):
        if membership.role != VendorStaffMembership.Role.WORKER:
            raise TicketCompletionRequestForbidden(
                "Only vendor workers can request completion on a ticket."
            )
        try:
            assignment = TicketAssignment.objects.get(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.VENDOR,
                state=TicketAssignment.State.ACCEPTED,
            )
            allocation = VendorStaffAllocation.objects.get(
                assignment=assignment,
                staff_membership=membership,
                state=VendorStaffAllocation.State.ACCEPTED,
            )
        except (TicketAssignment.DoesNotExist, VendorStaffAllocation.DoesNotExist) as error:
            raise TicketCompletionRequestForbidden(
                "No vendor worker allocation is available to this worker."
            ) from error
        return "vendor", assignment, allocation
    raise TicketCompletionRequestForbidden(
        "Only assigned technicians or named vendor workers can request completion."
    )


def _authorized_worker_for_completion_locked(*, ticket, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketCompletionRequestForbidden(
            "Membership does not belong to the actor and society."
        )
    if not membership.is_current():
        raise TicketCompletionRequestForbidden("An active membership is required.")
    if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
        raise TicketCompletionRequestForbidden(
            "Requesting completion is available only for service tickets."
        )
    if isinstance(membership, TechnicianProfile):
        try:
            assignment = TicketAssignment.objects.select_for_update().get(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.IN_HOUSE,
                technician=membership,
                state=TicketAssignment.State.ACCEPTED,
            )
        except TicketAssignment.DoesNotExist as error:
            raise TicketSubmissionConflict(
                code="ASSIGNMENT_UNAVAILABLE",
                message="No accepted in-house assignment is available for this technician.",
                ticket=ticket,
            ) from error
        return "technician", assignment, None
    if isinstance(membership, VendorStaffMembership):
        if membership.role != VendorStaffMembership.Role.WORKER:
            raise TicketCompletionRequestForbidden(
                "Only vendor workers can request completion on a ticket."
            )
        try:
            assignment = TicketAssignment.objects.select_for_update().get(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.VENDOR,
                state=TicketAssignment.State.ACCEPTED,
            )
            allocation = VendorStaffAllocation.objects.select_for_update().get(
                assignment=assignment,
                staff_membership=membership,
                state=VendorStaffAllocation.State.ACCEPTED,
            )
        except (TicketAssignment.DoesNotExist, VendorStaffAllocation.DoesNotExist) as error:
            raise TicketSubmissionConflict(
                code="VENDOR_WORKER_ALLOCATION_UNAVAILABLE",
                message="No accepted vendor worker allocation is available for this worker.",
                ticket=ticket,
            ) from error
        return "vendor", assignment, allocation
    raise TicketCompletionRequestForbidden(
        "Only assigned technicians or named vendor workers can request completion."
    )


def _completion_notification_recipient(*, society_id, ticket):
    instant = timezone.now()
    recipient = User.objects.select_for_update().get(id=ticket.creator_id)
    if (
        not recipient.is_active
        or not recipient.email
        or recipient.email_verified_at is None
    ):
        raise TicketCompletionRequestForbidden(
            "The ticket creator must be an active resident with a verified email address."
        )
    has_active_occupancy = (
        UnitOccupancy.objects.select_for_update()
        .filter(
            society_id=society_id,
            user_id=recipient.id,
            is_active=True,
            starts_at__lte=instant,
        )
        .filter(dj_models.Q(ends_at__isnull=True) | dj_models.Q(ends_at__gt=instant))
        .exists()
    )
    if not has_active_occupancy:
        raise TicketCompletionRequestForbidden(
            "The ticket creator must be an active resident with a verified email address."
        )
    return recipient


def request_service_ticket_completion(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    work_notes,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    if not work_notes or not work_notes.strip():
        raise ValueError("Non-empty work notes are required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _authorized_worker_for_completion(ticket=ticket, actor=actor, membership=membership)
    request_hash = _canonical_payload_hash(
        {
            "expected_version": expected_version,
            "ticket_id": str(ticket_id),
            "work_notes": work_notes.strip(),
        }
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    capsule_name = ""
    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            actor_persona, assignment, allocation = _authorized_worker_for_completion_locked(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.IN_PROGRESS:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Completion can only be requested for tickets currently in progress.",
                    ticket=ticket,
                )

            otp_code = f"{secrets.randbelow(1_000_000):06d}"
            expires_at = timezone.now() + timedelta(minutes=10)
            challenge_id = uuid.uuid4()
            _completion_notification_recipient(society_id=society_id, ticket=ticket)
            capsule_name = store_completion_otp_capsule(
                challenge_id=challenge_id,
                otp_code=otp_code,
                expires_at=expires_at,
            )

            challenge = TicketCompletionChallenge.objects.create(
                id=challenge_id,
                society_id=society_id,
                ticket=ticket,
                assignment=assignment,
                requested_by=actor,
                worker_notes=work_notes.strip(),
                otp_hash=make_password(otp_code),
                delivery_capsule_name=capsule_name,
                expires_at=expires_at,
            )

            previous_status = ticket.status
            ticket.status = Ticket.Status.PENDING_RESIDENT_CONFIRMATION
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))

            event_metadata = {
                "assignment_id": str(assignment.id),
                "challenge_id": str(challenge.id),
            }
            if allocation is not None:
                event_metadata["vendor_staff_allocation_id"] = str(allocation.id)
                event_metadata["staff_membership_id"] = str(allocation.staff_membership_id)
            if assignment.technician_id is not None:
                event_metadata["technician_id"] = str(assignment.technician_id)

            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_COMPLETION_REQUESTED,
                reason=work_notes.strip(),
                correlation_id=correlation_id,
                metadata=event_metadata,
            )
            TicketOutboxEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                ticket_event=event,
                completion_challenge=challenge,
                event_type=(
                    TicketOutboxEvent.EventType.SERVICE_COMPLETION_NOTIFICATION_REQUESTED
                ),
                payload={
                    "challenge_id": str(challenge.id),
                    "correlation_id": str(correlation_id),
                },
            )

            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "challenge_id": str(challenge.id),
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketCompletionRequestForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        if capsule_name:
            try:
                delete_completion_otp_capsule(capsule_name=capsule_name)
            except CompletionOtpCapsuleUnavailable:
                pass
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _persona_for_completion_verifier(*, ticket, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketCompletionVerificationForbidden(
            "Membership does not belong to the actor and society."
        )
    if not membership.is_current():
        raise TicketCompletionVerificationForbidden("An active membership is required.")
    if isinstance(membership, UnitOccupancy):
        if (
            ticket.workflow_type == Ticket.WorkflowType.SERVICE
            and ticket.unit_id is not None
            and ticket.unit_id != membership.unit_id
            and ticket.creator_id != actor.id
        ):
            raise TicketCompletionVerificationForbidden(
                "Residents may verify completion only for their own unit or created tickets."
            )
        return "resident"
    raise TicketCompletionVerificationForbidden(
        "Only residents can verify ticket completion with OTP."
    )


def verify_service_ticket_completion(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    otp,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    clean_otp = (otp or "").strip()
    if not clean_otp:
        raise ValueError("A valid OTP is required.")
    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _persona_for_completion_verifier(ticket=ticket, actor=actor, membership=membership)
    request_hash = _canonical_payload_hash(
        {
            "expected_version": expected_version,
            "otp": clean_otp,
            "ticket_id": str(ticket_id),
        }
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            actor_persona = _persona_for_completion_verifier(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.PENDING_RESIDENT_CONFIRMATION:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Verification can only be performed when the ticket is pending resident confirmation.",
                    ticket=ticket,
                )

            challenge = (
                TicketCompletionChallenge.objects.select_for_update()
                .filter(ticket=ticket, is_consumed=False)
                .order_by("-created_at")
                .first()
            )
            if challenge is None:
                raise TicketSubmissionConflict(
                    code="COMPLETION_CHALLENGE_NOT_FOUND",
                    message="No active completion challenge was found for this ticket.",
                    ticket=ticket,
                )

            if challenge.expires_at <= timezone.now():
                raise TicketSubmissionConflict(
                    code="OTP_EXPIRED",
                    message="The completion OTP has expired. Please request a new completion from the technician.",
                    ticket=ticket,
                )

            if challenge.attempts_count >= challenge.max_attempts:
                raise TicketSubmissionConflict(
                    code="OTP_MAX_ATTEMPTS_EXCEEDED",
                    message="Maximum OTP verification attempts exceeded. Please request a new completion from the technician.",
                    ticket=ticket,
                )

            if not check_password(clean_otp, challenge.otp_hash):
                challenge.attempts_count += 1
                challenge.save(update_fields=("attempts_count", "updated_at"))
                is_max = challenge.attempts_count >= challenge.max_attempts
                conflict_code = (
                    "OTP_MAX_ATTEMPTS_EXCEEDED"
                    if is_max
                    else "INVALID_COMPLETION_OTP"
                )
                conflict_msg = (
                    "Maximum OTP verification attempts exceeded. Please request a new completion from the technician."
                    if is_max
                    else "The provided completion OTP is invalid."
                )
                return _complete_conflict(
                    society_id=society_id,
                    record_id=claim.record_id,
                    conflict=TicketSubmissionConflict(
                        code=conflict_code,
                        message=conflict_msg,
                        ticket=ticket,
                    ),
                    correlation_id=correlation_id,
                )

            resolved_at = timezone.now()
            challenge.is_consumed = True
            challenge.consumed_at = resolved_at
            challenge.consumed_by = actor
            challenge.save(update_fields=("is_consumed", "consumed_at", "consumed_by", "updated_at"))

            event_metadata = {"challenge_id": str(challenge.id)}
            active_assignment = (
                TicketAssignment.objects.select_for_update()
                .filter(ticket=ticket)
                .exclude(state=TicketAssignment.State.ENDED)
                .first()
            )
            if active_assignment is not None:
                active_assignment.state = TicketAssignment.State.ENDED
                active_assignment.ended_at = resolved_at
                active_assignment.ended_reason = "Completed by resident confirmation"
                active_assignment.save(
                    update_fields=("state", "ended_at", "ended_reason")
                )
                event_metadata["assignment_id"] = str(active_assignment.id)
                if active_assignment.target_type == TicketAssignment.TargetType.IN_HOUSE:
                    technician = TechnicianProfile.objects.select_for_update().get(
                        id=active_assignment.technician_id,
                        society_id=society_id,
                    )
                    if technician.current_active_tickets_count > 0:
                        technician.current_active_tickets_count -= 1
                        technician.save(
                            update_fields=("current_active_tickets_count", "updated_at")
                        )
                    event_metadata["technician_id"] = str(technician.id)
                elif active_assignment.target_type == TicketAssignment.TargetType.VENDOR:
                    vendor_contract = VendorContract.objects.select_for_update().get(
                        id=active_assignment.vendor_contract_id,
                        society_id=society_id,
                    )
                    if vendor_contract.current_active_tickets_count > 0:
                        vendor_contract.current_active_tickets_count -= 1
                        vendor_contract.save(
                            update_fields=("current_active_tickets_count", "updated_at")
                        )
                    event_metadata["vendor_contract_id"] = str(vendor_contract.id)
                    active_allocation = (
                        VendorStaffAllocation.objects.select_for_update()
                        .filter(assignment=active_assignment)
                        .exclude(state=VendorStaffAllocation.State.ENDED)
                        .first()
                    )
                    if active_allocation is not None:
                        active_allocation.state = VendorStaffAllocation.State.ENDED
                        active_allocation.ended_at = resolved_at
                        active_allocation.ended_reason = "Completed by resident confirmation"
                        active_allocation.save(
                            update_fields=("state", "ended_at", "ended_reason")
                        )
                        event_metadata["vendor_staff_allocation_id"] = str(
                            active_allocation.id
                        )
                        event_metadata["staff_membership_id"] = str(
                            active_allocation.staff_membership_id
                        )

            sla_cycle = SLACycle.objects.select_for_update().get(
                ticket=ticket,
                ended_at__isnull=True,
            )
            sla_cycle.ended_at = resolved_at
            sla_cycle.outcome = SLACycle.Outcome.RESOLVED
            sla_cycle.save(update_fields=("ended_at", "outcome"))

            previous_status = ticket.status
            ticket.status = Ticket.Status.RESOLVED
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))

            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_RESOLVED,
                reason="Work verified and confirmed by resident OTP.",
                correlation_id=correlation_id,
                metadata=event_metadata,
            )

            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketCompletionVerificationForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _authorized_worker_for_estimate(*, ticket, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketEstimateSubmissionForbidden(
            "Membership does not belong to the actor and society."
        )
    if not membership.is_current():
        raise TicketEstimateSubmissionForbidden("An active membership is required.")
    if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
        raise TicketEstimateSubmissionForbidden(
            "Material estimates are available only for service tickets."
        )
    if isinstance(membership, TechnicianProfile):
        try:
            assignment = TicketAssignment.objects.select_for_update().get(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.IN_HOUSE,
                technician=membership,
                state=TicketAssignment.State.ACCEPTED,
            )
        except TicketAssignment.DoesNotExist as error:
            raise TicketEstimateSubmissionForbidden(
                "No accepted in-house assignment is available to this technician."
            ) from error
        return "technician", assignment, None
    if isinstance(membership, VendorStaffMembership):
        if membership.role != VendorStaffMembership.Role.WORKER:
            raise TicketEstimateSubmissionForbidden(
                "Only vendor workers can submit material estimates."
            )
        try:
            assignment = TicketAssignment.objects.select_for_update().get(
                ticket=ticket,
                target_type=TicketAssignment.TargetType.VENDOR,
                state=TicketAssignment.State.ACCEPTED,
            )
            allocation = VendorStaffAllocation.objects.select_for_update().get(
                assignment=assignment,
                staff_membership=membership,
                state=VendorStaffAllocation.State.ACCEPTED,
            )
        except (TicketAssignment.DoesNotExist, VendorStaffAllocation.DoesNotExist) as error:
            raise TicketEstimateSubmissionForbidden(
                "No accepted vendor worker allocation is available to this worker."
            ) from error
        return "vendor", assignment, allocation
    raise TicketEstimateSubmissionForbidden(
        "Only the current assigned worker can submit material estimates."
    )


def _persona_for_estimate_approver(*, ticket, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketEstimateDecisionForbidden(
            "Membership does not belong to the actor and society."
        )
    if not membership.is_current():
        raise TicketEstimateDecisionForbidden("An active membership is required.")
    if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
        raise TicketEstimateDecisionForbidden(
            "Material estimate decisions are available only for service tickets."
        )
    if ticket.category.cost_responsibility == TicketCategory.CostResponsibility.RESIDENT_UNIT:
        if isinstance(membership, UnitOccupancy):
            if ticket.unit_id is not None and ticket.unit_id != membership.unit_id and ticket.creator_id != actor.id:
                raise TicketEstimateDecisionForbidden(
                    "Residents may decide estimates only for their own unit or created tickets."
                )
            if not membership.can_approve_costs:
                raise TicketEstimateDecisionForbidden(
                    "Occupant lacks permission to approve costs for this unit."
                )
            return "resident"
        raise TicketEstimateDecisionForbidden(
            "Cost approval for resident-unit tickets requires an authorized resident."
        )
    if ticket.category.cost_responsibility == TicketCategory.CostResponsibility.SOCIETY:
        if isinstance(membership, StaffMembership) and membership.role == StaffMembership.Role.FACILITY_MANAGER:
            return "staff"
        if isinstance(membership, CommitteeMembership) and membership.can_approve_costs:
            return "committee"
        raise TicketEstimateDecisionForbidden(
            "Society cost approval requires a facility manager or authorized committee member."
        )
    raise TicketEstimateDecisionForbidden("Estimates are not permitted for this cost responsibility.")


def submit_ticket_estimate(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    items,
    tax_amount=Decimal("0.00"),
    notes="",
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    if not items or not isinstance(items, list):
        raise ValueError("A non-empty list of estimate line items is required.")

    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _authorized_worker_for_estimate(ticket=ticket, actor=actor, membership=membership)

    request_hash = _canonical_payload_hash(
        {
            "expected_version": expected_version,
            "items": [
                {
                    "description": i["description"].strip(),
                    "quantity": str(i["quantity"]),
                    "unit_cost": str(i["unit_cost"]),
                }
                for i in items
            ],
            "notes": (notes or "").strip(),
            "tax_amount": str(tax_amount),
            "ticket_id": str(ticket_id),
        }
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            actor_persona, assignment, allocation = _authorized_worker_for_estimate(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.IN_PROGRESS:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Estimates can only be submitted for tickets currently in progress.",
                    ticket=ticket,
                )
            if ticket.category.cost_responsibility == TicketCategory.CostResponsibility.NO_CHARGE:
                raise TicketSubmissionConflict(
                    code="ESTIMATES_NOT_PERMITTED",
                    message="Estimates are not permitted for categories with no charge.",
                    ticket=ticket,
                )
            if TicketEstimate.objects.filter(ticket=ticket, status=TicketEstimate.Status.SUBMITTED).exists():
                raise TicketSubmissionConflict(
                    code="ESTIMATE_ALREADY_PENDING",
                    message="An estimate is already pending approval for this ticket.",
                    ticket=ticket,
                )

            # Validate items & calculate totals
            subtotal = Decimal("0.00")
            parsed_items = []
            for item_data in items:
                desc = item_data.get("description", "").strip()
                if not desc:
                    raise ValueError("Each line item must have a description.")
                qty = Decimal(str(item_data.get("quantity", 0))).quantize(Decimal("0.01"))
                unit_cost = Decimal(str(item_data.get("unit_cost", 0))).quantize(Decimal("0.01"))
                if qty <= Decimal("0.00") or unit_cost <= Decimal("0.00"):
                    raise ValueError("Quantity and unit cost must be strictly positive.")
                total_cost = (qty * unit_cost).quantize(Decimal("0.01"))
                subtotal = (subtotal + total_cost).quantize(Decimal("0.01"))
                parsed_items.append((desc, qty, unit_cost, total_cost))

            tax = Decimal(str(tax_amount or 0)).quantize(Decimal("0.01"))
            if tax < Decimal("0.00"):
                raise ValueError("Tax amount cannot be negative.")
            total = (subtotal + tax).quantize(Decimal("0.01"))

            latest_version = (
                TicketEstimate.objects.filter(ticket=ticket).aggregate(
                    m=dj_models.Max("version")
                )["m"]
                or 0
            )
            next_version = latest_version + 1

            estimate = TicketEstimate.objects.create(
                society_id=society_id,
                ticket=ticket,
                assignment=assignment,
                created_by=actor,
                version=next_version,
                status=TicketEstimate.Status.SUBMITTED,
                cost_responsibility=ticket.category.cost_responsibility,
                subtotal_amount=subtotal,
                tax_amount=tax,
                total_amount=total,
                notes=(notes or "").strip(),
            )
            for desc, qty, unit_cost, total_cost in parsed_items:
                TicketEstimateLineItem.objects.create(
                    society_id=society_id,
                    estimate=estimate,
                    description=desc,
                    quantity=qty,
                    unit_cost=unit_cost,
                    total_cost=total_cost,
                )

            previous_status = ticket.status
            ticket.status = Ticket.Status.PENDING_ESTIMATE_APPROVAL
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))

            formatted_total = f"{estimate.total_amount:.2f}"
            event_metadata = {
                "estimate_id": str(estimate.id),
                "version": estimate.version,
                "total_amount": formatted_total,
                "cost_responsibility": estimate.cost_responsibility,
            }
            if assignment is not None:
                event_metadata["assignment_id"] = str(assignment.id)
            if allocation is not None:
                event_metadata["vendor_staff_allocation_id"] = str(allocation.id)

            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_ESTIMATE_SUBMITTED,
                reason=(notes or "").strip(),
                correlation_id=correlation_id,
                metadata=event_metadata,
            )

            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "estimate_id": str(estimate.id),
                "estimate_version": estimate.version,
                "total_amount": formatted_total,
                "event_id": str(event.id),
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketEstimateSubmissionForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def approve_ticket_estimate(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    notes="",
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")

    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _persona_for_estimate_approver(ticket=ticket, actor=actor, membership=membership)

    request_hash = _canonical_payload_hash(
        {
            "expected_version": expected_version,
            "notes": (notes or "").strip(),
            "ticket_id": str(ticket_id),
        }
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            actor_persona = _persona_for_estimate_approver(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.PENDING_ESTIMATE_APPROVAL:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Estimate approval can only be performed when the ticket is pending estimate approval.",
                    ticket=ticket,
                )

            estimate = (
                TicketEstimate.objects.select_for_update()
                .filter(ticket=ticket, status=TicketEstimate.Status.SUBMITTED)
                .first()
            )
            if estimate is None:
                raise TicketSubmissionConflict(
                    code="NO_PENDING_ESTIMATE",
                    message="No pending estimate was found for this ticket.",
                    ticket=ticket,
                )

            decided_at = timezone.now()
            estimate.status = TicketEstimate.Status.APPROVED
            estimate.decided_at = decided_at
            estimate.decided_by = actor
            estimate.decision_reason = (notes or "").strip()
            estimate.save(update_fields=("status", "decided_at", "decided_by", "decision_reason", "updated_at"))

            previous_status = ticket.status
            ticket.status = Ticket.Status.IN_PROGRESS
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))

            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_ESTIMATE_APPROVED,
                reason=(notes or "").strip(),
                correlation_id=correlation_id,
                metadata={
                    "estimate_id": str(estimate.id),
                    "version": estimate.version,
                    "total_amount": str(estimate.total_amount),
                },
            )

            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "estimate_id": str(estimate.id),
                "event_id": str(event.id),
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketEstimateDecisionForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def reject_ticket_estimate(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    reason,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise ValueError("A non-empty rejection reason is required.")

    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _persona_for_estimate_approver(ticket=ticket, actor=actor, membership=membership)

    request_hash = _canonical_payload_hash(
        {
            "expected_version": expected_version,
            "reason": clean_reason,
            "ticket_id": str(ticket_id),
        }
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            actor_persona = _persona_for_estimate_approver(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.PENDING_ESTIMATE_APPROVAL:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Estimate rejection can only be performed when the ticket is pending estimate approval.",
                    ticket=ticket,
                )

            estimate = (
                TicketEstimate.objects.select_for_update()
                .filter(ticket=ticket, status=TicketEstimate.Status.SUBMITTED)
                .first()
            )
            if estimate is None:
                raise TicketSubmissionConflict(
                    code="NO_PENDING_ESTIMATE",
                    message="No pending estimate was found for this ticket.",
                    ticket=ticket,
                )

            decided_at = timezone.now()
            estimate.status = TicketEstimate.Status.REJECTED
            estimate.decided_at = decided_at
            estimate.decided_by = actor
            estimate.decision_reason = clean_reason
            estimate.save(update_fields=("status", "decided_at", "decided_by", "decision_reason", "updated_at"))

            active_assignment = (
                TicketAssignment.objects.select_for_update()
                .filter(ticket=ticket)
                .exclude(state=TicketAssignment.State.ENDED)
                .first()
            )
            assignment_metadata = {}
            if active_assignment is not None:
                active_assignment.state = TicketAssignment.State.ENDED
                active_assignment.ended_at = decided_at
                active_assignment.ended_reason = "Estimate rejected"
                active_assignment.save(update_fields=("state", "ended_at", "ended_reason"))
                assignment_metadata["assignment_id"] = str(active_assignment.id)
                if active_assignment.target_type == TicketAssignment.TargetType.IN_HOUSE:
                    technician = TechnicianProfile.objects.select_for_update().get(
                        id=active_assignment.technician_id,
                        society_id=society_id,
                    )
                    if technician.current_active_tickets_count > 0:
                        technician.current_active_tickets_count -= 1
                        technician.save(update_fields=("current_active_tickets_count", "updated_at"))
                    assignment_metadata["technician_id"] = str(technician.id)
                else:
                    vendor_contract = VendorContract.objects.select_for_update().get(
                        id=active_assignment.vendor_contract_id,
                        society_id=society_id,
                    )
                    if vendor_contract.current_active_tickets_count > 0:
                        vendor_contract.current_active_tickets_count -= 1
                        vendor_contract.save(update_fields=("current_active_tickets_count", "updated_at"))
                    assignment_metadata["vendor_contract_id"] = str(vendor_contract.id)
                    active_allocation = (
                        VendorStaffAllocation.objects.select_for_update()
                        .filter(assignment=active_assignment)
                        .exclude(state=VendorStaffAllocation.State.ENDED)
                        .first()
                    )
                    if active_allocation is not None:
                        active_allocation.state = VendorStaffAllocation.State.ENDED
                        active_allocation.ended_at = decided_at
                        active_allocation.ended_reason = "Estimate rejected"
                        active_allocation.save(update_fields=("state", "ended_at", "ended_reason"))
                        assignment_metadata["vendor_staff_allocation_id"] = str(active_allocation.id)

            previous_status = ticket.status
            ticket.status = Ticket.Status.SUPERVISOR_TRIAGE
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))

            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_ESTIMATE_REJECTED,
                reason=clean_reason,
                correlation_id=correlation_id,
                metadata={
                    "estimate_id": str(estimate.id),
                    "version": estimate.version,
                    "total_amount": str(estimate.total_amount),
                    **assignment_metadata,
                },
            )

            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "estimate_id": str(estimate.id),
                "event_id": str(event.id),
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketEstimateDecisionForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def withdraw_ticket_estimate(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    reason,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise ValueError("A non-empty withdrawal reason is required.")

    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _authorized_worker_for_estimate(ticket=ticket, actor=actor, membership=membership)

    request_hash = _canonical_payload_hash(
        {
            "expected_version": expected_version,
            "reason": clean_reason,
            "ticket_id": str(ticket_id),
        }
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            actor_persona, _, _ = _authorized_worker_for_estimate(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.PENDING_ESTIMATE_APPROVAL:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Estimate withdrawal can only be performed when the ticket is pending estimate approval.",
                    ticket=ticket,
                )

            estimate = (
                TicketEstimate.objects.select_for_update()
                .filter(ticket=ticket, status=TicketEstimate.Status.SUBMITTED)
                .first()
            )
            if estimate is None:
                raise TicketSubmissionConflict(
                    code="NO_PENDING_ESTIMATE",
                    message="No pending estimate was found for this ticket.",
                    ticket=ticket,
                )
            if estimate.created_by_id != actor.id:
                raise TicketEstimateWithdrawalForbidden(
                    "Only the worker who created an estimate may withdraw it."
                )

            decided_at = timezone.now()
            estimate.status = TicketEstimate.Status.WITHDRAWN
            estimate.decided_at = decided_at
            estimate.decided_by = actor
            estimate.decision_reason = clean_reason
            estimate.save(update_fields=("status", "decided_at", "decided_by", "decision_reason", "updated_at"))

            previous_status = ticket.status
            ticket.status = Ticket.Status.IN_PROGRESS
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))

            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_ESTIMATE_WITHDRAWN,
                reason=clean_reason,
                correlation_id=correlation_id,
                metadata={
                    "estimate_id": str(estimate.id),
                    "version": estimate.version,
                    "total_amount": str(estimate.total_amount),
                },
            )

            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "estimate_id": str(estimate.id),
                "event_id": str(event.id),
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except (TicketEstimateSubmissionForbidden, TicketEstimateWithdrawalForbidden):
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _persona_for_reopener(*, ticket, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketReopenForbidden(
            "Membership does not belong to the actor and society."
        )
    if not membership.is_current():
        raise TicketReopenForbidden("An active membership is required.")
    if isinstance(membership, StaffMembership) and membership.role == StaffMembership.Role.FACILITY_MANAGER:
        return "staff"
    if isinstance(membership, UnitOccupancy):
        if ticket.unit_id is not None and ticket.unit_id != membership.unit_id and ticket.creator_id != actor.id:
            raise TicketReopenForbidden(
                "Residents may only reopen tickets for their own unit or created tickets."
            )
        return "resident"
    if ticket.creator_id == actor.id:
        return "resident"
    raise TicketReopenForbidden(
        "Only the ticket creator, unit occupant, or facility manager can reopen tickets."
    )


def _persona_for_closer(*, ticket, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketCloseForbidden(
            "Membership does not belong to the actor and society."
        )
    if not membership.is_current():
        raise TicketCloseForbidden("An active membership is required.")
    if isinstance(membership, StaffMembership) and membership.role == StaffMembership.Role.FACILITY_MANAGER:
        return "staff"
    if isinstance(membership, UnitOccupancy):
        if ticket.unit_id is not None and ticket.unit_id != membership.unit_id and ticket.creator_id != actor.id:
            raise TicketCloseForbidden(
                "Residents may only close tickets for their own unit or created tickets."
            )
        return "resident"
    if ticket.creator_id == actor.id:
        return "resident"
    raise TicketCloseForbidden(
        "Only the ticket creator, unit occupant, or facility manager can close tickets."
    )


def reopen_ticket(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    reason,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise ValueError("A non-empty reopen reason is required.")

    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _persona_for_reopener(ticket=ticket, actor=actor, membership=membership)

    request_hash = _canonical_payload_hash(
        {
            "expected_version": expected_version,
            "reason": clean_reason,
            "ticket_id": str(ticket_id),
        }
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            actor_persona = _persona_for_reopener(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status not in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED):
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only resolved or closed tickets can be reopened.",
                    ticket=ticket,
                )

            next_status = (
                Ticket.Status.SUPERVISOR_TRIAGE
                if ticket.workflow_type == Ticket.WorkflowType.SERVICE
                else Ticket.Status.UNDER_REVIEW
            )

            last_cycle = SLACycle.objects.filter(ticket=ticket).order_by("-cycle_number").first()
            if last_cycle is not None and last_cycle.snapshot_id is not None:
                snapshot = last_cycle.snapshot
            else:
                binding = SLAPolicyBinding.objects.get(
                    society_id=society_id,
                    category=ticket.category,
                    priority=ticket.priority,
                )
                snapshot = binding.snapshot

            now = timezone.now()
            resolution_deadline = business_calendar_deadline_calculator(
                started_at=now,
                duration=snapshot.reopen_resolution_duration,
                society_id=society_id,
                society_timezone=snapshot.society_timezone,
                calendar_version=snapshot.calendar_version,
            )
            next_cycle_number = (last_cycle.cycle_number + 1) if last_cycle else 1
            new_cycle = SLACycle.objects.create(
                society_id=society_id,
                ticket=ticket,
                snapshot=snapshot,
                cycle_number=next_cycle_number,
                cycle_type=SLACycle.CycleType.REOPEN,
                started_at=now,
                resolution_deadline=resolution_deadline,
            )

            previous_status = ticket.status
            ticket.status = next_status
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))

            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_REOPENED,
                reason=clean_reason,
                correlation_id=correlation_id,
                metadata={
                    "cycle_number": new_cycle.cycle_number,
                    "resolution_deadline": resolution_deadline.isoformat(),
                },
            )

            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "sla_cycle_id": str(new_cycle.id),
                "resolution_deadline": resolution_deadline.isoformat(),
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketReopenForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def close_ticket(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    reason="",
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")

    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        _persona_for_closer(ticket=ticket, actor=actor, membership=membership)

    clean_reason = (reason or "Administrative close").strip()
    request_hash = _canonical_payload_hash(
        {
            "expected_version": expected_version,
            "reason": clean_reason,
            "ticket_id": str(ticket_id),
        }
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            actor_persona = _persona_for_closer(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.RESOLVED:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only resolved tickets can be closed.",
                    ticket=ticket,
                )

            previous_status = ticket.status
            ticket.status = Ticket.Status.CLOSED
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))

            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=actor_persona,
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_CLOSED,
                reason=clean_reason,
                correlation_id=correlation_id,
            )

            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketCloseForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def reassign_service_ticket_from_triage(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    expected_version,
    target_type,
    technician_id=None,
    vendor_contract_id=None,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    if target_type not in (TicketAssignment.TargetType.IN_HOUSE, TicketAssignment.TargetType.VENDOR):
        raise ValueError("Invalid target_type.")
    if target_type == TicketAssignment.TargetType.IN_HOUSE and not technician_id:
        raise ValueError("technician_id is required for in-house assignment.")
    if target_type == TicketAssignment.TargetType.VENDOR and not vendor_contract_id:
        raise ValueError("vendor_contract_id is required for vendor assignment.")

    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        if membership.user_id != actor.id or membership.society_id != ticket.society_id:
            raise TicketTriageReassignmentForbidden(
                "Membership does not belong to the actor and society."
            )
        if not membership.is_current() or not isinstance(membership, StaffMembership) or membership.role != StaffMembership.Role.FACILITY_MANAGER:
            raise TicketTriageReassignmentForbidden(
                "Only facility managers can reassign tickets from triage."
            )

    request_hash = _canonical_payload_hash(
        {
            "expected_version": expected_version,
            "target_type": target_type,
            "technician_id": str(technician_id) if technician_id else "",
            "vendor_contract_id": str(vendor_contract_id) if vendor_contract_id else "",
            "ticket_id": str(ticket_id),
        }
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.SUPERVISOR_TRIAGE:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only tickets in supervisor triage can be reassigned.",
                    ticket=ticket,
                )
            if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only service tickets can be reassigned.",
                    ticket=ticket,
                )

            assignment_started_at = timezone.now()
            sla_cycle = SLACycle.objects.select_for_update().select_related("snapshot").filter(
                ticket=ticket,
                ended_at__isnull=True,
            ).first()
            if not sla_cycle:
                last_cycle = SLACycle.objects.filter(ticket=ticket).order_by("-cycle_number").first()
                if last_cycle is not None and last_cycle.snapshot_id is not None:
                    snapshot = last_cycle.snapshot
                else:
                    binding = SLAPolicyBinding.objects.get(
                        society_id=society_id,
                        category=ticket.category,
                        priority=ticket.priority,
                    )
                    snapshot = binding.snapshot
                resolution_deadline = business_calendar_deadline_calculator(
                    started_at=assignment_started_at,
                    duration=snapshot.reopen_resolution_duration,
                    society_id=society_id,
                    society_timezone=snapshot.society_timezone,
                    calendar_version=snapshot.calendar_version,
                )
                sla_cycle = SLACycle.objects.create(
                    society_id=society_id,
                    ticket=ticket,
                    snapshot=snapshot,
                    cycle_number=(last_cycle.cycle_number + 1) if last_cycle else 1,
                    cycle_type=SLACycle.CycleType.REOPEN,
                    started_at=assignment_started_at,
                    resolution_deadline=resolution_deadline,
                )

            acceptance_deadline = (
                assignment_started_at + sla_cycle.snapshot.acceptance_duration
            )

            if target_type == TicketAssignment.TargetType.IN_HOUSE:
                try:
                    technician = TechnicianProfile.objects.select_for_update().select_related(
                        "user", "society"
                    ).get(id=technician_id, society_id=society_id)
                except TechnicianProfile.DoesNotExist as error:
                    raise TicketSubmissionConflict(
                        code="TECHNICIAN_UNAVAILABLE",
                        message="The selected technician is unavailable.",
                        ticket=ticket,
                    ) from error
                if not technician.is_active:
                    raise TicketSubmissionConflict(
                        code="TECHNICIAN_UNAVAILABLE",
                        message="The selected technician is unavailable.",
                        ticket=ticket,
                    )
                if (
                    technician.max_active_tickets is not None
                    and technician.current_active_tickets_count >= technician.max_active_tickets
                ):
                    raise TicketSubmissionConflict(
                        code="TECHNICIAN_CAPACITY_UNAVAILABLE",
                        message="The selected technician has no remaining ticket capacity.",
                        ticket=ticket,
                    )
                assignment = TicketAssignment.objects.create(
                    society_id=society_id,
                    ticket=ticket,
                    target_type=TicketAssignment.TargetType.IN_HOUSE,
                    technician=technician,
                    assigned_by=actor,
                    acceptance_deadline=acceptance_deadline,
                    state=TicketAssignment.State.OFFERED,
                )
                technician.current_active_tickets_count += 1
                technician.save(update_fields=("current_active_tickets_count", "updated_at"))
            else:
                try:
                    vendor_contract = VendorContract.objects.select_for_update().select_related(
                        "vendor", "society"
                    ).get(id=vendor_contract_id, society_id=society_id)
                except VendorContract.DoesNotExist as error:
                    raise TicketSubmissionConflict(
                        code="VENDOR_CONTRACT_UNAVAILABLE",
                        message="The selected vendor contract is unavailable.",
                        ticket=ticket,
                    ) from error
                if not vendor_contract.is_current():
                    raise TicketSubmissionConflict(
                        code="VENDOR_CONTRACT_UNAVAILABLE",
                        message="The selected vendor contract is unavailable.",
                        ticket=ticket,
                    )
                if (
                    vendor_contract.max_active_tickets is not None
                    and vendor_contract.current_active_tickets_count >= vendor_contract.max_active_tickets
                ):
                    raise TicketSubmissionConflict(
                        code="VENDOR_CAPACITY_UNAVAILABLE",
                        message="The selected vendor contract has no remaining ticket capacity.",
                        ticket=ticket,
                    )
                assignment = TicketAssignment.objects.create(
                    society_id=society_id,
                    ticket=ticket,
                    target_type=TicketAssignment.TargetType.VENDOR,
                    vendor_contract=vendor_contract,
                    assigned_by=actor,
                    acceptance_deadline=acceptance_deadline,
                    state=TicketAssignment.State.OFFERED,
                )
                vendor_contract.current_active_tickets_count += 1
                vendor_contract.save(update_fields=("current_active_tickets_count", "updated_at"))

            sla_cycle.acceptance_deadline = acceptance_deadline
            sla_cycle.save(update_fields=("acceptance_deadline",))

            previous_status = ticket.status
            ticket.status = Ticket.Status.ASSIGNED
            ticket.state_version += 1
            ticket.save(
                update_fields=(
                    "status",
                    "state_version",
                    "updated_at",
                )
            )

            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona="staff",
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_TRIAGE_REASSIGNED,
                correlation_id=correlation_id,
                metadata={
                    "assignment_id": str(assignment.id),
                    "target_type": target_type,
                    "target_id": str(technician_id or vendor_contract_id),
                },
            )

            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "assignment_id": str(assignment.id),
                "acceptance_deadline": acceptance_deadline.isoformat(),
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketTriageReassignmentForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def override_resume_service_ticket_from_triage(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    validated_token,
    expected_version,
    reason,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise ValueError("A non-empty override reason is required.")
    validate_platform_step_up(validated_token)

    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        if membership.user_id != actor.id or membership.society_id != ticket.society_id:
            raise TicketTriageResumeForbidden(
                "Membership does not belong to the actor and society."
            )
        if not membership.is_current() or not isinstance(membership, StaffMembership) or membership.role != StaffMembership.Role.FACILITY_MANAGER:
            raise TicketTriageResumeForbidden(
                "Only facility managers can override and resume tickets from triage."
            )

    request_hash = _canonical_payload_hash(
        {
            "expected_version": expected_version,
            "reason": clean_reason,
            "ticket_id": str(ticket_id),
        }
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.SUPERVISOR_TRIAGE:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only tickets in supervisor triage can be resumed.",
                    ticket=ticket,
                )

            active_assignment = TicketAssignment.objects.select_for_update().filter(
                ticket=ticket,
                state=TicketAssignment.State.ACCEPTED,
                ended_at__isnull=True,
            ).first()
            if not active_assignment:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Cannot resume from triage without an active accepted assignment.",
                    ticket=ticket,
                )

            previous_status = ticket.status
            ticket.status = Ticket.Status.IN_PROGRESS
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))

            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona="staff",
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_TRIAGE_RESUMED_OVERRIDE,
                reason=clean_reason,
                correlation_id=correlation_id,
                metadata={"assignment_id": str(active_assignment.id)},
            )

            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "assignment_id": str(active_assignment.id),
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketTriageResumeForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def override_complete_service_ticket(
    *,
    society_id,
    ticket_id,
    actor,
    membership,
    validated_token,
    expected_version,
    reason,
    proof_notes,
    idempotency_key,
    route_template,
    correlation_id,
):
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")
    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise ValueError("A non-empty override reason is required.")
    clean_proof_notes = (proof_notes or "").strip()
    if not clean_proof_notes:
        raise ValueError("Non-empty proof notes are required for supervisor completion override.")
    validate_platform_step_up(validated_token)

    with transaction.atomic():
        set_local_society_id(society_id)
        ticket = Ticket.objects.get(id=ticket_id)
        if membership.user_id != actor.id or membership.society_id != ticket.society_id:
            raise TicketSupervisorCompletionForbidden(
                "Membership does not belong to the actor and society."
            )
        if not membership.is_current() or not isinstance(membership, StaffMembership) or membership.role != StaffMembership.Role.FACILITY_MANAGER:
            raise TicketSupervisorCompletionForbidden(
                "Only facility managers can perform supervisor completion overrides."
            )

    request_hash = _canonical_payload_hash(
        {
            "expected_version": expected_version,
            "reason": clean_reason,
            "proof_notes": clean_proof_notes,
            "ticket_id": str(ticket_id),
        }
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id)
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status != Ticket.Status.PENDING_RESIDENT_CONFIRMATION:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only tickets pending resident confirmation can be completed by supervisor override.",
                    ticket=ticket,
                )

            challenge = TicketCompletionChallenge.objects.select_for_update().filter(
                ticket=ticket,
                is_consumed=False,
            ).first()
            now = timezone.now()
            if challenge:
                challenge.is_consumed = True
                challenge.consumed_at = now
                challenge.consumed_by = actor
                challenge.save(
                    update_fields=("is_consumed", "consumed_at", "consumed_by", "updated_at")
                )

            active_assignment = (
                TicketAssignment.objects.select_for_update()
                .filter(ticket=ticket)
                .exclude(state=TicketAssignment.State.ENDED)
                .first()
            )
            if active_assignment is not None:
                active_assignment.state = TicketAssignment.State.ENDED
                active_assignment.ended_at = now
                active_assignment.ended_reason = "Completed by supervisor override"
                active_assignment.save(
                    update_fields=("state", "ended_at", "ended_reason")
                )
                if active_assignment.target_type == TicketAssignment.TargetType.IN_HOUSE and active_assignment.technician_id:
                    technician = TechnicianProfile.objects.select_for_update().get(
                        id=active_assignment.technician_id,
                        society_id=society_id,
                    )
                    if technician.current_active_tickets_count > 0:
                        technician.current_active_tickets_count -= 1
                        technician.save(update_fields=("current_active_tickets_count", "updated_at"))
                elif active_assignment.target_type == TicketAssignment.TargetType.VENDOR and active_assignment.vendor_contract_id:
                    contract = VendorContract.objects.select_for_update().get(
                        id=active_assignment.vendor_contract_id,
                        society_id=society_id,
                    )
                    if contract.current_active_tickets_count > 0:
                        contract.current_active_tickets_count -= 1
                        contract.save(update_fields=("current_active_tickets_count", "updated_at"))
                    active_allocation = (
                        VendorStaffAllocation.objects.select_for_update()
                        .filter(assignment=active_assignment)
                        .exclude(state=VendorStaffAllocation.State.ENDED)
                        .first()
                    )
                    if active_allocation is not None:
                        active_allocation.state = VendorStaffAllocation.State.ENDED
                        active_allocation.ended_at = now
                        active_allocation.ended_reason = "Completed by supervisor override"
                        active_allocation.save(
                            update_fields=("state", "ended_at", "ended_reason")
                        )

            active_cycle = SLACycle.objects.select_for_update().filter(
                ticket=ticket,
                ended_at__isnull=True,
            ).first()
            if active_cycle:
                active_cycle.ended_at = now
                active_cycle.outcome = SLACycle.Outcome.RESOLVED
                active_cycle.save(update_fields=("ended_at", "outcome"))

            previous_status = ticket.status
            ticket.status = Ticket.Status.RESOLVED
            ticket.state_version += 1
            ticket.save(update_fields=("status", "state_version", "updated_at"))

            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona="staff",
                ticket_version=ticket.state_version,
                previous_status=previous_status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_RESOLVED_OVERRIDE,
                reason=clean_reason,
                correlation_id=correlation_id,
                metadata={"proof_notes": clean_proof_notes},
            )

            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketSupervisorCompletionForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _validate_feedback_resident(*, ticket, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketFeedbackForbidden(
            "Membership does not belong to the actor and society."
        )
    if not membership.is_current():
        raise TicketFeedbackForbidden("An active membership is required.")
    if isinstance(membership, UnitOccupancy):
        if ticket.unit_id is not None and ticket.unit_id != membership.unit_id and ticket.creator_id != actor.id:
            raise TicketFeedbackForbidden(
                "Residents may only rate tickets for their own unit or created tickets."
            )
        return
    if ticket.creator_id == actor.id:
        return
    raise TicketFeedbackForbidden(
        "Only the ticket creator or active unit occupant can rate tickets."
    )


def submit_ticket_feedback(
    *,
    society_id: uuid.UUID,
    ticket_id: uuid.UUID,
    actor,
    membership,
    expected_version: int,
    overall_rating: int,
    timeliness_rating: int | None = None,
    quality_rating: int | None = None,
    technician_behavior_rating: int | None = None,
    tags: list[str] | None = None,
    comment: str = "",
    idempotency_key: str | None = None,
    correlation_id: uuid.UUID | None = None,
) -> TicketCommandResult:
    correlation_id = correlation_id or uuid.uuid4()
    route_template = "/api/v1/service-tickets/{ticket_id}/rate/"
    request_hash = _canonical_request_hash(
        ticket_id=ticket_id,
        expected_version=expected_version,
        action="rate",
        overall_rating=overall_rating,
        timeliness_rating=timeliness_rating,
        quality_rating=quality_rating,
        technician_behavior_rating=technician_behavior_rating,
        tags=tags or [],
        comment=comment or "",
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            ticket = Ticket.objects.select_for_update().get(id=ticket_id, society_id=society_id)
            _validate_feedback_resident(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )
            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The ticket has changed since it was loaded.",
                    ticket=ticket,
                )
            if ticket.status not in (Ticket.Status.RESOLVED, Ticket.Status.CLOSED):
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Only resolved or closed service tickets can receive ratings.",
                    ticket=ticket,
                )

            existing = TicketFeedback.objects.filter(ticket=ticket, society_id=society_id).first()
            if existing is not None:
                raise TicketSubmissionConflict(
                    code="FEEDBACK_ALREADY_EXISTS",
                    message="Feedback has already been submitted for this ticket.",
                    ticket=ticket,
                )

            last_assignment = (
                TicketAssignment.objects.select_for_update()
                .filter(ticket=ticket)
                .order_by("-assigned_at")
                .first()
            )
            tech = None
            contract = None
            if last_assignment is not None:
                if (
                    last_assignment.target_type == TicketAssignment.TargetType.IN_HOUSE
                    and last_assignment.technician_id
                ):
                    tech = last_assignment.technician
                elif (
                    last_assignment.target_type == TicketAssignment.TargetType.VENDOR
                    and last_assignment.vendor_contract_id
                ):
                    contract = last_assignment.vendor_contract

            clean_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
            clean_comment = comment.strip() if comment else ""

            feedback = TicketFeedback.objects.create(
                society_id=society_id,
                ticket=ticket,
                resident=actor,
                technician=tech,
                vendor_contract=contract,
                overall_rating=overall_rating,
                timeliness_rating=timeliness_rating,
                quality_rating=quality_rating,
                technician_behavior_rating=technician_behavior_rating,
                tags=clean_tags,
                comment=clean_comment,
            )

            ticket.state_version += 1
            ticket.save(update_fields=("state_version", "updated_at"))

            event_metadata = {
                "feedback_id": str(feedback.id),
                "overall_rating": feedback.overall_rating,
                "timeliness_rating": feedback.timeliness_rating,
                "quality_rating": feedback.quality_rating,
                "technician_behavior_rating": feedback.technician_behavior_rating,
                "tags": feedback.tags,
            }
            if tech is not None:
                event_metadata["technician_id"] = str(tech.id)
            if contract is not None:
                event_metadata["vendor_contract_id"] = str(contract.id)

            event = TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona="resident",
                ticket_version=ticket.state_version,
                previous_status=ticket.status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_RATED,
                correlation_id=correlation_id,
                metadata=event_metadata,
            )

            response_body = {
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "state_version": ticket.state_version,
                "event_id": str(event.id),
                "feedback": {
                    "id": str(feedback.id),
                    "ticket_id": str(ticket.id),
                    "overall_rating": feedback.overall_rating,
                    "timeliness_rating": feedback.timeliness_rating,
                    "quality_rating": feedback.quality_rating,
                    "technician_behavior_rating": feedback.technician_behavior_rating,
                    "tags": feedback.tags,
                    "comment": feedback.comment,
                    "technician_id": str(feedback.technician_id) if feedback.technician_id else None,
                    "vendor_contract_id": (
                        str(feedback.vendor_contract_id) if feedback.vendor_contract_id else None
                    ),
                    "created_at": feedback.created_at.isoformat(),
                },
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(
                id=claim.record_id
            )
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketFeedbackForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def merge_ticket(
    *,
    society_id: uuid.UUID,
    primary_ticket_id: uuid.UUID,
    secondary_ticket_id: uuid.UUID,
    actor,
    membership,
    expected_primary_version: int,
    expected_secondary_version: int,
    reason: str,
    idempotency_key: str | None = None,
    route_template: str = "/api/v1/service-tickets/{id}/merge/",
    correlation_id: uuid.UUID | None = None,
) -> TicketCommandResult:
    correlation_id = correlation_id or uuid.uuid4()
    clean_reason = reason.strip()
    if not clean_reason:
        raise TicketMergeForbidden("A merge reason is required.")
    if not isinstance(membership, StaffMembership) or membership.role != StaffMembership.Role.FACILITY_MANAGER:
        raise TicketMergeForbidden("Only facility managers may merge tickets.")
    if membership.user_id != actor.id or membership.society_id != society_id or not membership.is_current():
        raise TicketMergeForbidden("An active facility manager membership is required.")

    if primary_ticket_id == secondary_ticket_id:
        raise TicketSubmissionConflict(
            code="CANNOT_MERGE_SELF",
            message="A ticket cannot be merged into itself.",
        )

    request_hash = _canonical_request_hash(
        ticket_id=primary_ticket_id,
        expected_version=expected_primary_version,
        action="merge",
        secondary_ticket_id=str(secondary_ticket_id),
        expected_secondary_version=expected_secondary_version,
        reason=clean_reason,
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            try:
                primary_ticket = Ticket.objects.select_for_update().get(
                    id=primary_ticket_id, society_id=society_id
                )
            except Ticket.DoesNotExist as error:
                raise TicketSubmissionConflict(
                    code="PRIMARY_TICKET_NOT_FOUND",
                    message="The primary ticket does not exist in this society.",
                ) from error

            try:
                secondary_ticket = Ticket.objects.select_for_update().get(
                    id=secondary_ticket_id, society_id=society_id
                )
            except Ticket.DoesNotExist as error:
                raise TicketSubmissionConflict(
                    code="SECONDARY_TICKET_NOT_FOUND",
                    message="The secondary ticket does not exist in this society.",
                ) from error

            if primary_ticket.state_version != expected_primary_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The primary ticket has changed since it was loaded.",
                    ticket=primary_ticket,
                )
            if secondary_ticket.state_version != expected_secondary_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The secondary ticket has changed since it was loaded.",
                    ticket=secondary_ticket,
                )

            if primary_ticket.workflow_type != secondary_ticket.workflow_type:
                raise TicketSubmissionConflict(
                    code="TICKET_WORKFLOW_MISMATCH",
                    message="Cannot merge tickets of different workflow types.",
                    ticket=secondary_ticket,
                )

            terminal_statuses = {
                Ticket.Status.RESOLVED,
                Ticket.Status.CLOSED,
                Ticket.Status.CANCELLED,
                Ticket.Status.MERGED,
            }
            if primary_ticket.status in terminal_statuses:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="The primary ticket is in a terminal state and cannot receive merged tickets.",
                    ticket=primary_ticket,
                )
            if secondary_ticket.status in terminal_statuses:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="The secondary ticket is in a terminal state and cannot be merged.",
                    ticket=secondary_ticket,
                )

            if TicketEstimate.objects.filter(
                ticket__in=(primary_ticket, secondary_ticket),
                status__in=(
                    TicketEstimate.Status.SUBMITTED,
                    TicketEstimate.Status.APPROVED,
                ),
            ).exists():
                raise TicketSubmissionConflict(
                    code="TICKET_ESTIMATE_UNRESOLVED",
                    message="Tickets with pending or approved estimates cannot be merged.",
                    ticket=secondary_ticket,
                )

            active_merge = TicketMergeRecord.objects.filter(
                secondary_ticket=secondary_ticket,
                is_active=True,
            ).first()
            if active_merge is not None:
                raise TicketSubmissionConflict(
                    code="TICKET_ALREADY_MERGED",
                    message="The secondary ticket is already merged into another ticket.",
                    ticket=secondary_ticket,
                )

            now = timezone.now()
            # End active assignment and allocations on secondary ticket
            active_assignment = (
                TicketAssignment.objects.select_for_update()
                .filter(ticket=secondary_ticket)
                .exclude(state=TicketAssignment.State.ENDED)
                .first()
            )
            if active_assignment is not None:
                active_assignment.state = TicketAssignment.State.ENDED
                active_assignment.ended_at = now
                active_assignment.ended_reason = f"Ticket merged into {primary_ticket.ticket_number}"
                active_assignment.save(update_fields=("state", "ended_at", "ended_reason"))
                if (
                    active_assignment.target_type == TicketAssignment.TargetType.IN_HOUSE
                    and active_assignment.technician_id
                ):
                    technician = TechnicianProfile.objects.select_for_update().get(
                        id=active_assignment.technician_id,
                        society_id=society_id,
                    )
                    if technician.current_active_tickets_count > 0:
                        technician.current_active_tickets_count -= 1
                        technician.save(update_fields=("current_active_tickets_count", "updated_at"))
                elif (
                    active_assignment.target_type == TicketAssignment.TargetType.VENDOR
                    and active_assignment.vendor_contract_id
                ):
                    contract = VendorContract.objects.select_for_update().get(
                        id=active_assignment.vendor_contract_id,
                        society_id=society_id,
                    )
                    if contract.current_active_tickets_count > 0:
                        contract.current_active_tickets_count -= 1
                        contract.save(update_fields=("current_active_tickets_count", "updated_at"))
                    active_alloc = (
                        VendorStaffAllocation.objects.select_for_update()
                        .filter(assignment=active_assignment)
                        .exclude(state=VendorStaffAllocation.State.ENDED)
                        .first()
                    )
                    if active_alloc is not None:
                        active_alloc.state = VendorStaffAllocation.State.ENDED
                        active_alloc.ended_at = now
                        active_alloc.ended_reason = f"Ticket merged into {primary_ticket.ticket_number}"
                        active_alloc.save(update_fields=("state", "ended_at", "ended_reason"))

            # End active SLA cycle on secondary ticket
            active_cycle = (
                SLACycle.objects.select_for_update()
                .filter(ticket=secondary_ticket, ended_at__isnull=True)
                .first()
            )
            if active_cycle is not None:
                active_cycle.ended_at = now
                active_cycle.outcome = SLACycle.Outcome.MERGED
                active_cycle.save(update_fields=("ended_at", "outcome"))

            prev_secondary_status = secondary_ticket.status
            merge_record = TicketMergeRecord.objects.create(
                society_id=society_id,
                primary_ticket=primary_ticket,
                secondary_ticket=secondary_ticket,
                merged_by=actor,
                reason=clean_reason,
                previous_secondary_status=prev_secondary_status,
                is_active=True,
            )

            secondary_ticket.status = Ticket.Status.MERGED
            secondary_ticket.state_version += 1
            secondary_ticket.save(update_fields=("status", "state_version", "updated_at"))

            primary_ticket.state_version += 1
            primary_ticket.save(update_fields=("state_version", "updated_at"))

            TicketEvent.objects.create(
                society_id=society_id,
                ticket=secondary_ticket,
                actor=actor,
                actor_persona="facility_manager",
                ticket_version=secondary_ticket.state_version,
                previous_status=prev_secondary_status,
                new_status=Ticket.Status.MERGED,
                event_type=TicketEvent.EventType.TICKET_MERGED,
                correlation_id=correlation_id,
                reason=clean_reason,
                metadata={
                    "primary_ticket_id": str(primary_ticket.id),
                    "primary_ticket_number": primary_ticket.ticket_number,
                    "merge_record_id": str(merge_record.id),
                },
            )

            TicketEvent.objects.create(
                society_id=society_id,
                ticket=primary_ticket,
                actor=actor,
                actor_persona="facility_manager",
                ticket_version=primary_ticket.state_version,
                previous_status=primary_ticket.status,
                new_status=primary_ticket.status,
                event_type=TicketEvent.EventType.TICKET_MERGE_ATTACHED,
                correlation_id=correlation_id,
                reason=clean_reason,
                metadata={
                    "secondary_ticket_id": str(secondary_ticket.id),
                    "secondary_ticket_number": secondary_ticket.ticket_number,
                    "merge_record_id": str(merge_record.id),
                },
            )

            response_body = {
                "primary_ticket": {
                    "id": str(primary_ticket.id),
                    "ticket_number": primary_ticket.ticket_number,
                    "status": primary_ticket.status,
                    "state_version": primary_ticket.state_version,
                },
                "secondary_ticket": {
                    "id": str(secondary_ticket.id),
                    "ticket_number": secondary_ticket.ticket_number,
                    "status": secondary_ticket.status,
                    "state_version": secondary_ticket.state_version,
                },
                "merge_record": {
                    "id": str(merge_record.id),
                    "primary_ticket_id": str(primary_ticket.id),
                    "secondary_ticket_id": str(secondary_ticket.id),
                    "reason": merge_record.reason,
                    "previous_secondary_status": merge_record.previous_secondary_status,
                    "is_active": merge_record.is_active,
                    "merged_at": merge_record.merged_at.isoformat(),
                },
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(id=claim.record_id)
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketMergeForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def unmerge_ticket(
    *,
    society_id: uuid.UUID,
    primary_ticket_id: uuid.UUID,
    secondary_ticket_id: uuid.UUID,
    actor,
    membership,
    validated_token,
    expected_primary_version: int,
    expected_secondary_version: int,
    reason: str,
    idempotency_key: str | None = None,
    route_template: str = "/api/v1/service-tickets/{id}/unmerge/",
    correlation_id: uuid.UUID | None = None,
) -> TicketCommandResult:
    correlation_id = correlation_id or uuid.uuid4()
    clean_reason = reason.strip()
    if not clean_reason:
        raise TicketUnmergeForbidden("An unmerge reason is required.")
    if not isinstance(membership, StaffMembership) or membership.role != StaffMembership.Role.FACILITY_MANAGER:
        raise TicketUnmergeForbidden("Only facility managers may unmerge tickets.")
    if membership.user_id != actor.id or membership.society_id != society_id or not membership.is_current():
        raise TicketUnmergeForbidden("An active facility manager membership is required.")
    validate_platform_step_up(validated_token)

    request_hash = _canonical_request_hash(
        ticket_id=primary_ticket_id,
        expected_version=expected_primary_version,
        action="unmerge",
        secondary_ticket_id=str(secondary_ticket_id),
        expected_secondary_version=expected_secondary_version,
        reason=clean_reason,
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            try:
                primary_ticket = Ticket.objects.select_for_update().get(
                    id=primary_ticket_id, society_id=society_id
                )
            except Ticket.DoesNotExist as error:
                raise TicketSubmissionConflict(
                    code="PRIMARY_TICKET_NOT_FOUND",
                    message="The primary ticket does not exist in this society.",
                ) from error

            try:
                secondary_ticket = Ticket.objects.select_for_update().get(
                    id=secondary_ticket_id, society_id=society_id
                )
            except Ticket.DoesNotExist as error:
                raise TicketSubmissionConflict(
                    code="SECONDARY_TICKET_NOT_FOUND",
                    message="The secondary ticket does not exist in this society.",
                ) from error
            merge_record = TicketMergeRecord.objects.select_for_update().filter(
                primary_ticket=primary_ticket,
                secondary_ticket=secondary_ticket,
                is_active=True,
                society_id=society_id,
            ).first()

            if merge_record is None:
                raise TicketSubmissionConflict(
                    code="MERGE_RECORD_NOT_FOUND",
                    message="No active merge record exists between these tickets.",
                    ticket=secondary_ticket,
                )

            if timezone.now() - merge_record.merged_at >= timedelta(hours=24):
                raise TicketUnmergeForbidden(
                    "Facility manager unmerge authority expires 24 hours after the merge."
                )

            if primary_ticket.state_version != expected_primary_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The primary ticket has changed since it was loaded.",
                    ticket=primary_ticket,
                )
            if secondary_ticket.state_version != expected_secondary_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_CONFLICT",
                    message="The secondary ticket has changed since it was loaded.",
                    ticket=secondary_ticket,
                )

            if secondary_ticket.status != Ticket.Status.MERGED:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="The secondary ticket is not in merged status.",
                    ticket=secondary_ticket,
                )

            now = timezone.now()
            merge_record.is_active = False
            merge_record.unmerged_by = actor
            merge_record.unmerged_at = now
            merge_record.unmerge_reason = clean_reason
            merge_record.save(update_fields=("is_active", "unmerged_by", "unmerged_at", "unmerge_reason", "updated_at"))

            # Move secondary ticket back to actionable state
            new_secondary_status = (
                Ticket.Status.SUPERVISOR_TRIAGE
                if secondary_ticket.workflow_type == Ticket.WorkflowType.SERVICE
                else Ticket.Status.UNDER_REVIEW
            )

            # Start fresh SLA cycle on secondary ticket
            last_cycle = SLACycle.objects.filter(ticket=secondary_ticket).order_by("-cycle_number").first()
            if last_cycle is not None and last_cycle.snapshot_id is not None:
                snapshot = last_cycle.snapshot
            else:
                binding = SLAPolicyBinding.objects.get(
                    society_id=society_id,
                    category=secondary_ticket.category,
                    priority=secondary_ticket.priority,
                )
                snapshot = binding.snapshot

            SLACycle.objects.create(
                society_id=society_id,
                ticket=secondary_ticket,
                snapshot=snapshot,
                cycle_number=(last_cycle.cycle_number + 1) if last_cycle else 1,
                cycle_type=SLACycle.CycleType.REOPEN,
                started_at=now,
                resolution_deadline=business_calendar_deadline_calculator(
                    started_at=now,
                    duration=snapshot.reopen_resolution_duration,
                    society_id=society_id,
                    society_timezone=snapshot.society_timezone,
                    calendar_version=snapshot.calendar_version,
                ),
            )

            secondary_ticket.status = new_secondary_status
            secondary_ticket.state_version += 1
            secondary_ticket.save(update_fields=("status", "state_version", "updated_at"))

            primary_ticket.state_version += 1
            primary_ticket.save(update_fields=("state_version", "updated_at"))

            TicketEvent.objects.create(
                society_id=society_id,
                ticket=secondary_ticket,
                actor=actor,
                actor_persona="facility_manager",
                ticket_version=secondary_ticket.state_version,
                previous_status=Ticket.Status.MERGED,
                new_status=new_secondary_status,
                event_type=TicketEvent.EventType.TICKET_UNMERGED,
                correlation_id=correlation_id,
                reason=clean_reason,
                metadata={
                    "primary_ticket_id": str(primary_ticket.id),
                    "primary_ticket_number": primary_ticket.ticket_number,
                    "merge_record_id": str(merge_record.id),
                },
            )

            TicketEvent.objects.create(
                society_id=society_id,
                ticket=primary_ticket,
                actor=actor,
                actor_persona="facility_manager",
                ticket_version=primary_ticket.state_version,
                previous_status=primary_ticket.status,
                new_status=primary_ticket.status,
                event_type=TicketEvent.EventType.TICKET_UNMERGED,
                correlation_id=correlation_id,
                reason=clean_reason,
                metadata={
                    "secondary_ticket_id": str(secondary_ticket.id),
                    "secondary_ticket_number": secondary_ticket.ticket_number,
                    "merge_record_id": str(merge_record.id),
                },
            )

            response_body = {
                "primary_ticket": {
                    "id": str(primary_ticket.id),
                    "ticket_number": primary_ticket.ticket_number,
                    "status": primary_ticket.status,
                    "state_version": primary_ticket.state_version,
                },
                "secondary_ticket": {
                    "id": str(secondary_ticket.id),
                    "ticket_number": secondary_ticket.ticket_number,
                    "status": secondary_ticket.status,
                    "state_version": secondary_ticket.state_version,
                },
                "merge_record": {
                    "id": str(merge_record.id),
                    "primary_ticket_id": str(primary_ticket.id),
                    "secondary_ticket_id": str(secondary_ticket.id),
                    "reason": merge_record.reason,
                    "is_active": merge_record.is_active,
                    "unmerge_reason": merge_record.unmerge_reason,
                    "unmerged_at": merge_record.unmerged_at.isoformat() if merge_record.unmerged_at else None,
                },
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(id=claim.record_id)
            _complete_claim(
                record=record,
                response_status=200,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(200, response_body, response_headers)
    except TicketUnmergeForbidden:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def _lock_and_authorize_attachment_uploader(*, ticket, actor, membership):
    if membership.user_id != actor.id or membership.society_id != ticket.society_id:
        raise TicketAttachmentForbidden("Membership does not belong to the actor and society.")
    if not membership.is_current():
        raise TicketAttachmentForbidden("An active membership is required.")

    if isinstance(membership, UnitOccupancy):
        if ticket.workflow_type == Ticket.WorkflowType.SERVICE:
            if ticket.creator_id != actor.id and ticket.unit_id != membership.unit_id:
                raise TicketAttachmentForbidden(
                    "Residents may add attachments only to their own service tickets."
                )
            return "resident"
        if ticket.workflow_type == Ticket.WorkflowType.GOVERNANCE:
            if ticket.creator_id != actor.id:
                raise TicketAttachmentForbidden(
                    "Residents may add attachments only to governance tickets they created."
                )
            return "resident"

    if isinstance(membership, StaffMembership):
        if membership.role not in {
            StaffMembership.Role.FACILITY_MANAGER,
            StaffMembership.Role.HELPDESK_OPERATOR,
        }:
            raise TicketAttachmentForbidden("This staff role cannot add attachments.")
        return "staff"

    if isinstance(membership, CommitteeMembership):
        if ticket.workflow_type != Ticket.WorkflowType.GOVERNANCE:
            raise TicketAttachmentForbidden(
                "Committee members cannot add attachments to service tickets unless assigned."
            )
        return "committee"

    if isinstance(membership, TechnicianProfile):
        if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
            raise TicketAttachmentForbidden(
                "Technicians cannot add attachments to governance tickets."
            )
        active_assignment = (
            TicketAssignment.objects.select_for_update()
            .filter(
                society_id=ticket.society_id,
                ticket=ticket,
                target_type=TicketAssignment.TargetType.IN_HOUSE,
                technician=membership,
                state__in=(
                    TicketAssignment.State.OFFERED,
                    TicketAssignment.State.ACCEPTED,
                ),
            )
            .first()
        )
        if active_assignment is None:
            raise TicketAttachmentForbidden(
                "Technicians may add attachments only to tickets currently assigned to them."
            )
        return "technician"

    if isinstance(membership, VendorStaffMembership):
        if ticket.workflow_type != Ticket.WorkflowType.SERVICE:
            raise TicketAttachmentForbidden(
                "Vendor workers cannot add attachments to governance tickets."
            )
        if membership.role != VendorStaffMembership.Role.WORKER:
            raise TicketAttachmentForbidden("Only assigned vendor workers can add attachments.")
        active_assignment = (
            TicketAssignment.objects.select_for_update()
            .filter(
                society_id=ticket.society_id,
                ticket=ticket,
                target_type=TicketAssignment.TargetType.VENDOR,
                state__in=(
                    TicketAssignment.State.OFFERED,
                    TicketAssignment.State.ACCEPTED,
                ),
            )
            .first()
        )
        if active_assignment is None:
            raise TicketAttachmentForbidden(
                "No active vendor assignment exists on this ticket."
            )
        active_allocation = (
            VendorStaffAllocation.objects.select_for_update()
            .filter(
                society_id=ticket.society_id,
                assignment=active_assignment,
                staff_membership=membership,
                state__in=(
                    VendorStaffAllocation.State.ALLOCATED,
                    VendorStaffAllocation.State.ACCEPTED,
                ),
            )
            .first()
        )
        if active_allocation is None:
            raise TicketAttachmentForbidden(
                "Vendor workers may add attachments only to tickets currently allocated to them."
            )
        return "vendor_worker"

    raise TicketAttachmentForbidden("Your society role cannot add attachments to this ticket.")


def issue_ticket_attachment_upload_slot(
    *,
    society_id,
    ticket_id,
    workflow_type,
    actor,
    membership,
    expected_version,
    filename,
    content_type,
    byte_size,
    idempotency_key,
    route_template,
    correlation_id,
) -> TicketCommandResult:
    if not idempotency_key or len(idempotency_key) > 255:
        raise ValueError("A non-empty idempotency key of at most 255 characters is required.")

    try:
        validate_attachment_request(
            filename=filename,
            content_type=content_type,
            byte_size=byte_size,
        )
    except AttachmentValidationError as err:
        raise TicketAttachmentValidationForbidden(str(err)) from err

    request_hash = _canonical_request_hash(
        ticket_id=ticket_id,
        expected_version=expected_version,
        filename=filename.strip(),
        content_type=content_type.strip().lower(),
        byte_size=byte_size,
    )
    claim = _claim_idempotency(
        society_id=society_id,
        principal=actor,
        route_template=route_template,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.replay is not None:
        if claim.replay.response_status == 201:
            # Plan section 14.2: Idempotent upload-slot replay returns attachment metadata only;
            # pre-signed URLs are not replayed.
            replay_body = {
                "attachment": claim.replay.response_body.get("attachment"),
                "state_version": claim.replay.response_body.get("state_version"),
            }
            return TicketCommandResult(200, replay_body, claim.replay.response_headers)
        return claim.replay

    try:
        with transaction.atomic():
            set_local_society_id(society_id)
            try:
                ticket = Ticket.objects.select_for_update().get(
                    id=ticket_id, society_id=society_id
                )
            except Ticket.DoesNotExist as exc:
                raise TicketSubmissionConflict(
                    code="TICKET_NOT_FOUND",
                    message="Ticket does not exist.",
                ) from exc

            if ticket.workflow_type != workflow_type:
                raise TicketSubmissionConflict(
                    code="TICKET_WORKFLOW_MISMATCH",
                    message="Ticket workflow type does not match requested route.",
                    ticket=ticket,
                )

            if ticket.state_version != expected_version:
                raise TicketSubmissionConflict(
                    code="TICKET_VERSION_MISMATCH",
                    message="Expected state version does not match current state version.",
                    ticket=ticket,
                )
            if ticket.status in {
                Ticket.Status.CANCELLED,
                Ticket.Status.CLOSED,
                Ticket.Status.MERGED,
            }:
                raise TicketSubmissionConflict(
                    code="TICKET_STATE_CONFLICT",
                    message="Attachments cannot be added to a closed, cancelled, or merged ticket.",
                    ticket=ticket,
                )

            # Authorize and lock active assignment/allocation rows
            uploader_persona = _lock_and_authorize_attachment_uploader(
                ticket=ticket,
                actor=actor,
                membership=membership,
            )

            storage_key = generate_attachment_storage_key()
            upload_slot = issue_attachment_upload_slot(
                storage_key=storage_key,
                content_type=content_type.strip().lower(),
                byte_size=byte_size,
            )

            attachment = TicketAttachment.objects.create(
                society_id=society_id,
                ticket=ticket,
                uploaded_by=actor,
                uploader_persona=uploader_persona,
                original_filename=filename.strip(),
                declared_content_type=content_type.strip().lower(),
                declared_byte_size=byte_size,
                storage_key=storage_key,
                status=TicketAttachment.Status.PENDING_UPLOAD,
            )
            ticket.state_version += 1
            ticket.save(update_fields=("state_version", "updated_at"))

            TicketEvent.objects.create(
                society_id=society_id,
                ticket=ticket,
                actor=actor,
                actor_persona=uploader_persona,
                ticket_version=ticket.state_version,
                previous_status=ticket.status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_ATTACHMENT_UPLOAD_SLOT_ISSUED,
                reason="",
                correlation_id=correlation_id,
                metadata={
                    "attachment_id": str(attachment.id),
                    "declared_content_type": attachment.declared_content_type,
                    "declared_byte_size": attachment.declared_byte_size,
                },
            )

            response_body = {
                "attachment": {
                    "id": str(attachment.id),
                    "ticket_id": str(ticket.id),
                    "original_filename": attachment.original_filename,
                    "declared_content_type": attachment.declared_content_type,
                    "declared_byte_size": attachment.declared_byte_size,
                    "status": attachment.status,
                    "created_at": attachment.created_at.isoformat(),
                },
                "upload_url": upload_slot.upload_url,
                "upload_headers": upload_slot.headers,
                "expires_at": upload_slot.expires_at.isoformat(),
                "state_version": ticket.state_version,
            }
            response_headers = {"X-Correlation-ID": str(correlation_id)}
            record = IdempotencyRecord.objects.select_for_update().get(id=claim.record_id)
            _complete_claim(
                record=record,
                response_status=201,
                response_body=response_body,
                response_headers=response_headers,
            )
            return TicketCommandResult(201, response_body, response_headers)
    except (TicketAttachmentForbidden, TicketAttachmentValidationForbidden, AttachmentStorageError):
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise
    except TicketSubmissionConflict as conflict:
        return _complete_conflict(
            society_id=society_id,
            record_id=claim.record_id,
            conflict=conflict,
            correlation_id=correlation_id,
        )
    except Exception:
        _discard_claim(society_id=society_id, record_id=claim.record_id)
        raise


def complete_and_promote_attachment(
    *,
    society_id,
    attachment_id,
    actor=None,
    correlation_id=None,
) -> TicketAttachment:
    """Scan quarantine object and promote to available or mark rejected with audit evidence."""
    with tenant_atomic(society_id) as normalized_id:
        try:
            attachment = TicketAttachment.objects.select_for_update().get(
                id=attachment_id, society_id=normalized_id
            )
        except TicketAttachment.DoesNotExist:
            raise TicketAttachmentNotFoundError("Ticket attachment does not exist.")

        if attachment.status in {
            TicketAttachment.Status.AVAILABLE,
            TicketAttachment.Status.REJECTED,
        }:
            return attachment

        ticket = Ticket.objects.select_for_update().get(
            id=attachment.ticket_id, society_id=normalized_id
        )

        scan_result = scan_and_promote_storage_object(
            quarantine_storage_key=attachment.storage_key,
            declared_content_type=attachment.declared_content_type,
            declared_byte_size=attachment.declared_byte_size,
        )

        effective_actor = actor or attachment.uploaded_by
        effective_persona = attachment.uploader_persona
        cid = correlation_id or uuid.uuid4()

        if scan_result.is_clean:
            attachment.status = TicketAttachment.Status.AVAILABLE
            attachment.storage_key = scan_result.clean_storage_key
            attachment.checksum_sha256 = scan_result.checksum_sha256
            attachment.actual_content_type = scan_result.actual_content_type
            attachment.actual_byte_size = scan_result.actual_byte_size
            attachment.save(
                update_fields=(
                    "status",
                    "storage_key",
                    "checksum_sha256",
                    "actual_content_type",
                    "actual_byte_size",
                    "updated_at",
                )
            )

            ticket.state_version += 1
            ticket.save(update_fields=("state_version", "updated_at"))

            TicketEvent.objects.create(
                society_id=normalized_id,
                ticket=ticket,
                actor=effective_actor,
                actor_persona=effective_persona,
                ticket_version=ticket.state_version,
                previous_status=ticket.status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_ATTACHMENT_PROMOTED,
                reason="Attachment passed malware scan and verified clean.",
                correlation_id=cid,
                metadata={
                    "attachment_id": str(attachment.id),
                    "checksum_sha256": scan_result.checksum_sha256,
                    "actual_byte_size": scan_result.actual_byte_size,
                    "actual_content_type": scan_result.actual_content_type,
                },
            )
        else:
            attachment.status = TicketAttachment.Status.REJECTED
            if scan_result.checksum_sha256:
                attachment.checksum_sha256 = scan_result.checksum_sha256
            if scan_result.actual_content_type:
                attachment.actual_content_type = scan_result.actual_content_type
            if scan_result.actual_byte_size:
                attachment.actual_byte_size = scan_result.actual_byte_size
            attachment.save(
                update_fields=(
                    "status",
                    "checksum_sha256",
                    "actual_content_type",
                    "actual_byte_size",
                    "updated_at",
                )
            )

            ticket.state_version += 1
            ticket.save(update_fields=("state_version", "updated_at"))

            TicketEvent.objects.create(
                society_id=normalized_id,
                ticket=ticket,
                actor=effective_actor,
                actor_persona=effective_persona,
                ticket_version=ticket.state_version,
                previous_status=ticket.status,
                new_status=ticket.status,
                event_type=TicketEvent.EventType.TICKET_ATTACHMENT_REJECTED,
                reason=scan_result.rejection_reason or "Attachment failed validation or scan.",
                correlation_id=cid,
                metadata={
                    "attachment_id": str(attachment.id),
                    "threat_name": scan_result.threat_name,
                    "error_code": scan_result.error_code,
                },
            )

        return attachment
