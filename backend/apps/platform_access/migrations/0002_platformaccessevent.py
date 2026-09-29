import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

CREATE_IMMUTABILITY_TRIGGER = """
CREATE OR REPLACE FUNCTION reject_platform_access_event_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'platform_access_event is append-only'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER platform_access_event_immutable
BEFORE UPDATE OR DELETE ON platform_access_event
FOR EACH ROW
EXECUTE FUNCTION reject_platform_access_event_mutation();
"""

DROP_IMMUTABILITY_TRIGGER = """
DROP TRIGGER IF EXISTS platform_access_event_immutable ON platform_access_event;
DROP FUNCTION IF EXISTS reject_platform_access_event_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("platform_access", "0001_initial"),
        ("tenancy", "0006_vendor_vendorcontract_vendorstaffmembership_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformAccessEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("occurred_at", models.DateTimeField(auto_now_add=True)),
                (
                    "platform_role",
                    models.CharField(
                        choices=[
                            ("PLATFORM_SUPPORT", "Platform support"),
                            ("PLATFORM_AUDITOR", "Platform auditor"),
                            ("PLATFORM_ADMIN", "Platform administrator"),
                        ],
                        max_length=32,
                    ),
                ),
                ("support_session_id", models.UUIDField()),
                ("case_reference", models.CharField(max_length=128)),
                ("reason", models.TextField()),
                ("correlation_id", models.UUIDField()),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("SESSION_REQUESTED", "Session requested"),
                            ("SESSION_STARTED", "Session started"),
                            ("TENANT_ROUTE_ACCESSED", "Tenant route accessed"),
                            ("ACCESS_DENIED", "Access denied"),
                            ("SESSION_ENDED", "Session ended"),
                            ("SESSION_EXPIRED", "Session expired"),
                            (
                                "RECOVERY_ACTION_ATTEMPTED",
                                "Recovery action attempted",
                            ),
                            (
                                "RECOVERY_ACTION_COMPLETED",
                                "Recovery action completed",
                            ),
                            (
                                "RECOVERY_ACTION_DENIED",
                                "Recovery action denied",
                            ),
                        ],
                        max_length=32,
                    ),
                ),
                ("route_or_action", models.CharField(max_length=255)),
                (
                    "outcome",
                    models.CharField(
                        choices=[
                            ("SUCCEEDED", "Succeeded"),
                            ("DENIED", "Denied"),
                            ("FAILED", "Failed"),
                        ],
                        max_length=16,
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="platform_access_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "role_grant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="access_events",
                        to="platform_access.platformrolegrant",
                    ),
                ),
                (
                    "society",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="platform_access_events",
                        to="tenancy.society",
                    ),
                ),
            ],
            options={
                "db_table": "platform_access_event",
                "ordering": ("occurred_at", "id"),
                "indexes": [
                    models.Index(
                        fields=["society", "occurred_at"],
                        name="platform_event_society_time",
                    ),
                    models.Index(
                        fields=["actor", "occurred_at"],
                        name="platform_event_actor_time",
                    ),
                    models.Index(
                        fields=["support_session_id", "occurred_at"],
                        name="platform_event_session_time",
                    ),
                ],
            },
        ),
        migrations.RunSQL(
            sql=CREATE_IMMUTABILITY_TRIGGER,
            reverse_sql=DROP_IMMUTABILITY_TRIGGER,
        ),
    ]