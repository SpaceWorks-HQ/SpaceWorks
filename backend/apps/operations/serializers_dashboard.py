"""Typed dashboard counters, including optional programme families."""

from rest_framework import serializers


class DashboardSerializer(serializers.Serializer):
    upcoming_events = serializers.IntegerField(required=False, default=0)
    pending_event_registrations = serializers.IntegerField(required=False, default=0)
    pending_bookings = serializers.IntegerField(required=False, default=0)
    upcoming_bookings = serializers.IntegerField(required=False, default=0)
    scope_mode = serializers.ChoiceField(choices=["machine", "full"])
    overdue_loans = serializers.IntegerField(required=False, default=0)
    pending_requests = serializers.IntegerField(required=False, default=0)
    awaiting_issue = serializers.IntegerField(required=False, default=0)
    open_problem_reports = serializers.IntegerField(required=False, default=0)
    low_stock = serializers.IntegerField(required=False, default=0)
    pending_prints = serializers.IntegerField(required=False, default=0)
    active_prints = serializers.IntegerField(required=False, default=0)
    prints_awaiting_collection = serializers.IntegerField(required=False, default=0)
    failed_emails = serializers.IntegerField(required=False, default=0)
    stocktakes_awaiting_approval = serializers.IntegerField(required=False, default=0)
    warranty_expiring = serializers.IntegerField(required=False, default=0)
    maintenance_overdue = serializers.IntegerField(required=False, default=0)
    pending_payments = serializers.IntegerField(required=False, default=0)
    # Declared so the schema and the generated TypeScript carry it: the endpoint emits
    # this map and an undeclared field is invisible to typed frontend consumers. Amounts
    # are strings keyed by currency code -- never one combined number, since adding INR
    # to USD would be meaningless money.
    outstanding_by_currency = serializers.DictField(
        child=serializers.CharField(), required=False, default=dict
    )

