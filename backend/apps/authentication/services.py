from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException, AuthenticationFailed, ValidationError
from rest_framework_simplejwt.exceptions import TokenError

from apps.authentication.email_delivery import send_auth_email
from apps.authentication.tokens import SessionRefreshToken, validate_session_token
from apps.identity.models import EmailAuthChallenge, User
from apps.tenancy.context import set_local_society_id
from apps.tenancy.models import (
    CommitteeMembership,
    MembershipInvitation,
    StaffMembership,
    UnitOccupancy,
)

INVALID_CREDENTIALS_MESSAGE = "Invalid email or password."
PASSWORD_RESET_ACCEPTED_RESPONSE = {
    "detail": "If the account is eligible, password-reset instructions will be sent."
}


class InvalidCredentials(APIException):
    status_code = 401
    default_detail = INVALID_CREDENTIALS_MESSAGE
    default_code = "invalid_credentials"


class InvalidSessionToken(APIException):
    status_code = 401
    default_detail = "Token is invalid or expired."
    default_code = "invalid_session_token"


def authenticate_email_password(*, email, password):
    normalized_email = email.strip().casefold()
    user = User.objects.filter(email=normalized_email).first()
    if (
        user is None
        or not user.is_active
        or user.email_verified_at is None
        or not user.check_password(password)
    ):
        raise InvalidCredentials()

    refresh = SessionRefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def refresh_session(*, refresh):
    with transaction.atomic():
        token = _get_session_refresh_token(refresh)
        user = _get_session_token_user(token)
        token = _get_session_refresh_token(refresh)
        _validate_session_refresh_token(user=user, token=token)

        token.blacklist()
        token.set_jti()
        token.set_exp()
        token.set_iat()
        token.outstand()
        return {"access": str(token.access_token), "refresh": str(token)}


def logout_session(*, refresh):
    with transaction.atomic():
        token = _get_session_refresh_token(refresh)
        user = _get_session_token_user(token)
        token = _get_session_refresh_token(refresh)
        _validate_session_refresh_token(user=user, token=token)
        token.blacklist()


def _get_session_refresh_token(raw_token):
    try:
        return SessionRefreshToken(raw_token)
    except TokenError as exc:
        raise InvalidSessionToken() from exc


def _get_session_token_user(token):
    user_id = token.get("user_id")
    try:
        return User.objects.select_for_update().get(id=user_id, is_active=True)
    except (TypeError, ValueError, User.DoesNotExist) as exc:
        raise InvalidSessionToken() from exc


def _validate_session_refresh_token(*, user, token):
    try:
        validate_session_token(user=user, token=token)
    except AuthenticationFailed as exc:
        raise InvalidSessionToken() from exc


def request_password_reset(*, email):
    normalized_email = email.strip().casefold()
    user = User.objects.filter(
        email=normalized_email,
        is_active=True,
        email_verified_at__isnull=False,
    ).first()
    if user is None:
        return PASSWORD_RESET_ACCEPTED_RESPONSE

    with transaction.atomic():
        user = User.objects.select_for_update().get(id=user.id)
        cutoff = timezone.now() - timedelta(minutes=15)
        recent_challenge = (
            EmailAuthChallenge.objects.select_for_update()
            .filter(
                user=user,
                purpose=EmailAuthChallenge.Purpose.PASSWORD_RESET,
                created_at__gte=cutoff,
                consumed_at__isnull=True,
            )
            .first()
        )
        if recent_challenge is not None:
            return PASSWORD_RESET_ACCEPTED_RESPONSE

        challenge = EmailAuthChallenge.create_for_user(
            user=user,
            purpose=EmailAuthChallenge.Purpose.PASSWORD_RESET,
        )
        transaction.on_commit(lambda: _send_password_reset_email(user=user, challenge=challenge))

    return PASSWORD_RESET_ACCEPTED_RESPONSE


def reset_password(*, token, password):
    token_digest = EmailAuthChallenge.digest_token(token)
    with transaction.atomic():
        challenge = (
            EmailAuthChallenge.objects.select_for_update()
            .select_related("user")
            .filter(
                token_digest=token_digest,
                purpose=EmailAuthChallenge.Purpose.PASSWORD_RESET,
            )
            .first()
        )
        if challenge is None or not challenge.is_actionable() or not challenge.matches_token(token):
            raise ValidationError({"token": "This password-reset link is invalid or expired."})

        user = User.objects.select_for_update().get(id=challenge.user_id)
        if not user.is_active or user.email_verified_at is None:
            raise ValidationError({"token": "This password-reset link is invalid or expired."})

        user.set_password(password)
        user.session_version += 1
        user.sessions_revoked_at = timezone.now()
        user.save(
            update_fields=(
                "password",
                "session_version",
                "sessions_revoked_at",
                "updated_at",
            )
        )
        challenge.consumed_at = timezone.now()
        challenge.save(update_fields=("consumed_at",))
        EmailAuthChallenge.objects.filter(
            user=user,
            purpose=EmailAuthChallenge.Purpose.PASSWORD_RESET,
            consumed_at__isnull=True,
        ).exclude(id=challenge.id).update(consumed_at=timezone.now())


def activate_membership_invitation(*, society_id, invitation_id, token, password):
    with transaction.atomic():
        set_local_society_id(society_id)
        invitation = (
            MembershipInvitation.objects.select_for_update()
            .filter(id=invitation_id, society_id=society_id)
            .first()
        )
        if (
            invitation is None
            or not invitation.invitee_email
            or not invitation.is_actionable()
            or not invitation.matches_token(token)
        ):
            if (
                invitation is not None
                and invitation.status == MembershipInvitation.Status.PENDING
                and invitation.expires_at <= timezone.now()
            ):
                invitation.status = MembershipInvitation.Status.EXPIRED
                invitation.save(update_fields=("status", "updated_at"))
            raise ValidationError({"token": "This invitation is invalid or expired."})

        normalized_email = invitation.invitee_email.strip().casefold()
        existing_user = (
            User.objects.select_for_update()
            .filter(Q(phone=invitation.invitee_phone) | Q(email=normalized_email))
            .first()
        )
        if existing_user is not None:
            raise ValidationError({"token": "This invitation cannot be activated."})

        user = User.objects.create_user(
            phone=invitation.invitee_phone,
            email=normalized_email,
            password=password,
        )
        user.email_verified_at = timezone.now()
        user.save(update_fields=("email_verified_at", "updated_at"))

        _create_invited_membership(invitation=invitation, user=user)
        invitation.status = MembershipInvitation.Status.ACCEPTED
        invitation.accepted_at = timezone.now()
        invitation.accepted_by = user
        invitation.save(
            update_fields=("status", "accepted_at", "accepted_by", "updated_at")
        )


def _create_invited_membership(*, invitation, user):
    if invitation.persona == MembershipInvitation.Persona.RESIDENT:
        existing_membership = UnitOccupancy.objects.select_for_update().filter(
            society_id=invitation.society_id,
            unit_id=invitation.unit_id,
            user=user,
            is_active=True,
        )
        if existing_membership.exists():
            raise ValidationError({"token": "This invitation cannot be activated."})
        UnitOccupancy.objects.create(
            society_id=invitation.society_id,
            unit_id=invitation.unit_id,
            user=user,
            occupancy_type=invitation.occupancy_type,
        )
        return

    if invitation.persona == MembershipInvitation.Persona.STAFF:
        existing_membership = StaffMembership.objects.select_for_update().filter(
            society_id=invitation.society_id,
            user=user,
            is_active=True,
        )
        if existing_membership.exists():
            raise ValidationError({"token": "This invitation cannot be activated."})
        StaffMembership.objects.create(
            society_id=invitation.society_id,
            user=user,
            role=invitation.staff_role,
        )
        return

    if invitation.persona == MembershipInvitation.Persona.COMMITTEE:
        existing_membership = CommitteeMembership.objects.select_for_update().filter(
            society_id=invitation.society_id,
            user=user,
            is_active=True,
        )
        if existing_membership.exists():
            raise ValidationError({"token": "This invitation cannot be activated."})
        CommitteeMembership.objects.create(
            society_id=invitation.society_id,
            user=user,
            role=invitation.committee_role,
        )
        return

    raise ValidationError({"token": "This invitation cannot be activated."})


def _send_password_reset_email(*, user, challenge):
    query = urlencode({"token": challenge.raw_token})
    reset_url = f"{settings.PUBLIC_AUTH_FRONTEND_ORIGIN.rstrip('/')}/reset-password?{query}"
    send_auth_email(
        recipient=user.email,
        subject="Reset your NivasOps password",
        plain_text_content=f"Reset your NivasOps password: {reset_url}",
        html_content=(
            "<p>Reset your NivasOps password using this link:</p>"
            f'<p><a href="{reset_url}">{reset_url}</a></p>'
        ),
    )


def send_membership_invitation_email(*, invitation):
    query = urlencode(
        {
            "society_id": invitation.society_id,
            "invitation_id": invitation.id,
            "token": invitation.raw_token,
        }
    )
    activation_url = f"{settings.PUBLIC_AUTH_FRONTEND_ORIGIN.rstrip('/')}/activate?{query}"
    send_auth_email(
        recipient=invitation.invitee_email,
        subject="Activate your NivasOps account",
        plain_text_content=(
            "Activate your NivasOps account and set your password: "
            f"{activation_url}"
        ),
        html_content=(
            "<p>Activate your NivasOps account and set your password:</p>"
            f'<p><a href="{activation_url}">{activation_url}</a></p>'
        ),
    )