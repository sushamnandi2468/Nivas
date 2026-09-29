from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tickets", "0005_ticketcomment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ticketevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("TICKET_SUBMITTED", "Ticket submitted"),
                    ("TICKET_CANCELLED", "Ticket cancelled"),
                ],
                max_length=64,
            ),
        ),
    ]