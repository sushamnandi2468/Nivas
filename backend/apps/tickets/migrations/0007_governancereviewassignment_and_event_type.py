import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tickets", "0006_alter_ticketevent_event_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="GovernanceReviewAssignment",
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
                ("reviewer_persona", models.CharField(max_length=32)),
                ("is_active", models.BooleanField(default=True)),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                ("accepted_at", models.DateTimeField()),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                (
                    "assigned_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assigned_governance_reviews",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "reviewer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="governance_reviews",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "society",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="governance_review_assignments",
                        to="tenancy.society",
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="governance_review_assignments",
                        to="tickets.ticket",
                    ),
                ),
            ],
            options={
                "db_table": "tickets_governance_review_assignment",
                "ordering": ("society_id", "ticket_id", "assigned_at", "id"),
                "indexes": [
                    models.Index(
                        fields=["society", "reviewer", "is_active"],
                        name="tickets_gov_review_reviewer",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("society", "id"),
                        name="tickets_governance_review_society_id_uniq",
                    ),
                    models.UniqueConstraint(
                        condition=Q(("is_active", True)),
                        fields=("society", "ticket"),
                        name="tickets_governance_review_one_active_uniq",
                    ),
                    models.CheckConstraint(
                        condition=Q(("ended_at__isnull", True))
                        | Q(("ended_at__gte", models.F("assigned_at"))),
                        name="tickets_governance_review_valid_period",
                    ),
                ],
            },
        ),
        migrations.AlterField(
            model_name="ticketevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("TICKET_SUBMITTED", "Ticket submitted"),
                    ("TICKET_CANCELLED", "Ticket cancelled"),
                    ("GOVERNANCE_REVIEW_BEGUN", "Governance review begun"),
                ],
                max_length=64,
            ),
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE tickets_governance_review_assignment
                ADD CONSTRAINT tickets_governance_review_society_ticket_fk
                FOREIGN KEY (society_id, ticket_id)
                REFERENCES tickets_ticket (society_id, id)
                DEFERRABLE INITIALLY DEFERRED;

                ALTER TABLE tickets_governance_review_assignment ENABLE ROW LEVEL SECURITY;
                ALTER TABLE tickets_governance_review_assignment FORCE ROW LEVEL SECURITY;

                CREATE POLICY tickets_governance_review_society_isolation
                ON tickets_governance_review_assignment
                USING (
                    society_id = CASE
                        WHEN current_setting('app.society_id', true) ~*
                            '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
                        THEN current_setting('app.society_id', true)::uuid
                        ELSE NULL
                    END
                )
                WITH CHECK (
                    society_id = CASE
                        WHEN current_setting('app.society_id', true) ~*
                            '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
                        THEN current_setting('app.society_id', true)::uuid
                        ELSE NULL
                    END
                );
            """,
            reverse_sql="""
                DROP POLICY IF EXISTS tickets_governance_review_society_isolation
                    ON tickets_governance_review_assignment;
                ALTER TABLE tickets_governance_review_assignment NO FORCE ROW LEVEL SECURITY;
                ALTER TABLE tickets_governance_review_assignment DISABLE ROW LEVEL SECURITY;
                ALTER TABLE tickets_governance_review_assignment
                    DROP CONSTRAINT IF EXISTS tickets_governance_review_society_ticket_fk;
            """,
        ),
    ]