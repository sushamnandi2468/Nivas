import datetime
import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("platform_access", "0002_platformaccessevent"),
        ("tenancy", "0006_vendor_vendorcontract_vendorstaffmembership_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformSupportSession",
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
                ("session_version", models.PositiveIntegerField()),
                ("case_reference", models.CharField(max_length=128)),
                ("reason", models.TextField()),
                ("requested_duration_minutes", models.PositiveSmallIntegerField()),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("expires_at", models.DateTimeField()),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                (
                    "end_reason",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("ENDED_BY_USER", "Ended by user"),
                            ("EXPIRED", "Expired"),
                        ],
                        max_length=32,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "ended_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ended_platform_support_sessions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "role_grant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="support_sessions",
                        to="platform_access.platformrolegrant",
                    ),
                ),
                (
                    "society",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="platform_support_sessions",
                        to="tenancy.society",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="platform_support_sessions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "platform_support_session",
                "ordering": ("-started_at", "id"),
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "platform_role__in",
                                ("PLATFORM_SUPPORT", "PLATFORM_AUDITOR"),
                            )
                        ),
                        name="platform_session_eligible_role",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("requested_duration_minutes__gte", 5),
                            ("requested_duration_minutes__lte", 30),
                        ),
                        name="platform_session_duration_range",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "expires_at__gte",
                                models.F("started_at") + datetime.timedelta(minutes=5),
                            ),
                            (
                                "expires_at__lte",
                                models.F("started_at") + datetime.timedelta(minutes=30),
                            ),
                        ),
                        name="platform_session_valid_period",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(
                                ("end_reason", ""),
                                ("ended_at__isnull", True),
                                ("ended_by__isnull", True),
                            ),
                            models.Q(
                                ("ended_at__gte", models.F("started_at")),
                                ("ended_at__isnull", False),
                                models.Q(("end_reason", ""), _negated=True),
                            ),
                            _connector="OR",
                        ),
                        name="platform_session_end_metadata",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("ended_at__isnull", True)),
                        fields=("user",),
                        name="platform_session_one_open_per_user",
                    ),
                ],
            },
        ),
    ]