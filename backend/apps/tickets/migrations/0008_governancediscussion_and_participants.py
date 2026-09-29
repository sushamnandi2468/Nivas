import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tickets", "0007_governancereviewassignment_and_event_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="GovernanceDiscussion",
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
                ("purpose", models.TextField()),
                ("opened_at", models.DateTimeField(auto_now_add=True)),
                (
                    "opened_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="opened_governance_discussions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "society",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="governance_discussions",
                        to="tenancy.society",
                    ),
                ),
                (
                    "ticket",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="governance_discussion",
                        to="tickets.ticket",
                    ),
                ),
            ],
            options={
                "db_table": "tickets_governance_discussion",
                "ordering": ("society_id", "opened_at", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("society", "id"),
                        name="tickets_gov_discussion_society_id_uniq",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="GovernanceDiscussionParticipant",
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
                ("joined_at", models.DateTimeField(auto_now_add=True)),
                (
                    "discussion",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="participants",
                        to="tickets.governancediscussion",
                    ),
                ),
                (
                    "society",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="governance_discussion_participants",
                        to="tenancy.society",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="governance_discussion_participations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "tickets_governance_discussion_participant",
                "ordering": ("society_id", "discussion_id", "joined_at", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("society", "id"),
                        name="tickets_gov_disc_part_society_id_uniq",
                    ),
                    models.UniqueConstraint(
                        fields=("society", "discussion", "user"),
                        name="tickets_gov_disc_part_user_uniq",
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
                    ("GOVERNANCE_DISCUSSION_OPENED", "Governance discussion opened"),
                ],
                max_length=64,
            ),
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE tickets_governance_discussion
                ADD CONSTRAINT tickets_gov_discussion_society_ticket_fk
                FOREIGN KEY (society_id, ticket_id)
                REFERENCES tickets_ticket (society_id, id)
                DEFERRABLE INITIALLY DEFERRED;

                ALTER TABLE tickets_governance_discussion_participant
                ADD CONSTRAINT tickets_gov_disc_part_society_disc_fk
                FOREIGN KEY (society_id, discussion_id)
                REFERENCES tickets_governance_discussion (society_id, id)
                DEFERRABLE INITIALLY DEFERRED;

                ALTER TABLE tickets_governance_discussion ENABLE ROW LEVEL SECURITY;
                ALTER TABLE tickets_governance_discussion FORCE ROW LEVEL SECURITY;
                ALTER TABLE tickets_governance_discussion_participant ENABLE ROW LEVEL SECURITY;
                ALTER TABLE tickets_governance_discussion_participant FORCE ROW LEVEL SECURITY;

                CREATE POLICY tickets_gov_discussion_society_isolation
                ON tickets_governance_discussion
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

                CREATE POLICY tickets_gov_disc_part_society_isolation
                ON tickets_governance_discussion_participant
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
                DROP POLICY IF EXISTS tickets_gov_disc_part_society_isolation
                    ON tickets_governance_discussion_participant;
                DROP POLICY IF EXISTS tickets_gov_discussion_society_isolation
                    ON tickets_governance_discussion;
                ALTER TABLE tickets_governance_discussion_participant NO FORCE ROW LEVEL SECURITY;
                ALTER TABLE tickets_governance_discussion_participant DISABLE ROW LEVEL SECURITY;
                ALTER TABLE tickets_governance_discussion NO FORCE ROW LEVEL SECURITY;
                ALTER TABLE tickets_governance_discussion DISABLE ROW LEVEL SECURITY;
                ALTER TABLE tickets_governance_discussion_participant
                    DROP CONSTRAINT IF EXISTS tickets_gov_disc_part_society_disc_fk;
                ALTER TABLE tickets_governance_discussion
                    DROP CONSTRAINT IF EXISTS tickets_gov_discussion_society_ticket_fk;
            """,
        ),
    ]