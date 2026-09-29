import uuid


def tenant_cache_key(society_id, namespace, identifier):
    try:
        normalized_id = uuid.UUID(str(society_id))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("society_id must be a valid UUID") from exc

    normalized_namespace = str(namespace).strip().lower()
    normalized_identifier = str(identifier).strip().lower()
    if not normalized_namespace or ":" in normalized_namespace:
        raise ValueError("namespace must be non-empty and cannot contain ':'")
    if not normalized_identifier or ":" in normalized_identifier:
        raise ValueError("identifier must be non-empty and cannot contain ':'")

    return f"tenant:{normalized_id}:{normalized_namespace}:{normalized_identifier}"