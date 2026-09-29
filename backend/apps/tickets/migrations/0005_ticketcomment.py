import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tickets", "0004_businesscalendar"),
    ]

    operations = [
        migrations.CreateModel(
            name="TicketComment",
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
                ("author_persona", models.CharField(max_length=32)),
                (
                    "visibility",
                    models.CharField(
                        choices=[("PUBLIC", "Public"), ("INTERNAL", "Internal")],
                        default="PUBLIC",
                        max_length=16,
                    ),
                ),
                ("body", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "author",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ticket_comments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "society",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ticket_comments",
                        to="tenancy.society",
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="comments",
                        to="tickets.ticket",
                    ),
                ),
            ],
            options={
                "db_table": "tickets_ticket_comment",
                "ordering": ("created_at", "id"),
                "indexes": [
                    models.Index(
                        fields=["society", "ticket", "created_at"],
                        name="tickets_comment_ticket_time",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("society", "id"),
                        name="tickets_comment_society_id_uniq",
                    )
                ],
            },
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE tickets_ticket_comment
                ADD CONSTRAINT tickets_comment_society_ticket_fk
                FOREIGN KEY (society_id, ticket_id)
                REFERENCES tickets_ticket (society_id, id)
                DEFERRABLE INITIALLY DEFERRED;

                ALTER TABLE tickets_ticket_comment ENABLE ROW LEVEL SECURITY;
                ALTER TABLE tickets_ticket_comment FORCE ROW LEVEL SECURITY;

                CREATE POLICY tickets_comment_society_isolation
                ON tickets_ticket_comment
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

                CREATE FUNCTION tickets_reject_comment_mutation()
                RETURNS trigger
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RAISE EXCEPTION 'tickets_ticket_comment is immutable'
                        USING ERRCODE = '55000';
                END;
                $$;

                CREATE TRIGGER tickets_ticket_comment_immutable
                BEFORE UPDATE OR DELETE ON tickets_ticket_comment
                FOR EACH ROW EXECUTE FUNCTION tickets_reject_comment_mutation();
            """,
            reverse_sql="""
                DROP TRIGGER IF EXISTS tickets_ticket_comment_immutable
                    ON tickets_ticket_comment;
                DROP FUNCTION IF EXISTS tickets_reject_comment_mutation();
                DROP POLICY IF EXISTS tickets_comment_society_isolation
                    ON tickets_ticket_comment;
                ALTER TABLE tickets_ticket_comment NO FORCE ROW LEVEL SECURITY;
                ALTER TABLE tickets_ticket_comment DISABLE ROW LEVEL SECURITY;
                ALTER TABLE tickets_ticket_comment
                    DROP CONSTRAINT IF EXISTS tickets_comment_society_ticket_fk;
            """,
        ),
    ]