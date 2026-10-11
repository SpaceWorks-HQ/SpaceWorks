"""Explicit OpenAPI shapes for each registered finance report."""

from rest_framework import serializers
from apps.operations.serializers_reports_base import ReportRowsFieldMixin, TypedReportBaseSerializer


class FinanceAmountsSerializer(TypedReportBaseSerializer):
    currency = serializers.CharField()
    collected_amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    refunded_amount = serializers.DecimalField(max_digits=20, decimal_places=2)


class LedgerLineSerializer(FinanceAmountsSerializer):
    date = serializers.DateTimeField()
    row_kind = serializers.CharField()
    row_id = serializers.IntegerField()
    payment_id = serializers.IntegerField()
    document_number = serializers.CharField(allow_blank=True)
    subject_type = serializers.CharField()
    payer_type = serializers.CharField()
    payer_id = serializers.IntegerField(allow_null=True)
    status = serializers.CharField()
    amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    owed_amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    method = serializers.CharField(allow_blank=True)
    reference = serializers.CharField(allow_blank=True)
    effective = serializers.BooleanField()
    refund_status = serializers.CharField(allow_blank=True)


class RevenuePeriodSerializer(FinanceAmountsSerializer):
    period = serializers.DateField()
    subject_type = serializers.CharField()
    owed_amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    waived_amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    net_amount = serializers.DecimalField(max_digits=20, decimal_places=2)


class CashPeriodSerializer(FinanceAmountsSerializer):
    period = serializers.DateField()
    method = serializers.CharField()
    net_amount = serializers.DecimalField(max_digits=20, decimal_places=2)


class JournalLineSerializer(TypedReportBaseSerializer):
    date = serializers.DateField()
    document_number = serializers.CharField()
    kind = serializers.CharField()
    payment_id = serializers.IntegerField()
    subject_type = serializers.CharField()
    currency = serializers.CharField()
    account_code = serializers.CharField()
    debit = serializers.DecimalField(max_digits=20, decimal_places=2)
    credit = serializers.DecimalField(max_digits=20, decimal_places=2)
    settlement_method = serializers.CharField()


class PaymentsLedgerReportSerializer(ReportRowsFieldMixin):
    typed_rows = LedgerLineSerializer(many=True)


class RevenueOverTimeReportSerializer(ReportRowsFieldMixin):
    typed_rows = RevenuePeriodSerializer(many=True)


class CashBookReportSerializer(ReportRowsFieldMixin):
    typed_rows = CashPeriodSerializer(many=True)


class AccountingJournalReportSerializer(ReportRowsFieldMixin):
    typed_rows = JournalLineSerializer(many=True)
