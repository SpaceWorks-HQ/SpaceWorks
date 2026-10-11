"""Bounded checklist definitions and physical-count inputs shared by loan surfaces."""

import uuid

from rest_framework import serializers


class KitComponentSerializer(serializers.Serializer):
    key = serializers.UUIDField(default=uuid.uuid4)
    label = serializers.CharField(max_length=200)
    quantity = serializers.IntegerField(min_value=1, max_value=999)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        value["key"] = str(value["key"])
        return value


class KitDefinitionField(serializers.ListField):
    def __init__(self, **kwargs):
        super().__init__(child=KitComponentSerializer(), max_length=50, **kwargs)

    def run_validation(self, data=serializers.empty):
        value = super().run_validation(data)
        if value is serializers.empty:
            return value
        keys = [entry["key"] for entry in value]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError("Component keys must be unique.")
        return value


class KitCountSerializer(serializers.Serializer):
    key = serializers.UUIDField()
    present = serializers.IntegerField(min_value=0, max_value=2147483647)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        value["key"] = str(value["key"])
        return value


class KitCountsField(serializers.ListField):
    def __init__(self, **kwargs):
        super().__init__(child=KitCountSerializer(), max_length=3550, **kwargs)


class KitExpectationSerializer(serializers.Serializer):
    key = serializers.UUIDField()
    label = serializers.CharField()
    owner_label = serializers.CharField()
    quantity = serializers.IntegerField()
    issue_present = serializers.IntegerField(required=False)


class KitSnapshotSerializer(KitExpectationSerializer):
    present = serializers.IntegerField()
    baseline = serializers.IntegerField(required=False)


class KitPreviewSerializer(serializers.Serializer):
    components = KitExpectationSerializer(many=True)
