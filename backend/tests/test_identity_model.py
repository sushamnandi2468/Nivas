import uuid

import pytest
from django.core.exceptions import ValidationError

from apps.identity.models import User


def test_user_normalizes_identity_fields():
    user = User(
        phone="+91 98765 43210",
        email=" Resident@Example.COM ",
    )
    user.set_unusable_password()

    user.full_clean(validate_unique=False)

    assert isinstance(user.id, uuid.UUID)
    assert user.phone.as_e164 == "+919876543210"
    assert user.email == "resident@example.com"
    assert user.locale == "en-IN"
    assert user.timezone == "Asia/Kolkata"
    assert user.session_version == 1


def test_user_rejects_unknown_iana_timezone():
    user = User(phone="+91 98765 43210", timezone="India/Unknown")
    user.set_unusable_password()

    with pytest.raises(ValidationError) as error:
        user.full_clean(validate_unique=False)

    assert "timezone" in error.value.message_dict


def test_django_superuser_creation_is_disabled():
    with pytest.raises(RuntimeError, match="superuser accounts are disabled"):
        User.objects.create_superuser(phone="+91 98765 43210", password="unused")