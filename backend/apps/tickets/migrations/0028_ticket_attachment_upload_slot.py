# Generated for ticket attachment upload slot issuance

import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


_SOCIETY_POLICY = """
    society_id = CASE
        WHEN current_setting('app.society_id', true) ~*
            '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
        THEN current_setting('app.society_id', true)::uuid
        ELSE NULL
    END
"""


class Migration(migrations.Migration):

    dependencies = [
        ("tenancy", "0006_vendor_vendorcontract_vendorstaffmembership_and_more"),
        ("tickets", "0027_ticket_outbox_provider_submission"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="ticketevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("TICKET_SUBMITTED", "Ticket submitted"),
                    ("TICKET_CANCELLED", "Ticket cancelled"),
                    ("TICKET_ASSIGNED", "Ticket assigned"),
                    ("TICKET_ASSIGNMENT_ACCEPTED", "Ticket assignment accepted"),
                    ("TICKET_ASSIGNMENT_REJECTED", "Ticket assignment rejected"),
                    ("VENDOR_WORKER_ALLOCATED", "Vendor worker allocated"),
                    ("VENDOR_WORKER_REPLACED", "Vendor worker replaced"),
                    ("TICKET_WORK_STARTED", "Ticket work started"),
                    ("TICKET_COMPLETION_REQUESTED", "Ticket completion requested"),
                    ("TICKET_RESOLVED", "Ticket resolved"),
                    ("TICKET_ESTIMATE_SUBMITTED", "Ticket estimate submitted"),
                    ("TICKET_ESTIMATE_APPROVED", "Ticket estimate approved"),
                    ("TICKET_ESTIMATE_REJECTED", "Ticket estimate rejected"),
                    ("TICKET_ESTIMATE_WITHDRAWN", "Ticket estimate withdrawn"),
                    ("TICKET_REOPENED", "Ticket reopened"),
                    ("TICKET_CLOSED", "Ticket closed"),
                    ("TICKET_TRIAGE_REASSIGNED", "Ticket triage reassigned"),
                    ("TICKET_TRIAGE_RESUMED_OVERRIDE", "Ticket triage resumed by supervisor override"),
                    ("TICKET_RESOLVED_OVERRIDE", "Ticket resolved by supervisor override"),
                    ("TICKET_RATED", "Ticket rated"),
                    ("TICKET_MERGED", "Ticket merged"),
                    ("TICKET_MERGE_ATTACHED", "Secondary ticket merged into this ticket"),
                    ("TICKET_UNMERGED", "Ticket unmerged"),
                    ("GOVERNANCE_REVIEW_BEGUN", "Governance review begun"),
                    ("GOVERNANCE_DISCUSSION_OPENED", "Governance discussion opened"),
                    ("GOVERNANCE_ACTION_RECORDED", "Governance action recorded"),
                    ("TICKET_ATTACHMENT_UPLOAD_SLOT_ISSUED", "Ticket attachment upload slot issued"),
                ],
                max_length=64,
            ),
        ),
        migrations.CreateModel(
            name="TicketAttachment",
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
                ("uploader_persona", models.CharField(max_length=32)),
                ("original_filename", models.CharField(max_length=255)),
                ("declared_content_type", models.CharField(max_length=128)),
                ("declared_byte_size", models.BigIntegerField()),
                ("storage_key", models.CharField(max_length=255, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING_UPLOAD", "Pending upload"),
                            ("QUARANTINED", "Quarantined"),
                            ("AVAILABLE", "Available"),
                            ("REJECTED", "Rejected"),
                        ],
                        default="PENDING_UPLOAD",
                        max_length=32,
                    ),
                ),
                ("checksum_sha256", models.CharField(blank=True, max_length=64, null=True)),
                ("actual_content_type", models.CharField(blank=True, max_length=128, null=True)),
                ("actual_byte_size", models.BigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "society",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ticket_attachments",
                        to="tenancy.society",
                    ),
                ),
                (
                    "ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="attachments",
                        to="tickets.ticket",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ticket_attachments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "tickets_ticket_attachment",
                "ordering": ("society_id", "ticket_id", "-created_at"),
            },
        ),
        migrations.AddConstraint(
            model_name="ticketattachment",
            constraint=models.UniqueConstraint(
                fields=("society", "id"),
                name="tickets_attachment_society_id_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="ticketattachment",
            constraint=models.UniqueConstraint(
                fields=("society", "storage_key"),
                name="tickets_attachment_society_storage_key_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="ticketattachment",
            constraint=models.CheckConstraint(
                condition=models.Q(("declared_byte_size__gt", 0)),
                name="tickets_attachment_declared_byte_size_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="ticketattachment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("actual_byte_size__isnull", True),
                    ("actual_byte_size__gt", 0),
                    _connector="OR",
                ),
                name="tickets_attachment_actual_byte_size_positive",
            ),
        ),
        migrations.AddIndex(
            model_name="ticketattachment",
            index=models.Index(
                fields=("society", "ticket", "created_at"),
                name="tickets_attach_ticket_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="ticketattachment",
            index=models.Index(
                fields=("society", "status"),
                name="tickets_attach_status_idx",
            ),
        ),
        migrations.RunSQL(
            sql=f"""
                ALTER TABLE tickets_ticket_attachment
                ADD CONSTRAINT tickets_attachment_society_ticket_fk
                FOREIGN KEY (society_id, ticket_id)
                REFERENCES tickets_ticket (society_id, id)
                DEFERRABLE INITIALLY DEFERRED;

                ALTER TABLE tickets_ticket_attachment ENABLE ROW LEVEL SECURITY;
                ALTER TABLE tickets_ticket_attachment FORCE ROW LEVEL SECURITY;

                CREATE POLICY tickets_attachment_society_isolation
                ON tickets_ticket_attachment
                USING ({_SOCIETY_POLICY})
                WITH CHECK ({_SOCIETY_POLICY});
            """,
            reverse_sql="""
                DROP POLICY IF EXISTS tickets_attachment_society_isolation ON tickets_ticket_attachment;

                ALTER TABLE tickets_ticket_attachment NO FORCE ROW LEVEL SECURITY;
                ALTER TABLE tickets_ticket_attachment DISABLE ROW LEVEL SECURITY;

                ALTER TABLE tickets_ticket_attachment DROP CONSTRAINT IF EXISTS tickets_attachment_society_ticket_fk;
            """,
        ),
    ]
