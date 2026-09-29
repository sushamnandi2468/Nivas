from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.identity.models import User
from apps.tenancy.models import Society, StaffMembership


def test_society_normalizes_registration_and_currency_codes():
    society = Society(registration_code=" niv-001 ", currency=" inr ")

    society.full_clean(validate_unique=False)

    assert society.registration_code == "NIV-001"
    assert society.currency == "INR"
    assert society.timezone == "Asia/Kolkata"
    assert society.locale == "en-IN"


def test_staff_membership_rejects_invalid_period():
    starts_at = timezone.now()
    membership = StaffMembership(
        starts_at=starts_at,
        ends_at=starts_at - timedelta(seconds=1),
    )

    with pytest.raises(ValidationError) as error:
        membership.clean()

    assert "ends_at" in error.value.message_dict


def test_staff_membership_current_state_includes_account_and_society_state():
    instant = timezone.now()
    membership = StaffMembership(
        is_active=True,
        starts_at=instant - timedelta(days=1),
        ends_at=instant + timedelta(days=1),
    )
    membership.society = Society(registration_code="NIV-001", is_active=True)
    membership.user = User(phone="+919876543210", is_active=True)

    assert membership.is_current(at=instant) is True

    membership.society.is_active = False

    assert membership.is_current(at=instant) is False