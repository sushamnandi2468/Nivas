import secrets
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

from apps.identity.models import User
from apps.tenancy.models import (
    Block,
    CommitteeMembership,
    CommonArea,
    MembershipInvitation,
    Society,
    TechnicianProfile,
    Unit,
    UnitOccupancy,
    Vendor,
    VendorContract,
    VendorStaffMembership,
)


def tenant_user_queryset(society):
    return (
        User.objects.filter(is_active=True)
        .filter(
            Q(staff_memberships__society=society)
            | Q(unit_occupancies__society=society)
            | Q(committee_memberships__society=society)
            | Q(technician_profiles__society=society)
            | Q(vendor_staff_memberships__society=society)
        )
        .distinct()
    )


class SocietySerializer(serializers.ModelSerializer):
    class Meta:
        model = Society
        fields = (
            "id",
            "registration_code",
            "timezone",
            "locale",
            "currency",
            "is_active",
        )
        read_only_fields = fields


class BlockSerializer(serializers.ModelSerializer):
    society_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Block
        fields = ("id", "society_id", "name", "code", "is_active")
        read_only_fields = ("id", "society_id")

    def validate(self, attrs):
        attrs["name"] = " ".join(attrs["name"].split())
        attrs["code"] = attrs["code"].strip().upper()
        society = self.context["request"].society
        if Block.objects.filter(society=society, code=attrs["code"]).exists():
            raise serializers.ValidationError(
                {"code": "A block with this code already exists in the society."}
            )
        return attrs


class UnitSerializer(serializers.ModelSerializer):
    society_id = serializers.UUIDField(read_only=True)
    block = serializers.PrimaryKeyRelatedField(queryset=Block.objects.none())

    class Meta:
        model = Unit
        fields = ("id", "society_id", "block", "door_number", "is_active")
        read_only_fields = ("id", "society_id")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and hasattr(request, "society"):
            self.fields["block"].queryset = Block.objects.filter(
                society=request.society,
                is_active=True,
            )

    def validate(self, attrs):
        attrs["door_number"] = attrs["door_number"].strip().upper()
        society = self.context["request"].society
        if Unit.objects.filter(
            society=society,
            block=attrs["block"],
            door_number=attrs["door_number"],
        ).exists():
            raise serializers.ValidationError(
                {"door_number": "This unit already exists in the selected block."}
            )
        return attrs


class CommonAreaSerializer(serializers.ModelSerializer):
    society_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = CommonArea
        fields = ("id", "society_id", "name", "is_active")
        read_only_fields = ("id", "society_id")

    def validate(self, attrs):
        attrs["name"] = " ".join(attrs["name"].split())
        normalized_name = attrs["name"].casefold()
        society = self.context["request"].society
        if CommonArea.objects.filter(
            society=society,
            normalized_name=normalized_name,
        ).exists():
            raise serializers.ValidationError(
                {"name": "A common area with this name already exists in the society."}
            )
        attrs["normalized_name"] = normalized_name
        return attrs


class UnitOccupancySerializer(serializers.ModelSerializer):
    society_id = serializers.UUIDField(read_only=True)
    unit = serializers.PrimaryKeyRelatedField(queryset=Unit.objects.none())
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())

    class Meta:
        model = UnitOccupancy
        fields = (
            "id",
            "society_id",
            "unit",
            "user",
            "occupancy_type",
            "is_primary_contact",
            "can_approve_costs",
            "is_active",
            "starts_at",
            "ends_at",
        )
        read_only_fields = ("id", "society_id")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and hasattr(request, "society"):
            self.fields["unit"].queryset = Unit.objects.filter(
                society=request.society,
                is_active=True,
            )
            self.fields["user"].queryset = tenant_user_queryset(request.society)

    def validate(self, attrs):
        starts_at = attrs.get("starts_at", timezone.now())
        ends_at = attrs.get("ends_at")
        if ends_at is not None and ends_at <= starts_at:
            raise serializers.ValidationError(
                {"ends_at": "End time must be later than start time."}
            )

        society = self.context["request"].society
        if (
            attrs.get("is_active", True)
            and UnitOccupancy.objects.filter(
                society=society,
                unit=attrs["unit"],
                user=attrs["user"],
                is_active=True,
            ).exists()
        ):
            raise serializers.ValidationError(
                {"user": "This user already has an active occupancy for the unit."}
            )
        return attrs


class CommitteeMembershipSerializer(serializers.ModelSerializer):
    society_id = serializers.UUIDField(read_only=True)
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())

    class Meta:
        model = CommitteeMembership
        fields = (
            "id",
            "society_id",
            "user",
            "role",
            "is_active",
            "starts_at",
            "ends_at",
        )
        read_only_fields = ("id", "society_id")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and hasattr(request, "society"):
            self.fields["user"].queryset = tenant_user_queryset(request.society)

    def validate(self, attrs):
        starts_at = attrs.get("starts_at", timezone.now())
        ends_at = attrs.get("ends_at")
        if ends_at is not None and ends_at <= starts_at:
            raise serializers.ValidationError(
                {"ends_at": "End time must be later than start time."}
            )

        society = self.context["request"].society
        if (
            attrs.get("is_active", True)
            and CommitteeMembership.objects.filter(
                society=society,
                user=attrs["user"],
                is_active=True,
            ).exists()
        ):
            raise serializers.ValidationError(
                {"user": "This user already has an active committee membership."}
            )
        return attrs


class TechnicianProfileSerializer(serializers.ModelSerializer):
    society_id = serializers.UUIDField(read_only=True)
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = TechnicianProfile
        fields = (
            "id",
            "society_id",
            "user",
            "user_email",
            "is_active",
            "starts_at",
            "ends_at",
            "max_active_tickets",
            "current_active_tickets_count",
        )
        read_only_fields = ("id", "society_id", "user_email", "current_active_tickets_count")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and hasattr(request, "society"):
            self.fields["user"].queryset = tenant_user_queryset(request.society)

    def validate(self, attrs):
        starts_at = attrs.get("starts_at", timezone.now())
        ends_at = attrs.get("ends_at")
        if ends_at is not None and ends_at <= starts_at:
            raise serializers.ValidationError(
                {"ends_at": "End time must be later than start time."}
            )

        society = self.context["request"].society
        if (
            attrs.get("is_active", True)
            and TechnicianProfile.objects.filter(
                society=society,
                user=attrs["user"],
                is_active=True,
            ).exists()
        ):
            raise serializers.ValidationError(
                {"user": "This user already has an active technician profile."}
            )
        return attrs


class VendorSerializer(serializers.ModelSerializer):
    society_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Vendor
        fields = (
            "id",
            "society_id",
            "company_name",
            "contact_person",
            "phone_number",
            "email",
            "is_active",
        )
        read_only_fields = ("id", "society_id")

    def validate(self, attrs):
        attrs["company_name"] = " ".join(attrs["company_name"].split())
        attrs["normalized_company_name"] = attrs["company_name"].casefold()
        attrs["contact_person"] = " ".join(attrs["contact_person"].split())
        attrs["email"] = attrs.get("email", "").strip().lower()
        society = self.context["request"].society
        if Vendor.objects.filter(
            society=society,
            normalized_company_name=attrs["normalized_company_name"],
        ).exists():
            raise serializers.ValidationError(
                {"company_name": "A vendor with this name already exists."}
            )
        return attrs


class VendorContractSerializer(serializers.ModelSerializer):
    society_id = serializers.UUIDField(read_only=True)
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.none())

    class Meta:
        model = VendorContract
        fields = (
            "id",
            "society_id",
            "vendor",
            "starts_on",
            "ends_on",
            "is_active",
            "max_active_tickets",
            "current_active_tickets_count",
        )
        read_only_fields = ("id", "society_id", "current_active_tickets_count")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and hasattr(request, "society"):
            self.fields["vendor"].queryset = Vendor.objects.filter(
                society=request.society,
                is_active=True,
            )

    def validate(self, attrs):
        if attrs["ends_on"] < attrs["starts_on"]:
            raise serializers.ValidationError(
                {"ends_on": "End date cannot be earlier than start date."}
            )
        max_active_tickets = attrs.get("max_active_tickets")
        if max_active_tickets is not None and max_active_tickets <= 0:
            raise serializers.ValidationError(
                {
                    "max_active_tickets": (
                        "Capacity must be greater than zero or omitted for unlimited capacity."
                    )
                }
            )
        return attrs


class VendorStaffMembershipSerializer(serializers.ModelSerializer):
    society_id = serializers.UUIDField(read_only=True)
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.none())
    contract = serializers.PrimaryKeyRelatedField(queryset=VendorContract.objects.none())
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.none())

    class Meta:
        model = VendorStaffMembership
        fields = (
            "id",
            "society_id",
            "vendor",
            "contract",
            "user",
            "role",
            "is_active",
            "starts_at",
            "ends_at",
        )
        read_only_fields = ("id", "society_id")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and hasattr(request, "society"):
            self.fields["vendor"].queryset = Vendor.objects.filter(
                society=request.society,
                is_active=True,
            )
            self.fields["contract"].queryset = VendorContract.objects.filter(
                society=request.society,
                is_active=True,
            )
            self.fields["user"].queryset = tenant_user_queryset(request.society)

    def validate(self, attrs):
        starts_at = attrs.get("starts_at", timezone.now())
        ends_at = attrs.get("ends_at")
        if ends_at is not None and ends_at <= starts_at:
            raise serializers.ValidationError(
                {"ends_at": "End time must be later than start time."}
            )
        if attrs["contract"].vendor_id != attrs["vendor"].id:
            raise serializers.ValidationError(
                {"contract": "Contract must belong to the selected vendor."}
            )

        society = self.context["request"].society
        if (
            attrs.get("is_active", True)
            and VendorStaffMembership.objects.filter(
                society=society,
                contract=attrs["contract"],
                user=attrs["user"],
                is_active=True,
            ).exists()
        ):
            raise serializers.ValidationError(
                {"user": "This user already has an active membership for the contract."}
            )
        return attrs


class MembershipInvitationSerializer(serializers.ModelSerializer):
    society_id = serializers.UUIDField(read_only=True)
    invitee_email = serializers.EmailField(required=True)
    unit = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.none(),
        allow_null=True,
        required=False,
    )
    created_by_id = serializers.UUIDField(read_only=True)
    revoked_by_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = MembershipInvitation
        fields = (
            "id",
            "society_id",
            "invitee_phone",
            "invitee_email",
            "persona",
            "unit",
            "occupancy_type",
            "staff_role",
            "committee_role",
            "status",
            "expires_at",
            "created_by_id",
            "revoked_at",
            "revoked_by_id",
            "created_at",
        )
        read_only_fields = (
            "id",
            "society_id",
            "status",
            "created_by_id",
            "revoked_at",
            "revoked_by_id",
            "created_at",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is not None and hasattr(request, "society"):
            self.fields["unit"].queryset = Unit.objects.filter(
                society=request.society,
                is_active=True,
            )

    def validate(self, attrs):
        attrs["invitee_email"] = attrs["invitee_email"].strip().casefold()
        now = timezone.now()
        expires_at = attrs.get("expires_at") or now + timedelta(days=3)
        if expires_at <= now:
            raise serializers.ValidationError({"expires_at": "Expiry must be in the future."})
        if expires_at > now + timedelta(days=7):
            raise serializers.ValidationError(
                {"expires_at": "Expiry cannot be more than seven days away."}
            )

        persona = attrs["persona"]
        unit = attrs.get("unit")
        occupancy_type = attrs.get("occupancy_type")
        staff_role = attrs.get("staff_role")
        committee_role = attrs.get("committee_role")
        payload_is_valid = {
            MembershipInvitation.Persona.RESIDENT: bool(
                unit and occupancy_type and not staff_role and not committee_role
            ),
            MembershipInvitation.Persona.STAFF: bool(
                not unit and not occupancy_type and staff_role and not committee_role
            ),
            MembershipInvitation.Persona.COMMITTEE: bool(
                not unit and not occupancy_type and not staff_role and committee_role
            ),
        }.get(persona, False)
        if not payload_is_valid:
            raise serializers.ValidationError(
                {"persona": "Invitation details do not match the persona."}
            )

        society = self.context["request"].society
        MembershipInvitation.objects.filter(
            society=society,
            status=MembershipInvitation.Status.PENDING,
            expires_at__lte=now,
        ).update(status=MembershipInvitation.Status.EXPIRED)
        duplicate_filter = {
            "society": society,
            "invitee_phone": attrs["invitee_phone"],
            "persona": persona,
            "status": MembershipInvitation.Status.PENDING,
        }
        if persona == MembershipInvitation.Persona.RESIDENT:
            duplicate_filter["unit"] = unit
        if MembershipInvitation.objects.filter(**duplicate_filter).exists():
            raise serializers.ValidationError(
                {"invitee_phone": "A matching pending invitation already exists."}
            )

        attrs["expires_at"] = expires_at
        return attrs

    def create(self, validated_data):
        raw_token = secrets.token_urlsafe(32)
        invitation = MembershipInvitation.objects.create(
            token_digest=MembershipInvitation.digest_token(raw_token),
            **validated_data,
        )
        invitation.raw_token = raw_token
        return invitation
