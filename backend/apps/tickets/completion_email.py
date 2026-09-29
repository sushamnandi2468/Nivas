from html import escape

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class CompletionEmailSubmissionFailed(Exception):
    pass


class CompletionEmailSubmissionUnknown(Exception):
    pass


def submit_completion_otp_email(*, outbox_event_id, recipient, ticket_number, otp_code):
    backend = settings.TICKET_COMPLETION_EMAIL_BACKEND
    if backend == "test":
        return f"test-email-{outbox_event_id}"
    if backend == "azure_communication_services":
        if not settings.ACS_EMAIL_ENDPOINT or not settings.ACS_EMAIL_SENDER:
            raise ImproperlyConfigured(
                "ACS_EMAIL_ENDPOINT and ACS_EMAIL_SENDER are required for ACS email delivery."
            )
        from azure.communication.email import EmailClient
        from azure.identity import DefaultAzureCredential

        safe_ticket_number = escape(ticket_number)
        message = {
            "senderAddress": settings.ACS_EMAIL_SENDER,
            "recipients": {"to": [{"address": recipient}]},
            "content": {
                "subject": f"Confirm service completion for {ticket_number}",
                "plainText": (
                    f"Enter this code in NivasOps to confirm service completion for "
                    f"{ticket_number}: {otp_code}. This code expires in 10 minutes."
                ),
                "html": (
                    "<p>Enter this code in NivasOps to confirm service completion for "
                    f"{safe_ticket_number}:</p><p><strong>{otp_code}</strong></p>"
                    "<p>This code expires in 10 minutes.</p>"
                ),
            },
        }
        try:
            poller = EmailClient(
                settings.ACS_EMAIL_ENDPOINT, DefaultAzureCredential()
            ).begin_send(message)
        except Exception as exc:
            raise CompletionEmailSubmissionUnknown(
                "The completion email provider outcome is unknown."
            ) from exc
        try:
            result = poller.result()
        except Exception as exc:
            raise CompletionEmailSubmissionUnknown(
                "The completion email provider outcome is unknown."
            ) from exc
        provider_message_id = result.get("id") if isinstance(result, dict) else None
        if result.get("status") != "Succeeded":
            raise CompletionEmailSubmissionFailed(
                "The completion email provider did not accept the request."
            )
        if not provider_message_id:
            raise CompletionEmailSubmissionUnknown(
                "The completion email provider outcome is unknown."
            )
        return str(provider_message_id)
    if backend == "disabled":
        raise ImproperlyConfigured("Completion email delivery is disabled.")
    raise ImproperlyConfigured("TICKET_COMPLETION_EMAIL_BACKEND is not supported.")