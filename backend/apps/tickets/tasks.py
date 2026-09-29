import uuid
from datetime import timedelta

from celery import shared_task
from django.db import models as dj_models
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from apps.identity.models import User
from apps.tenancy.context import tenant_atomic
from apps.tenancy.models import UnitOccupancy
from apps.tickets.completion_delivery import (
    CompletionOtpCapsuleUnavailable,
    delete_completion_otp_capsule,
    retrieve_completion_otp_capsule,
)
from apps.tickets.completion_email import (
    CompletionEmailSubmissionFailed,
    CompletionEmailSubmissionUnknown,
    submit_completion_otp_email,
)
from apps.tickets.models import Ticket, TicketAttachment, TicketCompletionChallenge, TicketOutboxEvent
from apps.tickets.services import (
    TicketAttachmentNotFoundError,
    TicketOutboxClaimLost,
    claim_ticket_outbox_events,
    complete_and_promote_attachment,
    dead_letter_ticket_outbox_event,
    mark_ticket_outbox_event_submitted,
    release_ticket_outbox_event_for_retry,
)


@shared_task
def publish_ticket_completion_notifications(society_id, batch_size=50):
    claim_token = uuid.uuid4()
    claimed_events = claim_ticket_outbox_events(
        society_id=society_id,
        claim_token=claim_token,
        batch_size=batch_size,
        event_type=TicketOutboxEvent.EventType.SERVICE_COMPLETION_NOTIFICATION_REQUESTED,
    )
    outcome = {"submitted": 0, "retried": 0, "dead_lettered": 0, "claim_lost": 0}
    for event in claimed_events:
        _publish_claimed_completion_notification(
            society_id=society_id,
            outbox_event_id=event.id,
            claim_token=claim_token,
            outcome=outcome,
        )
    return outcome


def _publish_claimed_completion_notification(
    *, society_id, outbox_event_id, claim_token, outcome
):
    context = None
    try:
        context = _completion_notification_context(
            society_id=society_id,
            outbox_event_id=outbox_event_id,
        )
        if context["expires_at"] <= timezone.now():
            _dead_letter_claim(
                society_id=society_id,
                outbox_event_id=outbox_event_id,
                claim_token=claim_token,
                error_code="OTP_EXPIRED_BEFORE_SUBMISSION",
                outcome=outcome,
            )
            return
        otp_code = retrieve_completion_otp_capsule(
            capsule_name=context["capsule_name"]
        )
        if not otp_code:
            raise CompletionOtpCapsuleUnavailable("Completion OTP capsule is unavailable.")
        provider_message_id = submit_completion_otp_email(
            outbox_event_id=outbox_event_id,
            recipient=context["recipient_email"],
            ticket_number=context["ticket_number"],
            otp_code=otp_code,
        )
        mark_ticket_outbox_event_submitted(
            society_id=society_id,
            outbox_event_id=outbox_event_id,
            claim_token=claim_token,
            provider_message_id=provider_message_id,
        )
        outcome["submitted"] += 1
        try:
            delete_completion_otp_capsule(capsule_name=context["capsule_name"])
        except CompletionOtpCapsuleUnavailable:
            pass
    except TicketOutboxClaimLost:
        outcome["claim_lost"] += 1
    except ImproperlyConfigured:
        _dead_letter_claim(
            society_id=society_id,
            outbox_event_id=outbox_event_id,
            claim_token=claim_token,
            error_code="DELIVERY_CONFIGURATION_ERROR",
            outcome=outcome,
        )
    except CompletionEmailSubmissionFailed:
        _retry_or_dead_letter_claim(
            society_id=society_id,
            outbox_event_id=outbox_event_id,
            claim_token=claim_token,
            expires_at=context["expires_at"] if context else None,
            error_code="EMAIL_PROVIDER_UNAVAILABLE",
            outcome=outcome,
        )
    except CompletionEmailSubmissionUnknown:
        _dead_letter_claim(
            society_id=society_id,
            outbox_event_id=outbox_event_id,
            claim_token=claim_token,
            error_code="EMAIL_PROVIDER_OUTCOME_UNKNOWN",
            outcome=outcome,
        )
    except CompletionOtpCapsuleUnavailable:
        _retry_or_dead_letter_claim(
            society_id=society_id,
            outbox_event_id=outbox_event_id,
            claim_token=claim_token,
            expires_at=context["expires_at"] if context else None,
            error_code="OTP_CAPSULE_UNAVAILABLE",
            outcome=outcome,
        )
    except ValueError:
        _dead_letter_claim(
            society_id=society_id,
            outbox_event_id=outbox_event_id,
            claim_token=claim_token,
            error_code="RECIPIENT_UNAVAILABLE",
            outcome=outcome,
        )


def _completion_notification_context(*, society_id, outbox_event_id):
    with tenant_atomic(society_id) as normalized_society_id:
        event = TicketOutboxEvent.objects.select_for_update().get(id=outbox_event_id)
        if event.event_type != (
            TicketOutboxEvent.EventType.SERVICE_COMPLETION_NOTIFICATION_REQUESTED
        ):
            raise ValueError("Outbox event is not a completion notification.")
        challenge = TicketCompletionChallenge.objects.select_for_update().get(
            id=event.completion_challenge_id
        )
        ticket = Ticket.objects.select_for_update().get(id=event.ticket_id)
        recipient = User.objects.select_for_update().get(id=ticket.creator_id)
        instant = timezone.now()
        has_active_occupancy = UnitOccupancy.objects.select_for_update().filter(
            society_id=normalized_society_id,
            user_id=recipient.id,
            is_active=True,
            starts_at__lte=instant,
        ).filter(
            dj_models.Q(ends_at__isnull=True) | dj_models.Q(ends_at__gt=instant)
        ).exists()
        if (
            not recipient.is_active
            or not recipient.email
            or recipient.email_verified_at is None
            or not has_active_occupancy
            or not challenge.delivery_capsule_name
        ):
            raise ValueError("Completion notification recipient is unavailable.")
        return {
            "capsule_name": challenge.delivery_capsule_name,
            "expires_at": challenge.expires_at,
            "recipient_email": recipient.email,
            "ticket_number": ticket.ticket_number,
        }


def _retry_or_dead_letter_claim(
    *, society_id, outbox_event_id, claim_token, expires_at, error_code, outcome
):
    remaining = (expires_at - timezone.now()) if expires_at else timedelta()
    if remaining <= timedelta():
        _dead_letter_claim(
            society_id=society_id,
            outbox_event_id=outbox_event_id,
            claim_token=claim_token,
            error_code=error_code,
            outcome=outcome,
        )
        return
    retry_delay = min(timedelta(minutes=5), remaining)
    try:
        event = release_ticket_outbox_event_for_retry(
            society_id=society_id,
            outbox_event_id=outbox_event_id,
            claim_token=claim_token,
            error_code=error_code,
            retry_delay=retry_delay,
        )
    except TicketOutboxClaimLost:
        outcome["claim_lost"] += 1
        return
    if event.status == TicketOutboxEvent.Status.DEAD_LETTER:
        outcome["dead_lettered"] += 1
    else:
        outcome["retried"] += 1


def _dead_letter_claim(*, society_id, outbox_event_id, claim_token, error_code, outcome):
    try:
        dead_letter_ticket_outbox_event(
            society_id=society_id,
            outbox_event_id=outbox_event_id,
            claim_token=claim_token,
            error_code=error_code,
        )
    except TicketOutboxClaimLost:
        outcome["claim_lost"] += 1
        return
    outcome["dead_lettered"] += 1


@shared_task
def scan_and_promote_attachment(society_id, attachment_id, actor_id=None):
    """Celery task to scan and promote a single quarantined attachment."""
    actor = None
    if actor_id:
        actor = User.objects.filter(id=actor_id).first()
    try:
        attachment = complete_and_promote_attachment(
            society_id=society_id,
            attachment_id=attachment_id,
            actor=actor,
        )
        return {
            "attachment_id": str(attachment.id),
            "status": attachment.status,
            "storage_key": attachment.storage_key,
        }
    except TicketAttachmentNotFoundError:
        return {"error": "ATTACHMENT_NOT_FOUND", "attachment_id": str(attachment_id)}


@shared_task
def process_quarantined_attachments(society_id, batch_size=50):
    """Batch sweeper task to process all quarantined attachments for a society."""
    with tenant_atomic(society_id) as normalized_id:
        attachment_ids = list(
            TicketAttachment.objects.filter(
                society_id=normalized_id,
                status=TicketAttachment.Status.QUARANTINED,
            ).values_list("id", flat=True)[:batch_size]
        )

    results = {"scanned": 0, "available": 0, "rejected": 0}
    for att_id in attachment_ids:
        try:
            att = complete_and_promote_attachment(
                society_id=society_id,
                attachment_id=att_id,
            )
            results["scanned"] += 1
            if att.status == TicketAttachment.Status.AVAILABLE:
                results["available"] += 1
            elif att.status == TicketAttachment.Status.REJECTED:
                results["rejected"] += 1
        except Exception:
            pass
    return results