from rest_framework import serializers
from apps.operations.models import StocktakeLine, StocktakeSession


class StocktakeCreateSerializer(serializers.Serializer):
    blind = serializers.BooleanField(required=False)
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
    expected_quantity = serializers.IntegerField(read_only=True, allow_null=True)
    variance_quantity = serializers.IntegerField(read_only=True, allow_null=True)

    def to_representation(self, instance):
        result = super().to_representation(instance)
        if instance.stocktake.blind and instance.stocktake.status in ('draft', 'counting'):
            result['expected_quantity'] = None
            result['variance_quantity'] = None
        return result

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
    approval_required = serializers.BooleanField(read_only=True)
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
            "blind",
            "variance_threshold",
            "approval_required",
            "lines",
        ]


