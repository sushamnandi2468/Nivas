import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone as django_timezone
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField


def validate_iana_timezone(value: str) -> None:
	try:
		ZoneInfo(value)
	except ZoneInfoNotFoundError as exc:
		raise ValidationError(_("Enter a valid IANA timezone."), code="invalid_timezone") from exc


class UserManager(BaseUserManager):
	use_in_migrations = True

	def create_user(self, phone, password=None, **extra_fields):
		if not phone:
			raise ValueError("Users must have a phone number.")

		user = self.model(phone=phone, **extra_fields)
		user.set_password(password)
		user.full_clean()
		user.save(using=self._db)
		return user

	def create_superuser(self, phone, password=None, **extra_fields):
		raise RuntimeError("Django superuser accounts are disabled for NivasOps.")


class User(AbstractBaseUser, PermissionsMixin):
	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	phone = PhoneNumberField(unique=True, region=None)
	email = models.EmailField(blank=True, null=True, unique=True)
	email_verified_at = models.DateTimeField(blank=True, null=True)
	locale = models.CharField(max_length=16, default="en-IN")
	timezone = models.CharField(
		max_length=64,
		default="Asia/Kolkata",
		validators=[validate_iana_timezone],
	)
	is_active = models.BooleanField(default=True)
	is_staff = models.BooleanField(default=False)
	session_version = models.PositiveBigIntegerField(default=1)
	sessions_revoked_at = models.DateTimeField(blank=True, null=True)
	date_joined = models.DateTimeField(default=django_timezone.now, editable=False)
	updated_at = models.DateTimeField(auto_now=True)

	objects = UserManager()

	USERNAME_FIELD = "phone"
	REQUIRED_FIELDS: list[str] = []

	class Meta:
		db_table = "identity_user"
		ordering = ("phone",)

	def clean_fields(self, exclude=None):
		self._normalize_email()
		super().clean_fields(exclude=exclude)

	def clean(self):
		super().clean()
		self._normalize_email()

	def _normalize_email(self):
		if self.email:
			self.email = self.email.strip().casefold()

	def __str__(self):
		return str(self.phone)


class EmailAuthChallenge(models.Model):
	class Purpose(models.TextChoices):
		ACTIVATION = "ACTIVATION", _("Activation")
		PASSWORD_RESET = "PASSWORD_RESET", _("Password reset")

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	user = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		on_delete=models.CASCADE,
		related_name="email_auth_challenges",
	)
	purpose = models.CharField(max_length=32, choices=Purpose.choices)
	token_digest = models.CharField(max_length=64, unique=True, editable=False)
	expires_at = models.DateTimeField()
	consumed_at = models.DateTimeField(blank=True, null=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = "identity_email_auth_challenge"
		ordering = ("-created_at",)
		indexes = [
			models.Index(
				fields=("user", "purpose", "expires_at"),
				name="identity_email_auth_active_idx",
			)
		]
		constraints = [
			models.CheckConstraint(
				condition=models.Q(expires_at__gt=models.F("created_at")),
				name="identity_email_auth_future_expiry",
			)
		]

	def __str__(self):
		return f"{self.user_id} - {self.purpose}"

	@staticmethod
	def digest_token(raw_token):
		return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

	@classmethod
	def create_for_user(cls, *, user, purpose, expires_in=timedelta(minutes=15)):
		raw_token = secrets.token_urlsafe(32)
		challenge = cls.objects.create(
			user=user,
			purpose=purpose,
			token_digest=cls.digest_token(raw_token),
			expires_at=django_timezone.now() + expires_in,
		)
		challenge.raw_token = raw_token
		return challenge

	def is_actionable(self, at=None):
		instant = at or django_timezone.now()
		return self.consumed_at is None and instant < self.expires_at

	def matches_token(self, raw_token):
		return hmac.compare_digest(self.token_digest, self.digest_token(raw_token))
