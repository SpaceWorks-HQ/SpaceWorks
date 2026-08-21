from rest_framework import serializers

from apps.operations.org_report_strategies import AggregationKind


class OrganizationReportRowsSerializer(serializers.Serializer):
    rows = serializers.ListField(child=serializers.DictField())


class OrganizationReportBreakdownSerializer(OrganizationReportRowsSerializer):
    makerspace_id = serializers.IntegerField()


class OrganizationReportResponseSerializer(serializers.Serializer):
    report_key = serializers.CharField()
    strategy = serializers.ChoiceField(
        choices=[kind.value for kind in AggregationKind]
    )
    breakdown = OrganizationReportBreakdownSerializer(many=True)
    total = OrganizationReportRowsSerializer()
