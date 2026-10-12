from rest_framework import serializers

from apps.operations.serializers_reports_base import ReportRowsFieldMixin, TypedReportBaseSerializer


class MemberRetentionRowSerializer(TypedReportBaseSerializer):
    cohort_month = serializers.CharField()
    months_after_join = serializers.IntegerField()
    cohort_members = serializers.IntegerField()
    eligible_members = serializers.IntegerField()
    retained_members = serializers.IntegerField()
    retention_percent = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    churned_members = serializers.IntegerField()
    reactivated_members = serializers.IntegerField()


class MemberRetentionReportSerializer(ReportRowsFieldMixin):
    typed_rows = MemberRetentionRowSerializer(many=True)
    meta = serializers.DictField()
    report_key = serializers.CharField()


class MembershipRevenueRowSerializer(TypedReportBaseSerializer):
    period = serializers.DateField()
    currency = serializers.CharField()
    recurring_members = serializers.IntegerField()
    mrr = serializers.DecimalField(max_digits=24, decimal_places=2)
    arr = serializers.DecimalField(max_digits=24, decimal_places=2)
    arpu = serializers.DecimalField(max_digits=24, decimal_places=2)
    churned_members = serializers.IntegerField()
    reactivated_members = serializers.IntegerField()


class MembershipRevenueReportSerializer(ReportRowsFieldMixin):
    typed_rows = MembershipRevenueRowSerializer(many=True)
    meta = serializers.DictField()
    report_key = serializers.CharField()
