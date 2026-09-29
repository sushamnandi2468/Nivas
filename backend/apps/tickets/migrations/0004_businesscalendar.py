import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0006_vendor_vendorcontract_vendorstaffmembership_and_more"),
        ("tickets", "0003_slapolicysnapshot_slapolicybinding_slacycle_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="BusinessCalendar",
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
                ("version", models.PositiveIntegerField()),
                ("timezone", models.CharField(max_length=64)),
                ("working_intervals", models.JSONField(blank=True, default=list)),
                ("holidays", models.JSONField(blank=True, default=list)),
                ("is_emergency_24x7", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("retired_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "society",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="business_calendars",
                        to="tenancy.society",
                    ),
                ),
            ],
            options={
                "db_table": "tickets_business_calendar",
                "ordering": ("society_id", "-version"),
            },
        ),
        migrations.AddConstraint(
            model_name="businesscalendar",
            constraint=models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_calendar_society_id_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="businesscalendar",
            constraint=models.UniqueConstraint(
                fields=("society", "version"),
                name="tickets_calendar_society_version_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="businesscalendar",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("society",),
                name="tickets_calendar_active_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="businesscalendar",
            constraint=models.CheckConstraint(
                condition=models.Q(("version__gte", 1)),
                name="tickets_calendar_positive_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="businesscalendar",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("is_active", False),
                    models.Q(("is_active", True), ("retired_at__isnull", True)),
                    _connector="OR",
                ),
                name="tickets_calendar_retirement_state",
            ),
        ),
        migrations.RunSQL(
            sql="""
                ALTER TABLE tickets_business_calendar ENABLE ROW LEVEL SECURITY;
                ALTER TABLE tickets_business_calendar FORCE ROW LEVEL SECURITY;

                CREATE POLICY tickets_calendar_society_isolation
                ON tickets_business_calendar
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

                CREATE FUNCTION tickets_guard_business_calendar_mutation()
                RETURNS trigger
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    IF TG_OP = 'DELETE' AND EXISTS (
                        SELECT 1 FROM tickets_sla_policy_snapshot
                        WHERE society_id = OLD.society_id
                            AND calendar_version = OLD.version
                    ) THEN
                        RAISE EXCEPTION 'A used business calendar cannot be deleted'
                            USING ERRCODE = '55000';
                    END IF;

                    IF TG_OP = 'UPDATE' THEN
                        IF EXISTS (
                            SELECT 1 FROM tickets_sla_policy_snapshot
                            WHERE society_id = OLD.society_id
                                AND calendar_version = OLD.version
                        ) AND (
                            OLD.society_id IS DISTINCT FROM NEW.society_id
                            OR OLD.version IS DISTINCT FROM NEW.version
                            OR OLD.timezone IS DISTINCT FROM NEW.timezone
                            OR OLD.working_intervals IS DISTINCT FROM NEW.working_intervals
                            OR OLD.holidays IS DISTINCT FROM NEW.holidays
                            OR OLD.is_emergency_24x7 IS DISTINCT FROM NEW.is_emergency_24x7
                        ) THEN
                            RAISE EXCEPTION 'A used business calendar is immutable'
                                USING ERRCODE = '55000';
                        END IF;

                        IF OLD.is_active AND NOT NEW.is_active AND NOT EXISTS (
                            SELECT 1 FROM tickets_business_calendar
                            WHERE society_id = OLD.society_id
                                AND id <> OLD.id
                                AND retired_at IS NULL
                        ) THEN
                            RAISE EXCEPTION 'Create a replacement calendar before retirement'
                                USING ERRCODE = '55000';
                        END IF;
                    END IF;
                    RETURN COALESCE(NEW, OLD);
                END;
                $$;

                CREATE TRIGGER tickets_business_calendar_guard
                BEFORE UPDATE OR DELETE ON tickets_business_calendar
                FOR EACH ROW EXECUTE FUNCTION tickets_guard_business_calendar_mutation();
            """,
            reverse_sql="""
                DROP TRIGGER IF EXISTS tickets_business_calendar_guard
                    ON tickets_business_calendar;
                DROP FUNCTION IF EXISTS tickets_guard_business_calendar_mutation();
                DROP POLICY IF EXISTS tickets_calendar_society_isolation
                    ON tickets_business_calendar;
                ALTER TABLE tickets_business_calendar NO FORCE ROW LEVEL SECURITY;
                ALTER TABLE tickets_business_calendar DISABLE ROW LEVEL SECURITY;
            """,
        ),
    ]