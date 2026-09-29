from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tenancy", "0007_membershipinvitation_invitee_email"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE tenancy_membership_invitation
                        ALTER COLUMN occupancy_type DROP NOT NULL,
                        ALTER COLUMN staff_role DROP NOT NULL,
                        ALTER COLUMN committee_role DROP NOT NULL;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[],
        ),
    ]