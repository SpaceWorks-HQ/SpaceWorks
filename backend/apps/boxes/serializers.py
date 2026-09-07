from django.http import Http404
from rest_framework import serializers

from apps.boxes.models import Box, QrCode, QrScanEvent
from apps.inventory.models import InventoryAsset, InventoryProduct


class BoxSerializer(serializers.ModelSerializer):
    qr_code_id = serializers.SerializerMethodField()

    class Meta:
        model = Box
        fields = [
            "id",
            "makerspace",
            "parent",
            "code",
            "label",
            "location",
            "description",
            "is_active",
            "qr_code_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "code", "created_at", "updated_at"]

    def get_qr_code_id(self, obj) -> int | None:
        # Every box gets an active BOX QrCode at creation. Surfacing its id lets
        # QR-management flows (e.g. adding a box to a print batch) reference the
        # code directly instead of going through the scanner-gated resolve view.
        if hasattr(obj, "_active_qr_code_id"):
            return obj._active_qr_code_id
        qr = (
            QrCode.objects.filter(
                makerspace_id=obj.makerspace_id,
                target_type=QrCode.TargetType.BOX,
                target_id=obj.id,
                status=QrCode.Status.ACTIVE,
            )
            .order_by("id")
            .first()
        )
        return qr.id if qr else None


class QrCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = QrCode
        fields = [
            "id",
            "makerspace",
            "payload",
            "target_type",
            "target_id",
            "status",
            "created_at",
            "updated_at",
            "revoked_at",
        ]
        read_only_fields = ["id", "payload", "status", "created_at", "updated_at", "revoked_at"]


class CreateBoxQrSerializer(serializers.Serializer):
    makerspace_id = serializers.IntegerField()
    label = serializers.CharField()
    location = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    parent_id = serializers.IntegerField(required=False, allow_null=True)


class CreateToolQrSerializer(serializers.Serializer):
    makerspace_id = serializers.IntegerField()
    product_id = serializers.IntegerField(required=False)
    asset_id = serializers.IntegerField(required=False)

    def validate(self, attrs):
        if bool(attrs.get("product_id")) == bool(attrs.get("asset_id")):
            raise serializers.ValidationError("Provide exactly one of product_id or asset_id.")
        return attrs


class QrScanSerializer(serializers.Serializer):
    payload = serializers.CharField()
    context = serializers.ChoiceField(choices=[
        QrScanEvent.Context.ISSUE,
        QrScanEvent.Context.RETURN,
        QrScanEvent.Context.INVENTORY_CHECK,
    ])
    request_id = serializers.IntegerField(required=False, allow_null=True)


class QrScanResultSerializer(serializers.Serializer):
    qr = QrCodeSerializer()
    target = serializers.DictField()
    scan_id = serializers.IntegerField()


class QrResolveSerializer(serializers.Serializer):
    payload = serializers.CharField()


class QrResolveResultSerializer(serializers.Serializer):
    qr = QrCodeSerializer()
    target = serializers.DictField()
    allowed_actions = serializers.ListField(child=serializers.CharField())


class QrRebindTargetSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(
        choices=[QrCode.TargetType.PRODUCT, QrCode.TargetType.ASSET]
    )
    target_id = serializers.IntegerField()
    destination_makerspace_id = serializers.IntegerField(required=False, allow_null=True)
    destination_product_id = serializers.IntegerField(required=False, allow_null=True)
    # Cap to the smaller target column (asset_tag is 100, product name 200) so an
    # overlong rename returns a clean 400 instead of a DB-level error at save.
    new_name = serializers.CharField(required=False, allow_blank=True, max_length=100)


class QrRebindResultSerializer(serializers.Serializer):
    qr = QrCodeSerializer()
    target = serializers.DictField()


def qr_target_payload(qr):
    if qr.target_type == QrCode.TargetType.MEMBER_CARD:
        # Never a person from the generic scanner: VIEW_INVENTORY must not resolve identity.
        raise Http404
    if qr.target_type == QrCode.TargetType.BOX:
        box = Box.objects.get(pk=qr.target_id)
        return {"type": "box", "id": box.id, "label": box.label, "code": box.code}
    if qr.target_type == QrCode.TargetType.ASSET:
        asset = InventoryAsset.objects.select_related("product").get(pk=qr.target_id)
        return {
            "type": "asset",
            "id": asset.id,
            "asset_tag": asset.asset_tag,
            "product": asset.product.name,
            "status": asset.status,
        }
    product = InventoryProduct.objects.get(pk=qr.target_id)
    return {"type": "product", "id": product.id, "name": product.name}
