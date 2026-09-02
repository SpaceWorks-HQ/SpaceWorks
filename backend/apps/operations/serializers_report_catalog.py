from rest_framework import serializers


class ReportCatalogItemSerializer(serializers.Serializer):
    key = serializers.CharField()
    title = serializers.CharField()
    fields = serializers.ListField(child=serializers.CharField())
    exportable = serializers.BooleanField()
    summary = serializers.BooleanField()
    required_modules = serializers.ListField(child=serializers.CharField())
    available = serializers.BooleanField(allow_null=True)
    unavailable_reason = serializers.CharField(allow_null=True)
    grains = serializers.ListField(child=serializers.CharField())
    chart_hint = serializers.CharField()
    aggregate_supported = serializers.BooleanField()


class ReportCatalogSerializer(serializers.Serializer):
    results = ReportCatalogItemSerializer(many=True)


class GenericAnalyticsReportSerializer(serializers.Serializer):
    report_key = serializers.CharField(required=False)
    rows = serializers.ListField(child=serializers.ListField(child=serializers.JSONField()))
    typed_rows = serializers.ListField(child=serializers.DictField(), required=False)
    meta = serializers.DictField(required=False)
