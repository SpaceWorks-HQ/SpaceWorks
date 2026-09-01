from rest_framework import serializers


class TimelineActorSerializer(serializers.Serializer):
    username = serializers.CharField()
    role = serializers.CharField()


class TimelineEventSerializer(serializers.Serializer):
    kind = serializers.CharField()
    at = serializers.DateTimeField()
    actor = TimelineActorSerializer(allow_null=True)
    detail = serializers.DictField()
    evidence_id = serializers.IntegerField(allow_null=True)


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
