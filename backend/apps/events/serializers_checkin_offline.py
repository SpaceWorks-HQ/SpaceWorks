from rest_framework import serializers


class OfflineCheckInOperationSerializer(serializers.Serializer):
    operation_id = serializers.UUIDField()
    checkin_token = serializers.CharField(max_length=64)
    reported_occurred_at = serializers.DateTimeField()


class OfflineCheckInSyncRequestSerializer(serializers.Serializer):
    lease_token = serializers.CharField(max_length=8192)
    operations = OfflineCheckInOperationSerializer(many=True, allow_empty=False)

    def validate_operations(self, value):
        if len(value) > 200:
            raise serializers.ValidationError("At most 200 operations may be synchronized.")
        operation_ids = [item["operation_id"] for item in value]
        if len(operation_ids) != len(set(operation_ids)):
            raise serializers.ValidationError("Operation IDs must be unique within a batch.")
        return value


class OfflineRosterRegistrationSerializer(serializers.Serializer):
    registration_id = serializers.IntegerField()
    checkin_token = serializers.UUIDField()
    name = serializers.CharField()
    host_waiver_state = serializers.ChoiceField(
        choices=["not_required", "on_file", "missing"]
    )


class OfflineRosterEventSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class OfflineRosterResponseSerializer(serializers.Serializer):
    lease_token = serializers.CharField()
    lease_id = serializers.UUIDField()
    server_time = serializers.DateTimeField()
    issued_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
    scan_opens_at = serializers.DateTimeField()
    scan_closes_at = serializers.DateTimeField()
    sync_deadline = serializers.DateTimeField()
    event = OfflineRosterEventSerializer()
    registrations = OfflineRosterRegistrationSerializer(many=True)


class OfflineCheckInResultSerializer(serializers.Serializer):
    operation_id = serializers.UUIDField()
    outcome = serializers.ChoiceField(
        choices=[
            "applied",
            "duplicate_operation",
            "already_attended",
            "registration_changed",
            "event_unavailable",
            "invalid_token",
            "outside_window",
        ]
    )
    registration_id = serializers.IntegerField(required=False)
    attended_at = serializers.DateTimeField(required=False)


class OfflineCheckInSyncResponseSerializer(serializers.Serializer):
    recorded_at = serializers.DateTimeField()
    results = OfflineCheckInResultSerializer(many=True)
