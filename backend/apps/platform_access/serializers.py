from django.utils import timezone
from rest_framework import serializers

from apps.platform_access.models import PlatformRoleGrant, PlatformSupportSession
from apps.tenancy.models import Society


class PlatformRoleGrantSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformRoleGrant
        fields = (
            "id",
            "user",
            "role",
            "status",
            "reason",
            "starts_at",
            "ends_at",
            "requested_by",
            "approved_by",
            "approved_at",
            "revoked_by",
            "revoked_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "status",
            "requested_by",
            "approved_by",
            "approved_at",
            "revoked_by",
            "revoked_at",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        starts_at = attrs.get("starts_at", timezone.now())
        ends_at = attrs.get("ends_at")
        if ends_at is not None and ends_at <= starts_at:
            raise serializers.ValidationError(
                {"ends_at": "End time must be later than start time."}
            )

        if PlatformRoleGrant.objects.filter(
            user=attrs["user"],
            role=attrs["role"],
            status__in=(
                PlatformRoleGrant.Status.PENDING,
                PlatformRoleGrant.Status.ACTIVE,
            ),
        ).exists():
            raise serializers.ValidationError(
                {"role": "This user already has an open grant for this role."}
            )
        return attrs

    def create(self, validated_data):
        grant = PlatformRoleGrant(**validated_data)
        grant.full_clean()
        grant.save()
        return grant


class PlatformSupportSessionCreateSerializer(serializers.Serializer):
    society = serializers.PrimaryKeyRelatedField(
        queryset=Society.objects.filter(is_active=True)
    )
    case_reference = serializers.CharField(min_length=8, max_length=128)
    reason = serializers.CharField(min_length=20, max_length=1000)
    duration_minutes = serializers.IntegerField(min_value=5, max_value=30)
    platform_role = serializers.ChoiceField(
        choices=(
            PlatformRoleGrant.Role.PLATFORM_SUPPORT,
            PlatformRoleGrant.Role.PLATFORM_AUDITOR,
        ),
        required=False,
    )

    def validate_case_reference(self, value):
        if "\r" in value or "\n" in value:
            raise serializers.ValidationError("Case reference must be a single line.")
        return value


class PlatformSupportSessionSerializer(serializers.ModelSerializer):
    persona = serializers.SerializerMethodField()
    read_only = serializers.BooleanField(default=True, read_only=True)

    class Meta:
        model = PlatformSupportSession
        fields = (
            "id",
            "user",
            "role_grant",
            "platform_role",
            "persona",
            "society",
            "case_reference",
            "reason",
            "requested_duration_minutes",
            "started_at",
            "expires_at",
            "ended_at",
            "end_reason",
            "read_only",
        )
        read_only_fields = fields

    def get_persona(self, instance):
        if instance.platform_role == PlatformRoleGrant.Role.PLATFORM_SUPPORT:
            return "platform_support"
        return "platform_auditor"