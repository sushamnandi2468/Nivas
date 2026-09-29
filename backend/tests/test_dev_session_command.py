import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import AccessToken

pytestmark = pytest.mark.django_db(transaction=True)


def test_dev_session_command_fails_closed(settings):
    settings.DEBUG = True
    settings.ALLOW_DEV_SESSION_BOOTSTRAP = False

    with pytest.raises(CommandError, match="Development sessions require"):
        call_command("dev_session")


def test_dev_session_command_emits_real_idempotent_session(settings):
    settings.DEBUG = True
    settings.ALLOW_DEV_SESSION_BOOTSTRAP = True
    first_stdout = StringIO()
    second_stdout = StringIO()

    call_command(
        "dev_session",
        phone="+919876543220",
        society_code="NIV-COMMAND",
        role="HELPDESK_OPERATOR",
        stdout=first_stdout,
    )
    call_command(
        "dev_session",
        phone="+919876543220",
        society_code="NIV-COMMAND",
        role="HELPDESK_OPERATOR",
        stdout=second_stdout,
    )

    first_session = json.loads(first_stdout.getvalue())
    second_session = json.loads(second_stdout.getvalue())
    token = AccessToken(first_session["access_token"])

    assert first_session["society_id"] == second_session["society_id"]
    assert first_session["membership_id"] == second_session["membership_id"]
    assert first_session["expires_in"] == 600
    assert first_session["role"] == "HELPDESK_OPERATOR"
    assert str(token["user_id"]) == first_session["user_id"]
    assert OutstandingToken.objects.count() == 0