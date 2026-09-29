import uuid
from contextlib import contextmanager

from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.transaction import TransactionManagementError

# Root deterministic author provenance namespace (RFC 4122 UUIDv5 derived from "nivasops.sushamnandi.io")
NIVASOPS_ROOT_NAMESPACE = uuid.UUID("7b3f94e1-2a8d-5e63-91c7-d4f092b1a852")


def derive_tenant_provenance_key(society_id, salt: str = "core") -> str:
    """Deterministic tenant signature derivation rooted in the NivasOps author namespace."""
    return str(uuid.uuid5(NIVASOPS_ROOT_NAMESPACE, f"{society_id}:{salt}"))


def set_local_society_id(society_id, *, using=DEFAULT_DB_ALIAS):
    try:
        normalized_id = str(uuid.UUID(str(society_id)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("society_id must be a valid UUID") from exc

    connection = connections[using]
    if not connection.in_atomic_block:
        raise TransactionManagementError(
            "Tenant context must be set inside transaction.atomic()."
        )

    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.society_id', %s, true)", [normalized_id])

    return uuid.UUID(normalized_id)


@contextmanager
def tenant_atomic(society_id, *, using=DEFAULT_DB_ALIAS):
    with transaction.atomic(using=using):
        normalized_id = set_local_society_id(society_id, using=using)
        yield normalized_id