from rest_framework import serializers

from apps.devices.models import LabelPrintCommand
from apps.devices.serializers_printers import StrictSerializer

RESULT_MESSAGES = {
    "ok": "Labels printed.", "out_of_labels": "Printer needs labels.",
    "paper_empty": "Printer needs paper.", "offline": "Printer is unavailable.",
    "printer_error": "Printer reported an error.", "unknown_error": "Printing failed.",
}


class LabelCreateSerializer(StrictSerializer):
    device_id = serializers.UUIDField()
    request_id = serializers.UUIDField()


class LabelResultSerializer(StrictSerializer):
    operation_id = serializers.UUIDField()
    outcome = serializers.ChoiceField(choices=["succeeded", "retryable_failed", "failed"])
    result_code = serializers.ChoiceField(choices=tuple(RESULT_MESSAGES))

    def validate(self, attrs):
        if (attrs["outcome"] == "succeeded") != (attrs["result_code"] == "ok"):
            raise serializers.ValidationError("Result code does not match outcome.")
        return attrs


class LabelCommandSerializer(serializers.ModelSerializer):
    command_status = serializers.CharField(source="command.status", read_only=True)
    command_id = serializers.UUIDField(read_only=True)
    device_id = serializers.UUIDField(read_only=True)
    batch_id = serializers.IntegerField(read_only=True, allow_null=True)
    requested_by_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = LabelPrintCommand
        fields = ("id", "command_id", "command_status", "device_id", "batch_id", "request_id",
                  "batch_id_snapshot", "batch_title_snapshot", "item_count_snapshot", "result",
                  "result_code", "result_message", "completed_at", "requested_by_id", "created_at")
        read_only_fields = fields


class LabelReceiptSerializer(serializers.Serializer):
    operation_id = serializers.UUIDField()
    label_command_id = serializers.UUIDField()
    outcome = serializers.ChoiceField(choices=["succeeded", "retryable_failed", "failed"])
    result_code = serializers.ChoiceField(choices=tuple(RESULT_MESSAGES))
    response_result = serializers.ChoiceField(choices=LabelPrintCommand.Result.choices)
    response_command_status = serializers.CharField()
    response_completed_at = serializers.DateTimeField(allow_null=True)
