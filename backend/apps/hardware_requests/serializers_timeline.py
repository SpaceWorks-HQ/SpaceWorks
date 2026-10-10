from rest_framework import serializers


class TimelineActorSerializer(serializers.Serializer):
    username = serializers.CharField()
    role = serializers.CharField()


class EvidenceRetentionSerializer(serializers.Serializer):
    """Retention coordination only: ``null`` on the event means no state row exists,
    which is NOT a claim that the bytes are available."""

    state = serializers.ChoiceField(choices=["expiring", "expired"])
    object_expired_at = serializers.DateTimeField(allow_null=True)


class TimelineEventSerializer(serializers.Serializer):
    kind = serializers.CharField(
        help_text="Event kind. `audit` events carry `detail.action`, `detail.action_label`, "
        "projected `detail.meta`, `detail.meta_redacted` and `detail.target_link`."
    )
    at = serializers.DateTimeField()
    actor = TimelineActorSerializer(allow_null=True)
    detail = serializers.DictField()
    evidence_id = serializers.IntegerField(allow_null=True)
    evidence_retention = EvidenceRetentionSerializer(allow_null=True, required=False)


class RequestTimelineResponseSerializer(serializers.Serializer):
    request_id = serializers.IntegerField()
    limit = serializers.IntegerField()
    truncated = serializers.BooleanField()
    events = TimelineEventSerializer(many=True)


class AssetChainGroupSerializer(serializers.Serializer):
    asset_id = serializers.IntegerField(allow_null=True)
    asset_tag = serializers.CharField(allow_blank=True)
    serial_number = serializers.CharField(allow_blank=True)
    status = serializers.CharField(allow_blank=True)
    events = TimelineEventSerializer(many=True)


class QuantityChainSummarySerializer(serializers.Serializer):
    loan_count = serializers.IntegerField()
    direct_loan_count = serializers.IntegerField()
    issued_quantity = serializers.IntegerField()
    returned_quantity = serializers.IntegerField()
    damaged_quantity = serializers.IntegerField()
    missing_quantity = serializers.IntegerField()
    active_quantity = serializers.IntegerField()


class InventoryChainOfCustodyResponseSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    tracking_mode = serializers.CharField()
    limit = serializers.IntegerField()
    truncated = serializers.BooleanField()
    events = TimelineEventSerializer(many=True)
    asset_groups = AssetChainGroupSerializer(many=True)
    quantity_summary = QuantityChainSummarySerializer(allow_null=True)
