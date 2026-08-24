from rest_framework import serializers

from apps.boxes.models import Box, QrCode
from apps.inventory.models import InventoryAsset


class InventoryQuantityAdjustmentSerializer(serializers.Serializer):
    delta_available = serializers.IntegerField(default=0)
    delta_damaged = serializers.IntegerField(default=0)
    delta_lost = serializers.IntegerField(default=0)
    reason = serializers.CharField(allow_blank=False, trim_whitespace=True)

    def validate(self, attrs):
        deltas = [
            attrs.get("delta_available", 0),
            attrs.get("delta_damaged", 0),
            attrs.get("delta_lost", 0),
        ]
        if not any(deltas):
            raise serializers.ValidationError("At least one quantity delta is required.")
        return attrs


class PublicImageUploadRequestSerializer(serializers.Serializer):
    content_type = serializers.CharField(allow_blank=False)
    filename = serializers.CharField(allow_blank=False, max_length=255)


class PublicImageAttachRequestSerializer(serializers.Serializer):
    object_key = serializers.CharField(allow_blank=False, max_length=300)


class PublicImageUploadResponseSerializer(serializers.Serializer):
    object_key = serializers.CharField()
    url = serializers.URLField()
    fields = serializers.DictField(required=False)
    method = serializers.CharField(required=False)
    headers = serializers.DictField(required=False)


class InventoryAssetAdminSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    box_label = serializers.CharField(source="box.label", read_only=True, allow_null=True)
    qr_code_id = serializers.SerializerMethodField()
    qr_payload = serializers.SerializerMethodField()

    class Meta:
        model = InventoryAsset
        fields = [
            "id",
            "makerspace",
            "product",
            "product_name",
            "box",
            "box_label",
            "asset_tag",
            "serial_number",
            "status",
            "qr_code_id",
            "qr_payload",
            "public_self_checkout_enabled",
            "notes",
            "updated_at",
        ]
        read_only_fields = fields

    def _active_qr(self, obj):
        if not hasattr(obj, "_active_qr"):
            obj._active_qr = (
                QrCode.objects.filter(
                    makerspace_id=obj.makerspace_id,
                    target_type=QrCode.TargetType.ASSET,
                    target_id=obj.id,
                    status=QrCode.Status.ACTIVE,
                )
                .order_by("id")
                .first()
            )
        return obj._active_qr

    def get_qr_code_id(self, obj) -> int | None:
        qr = self._active_qr(obj)
        return qr.id if qr else None

    def get_qr_payload(self, obj) -> str | None:
        qr = self._active_qr(obj)
        return qr.payload if qr else None


class NullableBoxPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    def to_internal_value(self, data):
        if data == "":
            return None
        return super().to_internal_value(data)


class InventoryAssetAdminUpdateSerializer(serializers.ModelSerializer):
    box = NullableBoxPrimaryKeyRelatedField(
        queryset=Box.objects.all(),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = InventoryAsset
        fields = [
            "asset_tag",
            "serial_number",
            "box",
            "notes",
            "public_self_checkout_enabled",
        ]

    def validate_box(self, value):
        if value is not None and value.makerspace_id != self.instance.makerspace_id:
            raise serializers.ValidationError("Container is not in this makerspace.")
        return value

    def validate(self, attrs):
        asset_tag = attrs.get("asset_tag")
        if asset_tag is not None:
            duplicate = (
                InventoryAsset.objects.filter(
                    makerspace_id=self.instance.makerspace_id,
                    asset_tag=asset_tag,
                )
                .exclude(pk=self.instance.pk)
                .exists()
            )
            if duplicate:
                raise serializers.ValidationError(
                    {
                        "asset_tag": (
                            "An asset with this tag already exists in this makerspace."
                        )
                    }
                )
        return attrs


class InventoryAssetStatusActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["shelve", "repair"])
