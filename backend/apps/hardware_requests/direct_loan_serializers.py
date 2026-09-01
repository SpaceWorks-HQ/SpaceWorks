from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.hardware_requests.self_checkout_serializers import PublicToolLoanSerializer
from apps.hardware_requests.serializers import ReturnItemResolutionSerializer
from apps.inventory.models import InventoryAsset, TrackingMode


class DirectLoanItemSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class DirectLoanIssueSerializer(serializers.Serializer):
    borrower_id = serializers.IntegerField()
    evidence_id = serializers.IntegerField()
    remark = serializers.CharField(required=False, allow_blank=True)
    container_id = serializers.IntegerField(required=False, allow_null=True)
    qr_payloads = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        allow_empty=True,
        max_length=50,
    )
    items = DirectLoanItemSerializer(many=True, required=False, allow_empty=True)

    def validate(self, attrs):
        if (
            not attrs.get("qr_payloads")
            and not attrs.get("items")
            and attrs.get("container_id") is None
        ):
            raise serializers.ValidationError(
                "Provide qr_payloads, items, or a container."
            )
        return attrs


class DirectLoanReturnSerializer(serializers.Serializer):
    evidence_id = serializers.IntegerField()
    notes = serializers.CharField()
    qr_payload = serializers.CharField(max_length=64, required=False, allow_blank=True)
    # Optional + may be empty: a container-only direct loan carries no request
    # items, so a return resolves nothing. Loans WITH outstanding units still
    # require full resolution, enforced in return_direct_loan.
    resolutions = ReturnItemResolutionSerializer(many=True, required=False, default=list)

    def validate(self, attrs):
        # Duplicate item_ids would each be applied by availability.return_items
        # (over-returning the item), and the full-resolution check only keeps the
        # last one. Reject them up front (mirrors ReturnRequestSerializer).
        item_ids = [resolution["item_id"] for resolution in attrs.get("resolutions") or []]
        if len(item_ids) != len(set(item_ids)):
            raise serializers.ValidationError(
                {"resolutions": "Duplicate item_id values are not allowed."}
            )
        return attrs


class DirectLoanUserAttributionSerializer(serializers.Serializer):
    username = serializers.CharField()
    role = serializers.CharField()


class DirectLoanReturnAssetSerializer(serializers.Serializer):
    asset_id = serializers.IntegerField()
    asset_tag = serializers.CharField()


class DirectLoanReturnItemSerializer(serializers.Serializer):
    item_id = serializers.IntegerField()
    product_name = serializers.CharField()
    remaining_quantity = serializers.IntegerField()
    tracking_mode = serializers.CharField()
    assets = DirectLoanReturnAssetSerializer(many=True)


class DirectLoanSerializer(PublicToolLoanSerializer):
    id = serializers.IntegerField(read_only=True)
    target_type = serializers.CharField(read_only=True)
    target_label = serializers.CharField(read_only=True)
    container_id = serializers.IntegerField(read_only=True)
    container_label = serializers.SerializerMethodField()
    due_at = serializers.DateTimeField(read_only=True, allow_null=True)
    issue_evidence_id = serializers.IntegerField(
        source="request.issue_evidence_id",
        read_only=True,
        allow_null=True,
    )
    return_evidence_id = serializers.IntegerField(read_only=True, allow_null=True)
    return_notes = serializers.CharField(read_only=True, allow_blank=True)
    return_scan_required = serializers.SerializerMethodField()
    source = serializers.CharField(read_only=True)
    issued_by = serializers.SerializerMethodField()
    return_items = serializers.SerializerMethodField()

    @extend_schema_field(serializers.BooleanField())
    def get_return_scan_required(self, obj) -> bool:
        return bool(obj.qr_ids) or obj.container_id is not None

    @extend_schema_field(DirectLoanReturnItemSerializer(many=True))
    def get_return_items(self, obj) -> list[dict[str, object]]:
        # Per-item info the return modal needs to build resolutions: the request
        # item id, outstanding quantity, tracking mode, and (for individual-tracked
        # items) the still-issued physical units pulled from the loan's asset_ids.
        if "items" in getattr(obj.request, "_prefetched_objects_cache", {}):
            items = sorted(obj.request.items.all(), key=lambda item: item.product.name)
        else:
            items = list(
                obj.request.items.select_related("product").order_by("product__name")
            )
        asset_ids = [int(asset_id) for asset_id in (obj.asset_ids or [])]
        assets_by_product: dict[int, list[dict[str, object]]] = {}
        if asset_ids:
            for asset in InventoryAsset.objects.filter(
                pk__in=asset_ids,
                makerspace_id=obj.makerspace_id,
                status=InventoryAsset.Status.ISSUED,
            ).only("id", "asset_tag", "product_id"):
                assets_by_product.setdefault(asset.product_id, []).append(
                    {"asset_id": asset.id, "asset_tag": asset.asset_tag}
                )
        result = []
        for item in items:
            remaining = item.issued_quantity - (
                item.returned_quantity + item.damaged_quantity + item.missing_quantity
            )
            if remaining <= 0:
                continue
            is_individual = item.product.tracking_mode == TrackingMode.INDIVIDUAL
            result.append(
                {
                    "item_id": item.id,
                    "product_name": item.product.name,
                    "remaining_quantity": remaining,
                    "tracking_mode": item.product.tracking_mode,
                    "assets": assets_by_product.get(item.product_id, []) if is_individual else [],
                }
            )
        return result

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_container_label(self, obj):
        return obj.container.label if obj.container else None

    @extend_schema_field(DirectLoanUserAttributionSerializer(allow_null=True))
    def get_issued_by(self, obj):
        user = getattr(obj.request, "issued_by", None)
        if user is None:
            return None
        return {"username": user.username, "role": user.role}


class DirectLoanMemberSerializer(serializers.Serializer):
    membership_id = serializers.IntegerField(source="id", read_only=True)
    user_id = serializers.IntegerField(source="user.id", read_only=True)
    display_name = serializers.CharField(source="user.display_name", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    is_walk_in = serializers.BooleanField(source="user.is_walk_in", read_only=True)
