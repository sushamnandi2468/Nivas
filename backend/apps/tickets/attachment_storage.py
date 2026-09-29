import datetime
import secrets
import uuid
from dataclasses import dataclass
from pathlib import PurePath

from django.conf import settings
from django.utils import timezone

DANGEROUS_EXTENSIONS = {
    # Executables & scripts
    ".exe",
    ".dll",
    ".bat",
    ".cmd",
    ".sh",
    ".ps1",
    ".msi",
    ".js",
    ".vbs",
    ".scr",
    ".com",
    ".pif",
    ".jar",
    ".apk",
    ".dmg",
    ".bin",
    ".app",
    ".deb",
    ".rpm",
    ".hta",
    ".cpl",
    ".msc",
    ".msp",
    ".gadget",
    ".wsf",
    ".vbe",
    ".jse",
    # Macro-enabled Office documents and templates
    ".docm",
    ".dotm",
    ".xlsm",
    ".xltm",
    ".xlam",
    ".pptm",
    ".potm",
    ".ppam",
    ".ppsm",
    ".sldm",
}

ALLOWED_MIME_EXTENSIONS = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
    "application/pdf": {".pdf"},
}


class AttachmentStorageError(Exception):
    """Base exception for attachment storage operations."""


class AttachmentStorageConfigurationError(AttachmentStorageError):
    """Raised when attachment storage or security policy is not configured or disabled."""


class AttachmentValidationError(AttachmentStorageError):
    """Raised when declared attachment metadata fails validation rules."""


@dataclass(frozen=True)
class IssuedUploadSlot:
    storage_key: str
    upload_url: str
    expires_at: datetime.datetime
    headers: dict[str, str]


def generate_attachment_storage_key() -> str:
    """Generate a random, server-owned opaque key for quarantined attachment storage.

    Reveals no society, ticket number, resident identity, filename, or user path segments.
    """
    container_token = uuid.uuid4().hex
    object_token = secrets.token_hex(16)
    return f"quarantine/{container_token}/{object_token}"


def validate_attachment_request(*, filename: str, content_type: str, byte_size: int) -> None:
    """Validate requested attachment metadata against security rules and configured policies.

    Fails closed if the storage backend or policy allowlists are absent.
    """
    if not isinstance(filename, str) or not filename.strip():
        raise AttachmentValidationError("A non-empty filename is required.")

    clean_filename = filename.strip()
    if len(clean_filename) > 255:
        raise AttachmentValidationError("Filename must be 255 characters or fewer.")

    if any(char in clean_filename for char in ('/', '\\', '\x00')) or ".." in clean_filename:
        raise AttachmentValidationError("Filename contains invalid or path-traversal characters.")

    ext = PurePath(clean_filename).suffix.lower()
    if not ext:
        raise AttachmentValidationError("Filename must include a valid file extension.")

    if ext in DANGEROUS_EXTENSIONS:
        raise AttachmentValidationError(
            f"File extension '{ext}' is prohibited for security reasons."
        )

    if not isinstance(byte_size, int) or byte_size <= 0:
        raise AttachmentValidationError("Declared byte size must be a positive integer.")

    max_bytes = getattr(settings, "TICKET_ATTACHMENT_MAX_BYTES", 0)
    if not max_bytes or max_bytes <= 0:
        raise AttachmentStorageConfigurationError(
            "Attachment upload maximum size is not configured."
        )

    if byte_size > max_bytes:
        raise AttachmentValidationError(
            f"Declared byte size ({byte_size} bytes) exceeds the maximum allowed limit "
            f"({max_bytes} bytes)."
        )

    if not isinstance(content_type, str) or not content_type.strip():
        raise AttachmentValidationError("Declared content type is required.")

    clean_content_type = content_type.strip().lower()
    allowed_content_types = [
        ct.lower() for ct in getattr(settings, "TICKET_ATTACHMENT_ALLOWED_CONTENT_TYPES", [])
    ]
    if not allowed_content_types:
        raise AttachmentStorageConfigurationError(
            "Attachment allowed content types policy is not configured."
        )

    if clean_content_type not in allowed_content_types:
        raise AttachmentValidationError(
            f"Content type '{clean_content_type}' is not allowed."
        )

    permitted_extensions = ALLOWED_MIME_EXTENSIONS.get(clean_content_type)
    if permitted_extensions is not None and ext not in permitted_extensions:
        raise AttachmentValidationError(
            f"File extension '{ext}' is not permitted for declared content type "
            f"'{clean_content_type}'."
        )



def issue_attachment_upload_slot(
    *,
    storage_key: str,
    content_type: str,
    byte_size: int,
) -> IssuedUploadSlot:
    """Issue a short-lived quarantine upload URL for the specified storage key.

    Fails closed when storage is disabled or misconfigured.
    """
    backend = getattr(settings, "TICKET_ATTACHMENT_STORAGE_BACKEND", "disabled")
    expiry_seconds = getattr(settings, "TICKET_ATTACHMENT_UPLOAD_URL_EXPIRY_SECONDS", 900)
    expires_at = timezone.now() + datetime.timedelta(seconds=expiry_seconds)

    if backend == "disabled":
        raise AttachmentStorageConfigurationError(
            "Attachment storage backend is disabled or unconfigured."
        )

    if backend == "test":
        if not getattr(settings, "TICKET_ATTACHMENT_STORAGE_TEST_MODE", False):
            raise AttachmentStorageConfigurationError(
                "Test attachment storage requires test mode."
            )
        upload_url = f"https://test-quarantine.blob.local/{storage_key}?exp={int(expires_at.timestamp())}&sig=test_signed_token"
        headers = {"x-ms-blob-type": "BlockBlob"}
        return IssuedUploadSlot(
            storage_key=storage_key,
            upload_url=upload_url,
            expires_at=expires_at,
            headers=headers,
        )

    if backend == "azure_blob":
        raise AttachmentStorageConfigurationError(
            "Azure Blob Storage backend is not provisioned or configured in this environment."
        )

    raise AttachmentStorageConfigurationError(
        f"Unsupported attachment storage backend: {backend}"
    )


class AttachmentObjectNotFoundError(AttachmentStorageError):
    """Raised when an attachment object is missing from storage."""


@dataclass(frozen=True)
class AttachmentScanResult:
    is_clean: bool
    clean_storage_key: str | None = None
    checksum_sha256: str | None = None
    actual_content_type: str | None = None
    actual_byte_size: int | None = None
    threat_name: str | None = None
    rejection_reason: str | None = None
    error_code: str | None = None


# In-memory repository for test and local development storage objects
_TEST_STORAGE_OBJECTS: dict[str, bytes] = {}


def put_test_attachment_data(storage_key: str, data: bytes) -> None:
    """Store test object bytes in the in-memory test storage repository."""
    _TEST_STORAGE_OBJECTS[storage_key] = bytes(data)


def get_test_attachment_data(storage_key: str) -> bytes | None:
    """Retrieve test object bytes from the in-memory test storage repository."""
    return _TEST_STORAGE_OBJECTS.get(storage_key)


def move_test_attachment_data(src_key: str, dst_key: str) -> None:
    """Move test object from source to destination storage key."""
    if src_key in _TEST_STORAGE_OBJECTS:
        _TEST_STORAGE_OBJECTS[dst_key] = _TEST_STORAGE_OBJECTS.pop(src_key)


def delete_test_attachment_data(storage_key: str) -> None:
    """Remove test object from test storage."""
    _TEST_STORAGE_OBJECTS.pop(storage_key, None)


def clear_test_attachment_storage() -> None:
    """Clear all stored objects in test storage."""
    _TEST_STORAGE_OBJECTS.clear()


EICAR_STANDARD_TEST_SIGNATURE = (
    b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)


def detect_mime_type_from_bytes(data: bytes) -> str | None:
    """Detect MIME type by inspecting leading magic byte headers."""
    if len(data) >= 3 and data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 8 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 4 and data.startswith(b"%PDF"):
        return "application/pdf"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 2 and data.startswith(b"MZ"):
        return "application/x-dosexec"
    if len(data) >= 4 and data.startswith(b"\x7fELF"):
        return "application/x-executable"
    return None


def inspect_content_for_malware(data: bytes) -> tuple[bool, str | None]:
    """Inspect binary stream for malware signatures and disguised executables.

    Returns (is_infected, threat_name).
    """
    if EICAR_STANDARD_TEST_SIGNATURE in data:
        return True, "EICAR-Standard-AV-Test-Signature"
    if data.startswith(b"MZ"):
        return True, "Win32.Executable.Disguised"
    if data.startswith(b"\x7fELF"):
        return True, "Linux.ELF.Executable.Disguised"
    lower_prefix = data[:1024].lower()
    if b"#!/bin/sh" in lower_prefix or b"#!/bin/bash" in lower_prefix:
        return True, "Script.Shell.Disguised"
    if b"<?php" in lower_prefix:
        return True, "Script.PHP.Disguised"
    return False, None


def convert_quarantine_key_to_clean(storage_key: str) -> str:
    """Transform quarantine storage key into clean storage key."""
    if storage_key.startswith("quarantine/"):
        return "clean/" + storage_key[len("quarantine/"):]
    return f"clean/{storage_key}"


def scan_and_promote_storage_object(
    *,
    quarantine_storage_key: str,
    declared_content_type: str,
    declared_byte_size: int,
) -> AttachmentScanResult:
    """Scan quarantine object for malware, verify MIME and size, and promote if clean."""
    backend = getattr(settings, "TICKET_ATTACHMENT_STORAGE_BACKEND", "disabled")
    if backend == "disabled":
        raise AttachmentStorageConfigurationError("Attachment storage is disabled.")

    if backend == "test":
        if not getattr(settings, "TICKET_ATTACHMENT_STORAGE_TEST_MODE", False):
            raise AttachmentStorageConfigurationError("Test attachment storage requires test mode.")

        data = get_test_attachment_data(quarantine_storage_key)
        if data is None:
            # Generate deterministic clean fallback payload in test mode for dev/demo workflows
            clean_type = declared_content_type.strip().lower()
            if clean_type == "image/png":
                data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
            elif clean_type == "image/jpeg":
                data = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00"
            elif clean_type == "application/pdf":
                data = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\nxref\n0 1\ntrailer<</Size 1>>\nstartxref\n9\n%%EOF"
            elif clean_type == "image/webp":
                data = b"RIFF\x14\x00\x00\x00WEBPVP8 \x08\x00\x00\x00\x00\x00\x00\x9d\x01*\x01\x00\x01\x00"
            else:
                data = b"%PDF-1.4 clean document payload"

            if declared_byte_size > len(data):
                data = data + b"\x00" * (declared_byte_size - len(data))
            put_test_attachment_data(quarantine_storage_key, data)

        actual_byte_size = len(data)
        max_bytes = getattr(settings, "TICKET_ATTACHMENT_MAX_BYTES", 20 * 1024 * 1024)
        if actual_byte_size <= 0 or actual_byte_size > max_bytes:
            delete_test_attachment_data(quarantine_storage_key)
            return AttachmentScanResult(
                is_clean=False,
                threat_name=None,
                rejection_reason=f"Actual byte size ({actual_byte_size}) exceeds allowed maximum ({max_bytes}).",
                error_code="SIZE_EXCEEDED",
                actual_byte_size=actual_byte_size,
            )

        import hashlib
        checksum_sha256 = hashlib.sha256(data).hexdigest()

        is_infected, threat = inspect_content_for_malware(data)
        if is_infected:
            delete_test_attachment_data(quarantine_storage_key)
            return AttachmentScanResult(
                is_clean=False,
                checksum_sha256=checksum_sha256,
                actual_byte_size=actual_byte_size,
                threat_name=threat,
                rejection_reason=f"Malware signature detected: {threat}",
                error_code="MALWARE_DETECTED",
            )

        detected_mime = detect_mime_type_from_bytes(data)
        clean_declared = declared_content_type.strip().lower()
        if detected_mime and detected_mime != clean_declared:
            delete_test_attachment_data(quarantine_storage_key)
            return AttachmentScanResult(
                is_clean=False,
                checksum_sha256=checksum_sha256,
                actual_byte_size=actual_byte_size,
                actual_content_type=detected_mime,
                threat_name=None,
                rejection_reason=(
                    f"Declared content type '{clean_declared}' does not match "
                    f"detected content type '{detected_mime}'."
                ),
                error_code="MIME_TYPE_MISMATCH",
            )

        clean_key = convert_quarantine_key_to_clean(quarantine_storage_key)
        move_test_attachment_data(quarantine_storage_key, clean_key)

        return AttachmentScanResult(
            is_clean=True,
            clean_storage_key=clean_key,
            checksum_sha256=checksum_sha256,
            actual_content_type=detected_mime or clean_declared,
            actual_byte_size=actual_byte_size,
        )

    if backend == "azure_blob":
        raise AttachmentStorageConfigurationError(
            "Azure Blob Storage scanning worker is not configured in this environment."
        )

    raise AttachmentStorageConfigurationError(f"Unsupported storage backend: {backend}")

