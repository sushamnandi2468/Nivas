from django.contrib.auth import password_validation
from rest_framework import serializers


class EmailPasswordLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False, write_only=True)


class RefreshTokenSerializer(serializers.Serializer):
    refresh = serializers.CharField(trim_whitespace=False, write_only=True)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField(trim_whitespace=False, write_only=True)
    password = serializers.CharField(trim_whitespace=False, write_only=True)

    def validate_password(self, value):
        password_validation.validate_password(value)
        return value


class InvitationActivationSerializer(serializers.Serializer):
    society_id = serializers.UUIDField()
    invitation_id = serializers.UUIDField()
    token = serializers.CharField(trim_whitespace=False, write_only=True)
    password = serializers.CharField(trim_whitespace=False, write_only=True)

    def validate_password(self, value):
        password_validation.validate_password(value)
        return value