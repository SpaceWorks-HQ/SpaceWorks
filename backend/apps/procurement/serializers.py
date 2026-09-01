from rest_framework import serializers

from apps.machines.models import MachineType
from apps.procurement.models import ToBuyItem, ToBuyReceipt


class ErrorSerializer(serializers.Serializer):
    detail = serializers.CharField(required=False)


class ToBuyMachineTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = MachineType
        fields = ["id", "name"]
        read_only_fields = fields


class ToBuyMachineTypeOptionsSerializer(serializers.Serializer):
    """Options plus a SERVER-derived answer to "must the caller pick one?".

    The console must not infer this from effective actions. A null-`assigned_role`
    legacy membership is scope-exempt and cannot be expressed that way, and "holds
    MANAGE_MACHINES" is not the same question as "is narrowed by machine scope" -- a role
    holding MANAGE_MAKERSPACE holds both and is exempt. Deriving it here keeps one answer
    on the server, the same reason the dashboard carries `scope_mode`.
    """

    machine_type_required = serializers.BooleanField()
    results = ToBuyMachineTypeSerializer(many=True)


class ToBuyReceiptSerializer(serializers.ModelSerializer):
    uploaded_by_username = serializers.CharField(
        source="uploaded_by.username",
        read_only=True,
        default=None,
    )

    class Meta:
        model = ToBuyReceipt
        fields = [
            "id",
            "created_at",
            "uploaded_by",
            "uploaded_by_username",
        ]
        read_only_fields = fields


class ToBuyItemSerializer(serializers.ModelSerializer):
    # kind is decided server-side from the actor's role (see access.derive_kind),
    # never written from the request body - so it is read-only here.
    created_by_username = serializers.CharField(
        source="created_by.username",
        read_only=True,
        default=None,
    )
    purchaser = serializers.PrimaryKeyRelatedField(read_only=True)
    purchaser_username = serializers.CharField(
        source="purchaser.username",
        read_only=True,
        default=None,
    )
    receipts = ToBuyReceiptSerializer(many=True, read_only=True)
    machine_type_name = serializers.CharField(
        source="machine_type.name",
        read_only=True,
        default=None,
        allow_null=True,
    )
    # Declared explicitly with min_value=1 so the OpenAPI schema advertises
    # minimum: 1 - matching the server rule that quantity must be >= 1.
    quantity = serializers.IntegerField(min_value=1, default=1)

    class Meta:
        model = ToBuyItem
        fields = [
            "id",
            "makerspace",
            "kind",
            "machine_type",
            "machine_type_name",
            "name",
            "quantity",
            "link",
            "status",
            "estimated_unit_cost",
            "vendor_name",
            "actual_unit_cost",
            "purchaser",
            "purchaser_username",
            "ordered_at",
            "received_at",
            "moved_to_inventory_at",
            "resulting_product",
            "resulting_pool",
            "resulting_machine",
            "source_pool",
            "receipts",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "makerspace",
            "kind",
            "machine_type_name",
            "purchaser",
            "purchaser_username",
            "ordered_at",
            "received_at",
            "moved_to_inventory_at",
            "resulting_product",
            "resulting_pool",
            "resulting_machine",
            "source_pool",
            "receipts",
            "created_by",
            "created_by_username",
            "created_at",
            "updated_at",
        ]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name is required.")
        return value

    def validate_vendor_name(self, value):
        return value.strip()

    def validate_estimated_unit_cost(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Estimated unit cost cannot be negative.")
        return value

    def validate_actual_unit_cost(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Actual unit cost cannot be negative.")
        return value


class MoveToInventoryRequestSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=["create", "topup"])
    product_id = serializers.IntegerField(required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=1)
    box = serializers.IntegerField(required=False, allow_null=True)
    category = serializers.IntegerField(required=False, allow_null=True)
    tracking_mode = serializers.ChoiceField(
        choices=["quantity", "individual"],
        required=False,
        default="quantity",
    )
    is_public = serializers.BooleanField(default=True)
    public_availability_mode = serializers.ChoiceField(
        choices=["exact_count", "status_only", "hidden"],
        default="status_only",
    )
    show_public_count = serializers.BooleanField(default=False)
    public_self_checkout_enabled = serializers.BooleanField(default=False)
    name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        mode = attrs.get("mode")
        if mode == "topup" and not attrs.get("product_id"):
            raise serializers.ValidationError(
                {"product_id": "This field is required for topup."}
            )
        if mode == "create" and not (attrs.get("name") or "").strip():
            raise serializers.ValidationError({"name": "This field is required for create."})
        return attrs


class MoveToPrintingRequestSerializer(serializers.Serializer):
    target = serializers.ChoiceField(choices=["spool", "printer"])
    printer = serializers.IntegerField(required=False, allow_null=True)
    material = serializers.CharField(required=False, allow_blank=True, max_length=100)
    color = serializers.CharField(required=False, allow_blank=True, max_length=100)
    brand = serializers.CharField(required=False, allow_blank=True, max_length=100)
    lot_code = serializers.CharField(required=False, allow_blank=True, max_length=100)
    initial_weight_grams = serializers.DecimalField(
        required=False,
        max_digits=8,
        decimal_places=2,
    )
    remaining_weight_grams = serializers.DecimalField(
        required=False,
        max_digits=8,
        decimal_places=2,
    )
    is_active = serializers.BooleanField(required=False)
    opened_at = serializers.DateTimeField(required=False, allow_null=True)
    name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    model = serializers.CharField(required=False, allow_blank=True, max_length=200)
    status = serializers.ChoiceField(
        choices=["active", "maintenance", "offline"],
        required=False,
    )
    notes = serializers.CharField(required=False, allow_blank=True)


class ToBuyReceiptPresignSerializer(serializers.Serializer):
    filename = serializers.CharField(allow_blank=False, max_length=255)
    content_type = serializers.CharField(allow_blank=False, max_length=100)


class ToBuyReceiptFinalizeSerializer(serializers.Serializer):
    object_key = serializers.CharField(allow_blank=False, max_length=512)


class ToBuyReceiptUploadResponseSerializer(serializers.Serializer):
    object_key = serializers.CharField()
    upload = serializers.DictField()


class ToBuyReceiptUrlSerializer(serializers.Serializer):
    url = serializers.URLField()
