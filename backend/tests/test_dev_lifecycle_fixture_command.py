import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction

from apps.identity.models import User
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import Society, TechnicianProfile
from apps.tickets.management.commands.dev_lifecycle_fixture import Command
from apps.tickets.models import Ticket, TicketCompletionChallenge, TicketEvent

pytestmark = pytest.mark.django_db(transaction=True)


def test_dev_lifecycle_fixture_command_fails_closed(settings):
    settings.DEBUG = True
    settings.ALLOW_DEV_LIFECYCLE_FIXTURE = False

    with pytest.raises(CommandError, match="Development lifecycle fixtures require"):
        call_command("dev_lifecycle_fixture", "--enable")


def test_dev_lifecycle_fixture_requires_completion_schema_before_writes(settings, monkeypatch):
    settings.DEBUG = True
    settings.ALLOW_DEV_LIFECYCLE_FIXTURE = True
    marker = "missing-schema"
    society_code = "NIV-MISSING-SCHEMA"
    resident_phone = Command._phone_for(marker, "resident")
    monkeypatch.setattr(connection.introspection, "table_names", lambda: [])

    with pytest.raises(CommandError, match="tickets_ticket_completion_challenge"):
        call_command(
            "dev_lifecycle_fixture",
            "--enable",
            "--society-code",
            society_code,
            "--marker",
            marker,
        )

    assert not Society.objects.filter(registration_code=society_code).exists()
    assert not User.objects.filter(phone=resident_phone).exists()


def test_dev_lifecycle_fixture_creates_and_reuses_resolved_service_ticket(settings):
    settings.DEBUG = True
    settings.ALLOW_DEV_LIFECYCLE_FIXTURE = True
    first_stdout = StringIO()
    second_stdout = StringIO()

    call_command(
        "dev_lifecycle_fixture",
        "--enable",
        "--society-code",
        "NIV-LIFECYCLE",
        "--marker",
        "browser-check",
        stdout=first_stdout,
    )
    call_command(
        "dev_lifecycle_fixture",
        "--enable",
        "--society-code",
        "NIV-LIFECYCLE",
        "--marker",
        "browser-check",
        stdout=second_stdout,
    )

    first_fixture = json.loads(first_stdout.getvalue())
    second_fixture = json.loads(second_stdout.getvalue())
    society = Society.objects.get(id=first_fixture["society_id"])

    assert first_fixture["ticket_id"] == second_fixture["ticket_id"]
    assert first_fixture["status"] == Ticket.Status.RESOLVED
    assert first_fixture["state_version"] == 7
    resident = User.objects.get(phone=Command._phone_for("browser-check", "resident"))
    assert resident.email == "dev-lifecycle-browser-check-resident@example.test"
    assert resident.email_verified_at is not None

    with transaction.atomic():
        set_local_society_id(society.id)
        ticket = Ticket.objects.get(id=first_fixture["ticket_id"])
        challenge = TicketCompletionChallenge.objects.get(ticket=ticket)
        technician = TechnicianProfile.objects.get(id=first_fixture["technician_id"])

        assert ticket.status == Ticket.Status.RESOLVED
        assert TicketEvent.objects.filter(ticket=ticket).count() == 6
        assert challenge.is_consumed is True
        assert technician.current_active_tickets_count == 0