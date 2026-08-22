from rest_framework import serializers

from apps.operations.serializers_health import (
    ContainerAssetSummarySerializer,
    ContainerProductSummarySerializer,
    EmptySerializer,
    GenericObjectSerializer,
    HealthSerializer,
    ReadinessSerializer,
)

from apps.boxes.models import Box, QrCode
from apps.boxes.serializers import BoxSerializer, QrCodeSerializer
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.operations.models import (
    InventoryAdjustment,
    QrPrintBatch,
    QrPrintBatchItem,
    StockTransfer,
    StockTransferLine,
    StocktakeLine,
    StocktakeSession,
)


class ContainerContentsSerializer(serializers.Serializer):
    container = BoxSerializer()
    products = ContainerProductSummarySerializer(many=True)
    assets = ContainerAssetSummarySerializer(many=True)
    children = BoxSerializer(many=True)


class ContainerScanHistoryItemSerializer(serializers.Serializer):
    id = serializers.CharField()
    source = serializers.CharField()
    context = serializers.CharField()
    actor = serializers.IntegerField(allow_null=True)
    created_at = serializers.DateTimeField()


class ContainerHistorySerializer(serializers.Serializer):
    container = serializers.IntegerField()
    scans = ContainerScanHistoryItemSerializer(many=True)


class AnalyticsSummarySerializer(serializers.Serializer):
    products = serializers.IntegerField()
    assets = serializers.IntegerField()
    active_loans = serializers.IntegerField()
    available_quantity = serializers.IntegerField()
    issued_quantity = serializers.IntegerField()
    damaged_quantity = serializers.IntegerField()
    missing_quantity = serializers.IntegerField()


class ReportRowsSerializer(serializers.Serializer):
    rows = serializers.ListField(child=serializers.ListField(child=serializers.CharField(allow_blank=True, allow_null=True)))


class LedgerUnitSerializer(serializers.Serializer):
    asset_tag = serializers.CharField()
    serial_number = serializers.CharField(allow_blank=True)


class LedgerRowSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=["request", "self_checkout", "direct_handout"])
    item_name = serializers.CharField()
    container = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    holder = serializers.CharField(allow_blank=True)
    quantity = serializers.IntegerField()
    units = LedgerUnitSerializer(many=True)
    target_label = serializers.CharField(
        allow_blank=True,
        allow_null=True,
        required=False,
    )
    since = serializers.DateTimeField(allow_null=True)
    due = serializers.DateTimeField(allow_null=True)
    makerspace_id = serializers.IntegerField()
    reference_id = serializers.IntegerField()
    status = serializers.CharField()


class LedgerResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True, required=False)
    previous = serializers.CharField(allow_null=True, required=False)
    results = LedgerRowSerializer(many=True)


class AssetGenerateItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    asset_tag = serializers.CharField()
    qr = QrCodeSerializer()


class AssetGenerateResultSerializer(serializers.Serializer):
    assets = AssetGenerateItemSerializer(many=True)
    print_batch_id = serializers.IntegerField(allow_null=True)


class QrPrintBatchItemResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()


class StockTransferLineInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(required=False)
    asset_id = serializers.IntegerField(required=False)
    quantity = serializers.IntegerField(min_value=1, default=1)
    from_status = serializers.ChoiceField(choices=InventoryAsset.Status.choices, required=False, allow_blank=True)
    to_status = serializers.ChoiceField(choices=InventoryAsset.Status.choices, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if bool(attrs.get("product_id")) == bool(attrs.get("asset_id")):
            raise serializers.ValidationError("Provide exactly one of product_id or asset_id.")
        return attrs


class StockTransferCreateSerializer(serializers.Serializer):
    source_container_id = serializers.IntegerField(required=False, allow_null=True)
    destination_container_id = serializers.IntegerField(required=False, allow_null=True)
    destination_makerspace_id = serializers.IntegerField(required=False, allow_null=True)
    reason = serializers.CharField(allow_blank=False)
    lines = StockTransferLineInputSerializer(many=True, allow_empty=False)


class StockTransferLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockTransferLine
        fields = ["id", "product", "asset", "quantity", "from_status", "to_status", "notes"]


class StockTransferSerializer(serializers.ModelSerializer):
    lines = StockTransferLineSerializer(many=True, read_only=True)

    class Meta:
        model = StockTransfer
        fields = [
            "id",
            "makerspace",
            "source_container",
            "destination_container",
            "source_makerspace",
            "destination_makerspace",
            "created_by",
            "reason",
            "status",
            "created_at",
            "applied_at",
            "lines",
        ]


class StocktakeCreateSerializer(serializers.Serializer):
    container_id = serializers.IntegerField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class StocktakeLineInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(required=False)
    asset_id = serializers.IntegerField(required=False)
    container_id = serializers.IntegerField(required=False, allow_null=True)
    counted_quantity = serializers.IntegerField(min_value=0)
    condition = serializers.ChoiceField(choices=StocktakeLine.Condition.choices, default=StocktakeLine.Condition.AVAILABLE)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if bool(attrs.get("product_id")) == bool(attrs.get("asset_id")):
            raise serializers.ValidationError("Provide exactly one of product_id or asset_id.")
        return attrs


class StocktakeScanInputSerializer(serializers.Serializer):
    payload = serializers.CharField(max_length=64)


class StocktakeScanResultSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["box", "asset", "product"])
    container_id = serializers.IntegerField(required=False)
    asset_id = serializers.IntegerField(required=False)
    product_id = serializers.IntegerField(required=False)
    label = serializers.CharField(required=False)
    code = serializers.CharField(required=False)
    asset_tag = serializers.CharField(required=False)
    product = serializers.CharField(required=False)
    name = serializers.CharField(required=False)
    status = serializers.CharField(required=False)


class StocktakeLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = StocktakeLine
        fields = [
            "id",
            "product",
            "asset",
            "container",
            "expected_quantity",
            "counted_quantity",
            "variance_quantity",
            "condition",
            "notes",
        ]


class StocktakeSerializer(serializers.ModelSerializer):
    lines = StocktakeLineSerializer(many=True, read_only=True)

    class Meta:
        model = StocktakeSession
        fields = [
            "id",
            "makerspace",
            "container",
            "status",
            "started_by",
            "approved_by",
            "started_at",
            "completed_at",
            "approved_at",
            "notes",
            "lines",
        ]


class InventoryAdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryAdjustment
        fields = [
            "id",
            "makerspace",
            "stocktake",
            "transfer",
            "product",
            "asset",
            "delta_available",
            "delta_damaged",
            "delta_lost",
            "reason",
            "created_by",
            "created_at",
        ]


class ContainerMoveSerializer(serializers.Serializer):
    parent_id = serializers.IntegerField(required=False, allow_null=True)
    label = serializers.CharField(required=False)
    location = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)


class AssetGenerateSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=1, max_value=200)
    name_prefix = serializers.CharField(required=False, allow_blank=True)
    serial_numbers = serializers.ListField(child=serializers.CharField(), required=False)
    print_batch_id = serializers.IntegerField(required=False, allow_null=True)
    create_print_batch = serializers.BooleanField(default=False)


class QrPrintBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = QrPrintBatch
        fields = ["id", "makerspace", "title", "status", "created_by", "created_at", "printed_at"]


class QrPrintBatchItemSerializer(serializers.ModelSerializer):
    qr_code = QrCodeSerializer(read_only=True)

    class Meta:
        model = QrPrintBatchItem
        fields = ["id", "qr_code", "label_text", "target_type", "target_id", "sort_order"]


class QrPrintBatchDetailSerializer(QrPrintBatchSerializer):
    items = QrPrintBatchItemSerializer(many=True, read_only=True)

    class Meta(QrPrintBatchSerializer.Meta):
        fields = QrPrintBatchSerializer.Meta.fields + ["items"]


class QrPrintBatchCreateSerializer(serializers.Serializer):
    title = serializers.CharField()


class QrPrintBatchItemCreateSerializer(serializers.Serializer):
    qr_code_id = serializers.IntegerField()
    label_text = serializers.CharField(required=False, allow_blank=True)
    sort_order = serializers.IntegerField(min_value=0, required=False)
