from decimal import Decimal
from rest_framework import serializers

from apps.tenancy.models import CommonArea, Unit, UnitOccupancy
from apps.tickets.models import (
    Ticket,
    TicketAssignment,
    TicketAttachment,
    TicketCategory,
    TicketComment,
    TicketEstimate,
    TicketEstimateLineItem,
    TicketFeedback,
    TicketMergeRecord,
    TicketSubCategory,
)


class TicketSerializer(serializers.ModelSerializer):
    society_id = serializers.UUIDField(read_only=True)
    creator_id = serializers.UUIDField(read_only=True)
    category = serializers.PrimaryKeyRelatedField(queryset=TicketCategory.objects.none())
    subcategory = serializers.PrimaryKeyRelatedField(
        queryset=TicketSubCategory.objects.none()
    )
    unit = serializers.PrimaryKeyRelatedField(
        queryset=Unit.objects.none(),
        allow_null=True,
        required=False,
    )
    common_area = serializers.PrimaryKeyRelatedField(
        queryset=CommonArea.objects.none(),
        allow_null=True,
        required=False,
    )
    priority = serializers.ChoiceField(
        choices=TicketSubCategory.Priority.choices,
        required=False,
    )

    class Meta:
        model = Ticket
        fields = (
            "id",
            "society_id",
            "ticket_number",
            "creator_id",
            "category",
            "subcategory",
            "workflow_type",
            "unit",
            "common_area",
            "title",
            "description",
            "priority",
            "status",
            "state_version",
            "submitted_at",
            "archived_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "society_id",
            "ticket_number",
            "creator_id",
            "workflow_type",
            "status",
            "state_version",
            "submitted_at",
            "archived_at",
            "created_at",
            "updated_at",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        view = self.context.get("view")
        if request is None or view is None or not hasattr(request, "society"):
            return
        self.fields["category"].queryset = TicketCategory.objects.filter(
            society=request.society,
            workflow_type=view.workflow_type,
            is_active=True,
        )
        self.fields["subcategory"].queryset = TicketSubCategory.objects.filter(
            society=request.society,
            category__workflow_type=view.workflow_type,
            category__is_active=True,
            is_active=True,
        )
        self.fields["unit"].queryset = Unit.objects.filter(
            society=request.society,
            is_active=True,
        )
        self.fields["common_area"].queryset = CommonArea.objects.filter(
            society=request.society,
            is_active=True,
        )

    def validate(self, attrs):
        category = attrs["category"]
        subcategory = attrs["subcategory"]
        unit = attrs.get("unit")
        common_area = attrs.get("common_area")
        workflow_type = self.context["view"].workflow_type
        errors = {}
        if subcategory.category_id != category.id:
            errors["subcategory"] = "Subcategory must belong to the selected category."
        if unit is not None and common_area is not None:
            errors["common_area"] = "A ticket may target only one location."
        if workflow_type == Ticket.WorkflowType.SERVICE and unit is None and common_area is None:
            errors["unit"] = "Service tickets require exactly one location."
        if unit is not None and not category.allows_unit_location:
            errors["unit"] = "Category does not permit unit locations."
        if common_area is not None and not category.allows_common_area_location:
            errors["common_area"] = "Category does not permit common-area locations."
        if unit is None and common_area is None and not category.allows_no_location:
            errors["unit"] = "Category requires a location."

        membership = self.context["request"].membership
        if isinstance(membership, UnitOccupancy) and unit is not None:
            if membership.unit_id != unit.id:
                errors["unit"] = "Residents may create tickets only for their own unit."
        if errors:
            raise serializers.ValidationError(errors)

        attrs["priority"] = attrs.get("priority", subcategory.default_priority)
        return attrs


class TicketSubmitSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)


class TicketCancelSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class TicketBeginGovernanceReviewSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)


class TicketAssignInHouseSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    technician_id = serializers.UUIDField()


class TicketAssignVendorSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    vendor_contract_id = serializers.UUIDField()


class TicketAllocateVendorWorkerSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    staff_membership_id = serializers.UUIDField()


class TicketReplaceVendorWorkerSerializer(TicketAllocateVendorWorkerSerializer):
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class TicketAcceptVendorWorkerSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)


class TicketAcceptVendorWorkerOnBehalfSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class TicketRespondToInHouseAssignmentSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)


class TicketRejectInHouseAssignmentSerializer(
    TicketRespondToInHouseAssignmentSerializer
):
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class TicketStartWorkSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)


class TicketRejectVendorAssignmentSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class TicketRequestCompletionSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    work_notes = serializers.CharField(max_length=4000, trim_whitespace=True)


class TicketVerifyCompletionSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    otp = serializers.CharField(max_length=16, trim_whitespace=True)


class TicketEstimateLineItemSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=255, trim_whitespace=True)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    unit_cost = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))


class TicketEstimateLineItemReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketEstimateLineItem
        fields = (
            "id",
            "description",
            "quantity",
            "unit_cost",
            "total_cost",
            "created_at",
        )


class TicketEstimateReadSerializer(serializers.ModelSerializer):
    items = TicketEstimateLineItemReadSerializer(many=True, read_only=True)
    created_by_name = serializers.SerializerMethodField()
    decided_by_name = serializers.SerializerMethodField()
    can_decide = serializers.SerializerMethodField()

    class Meta:
        model = TicketEstimate
        fields = (
            "id",
            "ticket_id",
            "version",
            "status",
            "cost_responsibility",
            "currency",
            "subtotal_amount",
            "tax_amount",
            "total_amount",
            "notes",
            "decision_reason",
            "decided_by_id",
            "decided_by_name",
            "decided_at",
            "decision_deadline",
            "created_by_id",
            "created_by_name",
            "created_at",
            "updated_at",
            "items",
            "can_decide",
        )

    def get_created_by_name(self, obj):
        if obj.created_by:
            return str(getattr(obj.created_by, "phone", "") or getattr(obj.created_by, "email", "") or str(obj.created_by))
        return ""

    def get_decided_by_name(self, obj):
        if obj.decided_by:
            return str(getattr(obj.decided_by, "phone", "") or getattr(obj.decided_by, "email", "") or str(obj.decided_by))
        return ""

    def get_can_decide(self, obj):
        request = self.context.get("request")
        if not request or not hasattr(request, "membership") or not hasattr(request, "user"):
            return False
        if obj.status != TicketEstimate.Status.SUBMITTED:
            return False
        try:
            from apps.tickets.services import (
                TicketEstimateDecisionForbidden,
                _persona_for_estimate_approver,
            )

            _persona_for_estimate_approver(
                ticket=obj.ticket,
                actor=request.user,
                membership=request.membership,
            )
            return True
        except (TicketEstimateDecisionForbidden, Exception):
            return False



class TicketSubmitEstimateSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    items = serializers.ListField(
        child=TicketEstimateLineItemSerializer(),
        allow_empty=False,
    )
    tax_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        default=Decimal("0.00"),
        required=False,
    )
    notes = serializers.CharField(
        max_length=4000,
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
    )


class TicketApproveEstimateSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    notes = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
    )


class TicketRejectEstimateSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class TicketWithdrawEstimateSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class TicketReopenSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class TicketCloseSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(
        max_length=1000,
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
    )


class TicketReassignFromTriageSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    target_type = serializers.ChoiceField(choices=TicketAssignment.TargetType.choices)
    technician_id = serializers.UUIDField(required=False, allow_null=True)
    vendor_contract_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        target_type = attrs.get("target_type")
        if target_type == TicketAssignment.TargetType.IN_HOUSE and not attrs.get("technician_id"):
            raise serializers.ValidationError({"technician_id": "technician_id is required for in-house assignment."})
        if target_type == TicketAssignment.TargetType.VENDOR and not attrs.get("vendor_contract_id"):
            raise serializers.ValidationError({"vendor_contract_id": "vendor_contract_id is required for vendor assignment."})
        return attrs


class TicketOverrideResumeSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class TicketSupervisorCompletionSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)
    proof_notes = serializers.CharField(max_length=2000, trim_whitespace=True)


class TicketOpenGovernanceDiscussionSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    purpose = serializers.CharField(max_length=1000, trim_whitespace=True)


class TicketRecordGovernanceActionSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    summary = serializers.CharField(max_length=1000, trim_whitespace=True)


class TicketCommentSerializer(serializers.ModelSerializer):
    ticket_id = serializers.UUIDField(read_only=True)
    author_id = serializers.UUIDField(read_only=True)
    is_authored_by_requester = serializers.SerializerMethodField()

    class Meta:
        model = TicketComment
        fields = (
            "id",
            "ticket_id",
            "author_id",
            "author_persona",
            "visibility",
            "body",
            "created_at",
            "is_authored_by_requester",
        )
        read_only_fields = fields

    def get_is_authored_by_requester(self, comment):
        request = self.context.get("request")
        return request is not None and comment.author_id == request.user.id


class TicketCommentCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=4000, trim_whitespace=True)
    expected_version = serializers.IntegerField(min_value=1)


class TicketFeedbackSubmitSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    overall_rating = serializers.IntegerField(min_value=1, max_value=5)
    timeliness_rating = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    quality_rating = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    technician_behavior_rating = serializers.IntegerField(min_value=1, max_value=5, required=False, allow_null=True)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=64, trim_whitespace=True),
        required=False,
        default=list,
    )
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class TicketFeedbackSerializer(serializers.ModelSerializer):
    ticket_id = serializers.UUIDField(read_only=True)
    resident_id = serializers.UUIDField(read_only=True)
    technician_id = serializers.UUIDField(read_only=True, allow_null=True)
    vendor_contract_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = TicketFeedback
        fields = (
            "id",
            "ticket_id",
            "resident_id",
            "technician_id",
            "vendor_contract_id",
            "overall_rating",
            "timeliness_rating",
            "quality_rating",
            "technician_behavior_rating",
            "tags",
            "comment",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class TicketMergeSerializer(serializers.Serializer):
    expected_primary_version = serializers.IntegerField(min_value=1)
    expected_secondary_version = serializers.IntegerField(min_value=1)
    secondary_ticket_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class TicketUnmergeSerializer(serializers.Serializer):
    expected_primary_version = serializers.IntegerField(min_value=1)
    expected_secondary_version = serializers.IntegerField(min_value=1)
    secondary_ticket_id = serializers.UUIDField()
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class TicketMergeRecordSerializer(serializers.ModelSerializer):
    primary_ticket_id = serializers.UUIDField(read_only=True)
    secondary_ticket_id = serializers.UUIDField(read_only=True)
    merged_by_id = serializers.UUIDField(read_only=True)
    unmerged_by_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = TicketMergeRecord
        fields = (
            "id",
            "primary_ticket_id",
            "secondary_ticket_id",
            "merged_by_id",
            "merged_at",
            "reason",
            "previous_secondary_status",
            "is_active",
            "unmerged_by_id",
            "unmerged_at",
            "unmerge_reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class TicketAttachmentUploadSlotRequestSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(min_value=1)
    filename = serializers.CharField(max_length=255, trim_whitespace=True)
    content_type = serializers.CharField(max_length=128, trim_whitespace=True)
    byte_size = serializers.IntegerField(min_value=1)


class TicketAttachmentSerializer(serializers.ModelSerializer):
    ticket_id = serializers.UUIDField(read_only=True)
    uploaded_by_name = serializers.SerializerMethodField()
    byte_size_formatted = serializers.SerializerMethodField()

    class Meta:
        model = TicketAttachment
        fields = (
            "id",
            "ticket_id",
            "uploader_persona",
            "uploaded_by_name",
            "original_filename",
            "declared_content_type",
            "declared_byte_size",
            "byte_size_formatted",
            "status",
            "checksum_sha256",
            "actual_content_type",
            "actual_byte_size",
            "created_at",
        )
        read_only_fields = fields

    def get_uploaded_by_name(self, obj) -> str:
        user = getattr(obj, "uploaded_by", None)
        if not user:
            return ""
        phone = getattr(user, "phone", None)
        email = getattr(user, "email", None)
        return str(phone or email or user.id)

    def get_byte_size_formatted(self, obj) -> str:
        size = obj.declared_byte_size or 0
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"


class TicketAttachmentUploadSlotResponseSerializer(serializers.Serializer):
    attachment = TicketAttachmentSerializer()
    upload_url = serializers.CharField()
    upload_headers = serializers.DictField(child=serializers.CharField())
    expires_at = serializers.DateTimeField()
    state_version = serializers.IntegerField(min_value=1)