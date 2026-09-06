from rest_framework import serializers

class MemberLoanActivitySerializer(serializers.Serializer):
    label = serializers.CharField()
    checked_out_at = serializers.DateTimeField()
    due_at = serializers.DateTimeField(allow_null=True)
    overdue = serializers.BooleanField()


class MemberBookingActivitySerializer(serializers.Serializer):
    space_name = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    status = serializers.CharField()


class MemberPrintActivitySerializer(serializers.Serializer):
    public_token = serializers.UUIDField()
    status = serializers.CharField()
    title = serializers.CharField()
    created_at = serializers.DateTimeField()
    accepted_at = serializers.DateTimeField(allow_null=True)
    started_at = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)
    estimated_minutes = serializers.IntegerField()
    queue_position = serializers.IntegerField(allow_null=True)
    queue_approved_ahead = serializers.IntegerField(allow_null=True)
    queue_awaiting_review_ahead = serializers.IntegerField(allow_null=True)


class MemberEventRegistrationActivitySerializer(serializers.Serializer):
    registration_id = serializers.IntegerField()
    checkin_token = serializers.UUIDField(allow_null=True)
    event_title = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    status = serializers.CharField()
    waitlist_position = serializers.IntegerField(allow_null=True)
    feedback_available = serializers.BooleanField()
    feedback_path = serializers.CharField(allow_null=True)
    certificate = serializers.DictField(allow_null=True)


class MemberMachineServiceActivitySerializer(serializers.Serializer):
    machine_type = serializers.CharField(required=False)
    title = serializers.CharField()
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    queue_position = serializers.IntegerField(allow_null=True)


class MemberPresenceActivitySerializer(serializers.Serializer):
    started_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
    ended_at = serializers.DateTimeField(allow_null=True)
    end_reason = serializers.CharField(allow_blank=True)
    active = serializers.BooleanField()


class MemberAccountabilitySerializer(serializers.Serializer):
    membership_active = serializers.BooleanField()
    waiver_acceptance_required = serializers.BooleanField()
    restriction_code = serializers.CharField(allow_null=True)


class MemberLoanHistorySerializer(serializers.Serializer):
    label = serializers.CharField()
    checked_out_at = serializers.DateTimeField()
    returned_at = serializers.DateTimeField(allow_null=True)
    due_at = serializers.DateTimeField(allow_null=True)
    returned_late = serializers.BooleanField()


class MemberRequestHistorySerializer(serializers.Serializer):
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    item_count = serializers.IntegerField()
    returned_quantity = serializers.IntegerField()
    damaged_quantity = serializers.IntegerField()
    missing_quantity = serializers.IntegerField()


class MemberDuesSerializer(serializers.Serializer):
    dues_amount = serializers.CharField()
    # Amounts are strings keyed by currency code, never one summed number: outstanding
    # money cannot be added across currencies.
    outstanding_by_currency = serializers.DictField(child=serializers.CharField())


class MemberNoticeSerializer(serializers.Serializer):
    """A fact about the reader, derived from their own rows.

    Not `notifications.Notification`: that table is makerspace-wide, has no recipient
    and shares one `read_at`, so serving it would leak staff alerts.
    """

    level = serializers.CharField()
    event = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField(allow_blank=True)


class MemberActivitySerializer(serializers.Serializer):
    active_hardware_loans = MemberLoanActivitySerializer(many=True)
    print_requests = MemberPrintActivitySerializer(many=True, required=False)
    machine_service_requests = MemberMachineServiceActivitySerializer(many=True, required=False)
    bookings = serializers.DictField(child=serializers.ListField(), required=False)
    event_registrations = MemberEventRegistrationActivitySerializer(many=True, required=False)
    recent_presence_sessions = MemberPresenceActivitySerializer(many=True)
    currently_checked_in = serializers.BooleanField()
    accountability = MemberAccountabilitySerializer()
    loan_history = MemberLoanHistorySerializer(many=True, required=False)
    request_history = MemberRequestHistorySerializer(many=True, required=False)
    membership_dues = MemberDuesSerializer(required=False)
    notices = MemberNoticeSerializer(many=True, required=False)
