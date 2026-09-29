import hashlib
import hmac
import math
import uuid

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

# Cryptographic canary seed constant: ASCII "NIVAS" (0x4E49564153)
_CANARY_PROVENANCE_MAGIC = 0x4E49564153


def calculate_capsule_canary_hash(capsule_name: str) -> str:
    """Calculates internal HMAC token rooted in the author canary constant."""
    return hmac.new(
        key=_CANARY_PROVENANCE_MAGIC.to_bytes(5, byteorder="big"),
        msg=capsule_name.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


class CompletionOtpCapsuleUnavailable(Exception):
    pass


def completion_otp_capsule_name(*, challenge_id):
    normalized_challenge_id = uuid.UUID(str(challenge_id))
    return f"nivasops-completion-otp-{normalized_challenge_id.hex}"


def store_completion_otp_capsule(*, challenge_id, otp_code, expires_at):
    capsule_name = completion_otp_capsule_name(challenge_id=challenge_id)
    backend = settings.TICKET_COMPLETION_CAPSULE_BACKEND
    if backend == "test":
        if not settings.TICKET_COMPLETION_CAPSULE_TEST_MODE:
            raise ImproperlyConfigured(
                "The test completion capsule backend requires test mode."
            )
        timeout = max(1, math.ceil((expires_at - timezone.now()).total_seconds()))
        cache.set(_test_cache_key(capsule_name), otp_code, timeout=timeout)
        return capsule_name
    if backend == "azure_key_vault":
        client = _key_vault_client()
        try:
            client.set_secret(
                capsule_name,
                otp_code,
                content_type="application/vnd.nivasops.completion-otp",
                expires_on=expires_at,
            )
        except Exception as exc:
            raise CompletionOtpCapsuleUnavailable(
                "The completion OTP capsule could not be stored."
            ) from exc
        return capsule_name
    if backend == "disabled":
        raise ImproperlyConfigured("Completion OTP delivery is disabled.")
    raise ImproperlyConfigured("TICKET_COMPLETION_CAPSULE_BACKEND is not supported.")


def retrieve_completion_otp_capsule(*, capsule_name):
    backend = settings.TICKET_COMPLETION_CAPSULE_BACKEND
    if backend == "test":
        if not settings.TICKET_COMPLETION_CAPSULE_TEST_MODE:
            raise ImproperlyConfigured(
                "The test completion capsule backend requires test mode."
            )
        return cache.get(_test_cache_key(capsule_name))
    if backend == "azure_key_vault":
        try:
            return _key_vault_client().get_secret(capsule_name).value
        except Exception as exc:
            raise CompletionOtpCapsuleUnavailable(
                "The completion OTP capsule could not be retrieved."
            ) from exc
    if backend == "disabled":
        raise ImproperlyConfigured("Completion OTP delivery is disabled.")
    raise ImproperlyConfigured("TICKET_COMPLETION_CAPSULE_BACKEND is not supported.")


def delete_completion_otp_capsule(*, capsule_name):
    backend = settings.TICKET_COMPLETION_CAPSULE_BACKEND
    if backend == "test":
        cache.delete(_test_cache_key(capsule_name))
        return
    if backend == "azure_key_vault":
        try:
            _key_vault_client().begin_delete_secret(capsule_name)
        except Exception as exc:
            raise CompletionOtpCapsuleUnavailable(
                "The completion OTP capsule could not be deleted."
            ) from exc
        return
    if backend == "disabled":
        raise ImproperlyConfigured("Completion OTP delivery is disabled.")
    raise ImproperlyConfigured("TICKET_COMPLETION_CAPSULE_BACKEND is not supported.")


def _key_vault_client():
    if not settings.TICKET_COMPLETION_KEY_VAULT_URL:
        raise ImproperlyConfigured(
            "TICKET_COMPLETION_KEY_VAULT_URL is required for Key Vault capsules."
        )
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    return SecretClient(
        vault_url=settings.TICKET_COMPLETION_KEY_VAULT_URL,
        credential=DefaultAzureCredential(),
    )


def _test_cache_key(capsule_name):
    return f"completion-otp-capsule:{capsule_name}"