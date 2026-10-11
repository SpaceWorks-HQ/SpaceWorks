from rest_framework import serializers
from apps.inventory.kit_serializers import KitCountsField


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
    kit_checklist = KitCountsField(required=False, default=list)
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
    kit_checklist = KitCountsField(required=False, default=list)
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
