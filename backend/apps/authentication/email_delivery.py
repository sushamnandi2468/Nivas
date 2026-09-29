from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def send_auth_email(*, recipient, subject, html_content, plain_text_content):
    backend = settings.PUBLIC_AUTH_EMAIL_BACKEND
    if backend == "azure_communication_services":
        if not settings.ACS_EMAIL_ENDPOINT or not settings.ACS_EMAIL_SENDER:
            raise ImproperlyConfigured(
                "ACS_EMAIL_ENDPOINT and ACS_EMAIL_SENDER are required for ACS email delivery."
            )

        from azure.communication.email import EmailClient
        from azure.identity import DefaultAzureCredential

        client = EmailClient(settings.ACS_EMAIL_ENDPOINT, DefaultAzureCredential())
        poller = client.begin_send(
            {
                "senderAddress": settings.ACS_EMAIL_SENDER,
                "recipients": {"to": [{"address": recipient}]},
                "content": {
                    "subject": subject,
                    "plainText": plain_text_content,
                    "html": html_content,
                },
            }
        )
        poller.result()
        return

    if backend == "disabled":
        raise ImproperlyConfigured("Public authentication email delivery is disabled.")

    raise ImproperlyConfigured("PUBLIC_AUTH_EMAIL_BACKEND is not supported.")