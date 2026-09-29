"""Fail-closed settings for PostgreSQL-backed test execution."""

import re

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403

TEST_DATABASE_NAME = env("TEST_PGDATABASE", default="")  # noqa: F405
PRIMARY_DATABASE_NAME = DATABASES["default"]["NAME"]  # noqa: F405
TEST_DATABASE_NAME_PATTERN = re.compile(r"^(test_[a-z0-9_]+|nivasops[a-z0-9_]*test[a-z0-9_]*)$")

if not TEST_DATABASE_NAME:
    raise ImproperlyConfigured(
        "TEST_PGDATABASE must name an isolated PostgreSQL test database."
    )
if not TEST_DATABASE_NAME_PATTERN.fullmatch(TEST_DATABASE_NAME.lower()):
    raise ImproperlyConfigured(
        "TEST_PGDATABASE must start with 'test_' or use a NivasOps name containing 'test'."
    )
if TEST_DATABASE_NAME == PRIMARY_DATABASE_NAME:
    raise ImproperlyConfigured("TEST_PGDATABASE must not equal PGDATABASE.")

DATABASES["default"]["TEST"] = {"NAME": TEST_DATABASE_NAME}  # noqa: F405
DATABASES["default"]["CONN_MAX_AGE"] = 0  # noqa: F405
DATABASES["default"]["ATOMIC_REQUESTS"] = True  # noqa: F405
TICKET_COMPLETION_CAPSULE_BACKEND = "test"
TICKET_COMPLETION_CAPSULE_TEST_MODE = True
TICKET_COMPLETION_EMAIL_BACKEND = "test"
TICKET_ATTACHMENT_STORAGE_BACKEND = "test"
TICKET_ATTACHMENT_STORAGE_TEST_MODE = True
TICKET_ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024
TICKET_ATTACHMENT_ALLOWED_CONTENT_TYPES = [
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
]
TICKET_ATTACHMENT_UPLOAD_URL_EXPIRY_SECONDS = 900

