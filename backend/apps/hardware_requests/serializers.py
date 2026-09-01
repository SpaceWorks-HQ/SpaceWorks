from rest_framework import serializers

from apps.hardware_requests.display import requester_label
from apps.inventory.models import TrackingMode


class RequestItemInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=99)


class RequestSubmitSerializer(serializers.Serializer):
    CONTACT_FIELDS = ("contact_name", "contact_email", "contact_phone")

    website = serializers.CharField(required=False, allow_blank=True, write_only=True)
    contact_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        help_text="Required for an account-less submission.",
    )
    contact_email = serializers.EmailField(
        required=False,
        allow_blank=True,
        max_length=254,
        help_text="Required for an account-less submission; normalized to lowercase.",
    )
    contact_phone = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=32,
    )
    requested_for = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=500,
    )
    items = serializers.ListField(
        child=RequestItemInputSerializer(),
        allow_empty=False,
        max_length=20,
    )

    def to_internal_value(self, data):
        if not self.context.get("anonymous_submission", False):
            # Authenticated identity remains account-derived. Removing these fields
            # before child validation makes them genuinely ignored, including an
            # oversized spoof value that must not turn into a validation side channel.
            data = data.copy()
            for field_name in self.CONTACT_FIELDS:
                data.pop(field_name, None)
        return super().to_internal_value(data)

    def validate_contact_email(self, value):
        return value.strip().lower()

    def validate(self, attrs):
        attrs["website"] = attrs.get("website", "")
        if self.context.get("anonymous_submission", False):
            errors = {}
            if not attrs.get("contact_name", "").strip():
                errors["contact_name"] = "This field is required."
            if not attrs.get("contact_email", "").strip():
                errors["contact_email"] = "This field is required."
            if errors:
                raise serializers.ValidationError(errors)
        product_ids = [item["product_id"] for item in attrs["items"]]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError(
                {"items": "Duplicate product_id values are not allowed."}
            )
        return attrs


class RequestSubmitResponseSerializer(serializers.Serializer):
    public_token = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)


class PublicRequestItemStatusSerializer(serializers.Serializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    requested_quantity = serializers.IntegerField(read_only=True)


class PublicRequestStatusSerializer(serializers.Serializer):
    # Public + token-addressable: deliberately omits requester_username. The check-in
    # identity may be a name / email / badge / student id (PII), and the requester does
    # not need their own identity echoed back to learn a request's status.
    status = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    items = PublicRequestItemStatusSerializer(many=True, read_only=True)


class IssuedAssetSerializer(serializers.Serializer):
    asset_id = serializers.IntegerField(read_only=True, source="asset.id")
    asset_tag = serializers.CharField(read_only=True, source="asset.asset_tag")
    serial_number = serializers.CharField(read_only=True, source="asset.serial_number")


class AdminRequestItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    product_id = serializers.IntegerField(read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    # Free-text shelf/storage location so staff know where to physically fetch (issue) or
    # return each item during handover. Same prefetched product row as product_name (no N+1).
    storage_location = serializers.CharField(
        source="product.storage_location", read_only=True, allow_blank=True
    )
    # Exposed so the staff issue UI knows which accepted units require a scanned asset QR.
    # individual-mode products must be issued with one AVAILABLE asset QR per accepted unit
    # (handover_issue_helpers.issue_individual_assets), so the modal must collect scans for them.
    tracking_mode = serializers.CharField(source="product.tracking_mode", read_only=True)
    requires_asset_qr = serializers.SerializerMethodField()
    requested_quantity = serializers.IntegerField(read_only=True)
    accepted_quantity = serializers.IntegerField(read_only=True)
    issued_quantity = serializers.IntegerField(read_only=True)
    returned_quantity = serializers.IntegerField(read_only=True)
    damaged_quantity = serializers.IntegerField(read_only=True)
    missing_quantity = serializers.IntegerField(read_only=True)
    needs_fix_quantity = serializers.IntegerField(read_only=True)
    issued_assets = serializers.SerializerMethodField()

    def get_requires_asset_qr(self, obj) -> bool:
        return obj.product.tracking_mode == TrackingMode.INDIVIDUAL

    def get_issued_assets(self, obj) -> list:
        if obj.product.tracking_mode != TrackingMode.INDIVIDUAL:
            return []
        links = obj.asset_links.select_related("asset").filter(outcome="issued").order_by("asset_id")
        return IssuedAssetSerializer(links, many=True).data


class AdminRequestActorSerializer(serializers.Serializer):
    username = serializers.CharField(read_only=True)
    role = serializers.CharField(read_only=True)


class AdminRequestSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    makerspace_id = serializers.IntegerField(read_only=True)
    requester_username = serializers.CharField(read_only=True)
    requester_name = serializers.CharField(read_only=True)
    # Readable staff-facing label (Check-In email/phone), never the internal
    # checkin_<hash>. Additive - requester_username stays for the existing contract.
    requester_display = serializers.SerializerMethodField()
    requester_contact_email = serializers.EmailField(read_only=True)
    requester_contact_phone = serializers.CharField(read_only=True)
    requester_contact_verified = serializers.BooleanField(read_only=True)
    status = serializers.CharField(read_only=True)
    requested_for = serializers.CharField(read_only=True)
    rejection_reason = serializers.CharField(read_only=True)
    assigned_box_label = serializers.CharField(
        source="assigned_box.label",
        read_only=True,
        allow_null=True,
    )
    accepted_by = AdminRequestActorSerializer(read_only=True, allow_null=True)
    issued_by = AdminRequestActorSerializer(read_only=True, allow_null=True)
    accepted_at = serializers.DateTimeField(read_only=True)
    issued_at = serializers.DateTimeField(read_only=True)
    return_due_at = serializers.DateTimeField(read_only=True)
    return_reminder_sent_at = serializers.DateTimeField(read_only=True)
    closed_at = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    # Evidence-photo ids so the staff console can fetch signed view URLs (GET /admin/evidence/<id>)
    # and SHOW the issue/return photos - without these ids React had no way to view captured
    # evidence (only the Django admin could). issue_evidence is a direct FK; return photos hang
    # off the immutable ReturnEvent rows for this request.
    issue_evidence_id = serializers.IntegerField(read_only=True, allow_null=True)
    return_evidence_ids = serializers.SerializerMethodField()
    items = AdminRequestItemSerializer(many=True, read_only=True)

    def get_return_evidence_ids(self, obj) -> list:
        return [event.evidence_id for event in obj.returnevent_set.all() if event.evidence_id]

    def get_requester_display(self, obj) -> str:
        return requester_label(obj)


class AcceptQuantitySerializer(serializers.Serializer):
    item_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=0)


class AcceptRequestSerializer(serializers.Serializer):
    accepted_quantities = serializers.ListField(
        child=AcceptQuantitySerializer(),
        required=False,
    )

    def validate(self, attrs):
        item_ids = [entry["item_id"] for entry in attrs.get("accepted_quantities", [])]
        if len(item_ids) != len(set(item_ids)):
            raise serializers.ValidationError(
                {"accepted_quantities": "Duplicate item_id values are not allowed."}
            )
        return attrs


class RejectRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=False, trim_whitespace=True)


class AssignBoxSerializer(serializers.Serializer):
    box_code = serializers.CharField()


class IssueRejectSerializer(serializers.Serializer):
    item_id = serializers.IntegerField()
    broken = serializers.IntegerField(min_value=0, default=0)
    # "needs_fix" -> to-be-fixed shelf (default); "remove" -> scrapped out of inventory.
    disposition = serializers.ChoiceField(
        choices=["needs_fix", "remove"], default="needs_fix"
    )


class IssueRequestSerializer(serializers.Serializer):
    evidence_id = serializers.IntegerField()
    remark = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    asset_qr_payloads = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list,
    )
    # Per-item units rejected as broken at handover (quantity-mode items only).
    rejects = IssueRejectSerializer(many=True, required=False, default=list)


class ReturnDueSerializer(serializers.Serializer):
    return_due_at = serializers.DateTimeField(allow_null=True)


class ReturnAssetResolutionSerializer(serializers.Serializer):
    asset_id = serializers.IntegerField()
    outcome = serializers.ChoiceField(choices=["returned", "damaged", "missing"])


class ReturnItemResolutionSerializer(serializers.Serializer):
    item_id = serializers.IntegerField()
    returned = serializers.IntegerField(min_value=0, default=0)
    damaged = serializers.IntegerField(min_value=0, default=0)
    missing = serializers.IntegerField(min_value=0, default=0)
    assets = ReturnAssetResolutionSerializer(many=True, required=False, default=list)


class ReturnRequestSerializer(serializers.Serializer):
    evidence_id = serializers.IntegerField()
    box_code = serializers.CharField()
    remark = serializers.CharField(allow_blank=False, trim_whitespace=True)
    resolutions = ReturnItemResolutionSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        item_ids = [resolution["item_id"] for resolution in attrs["resolutions"]]
        if len(item_ids) != len(set(item_ids)):
            raise serializers.ValidationError(
                {"resolutions": "Duplicate item_id values are not allowed."}
            )
        asset_ids = []
        for resolution in attrs["resolutions"]:
            asset_ids.extend(asset["asset_id"] for asset in resolution.get("assets", []))
            if (
                resolution["returned"]
                + resolution["damaged"]
                + resolution["missing"]
                + len(resolution.get("assets", []))
            ) == 0:
                raise serializers.ValidationError(
                    {"resolutions": "Each resolution must resolve at least one item."}
                )
        if len(asset_ids) != len(set(asset_ids)):
            raise serializers.ValidationError(
                {"resolutions": "Duplicate asset_id values are not allowed."}
            )
        return attrs
