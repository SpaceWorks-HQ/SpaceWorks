from rest_framework import serializers


class GenericObjectSerializer(serializers.Serializer):
    detail = serializers.CharField(required=False)


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField()


class ArchiveCustodyReadinessSerializer(serializers.Serializer):
    below_floor_makerspaces = serializers.IntegerField(min_value=0)


class ReadinessSerializer(serializers.Serializer):
    status = serializers.CharField()
    database = serializers.CharField()
    archive_custody = ArchiveCustodyReadinessSerializer()


class EmptySerializer(serializers.Serializer):
    pass


class ContainerProductSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    available_quantity = serializers.IntegerField()
    tracking_mode = serializers.CharField()


class ContainerAssetSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    asset_tag = serializers.CharField()
    product = serializers.CharField()
    status = serializers.CharField()
