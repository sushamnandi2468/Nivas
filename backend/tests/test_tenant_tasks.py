import pytest
from celery.contrib.testing.worker import start_worker
from django.conf import settings
from django.core.cache import cache

from apps.identity.models import User
from apps.tenancy.cache import tenant_cache_key
from apps.tenancy.context import tenant_atomic
from apps.tenancy.models import Society, StaffMembership
from apps.tenancy.tasks import cache_active_staff_membership_count
from config.celery import app as celery_app

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def tenant_cache_keys():
    keys = []
    yield keys
    for key in keys:
        cache.delete(key)


def create_membership(society, phone):
    user = User.objects.create_user(phone=phone)
    with tenant_atomic(society.id):
        return StaffMembership.objects.create(
            society=society,
            user=user,
            role=StaffMembership.Role.HELPDESK_OPERATOR,
        )


def test_celery_task_scopes_database_and_cache_by_society(tenant_cache_keys):
    society_a = Society.objects.create(registration_code="NIV-TASK-A")
    society_b = Society.objects.create(registration_code="NIV-TASK-B")
    create_membership(society_a, "+919876543221")
    create_membership(society_a, "+919876543222")
    create_membership(society_b, "+919876543223")

    tenant_cache_keys.extend(
        [
            tenant_cache_key(society_a.id, "staff", "active-count"),
            tenant_cache_key(society_b.id, "staff", "active-count"),
        ]
    )

    result_a = cache_active_staff_membership_count.apply(
        args=(str(society_a.id),), throw=True
    ).get()
    result_b = cache_active_staff_membership_count.apply(
        args=(str(society_b.id),), throw=True
    ).get()

    assert result_a["count"] == 2
    assert result_b["count"] == 1
    assert result_a["cache_key"] != result_b["cache_key"]
    assert cache.get(result_a["cache_key"]) == 2
    assert cache.get(result_b["cache_key"]) == 1
    assert StaffMembership.objects.count() == 0


@pytest.mark.skipif(
    not settings.CACHE_URL.startswith("rediss://"),
    reason="requires the Azure Redis integration configuration",
)
def test_celery_worker_executes_tenant_task_through_redis(tenant_cache_keys):
    society = Society.objects.create(registration_code="NIV-WORKER")
    create_membership(society, "+919876543224")
    expected_cache_key = tenant_cache_key(society.id, "staff", "active-count")
    tenant_cache_keys.append(expected_cache_key)

    original_eager_mode = celery_app.conf.task_always_eager
    celery_app.conf.update(task_always_eager=False)
    try:
        with start_worker(
            celery_app,
            pool="solo",
            concurrency=1,
            perform_ping_check=False,
        ):
            result = cache_active_staff_membership_count.delay(str(society.id))
            payload = result.get(timeout=30)
    finally:
        celery_app.conf.update(task_always_eager=original_eager_mode)

    assert payload == {
        "cache_key": expected_cache_key,
        "count": 1,
        "society_id": str(society.id),
    }
    assert cache.get(expected_cache_key) == 1
    assert StaffMembership.objects.count() == 0


def test_tenant_cache_key_rejects_ambiguous_segments():
    society = Society.objects.create(registration_code="NIV-CACHE")

    with pytest.raises(ValueError, match="namespace"):
        tenant_cache_key(society.id, "staff:other", "active-count")

    with pytest.raises(ValueError, match="identifier"):
        tenant_cache_key(society.id, "staff", "active:count")


def test_celery_task_rejects_invalid_society_id():
    with pytest.raises(ValueError, match="valid UUID"):
        cache_active_staff_membership_count.apply(
            args=("not-a-uuid",), throw=True
        ).get()