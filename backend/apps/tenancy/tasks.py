from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from apps.tenancy.cache import tenant_cache_key
from apps.tenancy.context import tenant_atomic
from apps.tenancy.models import StaffMembership


@shared_task
def cache_active_staff_membership_count(society_id):
    with tenant_atomic(society_id) as normalized_id:
        instant = timezone.now()
        count = StaffMembership.objects.filter(
            society_id=normalized_id,
            is_active=True,
            starts_at__lte=instant,
        ).exclude(ends_at__lte=instant).count()

    cache_key = tenant_cache_key(normalized_id, "staff", "active-count")
    cache.set(cache_key, count, timeout=300)
    return {"cache_key": cache_key, "count": count, "society_id": str(normalized_id)}