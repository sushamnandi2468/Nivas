import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PlatformRoleGrant",
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
                    "role",
                    models.CharField(
                        choices=[
                            ("PLATFORM_SUPPORT", "Platform support"),
                            ("PLATFORM_AUDITOR", "Platform auditor"),
                            ("PLATFORM_ADMIN", "Platform administrator"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("ACTIVE", "Active"),
                            ("REVOKED", "Revoked"),
                        ],
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("reason", models.TextField()),
                ("starts_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("ends_at", models.DateTimeField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approved_platform_role_grants",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="requested_platform_role_grants",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "revoked_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="revoked_platform_role_grants",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="platform_role_grants",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "platform_role_grant",
                "ordering": ("user_id", "role", "created_at"),
            },
        ),
        migrations.AddConstraint(
            model_name="platformrolegrant",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("ends_at__isnull", True),
                    ("ends_at__gt", models.F("starts_at")),
                    _connector="OR",
                ),
                name="platform_role_grant_valid_period",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformrolegrant",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("approved_by__isnull", True),
                    models.Q(("approved_by", models.F("requested_by")), _negated=True),
                    _connector="OR",
                ),
                name="platform_role_grant_four_eyes",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformrolegrant",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("approved_at__isnull", True),
                        ("approved_by__isnull", True),
                        ("revoked_at__isnull", True),
                        ("revoked_by__isnull", True),
                        ("status", "PENDING"),
                    ),
                    models.Q(
                        ("approved_at__isnull", False),
                        ("approved_by__isnull", False),
                        ("revoked_at__isnull", True),
                        ("revoked_by__isnull", True),
                        ("status", "ACTIVE"),
                    ),
                    models.Q(
                        ("revoked_at__isnull", False),
                        ("revoked_by__isnull", False),
                        ("status", "REVOKED"),
                    ),
                    _connector="OR",
                ),
                name="platform_role_grant_status_metadata",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformrolegrant",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ("PENDING", "ACTIVE"))),
                fields=("user", "role"),
                name="platform_role_grant_open_unique",
            ),
        ),
    ]