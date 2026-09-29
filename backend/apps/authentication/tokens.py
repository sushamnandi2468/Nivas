from datetime import UTC, datetime

from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken


def _validate_token_user(user):
    if not user.is_active:
        raise AuthenticationFailed("Inactive accounts cannot receive tokens.")


def validate_session_token(*, user, token):
    if token.get("session_version") != user.session_version:
        raise AuthenticationFailed("The session has been revoked.")

    revoked_at = user.sessions_revoked_at
    issued_at = token.get("iat")
    if revoked_at is None or issued_at is None:
        return

    try:
        issued_at_datetime = datetime.fromtimestamp(int(issued_at), tz=UTC)
    except (TypeError, ValueError, OSError) as exc:
        raise AuthenticationFailed("The token issue time is invalid.") from exc

    if issued_at_datetime <= revoked_at:
        raise AuthenticationFailed("The session has been revoked.")


class SessionAccessToken(AccessToken):
    @classmethod
    def for_user(cls, user):
        _validate_token_user(user)
        token = super().for_user(user)
        token["session_version"] = user.session_version
        return token


class SessionRefreshToken(RefreshToken):
    @classmethod
    def for_user(cls, user):
        _validate_token_user(user)
        token = super().for_user(user)
        token["session_version"] = user.session_version
        return token

    @property
    def access_token(self):
        token = super().access_token
        token.set_iat(at_time=self.current_time)
        return token